# Changelog

All notable changes to DATA-CERTIFY are documented in this file.

## [0.1.0] — 2026-07-21

First tagged release. Summary of everything notable since the initial
public commit.

### Fixed

- **Clopper-Pearson exact binomial tail functions were O(n) in record
  count.** `clopper_pearson_upper_tail`/`clopper_pearson_lower_tail`
  (`data_certify/stats.py`) previously summed the binomial PMF term-by-term
  over the full tail — ~11.4 seconds for a 5,000,000-record catalog, on
  the hot path of every P1–P3 hard-override check. Replaced with the
  regularized incomplete beta function evaluated via a continued-fraction
  expansion (Numerical Recipes 3rd ed., Lentz's method) — effectively O(1)
  in practice (~13 microseconds for the same input), verified numerically
  identical to `scipy.stats.binom.sf`/`.cdf` to >=9 significant figures
  across small-n, large-n, and boundary cases.
- **A6's record-stratum substitution was not reflected in effective-weight
  / evidence-coverage accounting.** A6, when it externally corroborates
  records, *substitutes* for A1–A5 on a per-record basis rather than
  sitting alongside them at a fixed nominal share. The first cut of the
  evidence-coverage feature (see below) did not know this, and counted
  A1–A5's full fixed nominal weight as "missing evidence" even when A6 had
  already covered that same ground with strong corroboration — capping a
  strongly-verified ADMIT down to CONDITIONAL. Fixed by allocating A(D)'s
  axis weight across A6 and (A1–A5) in proportion to how many records each
  stratum actually covers, mirroring `score_authenticity()`'s own
  record-count blend exactly. Fully backward-compatible with the default
  (no live/local A6 reference) case. Regression tests added
  (`tests/test_decision.py::TestA6EvidenceWeighting`).
- **A3 (aftershock decay) had no spatial constraint.** Mainshock-aftershock
  clustering used only a time window and magnitude condition — two
  unrelated earthquakes anywhere on Earth within the same 30-day window
  could be merged into one "aftershock sequence." Fixed with a
  magnitude-dependent spatial radius (Gardner & Knopoff 1974, via van
  Stiphout, Wiemer & Marzocchi 2012). **Disclosed behavior change**: shifts
  A3's scored output for wide-area/multi-region datasets; recalibration
  against the internal corpus is an open item. Regression test added
  (`tests/test_axis_authenticity.py::TestIntrinsicMode::test_a3_spatial_constraint_excludes_geographically_distant_coincident_events`).
- **A4 (correlation dimension) computed raw Euclidean distance on (lat, lon)
  degrees**, distorting east-west vs. north-south spacing away from the
  equator and breaking entirely across the ±180° antimeridian. Fixed via a
  new local, antimeridian-unwrapped tangent-plane projection
  (`stats.project_lonlat_to_local_km`). **Disclosed behavior change**, same
  caveat as A3 above. While adding this function's own regression tests, a
  second bug was found and fixed in the same pass: its antimeridian-safe
  reference longitude was computed as a plain linear median, which itself
  breaks for point clouds that straddle the antimeridian symmetrically
  (e.g. two points at 179.999°/−179.999° have a linear median of 0°, on the
  wrong side of the globe) — fixed with a circular-mean pivot, re-centered
  via median for outlier robustness. Regression tests added
  (`tests/test_stats.py::TestProjectLonLatToLocalKm`,
  `tests/test_axis_authenticity.py::TestIntrinsicMode::test_a4_...` uniform-coordinate case unaffected).
- **A5 (duplicate detection) missed duplicates straddling the antimeridian**
  and had a residual worst-case quadratic cost in pathologically dense grid
  cells. Fixed via modulo-wrapped longitude cell indexing (antimeridian) and
  a disclosed, bounded safety valve (`MAX_A5_NEIGHBORHOOD_CANDIDATES = 500`,
  deterministic subsampling, same pattern as `MAX_A3_CLUSTERS`/
  `correlation_dimension`'s `max_points`) for the dense-bucket case. Also
  switched grid-bucket removal to avoid an unnecessary list scan. Regression
  tests added (`tests/test_axis_authenticity.py::TestIntrinsicMode::test_a5_flags_duplicate_pair_straddling_the_antimeridian`,
  `test_a5_dense_bucket_cap_does_not_crash_and_still_flags_duplicates`).

### Added

- **Per-sub-test `effective_weight`** on every `SubTestResult`: the
  sub-test's actual nominal share of `T(D)` in a given audit
  (`axis_weight * within_axis_weight`, record-stratum-adjusted for A6),
  surfaced in `--verbose` CLI output and JSON export. Makes explicit that
  the framework's 24 sub-tests are not equally weighted (e.g. A1+A3+A4
  alone account for most of A(D)'s nominal weight in the common
  intrinsic-only case).
- **Evidence-coverage safety gate**: a new diagnostic
  (`CertifyResult.evidence_coverage`) reporting what fraction of `T(D)`'s
  nominal calibrated weight was backed by applicable, computable evidence
  in a specific audit, plus an additive decision rule — an audit that
  would otherwise ADMIT is capped down to CONDITIONAL if evidence coverage
  falls below `--min-evidence-coverage` (default `0.5`, disabled with
  `0`). Never upgrades a decision and never overrides a Stage-1 hard
  override.
- **A6 reproducibility/audit-trail metadata**: every A6 result now records
  `source_name`, `query_timestamp_utc`, and `query_params` (including how
  many reference events were available to match against), across every
  `ExternalCatalogReference` implementation (USGS/EMSC/ISC/LocalCSV/
  Multi/WeightedMulti).
- Automated test suite (`tests/`, 321 tests) is now part of the public
  repository, along with a GitHub Actions CI workflow
  (`.github/workflows/tests.yml`) running the suite across Python
  3.8–3.12 on every push/PR.
- `CHANGELOG.md` (this file).

### Changed

- I5 renamed from "schema drift" to "temporal distribution drift"
  throughout code, comments, and output — the sub-test is an early-vs-late
  two-sample Kolmogorov-Smirnov test on a numeric field's distribution, not
  a structural schema-change detector; the underlying computation is
  unchanged.
- `SubTestResult.effective_weight`'s docstring (`data_certify/results.py`)
  corrected: it described `effective_weight` as a fixed nominal value
  "unaffected by per-audit renormalisation" for every sub-test. That is
  still true for every axis except A — the A6 record-stratum-weighting fix
  above made A1–A6's `effective_weight` genuinely dynamic (varies per audit
  based on how many records A6 corroborates), so the docstring no longer
  matched the code it was documenting. Purely a documentation correction,
  no behavior change.
