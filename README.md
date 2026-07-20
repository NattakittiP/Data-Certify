# DATA-CERTIFY

**A dataset trustworthiness audit framework for disaster seismic (earthquake) catalogs.**

DATA-CERTIFY is a computer-implemented, pre-ingestion admissibility audit for
earthquake catalog datasets. Before a seismic catalog is ever handed to a
downstream disaster-response model (aftershock forecasting, hazard mapping,
early-warning triage, etc.), DATA-CERTIFY asks a narrower, upstream question:

> **Is this dataset itself trustworthy enough to be used at all?**

It does this by combining physics-grounded plausibility checks (Gutenberg-Richter
magnitude-frequency statistics, Omori-Utsu aftershock decay, moment-magnitude
consistency, rupture-scaling relations), statistical fabrication-detection
methods (Benford's Law, correlation-dimension analysis, digit-pattern tests),
data-quality/completeness metrics, and provenance/instrumentation checks — then
combines them into a single auditable ADMIT / CONDITIONAL / REJECT decision.

This repository is the reference implementation of that framework.

---

## Why this exists

Disaster-response ML pipelines are only as trustworthy as the catalogs they are
trained and evaluated on. Corrupted, fabricated, or silently-degraded seismic
data can pass ordinary schema/format checks while still being physically
implausible or statistically inconsistent with how real earthquake catalogs
behave. DATA-CERTIFY is designed to catch that class of problem **before**
ingestion, independent of whatever model-selection or model-validation checks
a downstream pipeline might separately apply.

## What this system is — and is not

DATA-CERTIFY is a **selective pre-ingestion audit / triage framework**, not an
autonomous certificate of authenticity and not a mathematical proof that a
given dataset is fabricated or genuine. Its hard-override gate and composite
score are a safety-oriented screening mechanism, tuned to be conservative
(favor CONDITIONAL / mandatory-review routing over a false ADMIT) rather than
to assert certainty.

On a held-out, adversarial-only evaluation set (30 fabricated datasets never
seen during calibration), the system produced **0/30 ADMIT** and **30/30
CONDITIONAL** decisions. Read that precisely: it demonstrates the system
reliably prevents *automatic admission* of held-out fabrications — it does
not demonstrate that the system exhaustively classifies every fabrication as
REJECT. "ADMIT" should be read as "cleared, no mandatory-review flag raised,"
not as "verified genuine."

**That result is not the whole picture — a known, disclosed false-admit
finding exists on the internal calibration corpus.** Across the internal
968-dataset calibration corpus (real + corrupted + fabricated catalogs, not
public — see "Data & tooling not included" below), 22 `known_bad` datasets
scored `T(D) >= theta_admit` before any Stage-1 hard-override check. Of
those, 3 are independently caught by the hard-override gate regardless of
`T(D)` (depth-implausible corruptions, where P2 fires unconditionally),
leaving **19 genuine two-stage-decision false-admits**. Notably, every one
of these 22 is a *corrupted derivative of a real catalog* — not one of the
corpus's `fabricated_level1`–`level9` synthetic datasets scored anywhere
near `theta_admit` (the highest tops out at 0.7293, still below the 0.75
boundary) — so this is a distinct failure mode from the held-out-fabrication
result above: a "finite-N weakness of individual sub-tests" against
corrupted-real-data edge cases, not a fabrication-detection gap. As of this
writing, resolving this finding (e.g. revising `theta_admit`, or adding a
dedicated minimum-sample-size policy independent of the evidence-coverage
gate below) remains an **open decision, not yet made** — see
`data_certify/_constants.py`'s calibration-pass commentary for the full,
unedited history of this finding across successive corpus-expansion passes.

**Re-verified 2026-07-21 against the A3/A4/A5 geographic-scoring fixes
below** (full 968-dataset corpus + the 30-dataset held-out adversarial set
re-scored under the fixed code, current weights/thresholds held fixed —
i.e. this isolates the effect of the code fix from any weight
recalibration, which has not been done): the pooled false-admit rate is
**still 19/490 (3.9%)** — unchanged in count, but **not unchanged in
composition**. 3 previously-false-admitted datasets are now correctly
routed to CONDITIONAL (the spatial constraint correctly stopped treating
their spatially-scattered "aftershock" candidates as a genuine decaying
sequence), while 3 different datasets newly false-admit (the same
mechanism running the other way — see below). Both sets are small
(24–29 records) real-catalog derivatives where only A3+A5 are applicable;
this class of dataset is exactly the "finite-N weakness of individual
sub-tests" already named above, now empirically confirmed to persist
(in a different guise) after the fix, not resolved by it. Separately: 32/968
datasets changed decision overall (all ADMIT⇄CONDITIONAL churn — no dataset
moved into or out of REJECT), and the 0% false-reject rate on `known_good`
held. The 30-dataset held-out adversarial set remained **0/30 ADMIT, 30/30
CONDITIONAL** under the fixed code. Net assessment: the A3/A4/A5 fixes
changed individual dataset outcomes materially (607/968 had a non-trivial
`A(D)` change) but did not move the headline false-admit/false-reject rates
in either direction — consistent with fixing a real geographic bug without
that bug having been the dominant driver of the pre-existing false-admit
finding. See `calibration/group_b_reports/three_way_matrix_report.txt` for
the full breakdown (not published, internal corpus).

**A subsequent full weight/threshold refit against these fixed scores was
attempted and deliberately rejected.** `calibration/compute_ewm.py` (a
genuine, live re-derivation) shows the A3/A4/A5 fixes shift what Entropy
Weight Method would assign A3 within axis A substantially — from its
current 0.42 down to 0.20, with A1 rising from 0.38 to 0.52 to compensate.
Feeding that refit weight vector into `calibration/refit_full_corpus.py`'s
own threshold grid-search produces `theta_admit = 1.0`: under the refit
weights, several *mild* corrupted-real datasets (coordinate-jitter,
moderate magnitude-Gutenberg-Richter violations, light missingness) score
`T(D)` between 0.989 and 0.997 — indistinguishable in practice from genuine
data — forcing the "zero known-bad clears theta_admit" rule to the ceiling
to compensate. The refit's headline 0% false-admit rate is a degenerate
artifact of that ceiling (ADMIT becomes practically unreachable, evidenced
by only 77.6% decision agreement with current production, driven mostly by
real `known_good` catalogs losing clean ADMIT status), not a genuine
improvement in separating good data from bad. This is read as evidence that
naive EWM — which weights criteria by variance/entropy across the observed
corpus, not by demonstrated discriminative power against *known*
corruptions — is not a safe drop-in replacement for the current,
AHP-anchored weighting here. `AXIS_WEIGHTS`/`WITHIN_A`/`theta_admit`/
`theta_reject` were therefore deliberately left unchanged following this
investigation, not merely left unexamined. Separately, note
`calibration/calibrate_thresholds.py` was found to report hardcoded
threshold literals from an earlier (2026-07-07, 89-dataset) calibration
pass rather than deriving them live from the current corpus — its output
should not be read as an independent confirmation.

---

## Architecture

### Four-axis scoring framework

| Axis | Meaning | Sub-tests | Live blended weight |
|---|---|---|---|
| **A(D)** | Authenticity | A1–A6 | 0.6895 |
| **P(D)** | Physical & Logical Plausibility | P1–P9 (P1–P3 are hard gates) | 0.1684 |
| **C(D)** | Completeness & Coverage | C1–C4 | 0.0283 |
| **I(D)** | Instrumentation & Provenance-Pipeline Integrity | I1–I5 | 0.1139 |

24 sub-tests total, each independently derived from an established
seismological, statistical, or data-quality method (Gutenberg-Richter b-value
via Aki 1965 MLE with Shi & Bolt 1982 standard error, Omori-Utsu decay,
Kanamori 1977 / Hanks & Kanamori 1979 moment magnitude, Wells & Coppersmith
1994 rupture scaling, Benford's Law per Hill's 1995 derivation,
Grassberger-Procaccia correlation dimension, Mann-Kendall trend test with
Sen's slope, Clopper-Pearson exact binomial confidence intervals,
Fellegi-Sunter 1969 record linkage with Winkler 1988 EM parameter fitting,
Little's 1988 MCAR test, and Bakun & Wentworth 1997 intensity-magnitude
relations).

The weights above blend an Analytic Hierarchy Process (AHP) expert-elicited
prior with an Entropy Weight Method (EWM) fit computed empirically against
an internal calibration corpus (see `data_certify/_constants.py` for the
canonical values in use). Treat them as a documented, preliminary calibration
tied to the corpus used to derive them — not a fixed, universally converged
answer.

**Sub-test weight is not evenly distributed.** "24 sub-tests" should not be
read as "24 roughly-equal votes" — within each axis, a small number of
sub-tests carry most of that axis's own weight (e.g. within A(D), A1+A3+A4
alone account for most of the axis's internal weighting in the common
intrinsic-only case; see `WITHIN_A` / `WITHIN_P` / `WITHIN_C` / `WITHIN_I` in
`_constants.py`). Every `SubTestResult` now reports an `effective_weight`
field — its actual nominal share of `T(D)` in this specific audit — visible
in `--verbose` CLI output and in the JSON export, so this concentration is
directly inspectable rather than something you'd have to reconstruct by
hand. `effective_weight` is `null`/`None` only for P1–P3 (Stage-1 hard gates,
which sit outside the weighted sum entirely, not "zero-weight").

