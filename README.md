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
data-quality/completeness metrics, and provenance/instrumentation checks, then
combines them into a single auditable ADMIT / CONDITIONAL / REJECT decision.

This repository is the reference implementation of that framework.

---

## Why this exists

Disaster-response ML pipelines are only as trustworthy as the catalogs they are
trained and evaluated on. Corrupted, fabricated, or silently-degraded seismic
data can pass ordinary schema/format checks while still being physically
implausible or statistically inconsistent with how real earthquake catalogs
behave. DATA-CERTIFY is designed to catch that class of problem before
ingestion, independent of whatever model-selection or model-validation checks
a downstream pipeline might separately apply.

## What this system is, and is not

DATA-CERTIFY is a selective pre-ingestion audit and triage framework, not an
autonomous certificate of authenticity and not a mathematical proof that a
given dataset is fabricated or genuine. Its hard-override gate and composite
score are a safety-oriented screening mechanism, tuned to be conservative
(favor CONDITIONAL and mandatory-review routing over a false ADMIT) rather
than to assert certainty.

On a held-out, adversarial-only evaluation set of 30 fabricated datasets never
seen during calibration, the system produces 0/30 ADMIT and 30/30 CONDITIONAL
decisions. Read that precisely: it demonstrates the system reliably prevents
automatic admission of held-out fabrications, not that the system
exhaustively classifies every fabrication as REJECT. ADMIT should be read as
"cleared, no mandatory-review flag raised," not as "verified genuine."

That result is not the whole picture. Across the internal 968-dataset
calibration corpus (real, corrupted, and fabricated catalogs; see "Data and
tooling not included in this repository" below), 22 known-bad datasets score
`T(D) >= theta_admit` before any Stage-1 hard-override check, of which 3 are
independently caught by the hard-override gate regardless of `T(D)` (depth-
implausible corruptions, where P2 fires unconditionally), leaving 19 genuine
two-stage-decision false admits, or 3.9% of the 490 known-bad datasets. Every
one of these 22 is a corrupted derivative of a real catalog; none of the
corpus's synthetic-fabrication datasets score anywhere near `theta_admit`.
This is a distinct failure mode from the held-out-fabrication result above,
best described as a finite-sample weakness of individual sub-tests against
corrupted-real-data edge cases, rather than a fabrication-detection gap.

That 19/490 (3.9%) figure describes the two-stage threshold logic in
isolation, not what a real user of `DataCertifyAuditor`/`run_audit.py`
actually experiences: production also applies two further safety gates
(`min_evidence_coverage`, `min_sample_sufficiency`), which the paper's
own analysis pipeline had never applied when computing 19/490. Re-running
the full corpus through the real, gated `DataCertifyAuditor.audit()` call
puts the true false-admit rate at 4/490 (0.82%) from the two existing
gates alone, or 3/490 (0.61%, Wilson 95% CI [0.21%, 1.78%]) once the
two additional ADMIT-eligibility floors added in response to a
paper-readiness review (`MIN_N_RECORDS_FOR_ADMIT`,
`MIN_APPLICABLE_SUBTESTS_FOR_ADMIT`) are included, at the cost of
known_good's ADMIT rate falling from 98/508 (19.3%) under threshold logic
alone to 32/508 (6.3%) under the fully gated production path; known_good
false-rejects remain 0/508 throughout. Full detail, including the exact
provenance of this finding, the residual false-admit cases, and a
predictive-value analysis under shifting prevalence, is in
`data_certify/_constants.py`'s calibration commentary and `CHANGELOG.md`.

`AXIS_WEIGHTS`, `WITHIN_A`, `theta_admit`, and `theta_reject` are calibrated
by blending an Analytic Hierarchy Process (AHP) expert-elicited prior with an
Entropy Weight Method (EWM) fit against the internal calibration corpus,
anchored to the AHP prior rather than purely data-driven. A live,
corpus-derived refit of these values was evaluated and rejected: it collapses
A3's within-axis weight substantially and forces `theta_admit` to a
degenerate value of 1.0, because several mildly-corrupted real catalogs score
indistinguishably from genuine data under the refit weights. That refit's
apparently perfect false-admit rate is an artifact of `theta_admit` sitting at
an unreachable ceiling, not a genuine improvement in separating good data from
bad, so the AHP-anchored weights are used in production instead. Full
derivation in `calibration/compute_ewm.py`, `calibration/refit_full_corpus.py`,
and `CHANGELOG.md`.

---

## Architecture

### Four-axis scoring framework

| Axis | Meaning | Sub-tests | Live blended weight |
|---|---|---|---|
| **A(D)** | Authenticity | A1 to A6 | 0.6895 |
| **P(D)** | Physical and Logical Plausibility | P1 to P9 (P1 to P3 are hard gates) | 0.1684 |
| **C(D)** | Completeness and Coverage | C1 to C4 | 0.0283 |
| **I(D)** | Instrumentation and Provenance-Pipeline Integrity | I1 to I5 | 0.1139 |

24 sub-tests total, each independently derived from an established
seismological, statistical, or data-quality method: Gutenberg-Richter b-value
via Aki's (1965) maximum-likelihood estimator with the Shi and Bolt (1982)
standard error, Omori-Utsu aftershock decay, Kanamori (1977) and Hanks and
Kanamori (1979) moment magnitude, Wells and Coppersmith (1994) rupture
scaling, Benford's Law per Hill's (1995) derivation, Grassberger-Procaccia
correlation dimension, the Mann-Kendall trend test with Sen's slope,
Clopper-Pearson exact binomial confidence intervals, Fellegi-Sunter (1969)
record linkage with Winkler's (1988) EM parameter fitting, Little's (1988)
MCAR test, and the Bakun and Wentworth (1997) intensity-magnitude relation.

Sub-test weight is not evenly distributed. 24 sub-tests should not be read as
24 roughly-equal votes: within each axis, a small number of sub-tests carry
most of that axis's own weight (within A(D), A1, A3, and A4 alone account for
most of the axis's internal weighting in the common intrinsic-only case; see
`WITHIN_A`, `WITHIN_P`, `WITHIN_C`, and `WITHIN_I` in `_constants.py`). Every
`SubTestResult` reports an `effective_weight` field, its actual nominal share
of `T(D)` in that specific audit, visible in `--verbose` CLI output and in
the JSON export, so this concentration is directly inspectable. It is
`null`/`None` only for P1 to P3, the Stage-1 hard gates, which sit outside
the weighted sum entirely rather than carrying zero weight.

