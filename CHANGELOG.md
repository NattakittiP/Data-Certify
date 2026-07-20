# Changelog

All notable changes to DATA-CERTIFY are documented in this file.

## [0.1.1] — 2026-07-21 (CI fixes appended same day, after first push)

Two real, previously-undiagnosed CI failures were found from the actual
GitHub Actions logs (first push of this release) and fixed. Both share one
root cause: the public test suite assumed files/modules that `.gitignore`
deliberately excludes from GitHub were present -- true on every local
checkout (which has everything), false on a clean clone.

### Fixed

- **4 tests in `tests/test_adversarial.py::TestGraduatedFabricationLadder`
  failed with `ModuleNotFoundError: No module named 'calibration'`.**
  These tests did `from calibration import corrupt as _corrupt` to
  generate synthetic fabricated catalogs, but `calibration/` is
  intentionally gitignored (private corpus-building tooling). Fixed by
  extracting the two pure, deterministic generator functions these tests
  actually need (`fabricate_level1`, `fabricate_level10_adversarial`, and
  their shared `fabricate_graduated`/`_omori_like_times` engine) into a new
  self-contained `tests/_adversarial_fabrication.py`, credited back to
  `calibration/corrupt.py` as the origin. No private corpus data is
  involved -- these are procedural generators only -- so this does not
  change what's actually private; `calibration/corrupt.py` remains the
  authoritative copy for the maintainer's own corpus-building use.
- **`tests/test_gem_active_faults_database.py::TestDefaultPathDetection::
  test_default_gem_geojson_path_finds_repo_bundled_file` failed:
  `assert None is not None`.** The test's own claim ("this repo ships
  `Dataset/GAF-DB/gem_active_faults_harmonized.geojson`") was false for the
  public repository -- `Dataset/` is gitignored in its entirety. Fixed by
  publishing `Dataset/GAF-DB/` specifically (the GEM Global Active Faults
  Database, CC-BY-SA 4.0, already public at
  github.com/GEMScienceTools/gem-global-active-faults) with an
  `ATTRIBUTION.md` satisfying the license's attribution requirement, while
  the rest of `Dataset/` (private raw catalog CSVs) remains excluded, same
  pattern already used for `datasets/nz/`+`datasets/chile/`.
- **`tests/test_hard_override.py::test_isolated_violation_in_large_dataset_
  does_not_fire` failed on the Python 3.12 CI job only:
  `OverflowError: Overflow in datetime64 + timedelta64 addition`.** This
  test builds a 100,000-record dataset via `conftest.py`'s `make_dataset`,
  whose default `origin_time` spacing is one day per record starting
  2020-01-01 -- at n=100,000 that spans ~274 years, landing around the
  year 2294, past `datetime64[ns]`'s representable ceiling (the
  well-known ~292-year-from-epoch limit, i.e. roughly year 1678-2262).
  Confirmed by direct reproduction that this was ALREADY a latent bug on
  every numpy version, including the one this sandbox uses (numpy 2.2.6):
  `(base_time + np.arange(100_000) * np.timedelta64(1, "D"))` silently
  **wraps around to a garbage date** (`1709-03-27...`) rather than
  erroring -- it just happened not to matter for this specific test
  (which only checks that a `latitude=999` violation gets quarantined,
  not the dates themselves). Whatever newer numpy release pip resolved
  specifically for the Python 3.12 CI job added a proper overflow check
  that raises instead of silently corrupting the date, surfacing the
  latent bug as a hard failure. Fixed by overriding `origin_time` in this
  one test with 1-second spacing instead of relying on the shared
  fixture's 1-day default (origin_time is irrelevant to what this test
  actually checks) -- still exercises the same 100,000-record P1-P3
  non-trivial-fraction logic, just without silently overflowing the date
  range. Audited the rest of the suite for any other `make_dataset`/
  `make_gr_dataset` call with `n` large enough to risk the same overflow
  (the safe ceiling is roughly n<88,000 given the default 1-day spacing
  from 2020) -- no other test exceeds `n=25,000`.

Second external-review pass (same day as 0.1.0, following up on a review of
the tagged 0.1.0 release itself). Also corrects a release/tag mismatch: the
`v0.1.0` git tag pointed at an earlier commit that predated the A3/A4/A5
geographic-projection and dense-bucket fixes described in 0.1.0's own
changelog entry below. `v0.1.1` is the first tag guaranteed to point at a
commit whose actual code matches its changelog entry.