For P/C/I this is simply `axis_weight * within_axis_weight`. **A(D) is the
one exception**, because A6 does not sit *alongside* A1–A5 at a fixed nominal
share the way, say, P4 sits alongside P5–P9 — when A6 applies, it
*substitutes* for A1–A5 on a **per-record basis** (see "A6: three-state
external cross-validation" below). `effective_weight` reflects this:
`AXIS_WEIGHTS["A"]` is split between A6 and (A1–A5) in proportion to how many
records each stratum actually covers in *this* audit, e.g. if A6 externally
corroborates 90% of a dataset's records, A6 gets ~90% of A(D)'s nominal
weight and A1–A5 correspondingly split the remaining ~10% — collapsing
exactly to the original fixed `WITHIN_A` shares when A6 never applies at all
(the common default case, no live/local reference configured). An earlier
version of this feature did not do this reallocation — it gave A6
`effective_weight=None` (treating it like a pure hard gate) while leaving
A1–A5 at their full fixed share regardless of how many records A6 actually
covered, which silently miscounted strong A6 corroboration as "missing
evidence" under the coverage gate below. Fixed 2026-07-21; see
`data_certify/decision.py::_assign_effective_weights_axis_a` for the full
before/after and a worked reproduction.

### Two-stage decision architecture

**Stage 1 — Non-compensable hard-override veto.** A small number of checks
(P1–P3 physical-plausibility violations, evaluated via Bonferroni-corrected
Clopper-Pearson exact binomial tests; and A6, external cross-validation, in
its "externally contradicted" state) sit *outside* the weighted composite
score entirely. If any of these fire, the dataset is REJECTed immediately —
no amount of completeness or instrumentation quality can compensate for a
confirmed physical impossibility or externally-contradicted authenticity
failure.

**Stage 2 — Compensatory composite score.** If Stage 1 does not veto the
dataset, the blended weight vector above produces:

```
T(D) = w_A * A(D) + w_P * P(D) + w_C * C(D) + w_I * I(D)
```

`T(D)` is then compared against two calibrated thresholds, `theta_reject` and
`theta_admit`, to produce a final decision:

| Decision | Condition |
|---|---|
| **ADMIT** | `T(D) >= theta_admit` and no hard override fired |
| **CONDITIONAL** | `theta_reject <= T(D) < theta_admit` — routed to mandatory review |
| **REJECT** | `T(D) < theta_reject`, or a Stage-1 hard override fired |

### Evidence-coverage safety gate (additive, does not change `T(D)` itself)

Any sub-test or whole axis that is inapplicable (missing required fields, too
few records, etc.) has its weight **renormalised** across the remaining
applicable tests/axes — by design, so a dataset isn't penalized purely for
lacking an optional field. The flip side: it is possible for `T(D)` to clear
`theta_admit` while resting on only a small fraction of the framework's
*actual* battery of tests — a very small or minimally-populated catalog can
end up passing several tests vacuously (e.g. "0 duplicates" is trivially true
at n=3) while the sub-tests that would meaningfully stress-test it (Benford,
Gutenberg-Richter, aftershock decay, ...) are silently inapplicable rather
than counted against it.

To make this visible rather than silent, every audit result reports an
**evidence-coverage** diagnostic: the fraction of `T(D)`'s *nominal*
calibrated weight (see `effective_weight` above) that was actually backed by
an applicable, computable sub-test in that specific audit — as opposed to
weight quietly redistributed away from missing evidence. If an audit would
otherwise **ADMIT** but evidence coverage falls below `--min-evidence-coverage`
(default `0.5`), the decision is capped down to **CONDITIONAL** instead, with
a caveat naming the highest-weight missing sub-tests. This gate:

- Only ever caps ADMIT → CONDITIONAL — it never upgrades a decision, and
  never runs at all if a Stage-1 hard override already fired.
- Is a disclosed, pragmatic default (like `theta_admit`/`theta_reject`'s own
  pre-calibration provisional values), **not** itself empirically calibrated
  against the internal corpus. Set `--min-evidence-coverage 0` to disable it
  and reproduce the exact prior behavior.

### Sample-sufficiency safety gate (additive, distinct from evidence coverage)

Evidence coverage (above) answers "did an applicable sub-test run and produce
a score at all". It cannot distinguish a score built from a single fitted
Omori-Utsu aftershock cluster from one built from a few hundred — both count
as "covered" identically. A small or minimally-populated catalog can clear
`theta_admit` while several of the sub-tests actually backing that score ran
on a sample too thin to trust.

To close this gap, every A1–A5 `SubTestResult.detail` now reports `n_used` —
the sample size that sub-test's own score actually rests on (e.g. A3:
number of *independent* candidate mainshock-aftershock clusters identified,
not the event count within any one cluster; A1: the smallest per-field
Benford sample; A4: valid `(lat, lon)` pair count; A5: total record count).
Each sub-test has a disclosed, provisional `MIN_RELIABLE_N` floor
(`data_certify/_constants.py`: A1=30, A2=10, A3=2, A4=50, A5=2) below which
its `n_used` is considered too thin. Every audit result reports a
**sample-sufficiency** diagnostic: of the evidence already counted as
"covered" by evidence coverage, what fraction of its combined nominal weight
rests on a sub-test whose `n_used` actually meets its floor. If an audit
would otherwise **ADMIT** but sample sufficiency falls below
`--min-sample-sufficiency` (default `0.5`), the decision is capped down to
**CONDITIONAL**, with a caveat naming the thinnest-sampled contributions.
This gate:

- Only ever caps ADMIT → CONDITIONAL — same as evidence coverage, it never
  upgrades a decision, and never runs if a Stage-1 hard override already
  fired. Applies independently of, and in addition to, the evidence-coverage
  gate.
- Is a disclosed, pragmatic default, **not** itself empirically calibrated.
  Set `--min-sample-sufficiency 0` to disable it.
- Is currently scoped to axis A (A1–A5) only, since `MIN_RELIABLE_N` has no
  entries yet for P/C/I sub-tests — a disclosed scope limit, not a claim
  that every other sub-test's sample size is unconditionally trustworthy.

This directly targets a false-admit risk surfaced by external review: very
small catalogs (24–29 records) where only A3 and A5 were applicable at all,
each backed by a thin underlying sample — evidence coverage alone could not
see this, because both sub-tests *did* run.

### A5 duplicate-detection candidate-cap disclosure

`_score_a5_duplicates`'s dense-bucket safety valve
(`MAX_A5_NEIGHBORHOOD_CANDIDATES = 500`) bounds the worst-case cost of
exhaustively checking a pathologically dense cluster of mutual near-matches
by subsampling that cluster's candidate list once it exceeds the cap — see
"Fix A5 longitude wraparound + quadratic perf" below for why this exists.
Previously, whether or how severely this fired on a given audit was
invisible. Every A5 result's `detail` now reports `candidate_cap_triggered`,
`n_capped_queries` (how many record-queries hit the cap), and
`max_candidates_observed`/`sampling_fraction` (how dense the worst offending
cluster was, and how aggressively it was subsampled) — surfaced in the
sub-test's note whenever the cap actually fires, so `duplicate_fraction` is
never silently an approximation without saying so.

