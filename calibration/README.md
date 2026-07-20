# `calibration/` — corpus-building, calibration, and analysis tooling

This directory holds the scripts, manifests, score matrices, and analysis
reports behind every calibrated constant (`AXIS_WEIGHTS`, `WITHIN_*`,
`theta_admit`, `theta_reject`, `theta_auth`, `MIN_RELIABLE_N`,
`MAX_A5_NEIGHBORHOOD_CANDIDATES`, etc.) and every empirical claim in
`Docs/` and the eventual paper (false-admit/false-reject rates, ablations,
bootstrap stability, the downstream case studies, the degenerate-refit
finding). It was published on 2026-07-21 in response to an external
review: a Methodology Article reviewer cannot evaluate any calibrated
number without a way to inspect how it was derived, and "available upon
reasonable request" is not sufficient for that.

## What's here

- **Generation scripts**: `corrupt.py` (the seeded corruption/fabrication
  generator — every degradation function takes a real dataset, a severity
  in (0, 1], and a seeded `RandomState`), `build_corpus.py` /
  `build_adversarial_corpus.py` (assemble the 968-dataset corpus and the
  30-dataset adversarial holdout from the manifests below),
  `fetch_corpus_expansion_v8.py` / `fetch_corpus_expansion_v9.py` /
  `fetch_multisource_chile_iquique.py` (retrieval scripts for the real
  parent catalogs), `enrich_moment_tensor_finite_fault_from_usgs.py` /
  `enrich_tsunami_mmi_from_usgs.py` (metadata enrichment), `derive_parent_catalog.py`,
  `split_corpus.py`.
- **Calibration scripts**: `run_scoring.py` (scores the full corpus),
  `compute_ewm.py` (Entropy Weight Method derivation), `calibrate_thresholds.py`,
  `calibrate_hard_override_params.py`, `calibrate_theta_auth.py`,
  `calibrate_a6_three_state.py`, `refit_full_corpus.py` (the report-only
  full weight/threshold refit that was attempted and deliberately
  rejected — see `Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md`
  Section 4.3 / 6.3), `run_a6_scoring.py`, `score_adversarial_holdout.py`,
  `benchmark_runtime.py`.
- **Analysis scripts**: `analysis_ablation.py`, `analysis_decision_stability.py`,
  `analysis_selective_classification.py`, `analysis_three_way_matrix.py`,
  `analysis_d1_case_study.py` / `analysis_d1b_aftershock_forecast.py` /
  `analysis_d1d_cross_agency_merge.py` (the downstream case studies in
  `Docs/03_Paper_Prep/`), `bootstrap_ewm_stability.py`, `make_paper_figures.py`
  (every table/figure in the paper).
- **Corpus manifests**: `corpus_manifest.csv` (969 rows — every dataset in
  the 968-dataset corpus, with `dataset_id`, `source_file`, `category`,
  `label`, `corruption_type`, `severity`, `n_records`, `notes`
  (includes the random seed used, where applicable), `parent_catalog`)
  and `adversarial_corpus_manifest.csv` (the 30-dataset held-out set,
  same schema, no `parent_catalog` column).
- **Score matrices**: `score_matrix.csv` and the A6-source variants
  (`score_matrix_a6*.csv`) — the actual computed `T(D)`/sub-test scores
  per `dataset_id` for the current, in-use code and constants. These are
  scores, not raw earthquake-event data.
- **Reports**: `bootstrap_stability_report.*`, `ewm_report.*`,
  `hard_override_calibration_report.*`, `theta_auth_report.*`,
  `threshold_report.*`, and `group_b_reports/` / `group_c_reports/` /
  `group_d_reports/` (ablation, decision-stability, selective-classification,
  three-way confusion matrix, A6 three-state validation, runtime
  benchmarks, the downstream case-study variant tables, and the
  maximum-curvature re-calibration report) — the exact outputs the
  numbers in `Docs/` are quoted from.

## What's deliberately NOT here yet

The raw, per-record earthquake-event CSVs that the corpus's `real` and
`corrupted_real` rows were built from/derived from are not republished
verbatim in this directory yet. Every one of them is deterministically
regenerable from `corpus_manifest.csv` (source, corruption type, severity,
seed) plus the scripts above, applied to the original real catalog —
so nothing about the calibration logic itself is hidden. They are withheld
specifically pending a check of the redistribution terms of the original
external sources (USGS ComCat is U.S. public domain; EMSC/ISC and some
national-network sources have not yet been individually checked). This is
a disclosed, temporary gap, not a permanent one — see
`Docs/03_Paper_Prep/DATA-CERTIFY_Research_Positioning_and_Contribution_Framework.md`
for the current data-availability statement.

Also excluded (internal working artifacts, not needed to reproduce
anything): `__pycache__/`, `_archive_stale_backups/`, `_tmp_preprocessed/`,
`_manifest_parts/`, `debug_diagnostics/`, `_mt_ff_cache.json`, superseded
score-matrix/manifest backups (`*.pre_*`, `*.stale_*`), and
`group_d_reports/d1d_multisource/` (raw EMSC/USGS records used in the
cross-agency merge case study — same licensing-check gap as above) and
its two `_partial*` in-progress subdirectories.

## Reproducing a score matrix from scratch

```bash
python calibration/build_corpus.py            # assembles the corpus from corpus_manifest.csv
python calibration/run_scoring.py              # scores it -> calibration/score_matrix.csv
python calibration/score_adversarial_holdout.py --fresh   # scores the 30-dataset holdout
python calibration/refit_full_corpus.py        # report-only: refits weights/thresholds, does not modify _constants.py
```

Each script's own docstring documents its exact inputs/outputs and cites
the `Docs/` section it supports.