### Fixed

- **Omori-Utsu weighted-least-squares regression minimized the wrong
  objective.** `fit_omori_utsu` (`data_certify/stats.py`) reduced weighted
  least squares to OLS by multiplying both the design matrix and target by
  the raw per-bin count weight `w`, which minimizes `sum(w^2 * r^2)` — not
  `sum(w * r^2)`, the quantity the function's own reported `sse` claims to
  be minimizing. The correct reduction multiplies by `sqrt(w)` instead
  (`sqrt_w = np.sqrt(w)`, applied to both the design matrix and target).
  Fixed; verified against the existing regression suite
  (`tests/test_scientific_validity.py::TestOmoriUtsuFit`, 8/8 pass) and via
  a standalone before/after simulation (true `p`=0.9/1.1/1.4 recovered with
  comparable, sometimes larger, sometimes smaller error under the fix —
  e.g. p=1.4: 6.15% error (old, wrong objective) vs. 4.40% (new, correct
  objective); p=0.9: 2.27% vs. 4.94%). Disclosed honestly: this is a real
  mathematical-consistency fix, not a demonstrated large accuracy
  improvement in either direction — the previous inconsistency was modest
  in practice for the catalogs tested, but the objective function itself
  was wrong and is now correct.

### Added

- **Sample-sufficiency safety gate** (`CertifyResult.sample_sufficiency`,
  `DataCertifyAuditor(min_sample_sufficiency=0.5)`, CLI
  `--min-sample-sufficiency`): a new diagnostic and additive decision rule
  distinct from evidence coverage above. Evidence coverage answers "did an
  applicable sub-test run and produce a score at all"; it cannot tell a
  score built from a single fitted Omori-Utsu cluster apart from one built
  from a few hundred. Sample sufficiency answers the separate question —
  of the sub-tests that DID run, how much of their combined nominal weight
  rests on an underlying sample size (`n_used`, newly reported in each
  A1–A5 `SubTestResult.detail`) that meets a disclosed, provisional
  `MIN_RELIABLE_N` floor per sub-test (`data_certify/_constants.py`: A1=30,
  A2=10, A3=2 independent clusters, A4=50, A5=2). Like
  `min_evidence_coverage`, this only ever caps an otherwise-ADMIT decision
  down to CONDITIONAL, never overrides Stage 1, and is a pragmatic,
  disclosed default — not itself corpus-calibrated. Currently scoped to
  axis A (A1–A5) only; extending `MIN_RELIABLE_N` to P/C/I sub-tests is
  disclosed future work, not silently assumed unnecessary. Directly
  addresses the small-N / false-admit finding from the 2026-07-21 external
  review (tiny 24–29 record catalogs where only A3+A5 were applicable at
  all, each backed by a thin sample).
- **A5 candidate-cap diagnostics**: `_score_a5_duplicates`'s dense-bucket
  safety valve (`MAX_A5_NEIGHBORHOOD_CANDIDATES`) could silently turn an
  exact `duplicate_fraction` into a sampled approximation with no record of
  it happening. Every A5 `SubTestResult.detail` now reports
  `candidate_cap_triggered`, `n_capped_queries` (how many of the dataset's
  record-queries hit the cap), `max_candidates_observed` (the largest raw
  3×3-neighbourhood candidate list seen before subsampling), and
  `sampling_fraction` (the most aggressive subsampling ratio actually
  applied) — surfaced in the sub-test's note when triggered, and in JSON
  export via `detail`.
- 11 new regression tests covering the WLS fix, the `n_used` field on every
  A1–A5 `SubTestResult`, the A5 candidate-cap diagnostics, and the
  sample-sufficiency gate's constructor validation / additive-only /
  disable-hatch behaviour (`tests/test_axis_authenticity.py::
  TestSampleSufficiencyDiagnostics`, `tests/test_decision.py::
  TestSampleSufficiencyGate`) — full suite now 332 tests, all passing
  locally across the changes in this release.

### Re-verified (2026-07-21) — full 968-dataset corpus + 30-dataset adversarial holdout re-run

Both the main calibration corpus and the adversarial holdout were re-scored
against this release's code (WLS fix + sample-sufficiency gate + A5
diagnostics) using the real corpus, run by the maintainer:

- `calibration/run_scoring.py` — all 968 datasets scored successfully under
  the fixed code.
- `calibration/score_adversarial_holdout.py --fresh` — all 30 held-out
  adversarial datasets re-scored: **0/30 ADMIT, 30/30 CONDITIONAL, 0/30 hard
  override fired**, identical to the pre-0.1.1 result — the fixes in this
  release do not change this axis of behaviour, as expected (none of them
  touch A6, the documented load-bearing defense against this adversarial
  tier).
- `calibration/refit_full_corpus.py` — **reproduces the exact same
  degenerate-refit finding already documented above** ("Investigated and
  rejected" section): refit `theta_admit=1.0`, refit `theta_reject=0.34`,
  77.58% decision agreement with current production (217/968 disagreeing,
  same count as previously documented), A3 within-axis weight refitting
  down from 0.42 to 0.198 and A1 up to 0.52. This is a precise
  reproduction, not a coincidence — it confirms the WLS fix and the new
  sample-sufficiency gate do not materially move the corpus's raw
  per-sub-test scores enough to change this pre-existing conclusion.
  **`AXIS_WEIGHTS`/`WITHIN_A`/`theta_admit`/`theta_reject` remain
  unchanged in `data_certify/_constants.py` for this release**, for the
  same reason documented in "Investigated and rejected" below: the refit's
  headline 0% false-admit rate is a ceiling artifact (ADMIT becomes
  practically unreachable), not a genuine improvement.

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
  calibration done under the old (pre-A3/A4/A5-fix) behavior. A refit
  against the corrected scoring functions WAS attempted (see "Investigated
  and rejected" entry below) and found to produce a worse, degenerate
  result — current values are being kept deliberately, not by omission.
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

### Investigated and rejected (2026-07-21) — full weight/threshold refit against fixed scores

A full recalibration of `AXIS_WEIGHTS`/`WITHIN_A`/`theta_admit`/
`theta_reject` against the A3/A4/A5-fixed score matrix was attempted
(`calibration/compute_ewm.py` → `calibrate_thresholds.py` →
`refit_full_corpus.py`) and deliberately **not applied** to
`data_certify/_constants.py`, for two reasons:

- **`calibrate_thresholds.py` does not actually recompute thresholds from
  current data.** Its `NEW_THETA_ADMIT`/`NEW_THETA_REJECT` are hardcoded
  literals frozen from an earlier calibration pass (2026-07-07, 89-dataset
  corpus). Running it against the current 968-dataset, A3/A4/A5-fixed
  score matrix only validates those old literals against new data; it does
  not derive new ones. Its unchanged "0.75 → 0.75" output should not be
  read as confirmation that no recalibration is needed.
- **`refit_full_corpus.py`'s live, independent re-derivation produces a
  degenerate result.** `compute_ewm.py` (which genuinely does recompute
  from the current corpus) shows the fixed scores would shift A3's
  within-axis weight from 0.42 down to 0.20 and A1's up from 0.38 to 0.52.
  Feeding that refit weight vector through `refit_full_corpus.py`'s
  threshold grid-search forces `theta_admit` to **1.0**: under the refit
  weights, several mild `corrupted_real` datasets (e.g.
  `corrupt_real_202506_turkey_magnitude_gr_violation_med` at
  `T(D)=0.9973`) score between 0.989 and 0.997 — indistinguishable from
  genuine data — so the "zero known-bad clears theta_admit" rule has
  nowhere to go but the ceiling. The refit's reported 0% false-admit rate
  is an artifact of that ceiling (ADMIT becomes practically unreachable —
  only 77.6% decision agreement with current production, 217/968 datasets
  disagreeing, the overwhelming majority being real `known_good` catalogs
  losing clean ADMIT status), not a genuine improvement in known-good/
  known-bad separation.

Read as a methodology finding, not just a rejected number: pure
Entropy Weight Method reweights criteria by variance/entropy observed
across the corpus, which is not the same thing as discriminative power
against *known* corruptions, and can silently discard the latter when
optimizing for the former. `AXIS_WEIGHTS`/`WITHIN_A`/`theta_admit`/
`theta_reject` remain at their current, AHP-anchored values as a result
of this investigation, not for lack of one.