### A6: three-state external cross-validation

External corroboration against catalogs such as USGS ComCat, EMSC, or ISC is
classified into three states rather than a binary match/no-match:

- **Externally corroborated** — statistically confirmed match against ≥1
  independent external source.
- **Externally contradicted** — ≥2 independent sources statistically confirm
  a *non*-match (via Clopper-Pearson lower-tail test); this is the only A6
  state that can trigger the Stage-1 hard-override REJECT.
- **Externally unverifiable** — no conclusive external confirmation either
  way (e.g., regional catalog coverage gaps); falls back to the intrinsic
  A1–A5 sub-tests rather than penalizing the dataset for a coverage gap that
  isn't its fault.

**Important default-mode caveat:** `--reference-source usgs` (the CLI
default) can only ever reach *corroborated* or *unverifiable* — a single
source's non-match is deliberately treated as unverifiable, not
contradicted, because one disagreeing source isn't strong enough evidence
to hard-reject on its own. The "externally contradicted" hard-reject path
only becomes reachable with `--reference-source multi` or `weighted-multi`
**and** at least two of the configured external sources actually being
reachable at runtime. Running with the default single-source mode is a
real, intentional trade-off — it does not provide the same fabrication
protection as multi-source mode, and should not be assumed to.

**Reproducibility metadata.** Since A6 depends on a live, constantly-updated
external catalog, the exact same dataset audited months apart can legitimately
produce a different A6 verdict with no code change at all. To make this
traceable rather than mysterious, every A6 `SubTestResult.detail` (CLI
`--verbose` output and JSON export alike) now records `source_name` (which
catalog/combination was actually queried), `query_timestamp_utc` (when), and
`query_params` (tolerances used and how many reference events were available
to match against — a query that returns 0 reference events looks identical
to "nothing corroborates this dataset" in `matched_fraction` alone, but is a
very different situation).