For P, C, and I this is simply `axis_weight * within_axis_weight`. A(D) is
the exception, because A6 does not sit alongside A1 to A5 at a fixed nominal
share the way, for example, P4 sits alongside P5 to P9; when A6 applies, it
substitutes for A1 to A5 on a per-record basis (see the A6 section below).
`effective_weight` reflects this: `AXIS_WEIGHTS["A"]` is split between A6 and
A1 through A5 in proportion to how many records each stratum actually covers
in that audit, collapsing to the original fixed `WITHIN_A` shares when A6
never applies at all.

### Two-stage decision architecture

Stage 1 is a non-compensable hard-override veto. A small number of checks
(P1 to P3 physical-plausibility violations, evaluated via Bonferroni-corrected
Clopper-Pearson exact binomial tests, and A6 external cross-validation in its
"externally contradicted" state) sit outside the weighted composite score
entirely. If any of these fire, the dataset is REJECTed immediately; no
amount of completeness or instrumentation quality can compensate for a
confirmed physical impossibility or an externally-contradicted authenticity
failure.

Stage 2 is a compensatory composite score. If Stage 1 does not veto the
dataset, the blended weight vector above produces:

```
T(D) = w_A * A(D) + w_P * P(D) + w_C * C(D) + w_I * I(D)
```

`T(D)` is then compared against two calibrated thresholds, `theta_reject` and
`theta_admit`:

| Decision | Condition |
|---|---|
| **ADMIT** | `T(D) >= theta_admit` and no hard override fired |
| **CONDITIONAL** | `theta_reject <= T(D) < theta_admit`, routed to mandatory review |
| **REJECT** | `T(D) < theta_reject`, or a Stage-1 hard override fired |

### Evidence-coverage safety gate

Any sub-test or whole axis that is inapplicable (missing required fields,
too few records, and so on) has its weight renormalised across the remaining
applicable tests and axes, so a dataset is not penalized purely for lacking
an optional field. The tradeoff is that `T(D)` can clear `theta_admit` while
resting on only a small fraction of the framework's actual battery of tests:
a very small or minimally-populated catalog can pass several tests vacuously
(zero duplicates is trivially true at n=3) while the sub-tests that would
meaningfully stress-test it are silently inapplicable rather than counted
against it.

