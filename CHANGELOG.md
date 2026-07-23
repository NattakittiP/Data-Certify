# Changelog

All notable changes to DATA-CERTIFY are documented in this file.

## [0.1.4] — 2026-07-24 (Default reference-source change + decision-logic single-sourcing)

### Changed (BREAKING for anyone relying on the old CLI default)

- **`run_audit.py --reference-source` default changed from `usgs` to
  `multi`.** Motivation: single-source A6 (`usgs`, `emsc`, or `isc` alone)
  can only ever reach the "corroborated" or "unverifiable" states —
  `A6_CONTRADICTED_MIN_SOURCES=2` (`data_certify/_constants.py`) means the
  "externally contradicted" Stage-1 hard-reject path is structurally
  unreachable with fewer than two independently-queried sources, so the
  old default shipped a strict subset of A6's disclosed capability. `multi`
  (USGS+EMSC+ISC, `--min-corroborating-sources=2`) is now the default so a
  fresh install gets the full capability out of the box. Trade-off: three
  live network dependencies instead of one, i.e. more latency and more
  exposure to any one source being degraded/rate-limited — see the new
  `--max-reference-wait` flag immediately below, which exists specifically
  to bound this. Pass `--reference-source usgs` to restore the old,
  lower-latency, single-source default. `_build_reference()`'s and
  `--reference-source`'s own help text, and README.md's "A6: three-state
  external cross-validation" section, were updated to match. The
  `.github/workflows/tests.yml` CI smoke test is unaffected (it already
  runs with `--offline`, which bypasses `--reference-source` entirely).

### Added