- README: corrected `--reference-csv` vs `--dataset` documentation (the
  former overrides the A6 reference catalog, it does not select the audit
  target); added an explicit caveat that the default single-source
  (`--reference-source usgs`) mode cannot reach A6's "externally
  contradicted" hard-reject state; documented the new `effective_weight`,
  evidence-coverage gate, and A6 metadata features; disclosed a known,
  unresolved calibration finding (19 genuine false-admits out of 22
  `known_bad` datasets scoring `T(D) >= theta_admit` on the internal
  968-dataset calibration corpus, before Stage-1 hard-override rescue —
  see `data_certify/_constants.py` for the full, unedited history); added a
  "Geographic-scoring fixes" section disclosing the A3/A4/A5 fixes above.

### Known limitations (disclosed, not yet resolved)

- The internal 968-dataset calibration corpus, corruption/fabrication
  generation scripts, and calibration-fitting tooling are not published;
  external readers can verify the logic in this repository but cannot
  independently reproduce the calibrated weights/thresholds or a
  confusion matrix against that corpus.
- The evidence-coverage gate's `min_evidence_coverage=0.5` default is a
  disclosed, pragmatic choice, not itself empirically calibrated against
  the internal corpus.
- The 19-genuine-false-admit finding above predates the evidence-coverage
  gate; whether/how much the gate changes this figure has not yet been
  re-measured against the private corpus.
- `AXIS_WEIGHTS`/`WITHIN_A`/`theta_admit`/`theta_reject` still reflect
  calibration done under the old (pre-A3/A4/A5-fix) behavior — the fixes
  were verified against the corpus (see entry below) but weights/thresholds
  have not been refit against the corrected scoring functions. Whether
  that refit would change anything is itself an open question the
  verification below does not answer.
- Evidence coverage and the composite score do not yet account for small-N
  statistical power (a high-weight sub-test computed from very few
  applicable records is treated the same as one computed from thousands).
  Empirically confirmed as a live issue, not just a theoretical concern, by
  the A3/A4/A5 re-verification below: 3 of the corpus's tiny (24-29 record)
  real catalogs saw `A(D)` swing between ~0.01 and ~0.94 purely from
  whether a single, sparse aftershock-cluster fit happened to land on
  either side of the degenerate/non-degenerate boundary.

### Verified (2026-07-21) — A3/A4/A5 fixes re-run against the full corpus

The internal 968-dataset calibration corpus and 30-dataset held-out
adversarial set were re-scored under the A3/A4/A5 fixes above (via
`calibration/run_scoring.py` + `score_adversarial_holdout.py --fresh` +
`analysis_three_way_matrix.py`), with `AXIS_WEIGHTS`/`WITHIN_A`/thresholds
held at their current (pre-fix-calibrated) values — this isolates the
effect of the code fix itself from any weight recalibration, which has
*not* been done.

- `A(D)` changed materially (>0.01) for 607/968 datasets; 32/968 changed
  decision (all ADMIT⇄CONDITIONAL — no dataset moved into or out of
  REJECT).
- Pooled false-admit rate on `known_bad` (corrupted_real + fabricated +
  held_out_adversarial, n=490): **19/490 (3.9%), unchanged from the
  pre-fix baseline in count** — but not in composition. 3 previously
  false-admitted `corrupted_real` datasets are now correctly routed to
  CONDITIONAL (the spatial constraint stopped a spatially-incoherent
  event cluster from spuriously fitting an Omori-Utsu decay pattern), 3
  different datasets newly false-admit via the same mechanism running in
  reverse (a spatially-correct cluster now failing the same fit where an
  uncorrected, spatially-loose cluster previously happened to pass). The
  count is coincidentally flat; the underlying behavior is not unchanged.
- False-reject rate on `known_good` (n=508): unchanged at 0/508.
- Held-out adversarial set (n=30): 0/30 ADMIT, 30/30 CONDITIONAL under the
  fixed code (matches the pre-existing prediction in
  `tests/test_adversarial.py::TestGraduatedFabricationLadder::test_level10_adversarial_evades_intrinsic_only_scoring`
  that A6, not intrinsic scoring, is the load-bearing defense at this
  fabrication tier).
- Net assessment: the fixes are real, verified-correct geographic bugfixes
  with a material per-dataset effect, but they were not the dominant
  driver of this project's pre-existing false-admit finding — that finding
  persists, in a different specific composition, after the fix.

Full breakdown in `calibration/group_b_reports/three_way_matrix_report.txt`
(internal corpus, not published).