To make this visible, every audit result reports an evidence-coverage
diagnostic: the fraction of `T(D)`'s nominal calibrated weight that was
actually backed by an applicable, computable sub-test in that specific
audit, as opposed to weight quietly redistributed away from missing
evidence. If an audit would otherwise ADMIT but evidence coverage falls
below `--min-evidence-coverage` (default `0.5`), the decision is capped down
to CONDITIONAL instead, with a caveat naming the highest-weight missing
sub-tests. The gate only ever caps ADMIT down to CONDITIONAL, never upgrades
a decision, and never runs at all if a Stage-1 hard override already fired.
It is a disclosed, pragmatic default rather than a value empirically
calibrated against the internal corpus; set `--min-evidence-coverage 0` to
disable it.

### Sample-sufficiency safety gate

Evidence coverage answers whether an applicable sub-test ran and produced a
score at all. It cannot distinguish a score built from a single fitted
Omori-Utsu aftershock cluster from one built from a few hundred; both count
as covered identically. A small or minimally-populated catalog can clear
`theta_admit` while several of the sub-tests backing that score ran on a
sample too thin to trust.

Every A1 to A5 `SubTestResult.detail` reports `n_used`, the sample size that
sub-test's own score actually rests on, and each sub-test has a disclosed,
provisional `MIN_RELIABLE_N` floor (`_constants.py`: A1=30, A2=10, A3=2,
A4=50, A5=2) below which `n_used` is considered too thin. Every audit result
reports a sample-sufficiency diagnostic: of the evidence already counted as
covered by evidence coverage, what fraction of its combined nominal weight
rests on a sub-test whose `n_used` meets its floor. If an audit would
otherwise ADMIT but sample sufficiency falls below
`--min-sample-sufficiency` (default `0.5`), the decision is capped down to
CONDITIONAL, with a caveat naming the thinnest-sampled contributions. This
gate behaves the same way as evidence coverage (only ever caps ADMIT down to
CONDITIONAL, never overrides a hard override, is a disclosed default rather
than an empirically calibrated one, and is disabled with
`--min-sample-sufficiency 0`), applies independently of and in addition to
it, and is currently scoped to axis A only, since `MIN_RELIABLE_N` has no
entries yet for P, C, or I sub-tests.

### A5 duplicate-detection candidate-cap disclosure

`_score_a5_duplicates`'s dense-bucket safety valve
(`MAX_A5_NEIGHBORHOOD_CANDIDATES = 500`) bounds the worst-case cost of
exhaustively checking a pathologically dense cluster of mutual near-matches
by subsampling that cluster's candidate list once it exceeds the cap. Every
A5 result's `detail` reports `candidate_cap_triggered`, `n_capped_queries`
(how many record-queries hit the cap), and
`max_candidates_observed`/`sampling_fraction` (how dense the worst offending
cluster was, and how aggressively it was subsampled), surfaced in the
sub-test's note whenever the cap fires, so `duplicate_fraction` is never
silently an approximation without saying so.

### A6: three-state external cross-validation

External corroboration against catalogs such as USGS ComCat, EMSC, or ISC is
classified into three states rather than a binary match/no-match. Externally
corroborated means a statistically confirmed match against at least one
independent external source. Externally contradicted means at least two
independent sources statistically confirm a non-match, via a Clopper-Pearson
lower-tail test; this is the only A6 state that can trigger the Stage-1
hard-override REJECT. Externally unverifiable means no conclusive external
confirmation either way, for example a regional catalog with coverage gaps,
which falls back to the intrinsic A1 to A5 sub-tests rather than penalizing
the dataset for a coverage gap that is not its fault.

The CLI default, `--reference-source usgs`, can only ever reach corroborated
or unverifiable: a single source's non-match is deliberately treated as
unverifiable rather than contradicted, because one disagreeing source is not
strong enough evidence to hard-reject on its own. The externally-contradicted
hard-reject path only becomes reachable with `--reference-source multi` or
`weighted-multi`, and with at least two of the configured external sources
actually reachable at runtime. Running with the default single-source mode
is a real, intentional tradeoff; it does not provide the same fabrication
protection as multi-source mode.

Since A6 depends on a live, constantly-updated external catalog, auditing
the exact same dataset months apart can legitimately produce a different A6
verdict with no code change at all. Every A6 `SubTestResult.detail` records
`source_name` (which catalog or combination was queried), `query_timestamp_utc`,
and `query_params` (tolerances used and how many reference events were
available to match against), so this is traceable rather than mysterious.

### Geographic scoring in A3, A4, and A5