- **`run_audit.py --max-reference-wait`** (default: `180.0` seconds): an
  OVERALL wall-clock budget for the entire A6 external-reference step
  (all sources, all paginated requests combined), distinct from the
  pre-existing `--timeout` (a PER-REQUEST cap). Motivation: A6's
  pagination can issue up to `_PAGINATION_MAX_TOTAL_REQUESTS=500` requests
  per source, and `multi`/`weighted-multi` now query three sources by
  default — a per-request timeout alone does not bound the TOTAL time a
  single `.audit()` call can take, and a real prior investigation
  (`calibration/run_a6_scoring.py`'s `SCORE_ONE_TIMEOUT_SEC` comment)
  documented live cases of 5+ hours under a known EMSC/ISC pagination
  pathology before any such budget existed anywhere in this codebase.
  Implemented via `_audit_with_wallclock_budget()`, reusing the exact
  `threading.Thread(daemon=True)` + `queue.Queue` pattern already
  battle-tested (and already documented as fixing two real bugs) in
  `calibration/run_a6_scoring.py`'s `score_one_with_timeout()`, rather than
  `concurrent.futures.ThreadPoolExecutor` (which that function's own
  docstring shows does not actually bound wall-clock time when used as a
  context manager, and whose worker threads are not daemon threads by
  default). On timeout, `audit_dataset()` prints a warning and
  automatically falls back to an OFFLINE re-audit (A6 not applicable, A1-A5
  intrinsic scoring only) so the command still completes rather than
  hanging indefinitely — the same graceful-degradation philosophy already
  documented for the plain "source unreachable" case. Default `180.0`
  (3 minutes) chosen relative to the largest legitimate case observed to
  date (~90s, the `chile` corpus dataset against ISC — see `--timeout`'s
  own help text), leaving comfortable margin while still bounding
  pathological cases to minutes rather than hours. Set to `0` or negative
  to disable (unbounded, pre-2026-07-24 behavior). Ignored with
  `--reference-csv` or `--offline`.

### Fixed (code-duplication / drift-risk hardening, not a behavior change)

- **Single-sourced the Stage-2 decision logic.** Before this release,
  `data_certify/decision.py`'s `DataCertifyAuditor.audit()` and
  `calibration/_analysis_common.py`'s `assign_decision_gated()` (used by
  every Group-B post-hoc analysis report) each contained their OWN
  hand-written implementation of the Stage-2 threshold rule and the four
  ADMIT-eligibility gates — exactly the class of duplication that allowed
  the 2026-07-21 gate-awareness bug (the analysis pipeline silently
  applying a different decision rule than production) to happen in the
  first place. Extracted two new pure functions in `decision.py`:
  `assign_stage2_decision(trust_score, theta_admit, theta_reject)` (the
  three-way threshold rule) and `apply_admit_eligibility_gates(...)` (the
  four gates, in the same order production applies them, returning an
  `AdmitGateOutcome` with per-gate fired flags so callers can still build
  their own caveat text). `DataCertifyAuditor.audit()` now calls both
  directly. `calibration/_analysis_common.py`'s `assign_decision_gated()`
  now calls `apply_admit_eligibility_gates()` once per already-ADMIT row
  (negligible cost — a few tens of rows on the full 968-dataset corpus,
  and this function is not called inside `analysis_decision_stability.py`'s
  2000-draw Monte Carlo loop, which deliberately stays on the plain,
  gate-free `assign_decision()`). `assign_decision()` itself is
  deliberately KEPT as an independent vectorized implementation for that
  hot-loop's sake, but is now guarded by a new
  `_unit_test_assign_decision_matches_stage2()` self-check (runs
  automatically on import, same fail-loud-on-import philosophy as this
  file's existing self-checks) that verifies it against
  `assign_stage2_decision()` on an exhaustive grid of boundary/edge-case
  values. `calibration/run_scoring.py`'s `decision_ahp_only` diagnostic
  column now also calls `assign_stage2_decision()` instead of a hand-copied
  `>=`/`elif` chain. Verified byte-for-byte behavior-preserving: full test
  suite passes unchanged, and a fresh `assign_decision_gated()` run against
  the real 968-dataset corpus reproduces the exact previously-disclosed
  numbers (32/508 known_good ADMIT gated, 6.30%; 3/460 known_bad ADMIT
  gated) to the row.
- **New regression test**: `tests/test_decision_score_matrix_consistency.py`
  runs `DataCertifyAuditor.audit()` (production) and
  `calibration/run_scoring.py`'s `score_one()` fed into
  `calibration/_analysis_common.py`'s `composite_score()` +
  `assign_decision_gated()` (the calibration reconstruction path every
  Group-B report relies on) independently on the same bundled datasets
  (`nz`, `chile`, `fabricated_level1_1`, `fabricated_naive_1`) and asserts
  they reach the same decision — the automated guard the 2026-07-21
  gate-awareness bug never had. Wired into the existing `pytest tests/`
  CI job (`.github/workflows/tests.yml`); no separate CI step needed.

## [0.1.3] — 2026-07-21 (ADMIT-eligibility gates + Group-B analysis-pipeline gate-parity fix)

This release bundles two same-day, directly-related changes into one
tagged version: the root-cause diagnosis and new ADMIT-eligibility gates
(originally below, now the "Root cause and gate design" section further
down this entry), and the follow-up fix making the rest of the Group-B
analysis pipeline gate-aware (immediately below). Both are part of the
same fix and are released together rather than as separate versions.

### Part 1 — calibration analysis-pipeline gate-parity fix, follow-up

Follow-up to Part 2 below: that part diagnosed the root cause (the
paper's analysis pipeline never applied the two pre-existing safety
gates, nor the two new ADMIT-eligibility floors) and fixed the ONE report
most directly responsible for the disclosed 19/490 headline number
(`calibration/analysis_three_way_matrix.py`). This part finishes the job
across the REST of the Group-B analysis pipeline, so no script in
`calibration/` can silently reproduce the stale, gate-free 19/490 (3.9%)
figure going forward.

### Added

- **`calibration/_analysis_common.assign_decision_gated()`**: a new
  function reproducing the REAL, fully-gated production decision path
  (Stage 1 hard override + Stage 2 theta thresholds + min_evidence_coverage/
  min_sample_sufficiency safety gates + min_n_records_for_admit/
  min_applicable_subtests_for_admit ADMIT-eligibility floors) exactly as
  `DataCertifyAuditor.audit()` applies them, in the same order, with the
  same never-upgrades/never-overrides-hard-override semantics. Requires
  `evidence_coverage`/`sample_sufficiency`/`n_records`/
  `n_applicable_subtests` columns in the input DataFrame (raises `KeyError`
  with an actionable message, rather than silently falling back to the
  ungated behavior, if a caller passes a pre-fix `score_matrix.csv`).
  Supports `respect_hard_override=False` for the "weighted_sum_only"
  mechanism-ablation arm. A new `_unit_test_gate_defaults_match_production()`
  self-check (runs automatically on import) guards the two hand-copied
  `PRODUCTION_MIN_EVIDENCE_COVERAGE`/`PRODUCTION_MIN_SAMPLE_SUFFICIENCY`
  constants against `DataCertifyAuditor.__init__`'s real defaults via
  `inspect.signature`, raising immediately if they ever drift out of sync.
  The original `assign_decision()` is UNCHANGED and remains available for
  callers that legitimately need Stage-1+2-only logic (see below).
- **`calibration/run_scoring.py` / `calibration/score_adversarial_holdout.py`**:
  `score_one()` in both now also computes and writes `evidence_coverage`,
  `sample_sufficiency`, and `n_applicable_subtests` per dataset (via the
  same `_assign_effective_weights`/`_compute_evidence_coverage`/
  `_compute_sample_sufficiency`/`_compute_n_applicable_subtests` functions
  `decision.py` itself uses), computed from the axis_results already scored
  -- no re-scoring, no change to either script's existing
  performance-critical design (raw per-criterion scores are still recorded
  even when hard-override fires, needed for EWM). `calibration/score_matrix.csv`
  and `calibration/score_matrix_adversarial_holdout.csv` were regenerated
  with these three new columns for all 968 + 30 datasets (verified: every
  regenerated value matches an independent live `DataCertifyAuditor.audit()`
  re-run on a spot-checked sample, to floating-point precision).

### Fixed

- **`calibration/analysis_three_way_matrix.py`** (the script generating
  `calibration/group_b_reports/three_way_matrix_report.txt`, source of the
  originally-disclosed 19/490 figure): now reports BOTH the real, gated
  decision (`decision`, via `assign_decision_gated()`) AND the original
  Stage-1+2-only decision (`decision_ungated`), clearly labeled side by
  side in every matrix/headline/breakdown, so the size of the gates'
  effect is visible in the report itself rather than only in this
  changelog. Regenerated: false-admit 3/490 (0.61%, 95% CI [0.21%,1.78%])
  gated vs. 19/490 (3.88%) ungated; known_good ADMIT 32/508 (6.30%) gated
  vs. 98/508 (19.29%) ungated; known_good false-reject 0/508 unchanged.
- **`calibration/analysis_selective_classification.py`** (Group B5): its
  single `decision` variable -- reused for the "current production
  operating point," the per-group breakdown, the risk-coverage curve's
  reference decision, and the "full_two_stage (production)"/
  "weighted_sum_only" utility-analysis policies -- now uses
  `assign_decision_gated()` (respecting hard override for the production
  policy, `respect_hard_override=False` for weighted_sum_only). This
  report previously stated `false_admit=19` in its "current production
  operating point" section with no gate caveat at all; regenerated, it now
  correctly shows `false_admit=3`.
- **`calibration/analysis_ablation.py`** (Group B3): `eval_arm()` gained a
  `gated` parameter. The weight-vector ablation's `blended_current` row
  (the actual production weight vector, previously shown with
  `false_admit_rate=19/490` and no caveat) now uses the gated decision;
  every OTHER weight-vector row (ahp_only, ewm_only, equal_weight, the four
  single-axis arms) deliberately remains ungated, with an explicit report
  note explaining why gating them would be scientifically incoherent
  (evidence_coverage/sample_sufficiency are fixed values computed under the
  CURRENT production weight basis -- applying them against a T(D) computed
  under a DIFFERENT weight vector mixes two incompatible bases). The
  mechanism ablation's `full_two_stage` and `weighted_sum_only` arms (both
  already on the production weight basis) are now also gated;
  `hard_override_only` is correctly left untouched (it has no composite
  score at all, so Stage 2's gates do not apply to it by construction).

### Scope note (not a fix -- a disclosed, deliberate limitation)

- **`calibration/analysis_decision_stability.py`** (Group B4, Monte Carlo
  weight/threshold sensitivity analysis) was NOT changed to use
  `assign_decision_gated()`, and this is intentional: 2000 of its own
  draws each use a DIFFERENT, randomly-perturbed weight vector, and
  `evidence_coverage`/`sample_sufficiency` are fixed values computed only
  under the CURRENT production weight basis -- gating a per-draw T(D)
  against a fixed-weight-basis metric has no coherent interpretation the
  same way the ablation script's non-`blended_current` rows do not. A
  scope-note disclosure was added to both the module docstring and the
  report's own text making this explicit: this script answers "how stable
  is the raw Stage-1+2 threshold rule under perturbation," not "how stable
  is the final gated production decision" -- a related but different, and
  currently unanswered, question.

### Verification

Three independent verification passes were run before this fix was
considered complete (per the same standard as the gate implementation
itself): (1) a from-scratch, independent recomputation of every headline
number (false-admit rate, Wilson CI, PPV/NPV, the 4 residual false-admit
cases, current max known_bad T(D)) directly from `score_matrix.csv` and
the manifests, with no formula or arithmetic discrepancies found; (2) a
line-by-line code review of every changed file (gate ordering/composition,
NaN/None handling, A6 weight-blending arithmetic, the boolean-mask
recomputation risk in `assign_decision_gated()`, correct placement of the
new diagnostic-computation block relative to the hard-override try/except)
plus a full test-suite run (332/332 passing) and a live spot-check proving
the evidence-coverage gate is a real, functioning cap and not a no-op; (3)
a repo-wide consistency sweep confirming CHANGELOG.md/README.md/
`_constants.py`'s numbers agree with each other and with the regenerated
reports, which surfaced the two stale reports (`ablation_report.txt`,
`selective_classification_report.txt`) fixed above.

### Part 2 — Root cause and gate design: ADMIT-eligibility gate + gate-aware re-audit

Prompted by a paper-readiness review of the disclosed 19/490 (3.9%)
false-admit finding: is 3.9% acceptable, under what use case, what is its
confidence interval, how does it move with prevalence, why is
theta_admit=0.75 the right cut, and should small/thin catalogs be
categorically barred from ADMIT? Investigating these questions surfaced a
finding that changes the headline number itself, before any new gate was
even added.

### Found

- **The published 19/490 (3.9%) false-admit rate does not reflect what a
  real user of `DataCertifyAuditor`/`run_audit.py` experiences.**
  `calibration/_analysis_common.py`'s `assign_decision()` — used by every
  Group-B paper analysis report, including `three_way_matrix_report.txt`
  where 19/490 is disclosed — implements only Stage 1 (hard override) +
  Stage 2 (theta_admit/theta_reject) threshold logic. It does not apply
  the two safety gates (`min_evidence_coverage`, `min_sample_sufficiency`)
  that `DataCertifyAuditor` has applied by default in production since
  their introduction. A full re-audit of all 998 corpus + adversarial-
  holdout datasets using the actual `DataCertifyAuditor.audit()` call
  (not a threshold replica) found these two existing gates ALONE already
  cut false-admit from 19/490 (3.88%) to 4/490 (0.82%), at the cost of
  known_good's ADMIT rate falling from 98/508 (19.29%) to 35/508 (6.89%).
  known_good false-reject stayed 0/508 throughout. This gap between
  "what the paper's analysis pipeline measures" and "what the shipped
  code does" was previously undisclosed and is a distinct issue from the
  3.9% figure itself.
- The 4 residual false-admits after the existing gates
  (`corrupt_real_miyazaki_2024-2025_magnitude_gr_violation_med` n=46,
  `corrupt_real_tohoku_202511_inject_missingness_low` n=67,
  `corrupt_real_ridgecrest_california_2019_coordinate_jitter_low` n=108,
  `corrupt_real_azerbaijan_general_magnitude_gr_violation_med` n=310) all
  have evidence_coverage >= 0.70 and sample_sufficiency = 1.0 already —
  not a coverage/small-sample problem, but mild corruptions
  (magnitude-Gutenberg-Richter violation, low missingness, low coordinate
  jitter) that a well-powered test battery still doesn't flag strongly
  enough. This is a materially different, harder failure mode than "not
  enough evidence," and is why the new gate below only closes 1 of the 4.

### Added

- **`MIN_N_RECORDS_FOR_ADMIT=50` / `MIN_APPLICABLE_SUBTESTS_FOR_ADMIT=8`**
  (`data_certify/_constants.py`, wired through `DataCertifyAuditor.__init__`
  in `decision.py` and exposed as `--min-n-records-for-admit` /
  `--min-applicable-subtests-for-admit` in `run_audit.py`): two new,
  disclosed, additive-only ADMIT-eligibility floors, following the exact
  pattern of the existing `min_evidence_coverage`/`min_sample_sufficiency`
  gates (cap ADMIT down to CONDITIONAL only; never touch REJECT or the
  Stage-1 hard override). Unlike the two existing gates, which are
  WEIGHT-FRACTION metrics coupled to whatever `AXIS_WEIGHTS`/`WITHIN_*` are
  currently live, these two are raw, weight-independent COUNTS (total
  record count; number of distinct non-hard-gate sub-tests applicable and
  computable this audit), chosen to stay meaningful across future
  recalibration passes. See `_constants.py`'s inline comment for the full
  empirical derivation (grid search over candidate thresholds) and
  disclosed limitations.
- **`CertifyResult.n_applicable_subtests`**: new field (also printed in
  `str(result)` and `run_audit.py`'s summary) reporting the raw count (out
  of a possible 20) of non-hard-gate sub-tests that were applicable and
  produced a computable score, independent of their nominal calibrated
  weight.

### Result (verified against live code, full 998-dataset corpus + holdout)

| | gate-free (paper's current disclosed number) | + existing gates (0.5/0.5) | + new ADMIT-eligibility floors (this change) |
|---|---|---|---|
| known_bad -> ADMIT (false-admit) | 19/490 = 3.88%, 95% CI [2.50%, 5.98%] | 4/490 = 0.82% | **3/490 = 0.61%, 95% CI [0.21%, 1.78%]** |
| known_good -> ADMIT | 98/508 = 19.29% | 35/508 = 6.89% | **32/508 = 6.30%** |
| known_good -> REJECT (false-reject) | 0/508 | 0/508 | 0/508 |
| held_out_adversarial (n=30) -> ADMIT | 0/30 | 0/30 | 0/30 |

The new floors close 1 of the 4 remaining false-admits (the n=46 case);
the other 3 (n=67, n=108, n=310) clear both floors comfortably and remain
a genuine, disclosed residual. Reproduction: `DataCertifyAuditor()`'s
defaults now include both new gates; re-running the full corpus is a
one-line re-invocation of the existing scoring path, no separate script
needed.

### Paper-readiness framing (answers to the six questions above)

1. **Under what use case is a ~0.6% false-admit risk acceptable?** ADMIT is
   the compensatory, no-remaining-caveat top tier of a three-tier decision
   (ADMIT/CONDITIONAL/REJECT), not a binary go/no-go gate — CONDITIONAL
   already means "route to human review before use," which is the correct
   response to ~93.7% of known_good catalogs under current thresholds.
   Read narrowly, "~0.6% of known-bad catalogs slip past the strictest
   tier" is acceptable specifically in workflows where ADMIT triggers
   *reduced*, not *zero*, downstream scrutiny (e.g., skip a redundant
   manual QC pass, not skip disaster-response decision review entirely),
   and where a human or secondary system remains in the loop for
   consequential actions. It is not acceptable as the sole gate before an
   irreversible, high-stakes automated action with no human in the loop —
   see point 5.
2. **Confidence interval**: Wilson score interval (matches this project's
   existing convention in `_analysis_common.py`'s `wilson_ci`), computed
   against the live-code result: 3/490, 95% CI **[0.21%, 1.78%]**. (For
   reference, the previously-disclosed gate-free 19/490 figure's CI was
   [2.50%, 5.98%].)
3. **Predictive value under shifting prevalence**: using this corpus's
   measured operating point (P(ADMIT | good) = 32/508 = 6.30%,
   P(ADMIT | bad) = 3/490 = 0.61%) and Bayes' rule across assumed
   prevalence of bad catalogs in the *incoming, unvetted* population (not
   this balanced 49/51 calibration corpus):

   | prevalence(bad) | PPV(ADMIT implies actually good) | 1 − NPV(non-ADMIT implies actually good) |
   |---|---|---|
   | 5% | 99.49% | 5.29% |
   | 10% | 98.93% | 10.54% |
   | 30% | 96.00% | 31.25% |
   | 49.1% (this corpus's actual balance) | 91.43% | 50.57% |
   | 70% | 81.51% | 71.22% |
   | 90% | 53.34% | 90.52% |
   | 95% | 35.13% | 95.27% |

   PPV degrades sharply once the incoming population is itself mostly bad
   (crowd-sourced/unvetted ingestion): at 90% prevalence of bad catalogs,
   only ~53% of ADMITs are actually trustworthy — worse than a coin flip
   in the relevant sense. Practical implication: ADMIT's ~91-99% precision
   only holds for input populations no worse than roughly balanced to
   mildly-bad; any deployment ingesting from a substantially adversarial
   or unvetted source population must not treat ADMIT as reliable at face
   value without re-estimating local prevalence first. Note the low
   sensitivity (only 6.30% of genuinely good catalogs reach ADMIT) is the
   flip side of this same conservatism — the system is tuned to make
   ADMIT rare and precise, not to maximize how much good data reaches it.
4. **Why theta_admit=0.75**: per `calibration/threshold_report.md`'s
   sixth-pass finding, the maximum T(D) among all 460 known_bad datasets
   under the (at-the-time) corrected production formula was 0.6276 — a
   margin of ~0.12 below theta_admit=0.75, the widest, most defensible
   margin available given that known_good/known_bad T(D) distributions
   are otherwise heavily interleaved (0.17-0.63) with no theta_reject-side
   clean separation at all (documented in the same report). Since then,
   further calibration passes (documented in this file's history) shifted
   the corpus and weights enough that some known_bad datasets now do
   exceed 0.75 (hence 19/490, later 4/490, later 3/490 false-admits) —
   theta_admit=0.75 was never re-derived against the current corpus/weight
   combination and should be treated as historically-motivated rather than
   currently re-validated; a fresh margin analysis against the present
   `score_matrix.csv` is the natural next calibration task.
5. **When must the system be prohibited from ever issuing ADMIT?**
   Already partially enforced today: the Stage-1 hard override (P1-P3
   physical-bounds violations, A6 externally-contradicted) forces REJECT
   unconditionally, bypassing T(D) entirely — this is the one true
   "never ADMIT" mechanism in the system. Beyond that hard floor, this
   change adds two soft prohibitions (cap to CONDITIONAL, not force
   REJECT): fewer than 50 records, or fewer than 8 of 20 applicable
   sub-tests computable. Per point 3, a further, currently-unimplemented
   condition belongs on this list: **when the operator cannot bound the
   incoming population's prevalence of bad catalogs to well under ~50%**,
   ADMIT's predictive value cannot be assumed and should not be exposed to
   downstream automation without a human check.
6. **Should small catalogs be capped to CONDITIONAL?** Yes — this is
   exactly what `MIN_N_RECORDS_FOR_ADMIT=50` now does, per the user's
   proposed rule. It closes 1 of the current 4 residual false-admits (the
   n=46 case) at the cost of 3 known_good catalogs' ADMIT rate (35/508 ->
   32/508). The `MIN_APPLICABLE_SUBTESTS_FOR_ADMIT=8` companion floor is
   currently redundant on this corpus (a grid search found it has zero
   marginal effect at any tested value once the record-count floor is
   fixed) but is retained as a forward-looking robustness measure against
   future weight recalibrations that could concentrate weight on very few
   sub-tests. The 3 remaining false-admits (n=67, 108, 310) are NOT a
   sample-size problem — they clear n=50 comfortably — and capping them
   would require a much larger floor (n=350 to reach 0/490, at the cost of
   known_good ADMIT falling to 14/508 = 2.8%); this trade-off is disclosed
   but not acted on here, left as a deliberate choice pending
   maintainer/reviewer input on where the paper wants to sit on this
   curve.

## [0.1.2] — 2026-07-21 (calibration-tooling publish + reproducibility fix)

Corrects the same class of problem `v0.1.1` itself was cut to fix: by the
time `v0.1.1` was tagged, two more commits had already landed on `main`
(the calibration-tooling publish below, and a documentation-accuracy
follow-up), so the `v0.1.1` tag pointed at a commit that predated them —
the exact "tag doesn't match its own changelog" mismatch documented for
`v0.1.0` below. `v0.1.2` is cut specifically so the tag, the package
version, and this changelog entry all point at the same, current commit.

### Added

- **Published `calibration/`**, in response to an external review: a
  Methodology Article reviewer cannot check false-admit rates, threshold
  derivation, or weight calibration without access to the calibration
  tooling, and "available upon reasonable request" is not sufficient on
  its own. Now public: every corpus-building/calibration/analysis script
  (`corrupt.py`, `build_corpus.py`, `run_scoring.py`, `compute_ewm.py`,
  `calibrate_thresholds.py`, `calibrate_hard_override_params.py`,
  `calibrate_theta_auth.py`, `refit_full_corpus.py`,
  `score_adversarial_holdout.py`, `analysis_*.py`, `make_paper_figures.py`,
  and others); both corpus manifests (`corpus_manifest.csv`,
  `adversarial_corpus_manifest.csv` — dataset identity, category, label,
  corruption type/severity, seed, parent catalog, for all 968+30
  datasets); every score matrix (`score_matrix*.csv` — computed `T(D)`/
  sub-test scores per dataset, not raw catalog records); and every
  calibration/analysis report (`bootstrap_stability_report.*`,
  `ewm_report.*`, `hard_override_calibration_report.*`,
  `theta_auth_report.*`, `threshold_report.*`, `group_b_reports/`,
  `group_c_reports/`, `group_d_reports/`). See `calibration/README.md` for
  the complete list and the reasoning behind what's included.
- **Not yet published**: the raw, per-record earthquake-event CSVs the
  corpus's `real`/`corrupted_real` entries were built from/derived from.
  These are deterministically regenerable from the published manifest and
  scripts (same seeds, same corruption parameters applied to the same
  named real source), but are withheld verbatim pending a check of the
  redistribution terms of the original third-party sources (USGS ComCat is
  U.S. public domain; other sources have not yet been individually
  checked). Same reasoning applied to exclude
  `group_d_reports/d1d_multisource/` (raw EMSC/USGS records used in the
  cross-agency merge case study). This is disclosed as a temporary,
  specific gap, not a permanent one.

### Fixed

- Several `README.md`/`CHANGELOG.md`/`Docs/` passages still said
  calibration scripts, reports, and the test suite were private or
  unpublished, predating the publish above (and, for the test suite,
  predating `v0.1.0`). Corrected throughout to match current reality.
  `README.md`'s claim that the GEM Global Active Faults Database is "not
  included in this repository at all" was also stale — it has been bundled
  at `Dataset/GAF-DB/` since `v0.1.1`'s CI fixes — and is corrected here too.

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
  latent bug as a hard failure. **First fix attempt was incomplete**:
  overriding `origin_time` in the test itself wasn't enough, because
  `conftest.py`'s `make_dataset` built its entire `defaults` dict --
  including the unconditional default `origin_time` expression -- as one
  eagerly-evaluated dict literal, THEN called `defaults.update(overrides)`;
  Python evaluates every value in a dict literal regardless of what
  `.update()` does to it afterwards, so the default's overflow-prone
  computation still ran even when a caller supplied its own `origin_time`.
  Properly fixed by making that default computation conditional on
  `"origin_time" not in overrides` in `make_dataset` itself, so a
  caller-supplied override actually skips the unsafe default path instead
  of merely overwriting its result after the fact. Audited the rest of the
  suite for any other `make_dataset`/`make_gr_dataset` call with `n` large
  enough to risk the same overflow via the (now conditional, but still
  present for callers who don't override) default spacing -- no other test
  exceeds `n=25,000`.

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
  confusion matrix against that corpus. **Update (2026-07-21, later the
  same day, reproducibility fix):** the generation scripts and
  calibration-fitting tooling described here ARE now published in
  `calibration/` (see the `[0.1.1]` entry below and `calibration/README.md`),
  along with the corpus manifest, computed score matrices, and every
  calibration report. Only the raw, per-record earthquake-event catalogs
  themselves remain unpublished, pending a redistribution-rights check on
  third-party real-catalog sources — they are deterministically
  regenerable from the now-published manifest and scripts in the interim.
- The evidence-coverage gate's `min_evidence_coverage=0.5` default is a
  disclosed, pragmatic choice, not itself empirically calibrated against
  the internal corpus.
- The 19-genuine-false-admit finding above predates the evidence-coverage
  gate; whether/how much the gate changes this figure has not yet been
  re-measured against the corpus.
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
(published as of 2026-07-21 — see `calibration/README.md`).

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