### Geographic-scoring fixes (2026-07-21, external review) — disclosed behavior change

Three sub-tests had geographic bugs that are now fixed as the new default
behavior. These are genuine, deliberate changes to already-calibrated scoring
functions — real multi-region or dateline-spanning catalogs can score
differently under A3/A4 than they did before this fix. **Re-validated
2026-07-21**: the full internal calibration corpus (968 datasets) and
30-dataset held-out adversarial set were re-scored under the fixed code
(current weights/thresholds held fixed, i.e. this checks the code fix in
isolation from any weight recalibration). Result: `A(D)` changed materially
for 607/968 datasets and 32/968 changed ADMIT⇄CONDITIONAL decision (no
dataset moved into or out of REJECT), but the headline false-admit rate
(19/490) and false-reject rate (0/508 on `known_good`) were unchanged in
aggregate — see "What this system is — and is not" above for the full
breakdown, including that the false-admit *count* staying flat conceals a
real 3-in/3-out swap in which specific datasets false-admit.

**A full weight/threshold refit against the fixed scores was attempted and
deliberately rejected** — see "What this system is — and is not" above for
the finding: a naive Entropy Weight Method refit collapses A3's within-axis
weight and produces a degenerate `theta_admit=1.0`. `AXIS_WEIGHTS`/
`WITHIN_A`/`theta_admit`/`theta_reject` therefore intentionally remain at
their pre-fix-calibrated values (see "Data & tooling not included in this
repository" below for what re-deriving them would take).

- **A3 (aftershock-decay conformity) had no spatial constraint at all.**
  Mainshock-aftershock clustering previously used only a time window and a
  magnitude condition — two independent earthquakes on opposite sides of the
  planet, coincidentally within the same 30-day window, could be merged into
  one "aftershock sequence." Fixed by adding a magnitude-dependent spatial
  radius (Gardner & Knopoff 1974, `L(M) = 10^(0.1238*M + 0.983)` km, per van
  Stiphout, Wiemer & Marzocchi 2012), so only candidates within the
  mainshock's own radius count. Affects any dataset spanning a wide
  geographic area; a small/regional catalog is largely unaffected since its
  events were already within a plausible aftershock radius of each other.
- **A4 (correlation dimension) computed raw Euclidean distance on (lat, lon)
  in degrees.** This is wrong in two ways: a degree of longitude shrinks
  toward the poles (proportional to `cos(latitude)`), and it breaks entirely
  across the ±180° antimeridian (179.9° and −179.9° are ~11 km apart in
  reality, ~359.8 degrees apart as raw numbers). Fixed by projecting to a
  local, antimeridian-unwrapped tangent-plane coordinate system in km
  (`stats.project_lonlat_to_local_km`) before computing correlation
  dimension. This is a local/regional-scale approximation, not a
  globally-exact projection — adequate for a relative clustering-geometry
  statistic, not intended for catalogs spanning many thousands of km.
  `haversine_km`/`haversine_km_matrix` (used elsewhere, e.g. A5/A6/P8) are
  unaffected and remain exact.
- **A5 (duplicate detection) missed duplicates straddling the antimeridian,**
  and had a residual worst-case quadratic cost in pathologically dense
  buckets. The spatial pre-filter grid indexed longitude with no wraparound,
  so two near-duplicate records a few hundred metres apart across the
  dateline (e.g. Fiji, Tonga, the Aleutians, or NZ/Pacific catalogs) landed
  in cells at opposite ends of the index range and were never compared —
  fixed via modulo-wrapped cell indexing. Separately, an all-pairs check
  inside a single dense grid cell is inherently O(k²) for a genuinely dense
  cluster (no exact algorithm avoids this); a disclosed, bounded safety
  valve (`MAX_A5_NEIGHBORHOOD_CANDIDATES = 500`, subsampled deterministically
  like `MAX_A3_CLUSTERS`/`correlation_dimension`'s `max_points`) caps the
  worst case, at the cost of a documented approximation only in that already
  -anomalous regime (hundreds+ of records sharing one ~2km/5s/0.05-magnitude
  cell — not ordinary catalog behavior).

---

## Repository layout

```
data_certify/           Core library (the auditor itself)
  ├─ schema.py               Dataset schema, loading/validation
  ├─ axis_authenticity.py    A1–A6
  ├─ axis_plausibility.py    P1–P9
  ├─ axis_completeness.py    C1–C4
  ├─ axis_instrumentation.py I1–I5
  ├─ hard_override.py        Stage 1 veto logic
  ├─ decision.py              Stage 2 composite score + final decision
  ├─ reference_data.py        Pluggable external-catalog / fault-DB references
  ├─ stats.py                 Shared statistical/physics primitives
  ├─ results.py                Result data structures
  └─ _constants.py             Canonical weights / thresholds

examples/                 Minimal worked examples
datasets/               Two small, real, bundled demo catalogs used by Quick
  ├─ nz/records.csv         Start and examples/example_nz_chile_audit.py
  └─ chile/records.csv      (20,648 events, GeoNet NZ / 132,964 events, CSN Chile)
run_audit.py               CLI entry point for auditing a dataset
prepare_dataset.py         CLI helper to convert a raw CSV into the schema
                            DATA-CERTIFY expects
```

This repository ships the core system plus two small real-catalog demo
datasets so the Quick Start commands below work out of the box. Internal
calibration/verification tooling, the test suite, theory/validation
write-ups, and the full raw-data corpus used to calibrate the framework are
kept out of this repository and are not required to install or use
DATA-CERTIFY.

---

## Requirements

- Python ≥ 3.8
- `numpy` ≥ 1.21.0 — only dependency needed to run `run_audit.py` and audit
  datasets.
- `pandas` ≥ 1.3 — **required** (not optional) if you want to use
  `prepare_dataset.py` to convert your own raw CSV into the expected schema.

Install:

```bash
pip install -e .                 # core package only — enough for run_audit.py
pip install -e ".[prepare]"      # + pandas — needed for prepare_dataset.py
pip install -e ".[all]"          # everything
```

Either form also installs two console commands, `data-certify-audit` and
`data-certify-prepare`, as shorthand for `python run_audit.py` /
`python prepare_dataset.py`.

---

## Quick start

```bash
# List bundled example datasets
python run_audit.py --list

# Audit a bundled example dataset (verbose per-sub-test output)
python run_audit.py --dataset nz --verbose

# Audit without making any external network calls (A6 falls back to
# "externally unverifiable" rather than querying USGS/EMSC/ISC)
python run_audit.py --dataset chile --offline

# Audit your own dataset (after preparing it — see "Bringing your own
# dataset" below), saving full results to JSON
python run_audit.py --dataset my_catalog --save-json
```

By default (no `--offline`), `--dataset` runs also attempt a live A6
cross-check against USGS ComCat. If there is no network access, or the query
fails or times out, this is handled gracefully — A(D) automatically falls
back to intrinsic-only (A1–A5) scoring rather than erroring out.

Key CLI flags (`run_audit.py`):

| Flag | Purpose |
|---|---|
| `--dataset NAME` | Audit the dataset at `datasets/NAME/records.csv` — this is how you select **what gets audited**, whether it's a bundled example or your own prepared data |
| `--reference-csv PATH` | **Not** for selecting what to audit — overrides the *A6 external reference catalog* with a local CSV instead of querying USGS/EMSC/ISC live (use together with `--dataset`) |
| `--offline` | Skip all external network calls |
| `--reference-source {usgs,emsc,isc,multi,weighted-multi}` | Which external catalog(s) to cross-validate A6 against |
| `--fault-db` / `--fault-db-source` / `--gem-fault-db-path` | Enable/point to a fault database for rupture-plausibility checks |
| `--theta-admit`, `--theta-reject` | Override the calibrated composite-score thresholds |
| `--min-evidence-coverage` | Evidence-coverage safety gate threshold (default `0.5`) — see "Evidence-coverage safety gate" above; `0` disables it |
| `--uncertainty` / `--n-boot` / `--subsample-fraction` | Bootstrap the decision to see how stable it is under resampling |
| `--verbose` | Print full per-axis, per-sub-test detail |
| `--save-json` | Write the full result object to disk |

Run `python run_audit.py --help` for the complete, current list.

---

## Bringing your own dataset

1. **Get your catalog into the expected schema.** DATA-CERTIFY expects a CSV
   with (at minimum) event time, latitude, longitude, depth, and magnitude
   columns, plus whatever secondary fields (magnitude type, station count,
   azimuthal gap, etc.) your available sub-tests need. Use the helper script
   to convert an arbitrary raw CSV (requires `pandas` — see Requirements
   above):

   ```bash
   python prepare_dataset.py --input raw_catalog.csv --dataset my_catalog
   ```

   Pass `--date-col`/`--hour-col` (and other column-mapping flags — run
   `python prepare_dataset.py --help` for the full list) if your raw CSV uses
   non-default column names. Omit `--no-interactive` to be prompted
   interactively for any ambiguous column mappings.

2. **Run the audit** (use `--dataset`, matching the name you gave
   `prepare_dataset.py` above — **not** `--reference-csv`, which is a
   different flag that overrides the A6 external reference catalog, not
   the target dataset):

   ```bash
   python run_audit.py --dataset my_catalog --verbose --save-json
   ```

3. **Read the decision.** The output reports the Stage-1 hard-override
   verdict (fired / not fired, and why), the four axis scores, the blended
   composite score `T(D)`, and the final ADMIT / CONDITIONAL / REJECT
   decision, with a full per-sub-test breakdown under `--verbose`.

4. **(Optional) Sanity-check stability.** Add `--uncertainty` to bootstrap
   the decision under resampling and see how sensitive it is to the exact
   set of records present.

See `examples/example_custom_dataset.py` for a fully worked, minimal script
that constructs a dataset in Python and audits it programmatically without
going through the CLI (no external data needed — it generates its own
synthetic catalogs; runs in seconds). `examples/example_nz_chile_audit.py`
runs the same protocol against the two bundled real catalogs (`datasets/nz`,
`datasets/chile`), including the P8 fault-proximity check, an A6
self-consistency sanity check, and a threshold-sensitivity sweep — because
it runs several full audits over a 133k-record catalog, expect it to take
roughly 1–2 minutes rather than seconds.

---

## Data & tooling not included in this repository

This repository ships the core system plus two small bundled demo catalogs
(`datasets/nz`, `datasets/chile`) so the Quick Start actually runs. The
following are kept out of this repository, deliberately, and are not
required to install or use DATA-CERTIFY:

- The internal calibration/verification corpus (hundreds of additional
  known-good, corrupted, and fabricated seismic catalogs beyond the two
  bundled demo catalogs) and the scripts used to build, corrupt, score, and
  calibrate weights/thresholds against it.
- Internal theory and validation write-ups.

The automated test suite (`tests/`, 321 tests) IS included, unlike the two
items above — see "Repository layout" and the GitHub Actions CI workflow.

P8 (plate-boundary proximity) can optionally use the real **GEM Global
Active Faults Database** (Styron & Pagani 2020, ~13,700 faults,
`--fault-db-source gem`). GEM GAF-DB is licensed under **CC-BY-SA 4.0** by
the GEM Foundation and is not included in this repository at all — point
`--gem-fault-db-path` at your own copy of it to use this mode. By default
(`--fault-db-source bundled`, or the legacy `--fault-db` flag), P8 instead
uses a small (~30-point) demonstration plate-boundary reference that ships
with the code and is independent of GEM's dataset — sufficient to exercise
the scoring logic end to end, but not a substitute for the real database's
coverage.

---

## License

See [`LICENSE`](./LICENSE). All rights reserved.

## Author

Nattakitti Piyavechvirat
International Bachelor Program in Informatics, YuanZe University