A3's aftershock-decay conformity test restricts mainshock-aftershock
clustering to a Gardner and Knopoff (1974) space-time-magnitude window, using
a magnitude-dependent spatial radius (`L(M) = 10^(0.1238*M + 0.983)` km, per
van Stiphout, Wiemer, and Marzocchi 2012), so that two independent
earthquakes on opposite sides of the planet within the same time window are
never merged into one aftershock sequence.

A4's correlation-dimension estimator computes distance by projecting
`(lat, lon)` to a local, antimeridian-unwrapped tangent-plane coordinate
system in kilometres (`stats.project_lonlat_to_local_km`) rather than taking
raw Euclidean distance on degrees, which would shrink east-west spacing
toward the poles and break entirely across the ±180° antimeridian. This is a
local/regional-scale approximation, adequate for a relative
clustering-geometry statistic but not intended for catalogs spanning many
thousands of kilometres. `haversine_km` and `haversine_km_matrix`, used
elsewhere in A5, A6, and P8, are exact great-circle computations and are
unaffected.

A5's duplicate-detection grid indexes longitude with modulo wraparound, so
near-duplicate records a few hundred metres apart across the dateline (Fiji,
Tonga, the Aleutians, or Pacific catalogs) are correctly compared rather than
landing in cells at opposite ends of the index range. A dense cluster of
mutual near-matches inside a single grid cell is inherently quadratic to
check exhaustively; the `MAX_A5_NEIGHBORHOOD_CANDIDATES` safety valve
described above bounds that worst case at the cost of a documented
approximation, only in that already-anomalous regime.

---

## Repository layout

```
data_certify/           Core library (the auditor itself)
  |- schema.py               Dataset schema, loading/validation
  |- axis_authenticity.py    A1-A6
  |- axis_plausibility.py    P1-P9
  |- axis_completeness.py    C1-C4
  |- axis_instrumentation.py I1-I5
  |- hard_override.py        Stage 1 veto logic
  |- decision.py             Stage 2 composite score and final decision
  |- reference_data.py       Pluggable external-catalog / fault-DB references
  |- stats.py                Shared statistical/physics primitives
  |- results.py              Result data structures
  `- _constants.py           Canonical weights and thresholds

examples/               Minimal worked examples
datasets/               Two small, real, bundled demo catalogs used by Quick
  |- nz/records.csv         Start and examples/example_nz_chile_audit.py
  `- chile/records.csv      (20,648 events, GeoNet NZ / 132,964 events, CSN Chile)
calibration/            Corpus-building, calibration, and analysis tooling
                          (see calibration/README.md)
tests/                  Automated test suite
run_audit.py            CLI entry point for auditing a dataset
prepare_dataset.py      CLI helper to convert a raw CSV into the schema
                          DATA-CERTIFY expects
```

This repository ships the core library, two small real-catalog demo
datasets, the automated test suite (`tests/`), and the calibration and
analysis tooling in `calibration/` (corpus-building, calibration, and
analysis scripts, both corpus manifests, computed score matrices, and every
calibration report; see `calibration/README.md`). Internal theory and
validation write-ups, and the raw, per-record earthquake-event corpus used
to calibrate the framework, are kept out of this repository and are not
required to install or use DATA-CERTIFY; see "Data and tooling not included
in this repository" below for exactly what that means and why.

---

## Requirements

Python 3.8 or later. `numpy` 1.21.0 or later is the only dependency needed
to run `run_audit.py` and audit datasets. `pandas` 1.3 or later is required,
not optional, if you want to use `prepare_dataset.py` to convert your own
raw CSV into the expected schema.

Install:

```bash
pip install -e .                 # core package only, enough for run_audit.py
pip install -e ".[prepare]"      # + pandas, needed for prepare_dataset.py
pip install -e ".[all]"          # everything
```

Either form also installs two console commands, `data-certify-audit` and
`data-certify-prepare`, as shorthand for `python run_audit.py` and
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

