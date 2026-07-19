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

# Audit your own prepared CSV, saving full results to JSON
python run_audit.py --reference-csv path/to/your_dataset.csv --save-json
```

By default (no `--offline`), `--dataset`/`--reference-csv` runs also attempt
a live A6 cross-check against USGS ComCat. If there is no network access, or
the query fails or times out, this is handled gracefully — A(D) automatically
falls back to intrinsic-only (A1–A5) scoring rather than erroring out.

Key CLI flags (`run_audit.py`):

| Flag | Purpose |
|---|---|
| `--dataset NAME` | Audit one of the bundled example datasets |
| `--reference-csv PATH` | Audit your own prepared CSV |
| `--offline` | Skip all external network calls |
| `--reference-source {usgs,emsc,isc,multi,weighted-multi}` | Which external catalog(s) to cross-validate A6 against |
| `--fault-db` / `--fault-db-source` / `--gem-fault-db-path` | Enable/point to a fault database for rupture-plausibility checks |
| `--theta-admit`, `--theta-reject` | Override the calibrated composite-score thresholds |
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

2. **Run the audit:**

   ```bash
   python run_audit.py --reference-csv my_catalog_prepared.csv --verbose --save-json
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
- The automated test suite used during development.
- Internal theory and validation write-ups.

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