# Audit your own dataset (after preparing it, see "Bringing your own
# dataset" below), saving full results to JSON
python run_audit.py --dataset my_catalog --save-json
```

By default, without `--offline`, a `--dataset` run also attempts a live A6
cross-check against USGS ComCat. If there is no network access, or the query
fails or times out, this is handled gracefully: A(D) automatically falls
back to intrinsic-only (A1 to A5) scoring rather than erroring out.

Key CLI flags for `run_audit.py`:

| Flag | Purpose |
|---|---|
| `--dataset NAME` | Audit the dataset at `datasets/NAME/records.csv`, selecting what gets audited, whether bundled or your own prepared data |
| `--reference-csv PATH` | Overrides the A6 external reference catalog with a local CSV instead of querying USGS/EMSC/ISC live; used together with `--dataset`, not a substitute for it |
| `--offline` | Skip all external network calls |
| `--reference-source {usgs,emsc,isc,multi,weighted-multi}` | Which external catalog(s) to cross-validate A6 against |
| `--fault-db` / `--fault-db-source` / `--gem-fault-db-path` | Enable or point to a fault database for rupture-plausibility checks |
| `--theta-admit`, `--theta-reject` | Override the calibrated composite-score thresholds |
| `--min-evidence-coverage` | Evidence-coverage safety gate threshold, default `0.5`; `0` disables it |
| `--min-sample-sufficiency` | Sample-sufficiency safety gate threshold, default `0.5`; `0` disables it |
| `--uncertainty` / `--n-boot` / `--subsample-fraction` | Bootstrap the decision to see how stable it is under resampling |
| `--verbose` | Print full per-axis, per-sub-test detail |
| `--save-json` | Write the full result object to disk |

Run `python run_audit.py --help` for the complete, current list.

---

## Bringing your own dataset

First, get your catalog into the expected schema. DATA-CERTIFY expects a CSV
with, at minimum, event time, latitude, longitude, depth, and magnitude
columns, plus whatever secondary fields (magnitude type, station count,
azimuthal gap, and so on) your available sub-tests need. Use the helper
script to convert an arbitrary raw CSV (requires `pandas`, see Requirements
above):

```bash
python prepare_dataset.py --input raw_catalog.csv --dataset my_catalog
```

Pass `--date-col`/`--hour-col` and other column-mapping flags (run
`python prepare_dataset.py --help` for the full list) if your raw CSV uses
non-default column names. Omit `--no-interactive` to be prompted
interactively for any ambiguous column mappings.

Then run the audit, using `--dataset` with the name you gave
`prepare_dataset.py`, not `--reference-csv`, which is a different flag that
overrides the A6 external reference catalog rather than selecting the
target dataset:

```bash
python run_audit.py --dataset my_catalog --verbose --save-json
```

The output reports the Stage-1 hard-override verdict (fired or not, and
why), the four axis scores, the blended composite score `T(D)`, and the
final ADMIT / CONDITIONAL / REJECT decision, with a full per-sub-test
breakdown under `--verbose`. Add `--uncertainty` to bootstrap the decision
under resampling and see how sensitive it is to the exact set of records
present.

See `examples/example_custom_dataset.py` for a fully worked, minimal script
that constructs a dataset in Python and audits it programmatically without
going through the CLI; it generates its own synthetic catalogs and runs in
seconds. `examples/example_nz_chile_audit.py` runs the same protocol against
the two bundled real catalogs (`datasets/nz`, `datasets/chile`), including
the P8 fault-proximity check, an A6 self-consistency sanity check, and a
threshold-sensitivity sweep; because it runs several full audits over a
133,000-record catalog, expect it to take roughly one to two minutes rather
than seconds.

---

## Data and tooling not included in this repository

The raw, per-record earthquake-event catalogs the calibration corpus's real
and corrupted-real entries were built from, hundreds of catalogs beyond the
two bundled demo datasets, are not included. They are deterministically
regenerable from `calibration/corpus_manifest.csv` plus the published
generation scripts, using the same seeds and corruption parameters, but are
not republished verbatim, pending a check of the redistribution terms of the
original third-party real-catalog sources. Internal theory and validation
write-ups (`Docs/`) are likewise not included. Neither is required to
install or use DATA-CERTIFY.

P8, the plate-boundary proximity test, can optionally use the real GEM
Global Active Faults Database (Styron and Pagani 2020, roughly 13,700
faults, `--fault-db-source gem`). GEM GAF-DB is licensed under CC-BY-SA 4.0
by the GEM Foundation and is bundled with this repository at
`Dataset/GAF-DB/`, with attribution in `Dataset/GAF-DB/ATTRIBUTION.md`, so
`--fault-db-source gem`'s default path auto-discovery works out of the box
on a fresh clone; point `--gem-fault-db-path` at a different copy only if
you want a different GAF-DB version or location. By default
(`--fault-db-source bundled`, or the legacy `--fault-db` flag), P8 instead
uses a small, roughly 30-point demonstration plate-boundary reference that
ships with the code and is independent of GEM's dataset, sufficient to
exercise the scoring logic end to end but not a substitute for the real
database's coverage.

---

## License

See [`LICENSE`](./LICENSE). All rights reserved.

## Author

Nattakitti Piyavechvirat
International Bachelor Program in Informatics, YuanZe University
