# -*- coding: utf-8 -*-
"""
data_certify/_constants.py -- Canonical constants for DATA-CERTIFY.

Single source of truth for every weight and threshold used by the audit.
All other modules import from here so that a value can never silently
diverge between two call sites.

*** CALIBRATED (2026-07-05, revised TWICE that day during an independent
re-verification pass): weights and theta_admit/theta_reject below are no
longer AHP-only priors -- they are the AHP x EWM blended weights and
empirically-derived thresholds computed from a real 73-dataset
calibration corpus (50 real known-good catalogs + 19 disclosed synthetic
corruptions + 4 fully-fabricated catalogs). Two distinct issues were
found and fixed during that pass, in order:

  (1) CORPUS GAP: the corpus grew from 71 to 73 datasets when the
      re-verification discovered that ishikawa_202401.json and
      japan_2023-.json -- present in the original user-supplied file
      list -- had been missed by the initial corpus build and never
      recorded as excluded either; both are genuine, distinct real USGS
      ComCat catalogs and were added as known_good (see
      calibration/parsers.py's prepare_usgs_geojson and
      calibration/corpus_manifest.csv notes).

  (2) CIRCULARITY BUG (more significant): the first re-scoring attempt
      after (1) produced axis-level A/P/C/I values that were
      INCONSISTENT across rows, because calibration/run_scoring.py calls
      the PRODUCTION axis-scoring functions, which read whatever
      WITHIN_A/P/C/I happens to be LIVE in this file at call time -- the
      2 newly-added datasets got scored against this session's own
      already-BLENDED weights, while the original 71 had been scored
      back when these constants still held the pure AHP prior. Fixed by
      making calibration/compute_ewm.py and
      calibration/calibrate_thresholds.py self-correcting: both now
      unconditionally recompute the axis-level columns from the
      underlying (weight-independent) sub-criteria using the fixed
      AHP_PRIOR weights before doing anything else, regardless of
      whatever score_matrix.csv already contains. See
      calibration/compute_ewm.py's recompute_axis_columns_from_ahp_prior
      docstring for the full finding.

*** THIRD CALIBRATION PASS (2026-07-05, later the same day): P4
(tsunami), P5 (Wells & Coppersmith rupture-length), and P6 (moment-
magnitude self-consistency) had ZERO or near-zero real observations in
the original 73-dataset corpus because the corpus's real_XXX datasets
were downloaded via USGS's plain-CSV export format, which never
included tsunami_flag/mmi/seismic_moment_n_m/rupture_length_km columns
at all (confirmed by inspecting a raw source file's header). USGS's own
GeoJSON query endpoint and per-event "moment-tensor"/"finite-fault"
PRODUCTS do carry this data for the same real events already in the
corpus (joined back by the exact USGS event_uid_source id already
present in every USGS-sourced dataset) -- see
calibration/enrich_tsunami_mmi_from_usgs.py and
calibration/enrich_moment_tensor_finite_fault_from_usgs.py. After
backfilling and a full fresh re-score + re-run of compute_ewm.py /
calibrate_thresholds.py:
  - P4 went from 2/73 to 52/73 non-NaN observations -- now DATA-DRIVEN.
  - P5 went from 0/73 to 24/73 -- now DATA-DRIVEN (just clears MIN_EWM_N=20).
  - P6 went from 0/73 to 44/73 -- now DATA-DRIVEN.
  - P8/P9 remain 0/73 (P8 needs a configured fault database, unrelated to
    this enrichment; P9 needs station_distance_km, which is per-station
    ShakeMap/DYFI data outside this enrichment's scope) -- both still
    retain their AHP prior.
  This substantially increased P(D)'s cross-dataset variance budget being
  captured correctly instead of falling back to AHP defaults, which in
  turn shifted EVERY axis's blended weight (not just P's) since EWM's
  budget-normalization is corpus-relative: A(D) rose further (0.682 ->
  0.709), P(D) fell further (0.048 -> 0.036), C(D) fell slightly (0.050
  -> 0.046), I(D) fell slightly (0.220 -> 0.209). theta_admit (0.75) and
  theta_reject (0.45) were RE-VALIDATED against these new weights and
  did NOT need to change -- the known_good/known_bad separation
  (0 false-admits, 0 false-rejects) held at the same values. theta_auth
  is unaffected by this pass (see its own comment below) -- it needed a
  live A6 catalog run, not enrichment of the intrinsic P sub-tests.

*** FOURTH CALIBRATION PASS (2026-07-06): triggered by an EMSC-reference
A6 pilot run on "chile" and "nz" that surfaced THREE real, unrelated bugs:
(a) _estimate_mc_ref could fit an implausibly
low reference-completeness floor from a live query whose own magnitude
floor was set by the audited dataset's own minimum magnitude -- fixed by
MC_REF_GLOBAL_FLOOR=4.5 (data_certify/reference_data.py); (b) "chile"'s
records.csv had origin_time stored in local Chile time (UTC-3/-4)
mislabeled as UTC, verified against the real, documented 2015-09-16
Illapel M8.3 sequence; (c) "chile"'s records.csv also mixed in 626 rows
(0.47%) of far-flung "global significant earthquake" bulletin entries
(e.g. Kamchatka, 15,000+ km away) that CSN Chile publishes alongside its
own local-network detections, which blew up A6's bounding-box query to
near-global scope -- fixed with a data-driven 500 km filter on the raw
source's own distance-from-reference-city field. After (b)+(c), chile's
A6 matched_fraction against the CLI's default USGS reference went from
0.0 (a false positive indistinguishable from confirmed fabrication) to
0.765 (hard_reject_would_fire=False) -- fully resolved. Against EMSC,
chile still shows only 0.055 and "nz" remains low against both sources
(0.391 USGS / 0.335 EMSC); disclosed as an OPEN, NOT-further-investigated
gap (see the Master Reference doc) rather than a fourth bug, since USGS
is the CLI's production default and is fully fixed.

The SAME pass also closed a separate, longstanding gap: P8 (plate-
boundary proximity) had 0/73 observations corpus-wide not because the
data doesn't exist, but because calibration/run_scoring.py never wired a
fault_db into score_plausibility() -- unlike A6, P8 needs NO live
network call, since the real GEM Global Active Faults Database ships
bundled locally under Dataset/GAF-DB/. Wiring it in
(GEMActiveFaultsDatabase via default_gem_geojson_path()) took P8 from
0/73 to 73/73 non-NaN observations, so P8 is DATA-DRIVEN for the first
time this pass. P9 remains 0/73 (still needs station_distance_km, for
which no readily-available public data source exists) and retains its
AHP prior.

Both the corrected chile data and the newly-wired P8 observations feed
into every downstream axis (the chile data-quality fix changes chile's
A1/A3/A4/C-axis/I-axis sub-scores too, not just A6, since those depend on
the same corrected records.csv), so a full 73-dataset re-score +
compute_ewm.py + calibrate_thresholds.py re-run was required. Result:
A(D) rose slightly further (0.709 -> 0.715), P(D) fell slightly (0.036 ->
0.027, despite P8 now being data-driven -- P8's own EWM weight came out
low, 0.048, because plate-boundary proximity showed comparatively little
cross-dataset variance in this corpus), C(D) essentially unchanged
(0.046), I(D) essentially unchanged (0.209 -> 0.212). theta_admit (0.75)
and theta_reject (0.45) were RE-VALIDATED against these new weights and
again did NOT need to change (0 false-admits, 0 false-rejects; see their
own comments below for the fresh margin numbers). theta_auth is
unaffected by this pass for the SAME reason as before -- see its own
comment below -- the chile/nz A6 pilot above was run standalone via
calibration/run_a6_scoring.py, not through calibration/run_scoring.py,
so A6 is still applicable=False throughout score_matrix.csv.

See calibration/ for the full toolchain and calibration/ewm_report.md +
calibration/threshold_report.md for the full numeric reports and
reasoning. theta_auth is the ONE exception -- see its own comment below
for why it remains provisional. ***

*** FIFTH CALIBRATION PASS (2026-07-06, later still the same day): the
corpus's two corrupt_chile_depth_implausible_low/high rows were stale --
they had been derived (via calibration/corrupt.py's depth_implausible())
from the OLD, pre-timezone/geo-contamination-fix 133590-row chile
records.csv, even after chile itself was corrected during the fourth
pass. This meant the fourth pass's blended weights above were computed
against a score_matrix.csv with an internal inconsistency: chile's own
row reflected the fix, but its two corrupted derivatives did not.
Regenerated both derivative datasets from the corrected 132964-row chile
using the exact deterministic seeds calibration/build_corpus.py's
CORRUPTION_PLAN specifies (RandomState(1009) for low severity,
RandomState(1010) for high), re-scored them via calibration/run_scoring.py's
score_one(), and re-ran compute_ewm.py + calibrate_thresholds.py fresh
against the now-fully-consistent 73-dataset corpus. Weight shifts were
small (3rd-4th decimal place) since only 2/73 corpus rows changed: A(D)
0.7153 -> 0.7149, P(D) 0.02729 -> 0.02739, C(D) 0.04582 -> 0.04497, I(D)
0.21162 -> 0.21278.

*** SIXTH CALIBRATION PASS (2026-07-06, still later the same day -- THE
MOST CONSEQUENTIAL FINDING IN THIS FILE'S CALIBRATION HISTORY, found by
running `run_audit.py --dataset chile` live rather than trusting the
fifth pass's own report): the fifth pass (and every pass back to the
2026-07-05 circularity-bug fix) validated theta_reject using a formula
`DataCertifyAuditor.audit()` never actually runs. calibration/calibrate_
thresholds.py recomputed each dataset's A/P/C/I using the AHP_PRIOR
within-axis weights (correct for compute_ewm.py's own entropy input, see
that script's docstring) but then combined those AHP-prior-based A/P/C/I
values with the BLENDED AXIS_WEIGHTS to get T(D) -- a hybrid production
never computes. Production combines sub-criteria into A/P/C/I using the
BLENDED WITHIN_A/P/C/I. For a high-variance criterion like A1 (Benford),
whose blended weight (~53%) is far above its AHP prior (~30%), this
mattered enormously: chile -- the flagship example the whole
theta_reject=0.45 narrative was built on -- recomputes to A(D)~0.49
under the (wrong) AHP-prior basis, giving the previously-reported
T(D)=0.4741 (CONDITIONAL), but its ACTUAL live-production A(D) is ~0.24,
giving T(D)~0.22 (REJECT) -- confirmed by calling score_authenticity()
directly and cross-checked against the live CLI. Once calibrate_
thresholds.py was fixed to combine sub-criteria using the BLENDED
within-axis weights end-to-end (calibration/compute_ewm.py's new
recompute_axis_columns_from_blended helper), the true picture is far
more sobering than any prior pass's "0 false-admits, 0 false-rejects"
claim: 12 of the 50 known_good datasets (not just chile) score below any
plausible theta_reject, and known_good/known_bad T(D) distributions are
heavily interleaved from ~0.17 to ~0.63 (e.g. the known_bad
corrupt_real_morocco_20230908_query_timestamp_collision_high scores
0.6276, higher than all but 12 of the 50 known_good datasets). NO value
of theta_reject cleanly separates the two populations. theta_admit is
UNAFFECTED by this finding and remains safely validated (max known_bad
T(D) under the corrected formula is 0.6276, an even larger margin than
previously reported). theta_reject (0.45 -> 0.20) was revised per this
project's own stated asymmetric-cost principle (Deep-Dive 05 Section
2.1: a false REJECT of genuine data is a real but far smaller cost than
a false ADMIT of bad data) to guarantee ZERO known_good false-rejects,
at the disclosed cost that it now catches only 1 of 15 non-hard-override
known_bad datasets by itself (the remaining 14 rely on CONDITIONAL or on
the Stage-1 hard-override gate, which independently catches 8 of the 23
known_bad datasets regardless of T(D)). See
calibration/calibrate_thresholds.py's module docstring and
calibration/threshold_report.md's "no-clean-separation" section for the
full numeric picture and reasoning. theta_auth is unaffected for the
same reason as prior passes.

*** SEVENTH CALIBRATION PASS (2026-07-07): corpus expansion, undertaken
specifically to address a paper-readiness concern raised about the
sixth pass's 73-dataset corpus (see calibration/bootstrap_stability_report.md,
added the same day, which first quantified the sixth pass's weight
uncertainty via bootstrap resampling). 11 new real USGS-sourced
earthquake catalogs -- covering major historical sequences previously
absent from the corpus (2018 Palu/Indonesia, 2019 Ridgecrest/California,
2016 Amatrice-Norcia/Italy, 2018 Anchorage/Alaska, 2017 Chiapas/Mexico,
2015 Gorkha/Nepal, 2010 Haiti, 2023 Kahramanmaras/Turkey-Syria, 2017
Kermanshah/Iran, 2016 Muisne-Pedernales/Ecuador, 2018 PNG Highlands) --
were added as known_good, plus 4 new corrupted derivatives (one each of
inject_duplicates, timestamp_collision, magnitude_gr_violation,
coordinate_jitter, drawn from 4 of the new real datasets) and 1 new
fabricated_sophisticated catalog, growing the corpus from 73 to 89
datasets (61 known_good, 28 known_bad) while preserving its
~50:19:4 (now ~61:23:5) real:corrupted:fabricated ratio. See
calibration/build_corpus.py's STANDARD_FILES_V7/NEW_CORRUPTION_PLAN
additions for the exact provenance and seeds.

Result: AXIS_WEIGHTS moved only modestly (A 0.7149->0.7110, P
0.0274->0.0335, C 0.0450->0.0446, I 0.2128->0.2108) -- every one of these
new values falls WELL WITHIN the sixth pass's own bootstrap-predicted 95%
CI (A [0.598,0.811], P [0.015,0.044], C [0.033,0.060], I [0.114,0.339]),
which is itself a meaningful (if informal) out-of-sample check that the
bootstrap uncertainty quantification was not badly miscalibrated: a
~22%-larger, more geographically diverse corpus shifted every axis
weight by an amount the bootstrap had already predicted as plausible
sampling noise, rather than moving weights outside the predicted range
entirely. theta_admit (0.75) and theta_reject (0.20) BOTH remain
unchanged in value and both still hold with ZERO known_good
false-rejects and ZERO known_bad false-admits on the expanded corpus --
but the theta_reject margin against the corpus's nearest known_bad
dataset TIGHTENED sharply, from 0.0293 (73-dataset corpus) to 0.0076
(89-dataset corpus, corrupt_nz_inject_missingness_high at 0.1924): this
is a genuine, disclosed finding, not a reassuring one -- it shows
theta_reject=0.20 sits closer to a knife-edge than the sixth pass's own
margin figure suggested, and a future corpus expansion could plausibly
flip it. theta_admit's margin against the corpus's max known_bad T(D)
also tightened somewhat (0.0676, corrupt_real_kahramanmaras_turkey_2023_
timestamp_collision_med at 0.6824, vs the sixth pass's 0.1224 margin) but
remains comfortable. See calibration/threshold_report.md and
calibration/ewm_report.md for the full seventh-pass numeric reports.

*** EIGHTH CALIBRATION PASS (2026-07-10): major corpus expansion, undertaken
specifically to test the seventh pass's own open question ("a future corpus
expansion could plausibly flip [theta_reject's tight margin]") and to push
the bootstrap-quantified weight uncertainty down toward a conventionally
stable band. 144 new real USGS-sourced earthquake catalogs were fetched
(calibration/fetch_corpus_expansion_v8.py) from major geographic regions
absent from the corpus through the seventh pass -- mainland China, the
Indian subcontinent, most of Central/South America beyond Chile/Ecuador/
Peru/Mexico, the Caribbean beyond Haiti, the Balkans, East Africa's rift,
most of the Middle East, Russia's Far East/Siberia/Caucasus, Central Asia,
Hawaii, several deliberately low-seismicity edge cases (Switzerland,
Germany, Greenland, Australia), and induced/volcanic-regime contrasts
(Oklahoma wastewater injection, Yellowstone, Iceland) -- plus 50 new
corrupted derivatives and 12 new fabricated catalogs to roughly preserve
the corpus's ~70:25:6 real:corrupted:fabricated ratio (see
calibration/build_corpus.py's STANDARD_FILES_V8/CORRUPTION_PLAN 8th-pass
additions). Grew the corpus from 89 to 295 datasets (205 known_good, 90
known_bad).

Result: unlike the seventh pass, weights did NOT move "only modestly" --
P(D)'s blended weight nearly DOUBLED (0.0335 -> 0.0770) while I(D)'s fell
substantially (0.2108 -> 0.1692); only A(D) stayed close to its prior value
(0.7110 -> 0.7134). This is a materially different outcome from the
seventh pass's reassuring "shifted within the bootstrap-predicted CI"
finding -- it shows axis weights are not just noisy around a fixed center,
but can move their center under corpus composition changes, which is a
STRONGER form of the "not yet converged" disclosure than previously
demonstrated. Bootstrap CV (2,000 replicates, re-run on the 295-dataset
corpus) improved for every axis -- A 7.2%->3.9%, C 14.8%->8.5%,
I 26.1%->15.6%, P 24.0%->20.1% (P improved least, consistent with its
point estimate itself having shifted the most) -- roughly in line with
1/sqrt(N) scaling for A/C/I but not for P.

Sub-criteria P5 (n_obs=24), P9 (n_obs=0), and I4 (n_obs=4) are UNCHANGED
in observation count from the 89-dataset corpus despite the +206-dataset
expansion -- decisive empirical confirmation (not just an inference) that
these three sub-criteria are limited by the scarcity of a specific
required field in real-world catalogs (station_distance_km for P5/P9,
multi-agency source for I4), not by overall corpus size: no amount of
generic corpus growth will move them further.

theta_reject's margin against the nearest known_bad dataset REVERSED its
prior shrinking trend: 0.0293 (73-dataset corpus) -> 0.0076 (89-dataset
corpus) -> 0.0425 (295-dataset corpus, corrupt_nz_inject_missingness_high
at T(D)=0.2425). This is a genuinely encouraging data point, but should
NOT be read as proof the margin will keep growing -- the 73->89 pass
showed shrinkage, the 89->295 pass showed growth, so the honest disclosure
is that this margin is volatile under corpus composition changes in
either direction, not monotonically trending either way.

theta_admit, however, surfaced a NEW finding the seventh pass's 0.0676
margin claim did not anticipate: under the new blended weights, 6 of the
90 known_bad datasets are now FALSELY ADMITTED (T(D) >= 0.75,
hard_override NOT fired) -- corrupt_real_russia_sakhalin_general_
inject_duplicates_high (0.7581), corrupt_real_usa_puertorico_general_
coordinate_jitter_low (0.7658), corrupt_real_yemen_general_
inject_missingness_low (0.7939), corrupt_real_iran_bam_2003_
inject_duplicates_high (0.9093), corrupt_real_northkorea_general_
magnitude_gr_violation_med (0.9696), and corrupt_real_croatia_
petrinja_2020_timestamp_collision_high (0.9730). All six are corrupted
derivatives of very small source catalogs (n=17-227 records, several
under 30) -- consistent with, and now a concrete instance of, the
already-disclosed finite-N weaknesses of individual sub-tests (A4's
finite-sample bias, Benford's Law needing reasonable N for power) rather
than a new mechanism. Disposition of this finding (recalibrate
theta_admit, exclude very-small-N catalogs from future corpus passes, or
disclose as a new limitation) is a decision for the maintainer -- see
Current_State_and_Limitations_Summary.md for the resolution once made. Until resolved, do
NOT repeat the seventh pass's "0 known_bad false-admits" claim anywhere;
it is no longer true at the 295-dataset scale.

See calibration/threshold_report.md, calibration/ewm_report.md, and
calibration/bootstrap_stability_report.md for the full eighth-pass numeric
reports.

*** NINTH CALIBRATION PASS (2026-07-11): the first pass to add SYNTHETIC
(fabricated) data deliberately shaped along a graduated realism ladder,
rather than the ad-hoc "naive"/"sophisticated" fabrications used in every
prior pass, plus a further real-catalog expansion. Motivated by the
maintainer's own question: would the audit calibrate any differently if it
learned from two distinct kinds of known_bad data (disclosed corruptions of
real catalogs vs. wholly synthetic catalogs), and specifically whether
populating the P5/P9/I4 fields that have sat at 0 or near-0 observations
since the seventh pass in SOME synthetic datasets would move them off their
AHP-prior floor. calibration/corrupt.py gained fabricate_level1..level9 (each
level cumulatively adding one more realistic statistical property --
magnitude distribution, depth distribution, spatial clustering, temporal
(Omori) clustering, metadata completeness, then P5/P9-relevant fields, then
Benford-compliant seismic moment) plus a SEPARATE fabricate_level10_adversarial
that is deliberately held OUT of this calibration corpus entirely (built via
calibration/build_adversarial_corpus.py into datasets_adversarial/, never
touched by build_corpus.py/run_scoring.py/compute_ewm.py -- see that script's
own docstring) to avoid tuning weights against the exact adversarial
construction being evaluated. Corpus grew from 295 to 968 datasets: +303 new
real catalogs (calibration/fetch_corpus_expansion_v9.py, cross-checked
filename-by-filename against the eighth pass's own file list to avoid
double-counting already-present real events -- see
calibration/build_corpus.py's STANDARD_FILES_V9 comment) taking real from 205
to 508; +100 new corrupted derivatives, each drawn from a real source never
before corrupted in any prior pass, taking corrupted from 73 to 173; +270 new
fabricated datasets (levels 1-9, 30 datasets/level), taking fabricated from
17 to 287. known_good = 508, known_bad = 460.

Result: bootstrap CV (2,000 replicates, calibration/bootstrap_ewm_stability.py)
improved sharply for every axis, continuing the corpus-size convergence trend
the seventh/eighth passes had been tracking -- A 3.9%->2.3%, P 20.1%->7.7%
(P was the worst-converged axis in every prior pass; it is now in a
comparable range to the others for the first time), C 8.5%->4.2%,
I 15.6%->7.1%. Axis weights moved further, not just narrowed: A fell
(0.7134->0.6884), P rose sharply again (0.0770->0.1686, more than doubling a
second consecutive pass), C fell slightly (0.0403->0.0281), I fell
(0.1692->0.1150).

I4 (cross-catalog duplicate-ID detection) moved off its AHP-prior floor for
the FIRST TIME in this project's calibration history: n_obs rose from 4 (at
the 89-dataset corpus) to 124, comfortably clearing MIN_EWM_N=20, because
some of the new fabricated datasets were deliberately given populated
event_uid_source values as a direct test of "would EWM weight I4 differently
if the field existed." It now gets a genuine data-driven blended weight
(0.1560 -> 0.0040). P9 (Bakun & Wentworth intensity-distance consistency),
by contrast, remains at n_obs=0 and RETAINS its exact AHP prior unchanged --
the synthetic ladder populated rupture_length_km (feeding P5) but not
station_distance_km (feeding P9), so this pass answers the "would EWM
change" question for I4 but leaves P9 exactly where it was, a disclosed
asymmetry in what the augmentation actually tested. P5 itself jumped from
n_obs=24 (barely clearing MIN_EWM_N) to 90 and its blended weight rose
sharply (0.0125 -> 0.7657) as a direct consequence. P6 (moment-magnitude
self-consistency) picked up n_obs=30 (only the 30 level-9 fabricated
datasets carry seismic_moment_n_m) but blended to essentially 0.0000 --
those 30 datasets are generated by the same deterministic
Wells-Coppersmith-consistent process and so show almost no cross-dataset
variance among themselves, which EWM correctly recognizes as
non-discriminative rather than a bug.

theta_admit's already-disclosed eighth-pass false-admit finding WORSENED:
22 known_bad datasets now have T(D) >= 0.75 (raw count, before hard-override
rescue), up from 6 at the 89->295 pass. Of those 22, 3 are still caught by
the independent hard-override gate (depth_implausible derivatives of
usa_california_southnapa_2014, iran_ahar_varzaghan_2012, and yamanashi_202606
-- P2 fires regardless of T(D)), leaving 19 as genuine two-stage-decision
false-admits. IMPORTANT DISCLOSED FINDING: every one of these 22 is a
corrupt_real_* derivative of a real catalog; NOT ONE fabricated_level1
through fabricated_level9 dataset scores anywhere near 0.75 (the highest,
fabricated_level8_29, tops out at 0.7293 -- still below the boundary). This
means the new graduated-fabrication-ladder methodology contributes ZERO to
this pass's false-admit growth -- the growth is entirely the same
already-disclosed "finite-N weakness of individual sub-tests" mechanism from
the eighth pass, simply given more opportunities to manifest by the +100 new
corruption sources. Disposition of the false-admit finding remains an open
decision for the maintainer (unchanged from the eighth pass's disclosure).

theta_reject's margin reversed again: nearest known_bad below 0.20 is now
`corrupt_real_lebanon_general_inject_duplicates_high` at 0.184505 (a margin
of 0.015495), down from the eighth pass's 0.0425 -- consistent with the
eighth pass's own disclaimer that this margin is genuinely volatile under
corpus composition changes in either direction, not monotonically trending.
theta_admit and theta_reject both remain unchanged in VALUE (0.75/0.20).
theta_auth is unaffected for the same reason as every prior pass (A6 still
not exercised in this corpus's main scoring run).

calibration/calibrate_hard_override_params.py WAS re-run against the full
968-dataset corpus (2026-07-11, same day as this pass). Result: still ZERO
known_good false positives (no genuine dataset ever exhibits a P1-P3
violation), but for the first time across all nine passes, ONE known_bad
case is MISSED: corrupt_real_japan_20220317_query_depth_implausible_med
(k=1 violating record out of n=6 total -- this is the entire dataset, a
genuine ~1-week USGS ComCat query bracketing the 2022-03-17 Japan M7.3
mainshock/foreshock sequence, not a corpus-building artifact; see
corpus_manifest.csv). fraction=0.1667, p=5.99e-03 -- this clears the
uncorrected alpha=0.01 but NOT the Bonferroni-corrected alpha=0.00333 (over
the fixed m=3 {P1,P2,P3} family). Root cause, confirmed: pure small-sample
statistical power, not a bug or a miscalibrated epsilon_tol/alpha -- n=6 is
the smallest n by a wide margin among all 27 depth_implausible known_bad
cases (next-smallest is n=9, comfortably caught); sweeping epsilon_tol down
to 0.0005 already makes this case clean (see
calibration/hard_override_calibration_report.md's sweep table), confirming
the parameter itself is not the problem -- a k=1/n=6 binomial test simply
cannot reach that corrected significance level regardless of the true
corruption rate. Compounding note: this case is also NOT caught by the
compensatory T(D) path (T(D)=0.9933, identical to the score of the
uncorrupted real dataset itself in calibration/threshold_report.md) --
expected, since P1-P3 are Stage-1-only checks with no compensatory-score
counterpart, so a single corrupted record out of 6 has zero visibility
anywhere in the framework once the gate's significance test lacks power.
Per an explicit maintainer decision (2026-07-11), the corpus is now FINAL
at 968 datasets (+30 held-out adversarial-only) for this paper -- this
finding is disclosed as a bounded, understood limitation and Future Work
item (recalibrating or special-casing very-small-N catalogs, e.g. a
minimum-N floor before the hard-override gate is trusted), not chased with
a further corpus pass. See README.md for the same disclosure.

See calibration/threshold_report.md, calibration/ewm_report.md, and
calibration/bootstrap_stability_report.md for the full ninth-pass numeric
reports. ***

*** TENTH CALIBRATION PASS (2026-07-16): triggered by a genuine, previously-
undiscovered floating-point bug found during a user-requested independent
re-verification of Group D1(d) -- see data_certify/stats.py::maximum_curvature_mc()'s
own module comment for the full root-cause. The bug affected the Mc estimate (and therefore the downstream
A2/I2 scores, and A6's stratification threshold, and C2) for 175 of the
968-dataset corpus's datasets, though only 18 datasets' A2 score actually
changed by a nonzero amount (10 by more than 0.1) once propagated through
gr_b_value_aki -- the rest of the 175 had their Mc shift with no material
effect on the derived b-value/score. calibration/score_matrix.csv's 18
affected rows were regenerated via calibration/run_scoring.py (confirmed:
zero decision_ahp_only flips across all 18) and compute_ewm.py was re-run
against the corrected score matrix. Result: every blended weight moved by
under 0.004 (axis-level: A 0.6884->0.6895, P 0.1686->0.1684, C 0.0281->
0.0283, I 0.1150->0.1139; largest single within-axis move was C2,
0.3337->0.3372) -- an order of magnitude smaller than any prior
calibration pass's weight movement, consistent with the fix touching only
18/968 (1.9%) of the corpus. calibration/calibrate_thresholds.py was
re-run against the corrected score matrix and confirmed THETA_ADMIT/
THETA_REJECT (0.75/0.20) both still hold with the SAME known_good/
known_bad separation properties as the ninth pass (no new false-admits or
false-rejects introduced or removed by this fix) -- see
calibration/threshold_report.md's 2026-07-16 addendum. This is the
smallest-magnitude calibration pass in this file's history, included here
for completeness and honesty (per this project's established disclosure
discipline) even though its practical effect on any previously-reported
number is below the precision most of this project's documentation
quotes weights to (4 decimal places).

See calibration/threshold_report.md, calibration/ewm_report.md, and
calibration/group_d_reports/maximum_curvature_recalibration_report.txt
for the full tenth-pass numeric reports.

Every number below traces to a documented derivation. Three different
epistemic categories of constant are kept explicitly distinct:

  1. AHP weights -- the original data-independent pairwise-comparison
     priors. These are single-analyst-derived priors, not multi-expert-
     elicited weights in the strict AHP sense. They still exist below
     (as *_AHP_PRIOR names) purely as the documented input to the blend
     and for traceability -- they are NOT what the audit uses.

  2. AHP x EWM blended weights -- the values actually used by the audit
     (AXIS_WEIGHTS, WITHIN_A/P/C/I
     below). Computed by calibration/compute_ewm.py from the real corpus's
     score matrix (89 datasets as of the seventh pass, 2026-07-07), per the
     exact formulas in Section 5.2 (entropy) and 5.4 (blend), with a
     disclosed MIN_EWM_N=20 floor below which a criterion retains its exact
     AHP weight rather than getting a data-driven weight from too little
     data (P9 -- zero observations corpus-wide; I4 -- only 4/89
     observations).

  3. Decision thresholds (theta_admit, theta_reject) and hard-override
     parameters (epsilon_tol, alpha) -- theta_admit/theta_reject are now
     EMPIRICALLY CALIBRATED against the same real corpus's T(D) separation
     (calibration/calibrate_thresholds.py). theta_auth remains a PROVISIONAL
     PRIOR (see its own comment) because A6 was never exercised anywhere in
     this corpus's scoring run -- no external reference catalog was wired
     up, so there is no A6 data to calibrate it from.
"""

# =============================================================================
# Axis-level AHP priors  (Criteria & Weights Master Reference, Section 1.4)
# =============================================================================
# Derived from the 4x4 Saaty pairwise-comparison matrix over
# (Authenticity, Plausibility, Completeness, Instrumentation), consistency
# ratio CR = 0.028 (well under Saaty's 0.10 threshold -- Section 1.3).
# These are the AHP INPUT to the blend below, not what the audit uses directly.
W_A_AHP_PRIOR: float = 0.514   # Authenticity        -- A(D)
W_P_AHP_PRIOR: float = 0.216   # Plausibility        -- P(D), P4-P9 portion only (P1-P3 are hard gates)
W_C_AHP_PRIOR: float = 0.073   # Completeness        -- C(D)
W_I_AHP_PRIOR: float = 0.197   # Instrumentation     -- I(D)

AXIS_WEIGHTS_AHP_PRIOR = {"A": W_A_AHP_PRIOR, "P": W_P_AHP_PRIOR, "C": W_C_AHP_PRIOR, "I": W_I_AHP_PRIOR}

# AHP x EWM blended axis weights -- calibration/compute_ewm.py, run against
# calibration/score_matrix.csv (NINTH PASS: 968 real+corrupted+fabricated
# datasets, up from 295 -- see module docstring), per Weights Master
# Reference Section 5.4. All 4 axes had >=20 non-NaN observations
# corpus-wide, so all 4 are data-driven blends (none retained at their
# AHP-only value). Full report: calibration/ewm_report.md.
# NINTH-PASS values (2026-07-11, 968-dataset corpus -- corpus expansion
# with a new graduated synthetic-fabrication ladder, levels 1-9, plus 303
# new real catalogs and 100 new corrupted derivatives; see the module
# docstring's NINTH CALIBRATION PASS section). A(D) fell somewhat
# (0.7134 -> 0.6884), P(D) rose sharply for a second consecutive pass
# (0.0770 -> 0.1686), C(D) fell slightly (0.0403 -> 0.0281), I(D) fell
# (0.1692 -> 0.1150). Bootstrap CV (2,000 replicates) improved sharply for
# every axis this pass -- see calibration/bootstrap_stability_report.md.
AXIS_WEIGHTS = {
    "A": 0.6894844988460549,
    "P": 0.16836943659202896,
    "C": 0.028258588896277272,
    "I": 0.11388747566563887,
}
# Recalibrated 2026-07-16 (delta vs prior values all < 0.0011) after fixing a
# floating-point bin-edge bug in data_certify/stats.py::maximum_curvature_mc()
# that affected A2/I2/A6-threshold/C2 scores for 18 of the 968-dataset
# calibration corpus's datasets. Re-verified: zero ADMIT/CONDITIONAL/REJECT
# decision changes for any of the 968 corpus datasets under these updated
# weights versus the pre-fix weights. See the module docstring's TENTH
# CALIBRATION PASS section for the full narrative.

# =============================================================================
# Authenticity sub-criteria weights, intrinsic-only mode  (Section 2.1)
# =============================================================================
# CR = 0.006. Original AHP priors (input to the blend below):
WITHIN_A_AHP_PRIOR = {
    "A1": 0.303,  # Benford's Law on derived multi-order-of-magnitude quantities
    "A2": 0.165,  # Gutenberg-Richter b-value conformity
    "A3": 0.165,  # Omori-Utsu aftershock-decay conformity
    "A4": 0.303,  # Spatial fractal-clustering conformity (correlation dimension)
    "A5": 0.065,  # Duplicate / near-duplicate detection
}
# AHP x EWM blended weights (all 5 sub-criteria had >=20 observations
# corpus-wide -- fully data-driven, none retained). NINTH-PASS values
# (2026-07-11, 968-dataset corpus). A3 (Omori-Utsu aftershock-decay
# conformity) now dominates the blend (0.165 AHP -> 0.4228), overtaking A1
# (Benford), likely because the new graduated synthetic ladder's
# uniform-vs-Omori temporal-clustering levels (see calibration/corrupt.py's
# LEVEL_DESCRIPTIONS) added substantial genuine cross-dataset variance to
# A3 specifically. See calibration/ewm_report.md for the full numeric
# report.
WITHIN_A = {
    "A1": 0.3761270287081997,
    "A2": 0.008668999147779084,
    "A3": 0.42246229044903777,
    "A4": 0.18974276547380506,
    "A5": 0.002998916221178312,
}
# Recalibrated 2026-07-16 alongside AXIS_WEIGHTS above (maximum_curvature_mc
# bug fix) -- deltas all < 0.001.
# A6 (external cross-validation) substitutes A1-A5 ENTIRELY, per magnitude
# stratum, when an external reference catalog is feasible for that stratum
# (Section 3.1 of the main framework; Gap-Remediation Section 1). It is not
# blended -- it carries the full within-axis weight of 1.0 in that mode.
# NOT recalibrated by EWM: A6 was never exercised in the calibration corpus
# (no external reference catalog was wired up during scoring), so there is
# no data to recompute this from -- it remains its original design value.
WITHIN_A_A6_SUBSTITUTE_WEIGHT: float = 1.0

# =============================================================================
# Plausibility sub-criteria weights, compensatory portion P4-P9  (Section 2.2)
# =============================================================================
# P1-P3 are NOT weighted -- they are structural hard gates (veto, not score).
# CR = 0.011. Original AHP priors (input to the blend below):
WITHIN_P_AHP_PRIOR = {
    "P4": 0.143,  # Tsunami joint plausibility (mag x depth x mechanism)
    "P5": 0.143,  # Wells & Coppersmith (1994) rupture-scaling consistency
    "P6": 0.368,  # Moment-magnitude self-consistency (Mw vs M0)
    "P7": 0.235,  # Chronological consistency
    "P8": 0.056,  # Plate-boundary proximity (soft, distance-decay)
    "P9": 0.056,  # Bakun & Wentworth (1997) intensity-distance consistency
}
# NINTH-PASS AHP x EWM blend (2026-07-11, 968-dataset corpus). P9 remains
# at n_obs=0 (the synthetic ladder populated rupture_length_km for P5 but
# not station_distance_km for P9) and RETAINS its exact AHP prior
# unchanged. P4 no longer dominates: P5 (Wells & Coppersmith rupture-
# scaling consistency) now takes the overwhelming majority of the blend
# (0.143 AHP -> 0.7657) because it jumped from n_obs=24 to 90 once the
# graduated ladder started populating rupture_length_km at levels 7-9,
# giving it far more cross-dataset variance to work with than any other
# P criterion. P6 (moment-magnitude self-consistency) picked up n_obs=30
# for the first time (only level-9 fabricated datasets carry
# seismic_moment_n_m) but blended to ~0 -- those 30 datasets are generated
# by the same deterministic process and show almost no variance among
# themselves. See the module docstring's NINTH CALIBRATION PASS section
# and calibration/ewm_report.md for the full numeric report.
WITHIN_P = {
    "P4": 0.002239068172281027,
    "P5": 0.7657437676196038,
    "P6": 2.450103053546287e-15,
    "P7": 0.12608347509535475,
    "P8": 0.04993368911275801,
    "P9": 0.056,
}

# =============================================================================
# Completeness sub-criteria weights  (Section 2.3)
# =============================================================================
# CR = 0.008. Original AHP priors (input to the blend below):
WITHIN_C_AHP_PRIOR = {
    "C1": 0.144,  # Field-level missingness
    "C2": 0.320,  # Magnitude-of-completeness (Mc) adequacy
    "C3": 0.391,  # Spatio-temporal coverage-gap detection
    "C4": 0.144,  # Sample-size sufficiency per stratum
}
# AHP x EWM blended weights (all 4 had >=20 observations -- fully
# data-driven). NINTH-PASS values (2026-07-11, 968-dataset corpus). C4
# (sample-size sufficiency per stratum) now dominates (0.144 AHP -> 0.436),
# overtaking C3 (coverage-gap detection); C1 (field-level missingness)
# remains nearly vanished for the same reason as prior passes -- most real
# catalogs have near-identical, near-zero field-level missingness. See
# calibration/ewm_report.md for the full numeric report.
WITHIN_C = {
    "C1": 0.0012354172361284206,
    "C2": 0.3372086862465165,
    "C3": 0.2280560865324849,
    "C4": 0.43349980998487014,
}
# Recalibrated 2026-07-16 alongside AXIS_WEIGHTS above (maximum_curvature_mc
# bug fix) -- deltas all < 0.0036.

# =============================================================================
# Instrumentation sub-criteria weights  (Section 2.4)
# =============================================================================
# CR = 0.0025. Original AHP priors (input to the blend below):
WITHIN_I_AHP_PRIOR = {
    "I1": 0.156,  # Temporal drift (Mann-Kendall + Sen's slope)
    "I2": 0.295,  # Large-event clipping / saturation
    "I3": 0.083,  # Revision-flag (preliminary/final) consistency
    "I4": 0.156,  # Cross-catalog duplicate-ID detection
    "I5": 0.311,  # Temporal distribution drift (early-vs-late KS test)
}
# AHP x EWM blend: I4 (cross-catalog duplicate-ID detection) FINALLY
# cleared MIN_EWM_N=20 this pass -- n_obs rose from 4/89 to 124/968 because
# some new fabricated datasets were deliberately given populated
# event_uid_source values (see the module docstring's NINTH CALIBRATION
# PASS section), so I4 is now genuinely data-driven for the first time
# (0.156 -> 0.0040) rather than retaining its AHP prior. I1/I2/I3/I5 all
# had >=20 observations and were blended among themselves for the
# remaining budget. NINTH-PASS values (2026-07-11, 968-dataset corpus).
WITHIN_I = {
    "I1": 0.48778188493130464,
    "I2": 0.2689926977757587,
    "I3": 0.19954635267409818,
    "I4": 0.003980451893249224,
    "I5": 0.03969861272558927,
}
# Recalibrated 2026-07-16 alongside AXIS_WEIGHTS above (maximum_curvature_mc
# bug fix) -- deltas all < 0.0027. WITHIN_P is unaffected (P criteria never
# touch maximum_curvature_mc) and was left unchanged.

# =============================================================================
# Decision thresholds  (Criteria & Weights Master Reference, Section 4)
# =============================================================================
# THETA_ADMIT / THETA_REJECT: EMPIRICALLY CALIBRATED against the real
# calibration corpus's T(D) distribution under the new AHP x EWM blended
# weights above (calibration/calibrate_thresholds.py; full numeric report:
# calibration/threshold_report.md). Both VALUES have been re-confirmed
# unchanged across every pass since the sixth (2026-07-06): 0.75/0.20,
# most recently on the 968-dataset TENTH-pass corpus (2026-07-16 -- see
# this file's module docstring). "Holds cleanly" no longer describes
# THETA_ADMIT, however -- see below; do not resurrect the pre-eighth-pass
# "0 false-admits, 0 false-rejects" claim anywhere.
#
# THETA_ADMIT = 0.75 (unchanged in value since the original AHP-only
# prior). The eighth pass (295-dataset corpus) first found this no longer
# holds cleanly: 6 known_bad datasets scored >= 0.75. The ninth pass
# (968-dataset corpus) found this WORSENED to 22 known_bad datasets with
# T(D) >= 0.75 (raw count), of which 3 are still caught by the independent
# Stage-1 hard-override gate (P2 depth-implausible derivatives), leaving
# 19 as genuine two-stage-decision false-admits. IMPORTANT: every one of
# these is a corrupt_real_* derivative of a real catalog -- NOT ONE of the
# new fabricated_level1..level9 synthetic datasets scores anywhere near
# 0.75 (highest: fabricated_level8_29 at 0.7293). The new graduated-
# fabrication-ladder methodology contributes ZERO to this finding; it is
# the same already-disclosed finite-N weakness of individual sub-tests
# (small-source-catalog corruptions), simply given more opportunities to
# manifest by more corruption sources. The TENTH pass (2026-07-16,
# maximum_curvature_mc fix) re-confirmed this count is UNCHANGED at 22/3/19
# under the corrected weights -- the fix did not add or remove any
# false-admit. Disposition (recalibrate THETA_ADMIT, exclude very-small-N
# catalogs from future corpus passes, or disclose as a standing limitation)
# remains an OPEN decision for the maintainer -- see
# calibration/threshold_report.md for the full known_bad T(D) list.
#
# THETA_REJECT = 0.20 (unchanged in value since the sixth pass). known_good
# and known_bad T(D) distributions remain heavily interleaved across
# nearly the entire range -- NO value of THETA_REJECT cleanly separates
# them (a disclosed limitation of the current AHP x EWM axis weighting,
# not a numerically fragile boundary a different round number would fix).
# Per this project's own stated asymmetric-cost principle (a false REJECT
# of genuine data is a real but far smaller cost than a false ADMIT of bad
# data -- Deep-Dive 05 Section 2.1), 0.20 was retained to guarantee ZERO
# known_good false-rejects on every corpus through the tenth pass. The
# margin by which it does so has been genuinely VOLATILE, not
# monotonically trending, across every pass: 0.0293 (73-dataset corpus,
# sixth pass) -> 0.0076 (89-dataset corpus, seventh pass) -> 0.0425
# (295-dataset corpus, eighth pass) -> 0.015495 (968-dataset corpus, ninth
# pass: nearest known_bad is corrupt_real_lebanon_general_
# inject_duplicates_high at 0.184505). The tenth pass (maximum_curvature_mc
# fix) re-confirmed ZERO known_good false-rejects still holds under the
# corrected weights (the nearest known_bad's T(D) moved only slightly,
# 0.184505 -> 0.167261, still comfortably below 0.20). Each pass's margin
# should be read as a fresh data point on this volatility, not as evidence
# of a trend in either direction. See calibration/threshold_report.md for
# the full known_good/known_bad T(D) lists and confusion-count tables
# underlying this choice.
THETA_ADMIT: float = 0.75   # T(D) >= THETA_ADMIT -> ADMIT (absent hard override)
THETA_REJECT: float = 0.20  # T(D) < THETA_REJECT -> REJECT (absent hard override)

# THETA_AUTH: STILL PROVISIONAL, but no longer for lack of trying -- A6 HAS
# now been exercised across the full 89-dataset corpus with a real external
# reference (calibration/run_a6_scoring.py / calibration/score_matrix_a6.csv,
# 89/89 rows scored via score_authenticity() with a live/manually-fetched
# USGS ComCat reference; calibration/calibrate_theta_auth.py +
# calibration/theta_auth_report.md). The result is a genuine, confirmed
# STRUCTURAL finding, not missing data: no single THETA_AUTH value can admit
# the known-good "nz" dataset (matched_fraction=0.3913) without also
# admitting known-bad datasets that score a perfect matched_fraction=1.0000
# (corrupt_real_chiapas_mexico_2017_inject_duplicates_med,
# corrupt_real_taiwan_2024_query_depth_implausible_med) -- because A6's
# matcher checks time/lat/lon/magnitude only, never depth, and a duplicated
# real record still individually matches. Both of those known-bad datasets
# ARE still caught by the full two-stage decision, just not by A6 alone:
# the depth-implausible case hard-REJECTs via P2 (an independent,
# network-agnostic check), and the duplicate-injection case lands at
# CONDITIONAL because A5 (near-duplicate detection), not A6, flags it. This
# is the multi-axis compensatory design working as intended, not a gap --
# see Criteria & Weights Master Reference Section 4's THETA_AUTH row for the
# full disclosure. Changing THETA_AUTH's value would not fix this (it is a
# property of what A6 measures, not of where the boundary sits), so it
# remains at its original a-priori design value as a confirmed, evidence-
# based non-change, not an unexamined omission.
THETA_AUTH: float = 0.50    # A6 matched_fraction below this -> hard-override REJECT

# =============================================================================
# A6 three-state semantics (Group C3, 2026-07-12)
# =============================================================================
# PROBLEM THIS FIXES: the binary "matched_fraction < THETA_AUTH -> hard-REJECT"
# rule above treats ANY non-match, from a SINGLE reference source, as
# equivalent to confirmed fabrication. Section 4.2's own disclosure (and the
# theta_auth row above) already documents a real, confirmed false-positive
# risk from exactly this: "nz" (GeoNet New Zealand, known_good) scores
# matched_fraction=0.3913 against USGS ComCat alone -- a genuine regional
# coverage gap, not evidence of fabrication -- which the binary rule cannot
# distinguish from a genuinely fabricated dataset scoring the same fraction.
#
# FIX: A6 now classifies each reference-complete-stratum record into one of
# three states instead of a binary matched/unmatched:
#   - "Externally corroborated": at least one independently-feasible
#     reference source found a matching event. Contributes positively to
#     A6's composite score exactly as a binary match did before.
#   - "Externally contradicted": queried against >= A6_CONTRADICTED_MIN_SOURCES
#     independently-feasible sources, ALL of them failed to find a match
#     (per record), AND the dataset-level MATCH rate over the FULL
#     population that was meaningfully queried (corroborated +
#     contradicted-eligible records together -- n_queried) is confirmed
#     statistically (Clopper-Pearson lower-tail test, reusing the same
#     machinery as the P1-P3 hard-override test in hard_override.py) to sit
#     below THETA_AUTH with confidence -- i.e. genuinely strong, multi-source,
#     statistically-robust negative evidence. ONLY this state can fire the
#     A6 hard-override REJECT.
#     BUGFIX (2026-07-13, caught on the first live multi-source corpus run):
#     an earlier version of this test evaluated Clopper-Pearson against ONLY
#     the contradicted-eligible subset (which is DEFINED to have zero
#     matches), making the test tautological -- it would "confirm"
#     contradiction for any dataset with >=A6_CONTRADICTED_MIN_N_STRATUM
#     non-matching records regardless of the dataset's true overall match
#     rate. This was caught when "nz" (matched_fraction=0.568, a MAJORITY
#     of records matched) still hard-rejected. Fixed by testing
#     k=n_corroborated out of n=n_queried instead of k=0 out of
#     n=n_contradicted_eligible -- see axis_authenticity.py's
#     _score_a6_external() for the corrected implementation.
#   - "Externally unverifiable": everything else that isn't a match --
#     single-source non-matches, non-matches from too few independently-
#     feasible sources, or a contradicted-eligible sub-stratum too small to
#     trust statistically. These records get NO A6 penalty at all (positive
#     or negative) -- they fall back to being scored by the intrinsic A1-A5
#     battery instead, exactly as if A6 had been infeasible for them.
#
# CONSEQUENCE, DISCLOSED PROMINENTLY: A6_CONTRADICTED_MIN_SOURCES=2 means
# that under the DEFAULT single-source production configuration
# (run_audit.py's default `USGSComCatReference()`), A6 can NEVER reach
# "contradicted" and therefore NEVER fires the hard-override REJECT -- only
# "corroborated" (positive) evidence is ever contributed. To retain A6's
# hard-override capability, a deployment must configure
# `--reference-source multi` (or `weighted-multi`) with >= 2 independently
# reachable sources (e.g. USGS + EMSC). This is an intentional, disclosed
# trade-off (single-source non-match is deliberately never enough to REJECT
# on its own any more), not an oversight.
#
# THESE VALUES WERE PROVISIONAL AT DESIGN TIME and have since been
# calibrated against a live 968-dataset corpus run (`--reference-source
# multi`, USGS+EMSC+ISC; calibration/calibrate_a6_three_state.py ->
# calibration/group_c_reports/a6_three_state_report.json/.md; 2026-07-13).
# DISPOSITION: all three values below are RETAINED UNCHANGED -- the live run
# confirmed rather than contradicted them (Q1 false-positive check: 0/320
# known_good datasets reached "contradicted", 95% CI upper bound 0.93%; Q2
# security-property check: 258/328 eligible known_bad datasets correctly
# confirmed "contradicted"; Q3 threshold-sensitivity check found no evidence
# these specific values need revision). See
# Criteria_and_Weights_Master_Reference.md Section 4.4 for the full result,
# including the disclosed 212/968 (21.9%) timeout coverage gap this run hit.
# Starting values were reasoned defaults, not arbitrary:
A6_CONTRADICTED_MIN_SOURCES: int = 2
# Reuses the existing MIN_EWM_N=20 "minimum N for a statistically meaningful
# read" convention already established elsewhere in this project
# (calibration/compute_ewm.py) -- gates n_queried (= n_corroborated +
# n_contradicted_eligible, the full >=2-source-queried population, NOT just
# the contradicted-eligible subset alone -- see the 2026-07-13 bugfix note
# above). A queried population smaller than this is not trusted to support
# a hard-REJECT verdict, falls back to "unverifiable" instead.
A6_CONTRADICTED_MIN_N_STRATUM: int = 20
# Reuses the existing hard-override ALPHA=0.01 significance-level
# convention (see below) for the Clopper-Pearson lower-tail test that must
# confirm the queried population's match rate is below THETA_AUTH with
# statistical confidence, not just as a point estimate.
A6_CONTRADICTED_ALPHA: float = 0.01

# =============================================================================
# Hard-override statistical parameters  (Gap-Remediation Addendum, Section 2 & 7.1)
# =============================================================================
# "Non-trivial fraction" of P1-P3 violations is operationalised via a
# Clopper-Pearson (1934) exact one-sided binomial test against a disclosed
# provisional tolerance, at significance level ALPHA, Bonferroni-corrected
# for the FIXED family of exactly m=3 tests (one each for P1, P2, P3),
# computed once over the whole dataset -- NOT further split by region or
# time-bin, precisely to avoid the multiple-testing blow-up that a
# variable-size family would create (Section 7.1's central argument: this
# family size is fixed BY DESIGN, not shrunk-alpha-to-compensate).
EPSILON_TOL: float = 0.001   # max fraction of P1-P3 violations attributable to isolated error
ALPHA: float = 0.01          # per-test significance level before correction
HARD_OVERRIDE_FAMILY_SIZE: int = 3          # exactly {P1, P2, P3}
ALPHA_CORRECTED: float = ALPHA / HARD_OVERRIDE_FAMILY_SIZE   # Bonferroni (Dunn 1961)

# =============================================================================
# Physical hard bounds  (main framework Section 3.2, P1-P3)
# =============================================================================
LAT_MIN, LAT_MAX = -90.0, 90.0
LON_MIN, LON_MAX = -180.0, 180.0
# Set at 750 km (not the conventional ~700 km Wadati-Benioff description) to
# keep a documented real event (Mw 4.2, Vanuatu/Tonga, 2004, 735.8 km) safely
# out of the automatic-REJECT zone. See Deep-Dive 02 Section 5.1.
DEPTH_MAX_KM: float = 750.0
# REVISED 2026-07-06 (was 0.0): calibration/calibrate_hard_override_params.py
# -- run against the real 73-dataset corpus, no live network required, since
# P1-P3 are pure local computations over each dataset's own records.csv --
# found that a hard floor of 0.0 wrongly flagged THREE real known_good
# datasets as "non_trivial P2 violations" (which would hard-REJECT them
# outright): real_usgs_main (4,041/74,940 records, 5.4%), real_all_month, and
# real_events_atkinson all contain small negative reported depths, ranging
# from -0.01 km to -3.8 km (the corpus-wide minimum across all 50 known_good
# datasets; 5/50 known_good datasets exhibit this). This is a known,
# recurring pattern in real hypocenter solutions for very shallow events --
# small negative depths arise from ordinary velocity-model/depth-inversion
# uncertainty placing the computed hypocenter marginally above the reference
# datum, not from data fabrication or entry error.
# PRIMARY-SOURCE VERIFICATION CLOSED (2026-07-06, later the same day): this
# rationale was left unverified above because the environment that made the
# fix had no live network access. It has since been independently confirmed
# directly against USGS's own published documentation (fetched from a
# separate reviewing session with outbound web access, not this project's
# own offline calibration environment):
#   - USGS FAQ, "What does it mean that the earthquake occurred at a depth
#     of 0 km? ... How can an earthquake have a negative depth?"
#     (usgs.gov/faqs/what-does-it-mean-earthquake-occurred-a-depth-0-km-how-
#     can-earthquake-have-a-negative-depth): depths are referenced to the
#     geoid (sea level), not the local ground surface -- a shallow
#     hypocenter under high-elevation terrain can compute to ABOVE the
#     geoid, i.e. a negative depth, entirely independent of any data-entry
#     error.
#   - USGS Volcano Watch, "Why do some earthquakes have negative depths?"
#     (usgs.gov/observatories/hvo/news/volcano-watch-why-do-some-
#     earthquakes-have-negative-depths): gives the worked example (surface
#     2 km above sea level, focus 1 km below the surface -> geoid depth
#     -1 km) and states explicitly that "a negative depth can sometimes be
#     an artifact of the poor resolution for a shallow event" -- i.e. USGS
#     itself names shallow-event depth-inversion uncertainty as a source of
#     small negative depths, exactly this constant's stated rationale.
# This closes the "spot-check before treating as final" item above -- the
# rationale is confirmed from USGS's own primary documentation, not merely
# inferred. -5.0 km (a 1.2 km margin below the observed corpus-wide minimum
# of -3.8 km, mirroring DEPTH_MAX_KM's own margin-above-worst-observed-case
# logic) remains the value in use -- while still tight enough that the
# corpus's `depth_implausible` known-bad injections (-1/-50/900/5000 km +/-
# noise; calibration/corrupt.py) are overwhelmingly caught: re-verified via
# calibrate_hard_override_params.py after the original change, zero known_bad
# depth_implausible cases were missed -- AT THE TIME (295-dataset corpus).
# UPDATE (2026-07-11, 968-dataset corpus): re-running the same script found
# ONE known_bad depth_implausible case now missed --
# corrupt_real_japan_20220317_query_depth_implausible_med, a k=1/n=6 case
# (the entire dataset is only 6 records) that fails Bonferroni-corrected
# significance purely for lack of statistical power, not because -5.0 km is
# wrong -- see this file's "NINTH CALIBRATION PASS" docstring section above
# for the full root-cause and disclosure. DEPTH_MIN_KM itself is NOT
# implicated (the miss is a small-sample power issue in the significance
# test, not a boundary-value issue) and is left unchanged.
DEPTH_MIN_KM: float = -5.0
# Largest instrumentally recorded earthquake: 1960 Valdivia, Mw 9.5.
MAGNITUDE_MAX: float = 9.5
# REVISED 2026-07-06 (was 0.0): same calibration pass as DEPTH_MIN_KM above
# found real_all_month wrongly flagged for "non_trivial P3 violations" --
# 427/10,189 records (4.2%) have small negative magnitudes, from -0.01 to
# -1.9 (the corpus-wide minimum across all 50 known_good datasets; 4/50
# known_good datasets exhibit this). Negative-magnitude events are a known,
# ordinary feature of dense local/regional seismic networks reporting very
# small (micro-seismic) events on a logarithmic magnitude scale.
# PRIMARY-SOURCE VERIFICATION CLOSED (2026-07-06, later the same day, same
# out-of-band web access described in DEPTH_MIN_KM's comment above):
#   - USGS FAQ, "How can an earthquake have a negative magnitude?"
#     (usgs.gov/faqs/how-can-earthquake-have-a-negative-magnitude): magnitude
#     is a logarithmic amplitude scale, so ever-smaller amplitudes simply
#     keep decreasing the number below zero -- there is no physical floor at
#     M=0. Modern instrumentation is roughly 1000x more sensitive than early
#     seismographs, and dense local networks routinely detect and report
#     these sub-zero microearthquakes (a commonly cited local-network
#     detection threshold is approximately ML=-0.1 within 25 km of a
#     station using a 10-station array) -- confirming this is ordinary
#     instrumentation capability, not a data-entry or fabrication artifact.
# This closes the "spot-check before treating as final" item above. -2.5 (a
# 0.6-unit margin below the observed corpus-wide minimum of -1.9) remains
# the value in use -- tight enough that `magnitude_gr_violation`
# (calibration/corrupt.py, which resamples only within each dataset's OWN
# observed [min,max] range and therefore never introduces a new value below
# a dataset's real minimum) cannot exploit it.
MAGNITUDE_MIN: float = -2.5

# =============================================================================
# Moment-magnitude constant  (Deep-Dive 02, Section 3.2)
# =============================================================================
# Mw = (2/3)*log10(M0_N_m) - 6.07   (M0 in N.m, SI units)
# Hard-coded directly for SI-unit inputs -- do NOT recompute at runtime from
# the CGS-unit constant (-10.7); the two do not perfectly round-trip through
# naive unit conversion (see Deep-Dive 02 Section 3.2's rounding-order note).
MOMENT_MAGNITUDE_SI_CONSTANT: float = -6.07

# =============================================================================
# Other named provisional tolerances  (Gap-Remediation Addendum, Section 3)
# =============================================================================
TAU_MC: float = 0.3          # C2: max acceptable sigma_Mc (magnitude units)
TAU_DRIFT: float = 0.05      # I1: max acceptable |Sen slope| per decade (magnitude units)

# Gutenberg-Richter plausibility band (main framework Section 3.1, A2)
GR_B_VALUE_CENTER: float = 1.0
GR_B_VALUE_BAND: float = 0.5   # plausible band is [center-band, center+band] = [0.5, 1.5]

# Equal-width bin count / minimum sample-size rule of thumb (C4, A2)
MIN_STRATUM_N: int = 30

# Random-Index table for Saaty's AHP consistency ratio (Saaty 1980)
AHP_RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41}

SEED: int = 42

# =============================================================================
# MIN_RELIABLE_N: sample-sufficiency / statistical-power floors (2026-07-21,
# external review, Section 6.4 of DATA-CERTIFY_Criteria_and_Weights_Master_
# Reference.md)
# =============================================================================
# `evidence_coverage` (decision.py, review point 3.5) already distinguishes
# "this sub-test was applicable and computed a score" from "this sub-test's
# nominal weight was silently renormalised away because it did not apply" --
# but it does NOT distinguish "computed from a well-powered sample" from
# "computed from technically enough data to run at all, but too little to
# trust the resulting number." A concrete finding motivating this: several
# of the 968-dataset corpus's disclosed false-admits (see the `theta_admit`
# row in Criteria & Weights Master Reference Section 4) are small (24-29
# record) `corrupt_real_*` derivatives where only A3 and A5 are applicable
# at all -- and A3 in particular can be "applicable" (per its own >=5-events-
# per-cluster floor in axis_authenticity.py) from a SINGLE fitted aftershock
# cluster, which is enough to average over but not enough to trust as
# representative of the catalog's true decay behaviour.
#
# These floors are a NEW, DISCLOSED, PROVISIONAL prior -- of identical
# epistemic status to `theta_admit`/`theta_reject`/`theta_auth`/`epsilon_tol`
# when they were first introduced: principled starting points (informed by
# each sub-test's own existing internal floor, e.g. A1/A2's pre-existing
# `>=30`, C4/A2's shared `MIN_STRATUM_N=30` rule of thumb, and A4's
# pre-existing `>=50` correlation-dimension floor), NOT yet empirically
# calibrated against the full corpus. A dedicated calibration pass (does
# `sample_sufficiency` below THIS floor actually predict a wider score
# swing / higher false-admit rate on held-out corrupted-real derivatives
# specifically) is disclosed as open follow-up work, analogous to how
# `epsilon_tol`/`alpha` were only justified AFTER `calibrate_hard_override_
# params.py` was run against the full corpus (Section 2.3 of the Gap-
# Remediation Addendum). Only sub-tests where a `n_used`-equivalent sample
# size is meaningfully reported in `SubTestResult.detail` are covered here;
# a sub-test absent from this table is treated as NOT penalised by the
# sample-sufficiency gate below (conservative in the sense of never
# introducing a caveat this project cannot yet justify empirically, mirroring
# how P9 is excluded from EWM weighting entirely rather than assigned an
# unjustified number -- see Criteria & Weights Master Reference Section 5.8).
#
# Units/meaning per sub-test (NOT simply "record count" in every case --
# each is the specific dimension of statistical replication that sub-test's
# own estimator actually depends on):
#   A1: minimum valid-value count across whichever multi-order-of-magnitude
#       field(s) were actually used (already >=30 by construction; this
#       floor is a no-op today, retained for forward-compatibility with a
#       future stricter per-field requirement).
#   A2: number of events at/above the estimated Mc used for the b-value fit
#       (already >=10 by construction; see note above).
#   A3: number of INDEPENDENT candidate mainshock-aftershock clusters
#       identified (`n_clusters_found` in `_score_a3_omori_utsu`'s detail),
#       NOT the event count within any one cluster -- a single cluster,
#       however many events it contains, is one draw from "does this
#       catalog show genuine Omori-Utsu decay," not a sample the framework
#       can average confidently over.
#   A4: number of valid (lat, lon) pairs used for the correlation-dimension
#       fit (already >=50 by construction; see note above).
#   A5: total record count `n` (duplicate detection needs very little data
#       to be informative -- this floor is intentionally low).
MIN_RELIABLE_N = {
    "A1": 30,
    "A2": 10,
    "A3": 2,   # >=2 independent clusters -- a single cluster cannot be averaged over
    "A4": 50,
    "A5": 2,
}

# =============================================================================
# MIN_N_RECORDS_FOR_ADMIT / MIN_APPLICABLE_SUBTESTS_FOR_ADMIT: hard
# ADMIT-eligibility floors (2026-07-21, response to a paper-readiness
# review of the ninth-pass 19/490 (3.9%) false-admit finding above)
# =============================================================================
# Distinct from evidence_coverage/sample_sufficiency (both WEIGHT-fraction
# metrics, and therefore coupled to whatever AXIS_WEIGHTS/WITHIN_* happen to
# be live -- a future recalibration pass could silently change which
# datasets those two gates catch). These two are raw, weight-independent
# COUNTS: total record count, and the number of distinct non-hard-gate
# sub-tests (out of a max of 20: A1-A5, P4-P9, C1-C4, I1-I5, with A6
# substituting into the A1-A5 slot when it applies) that were applicable
# and produced a computable score for THIS specific audit.
#
# EMPIRICAL BASIS (calibration_gates_rescore_merged.csv, a full re-audit of
# the 968-dataset corpus + 30-dataset adversarial holdout via the REAL
# DataCertifyAuditor.audit() -- i.e. INCLUDING the evidence_coverage/
# sample_sufficiency gates at their 0.5/0.5 defaults, which
# calibration/_analysis_common.py's assign_decision() had never applied;
# see CHANGELOG.md's 2026-07-21 "gate-aware re-audit" entry for the full
# reproduction): those two existing gates ALONE already cut the disclosed
# 19/490 (3.9%) false-admit rate to 4/490 (0.82%), at the cost of
# known_good's ADMIT rate falling from 98/508 (19.3%) to 35/508 (6.9%).
# The 4 residual false-admits (corrupt_real_miyazaki_2024-2025_magnitude_
# gr_violation_med n=46, corrupt_real_tohoku_202511_inject_missingness_low
# n=67, corrupt_real_ridgecrest_california_2019_coordinate_jitter_low
# n=108, corrupt_real_azerbaijan_general_magnitude_gr_violation_med n=310)
# ALL have evidence_coverage>=0.70 and sample_sufficiency=1.0 already --
# they are not a coverage or small-sample problem, they are mild
# corruptions (magnitude_gr_violation_med, inject_missingness_low,
# coordinate_jitter_low) that a well-powered battery still does not flag
# strongly enough, a genuinely different and harder failure mode than the
# one these two new floors target. A grid search over
# (MIN_N_RECORDS_FOR_ADMIT, MIN_APPLICABLE_SUBTESTS_FOR_ADMIT) found the
# applicable-subtest-count floor to have ZERO marginal bite on this corpus
# at any tested value (0/5/8/10/12) once the record-count floor is fixed --
# every dataset that survives the existing two gates already has enough
# applicable tests, on this corpus, that a count floor is currently
# redundant with them. It is kept anyway, at a value chosen independently
# of this corpus (a plain majority, 8 of a possible 20), as a
# forward-looking robustness measure: evidence_coverage's num applicable
# tests can pass this even under a FUTURE weight recalibration that
# concentrates weight on very few high-weight sub-tests -- the same "22
# false-admits from a corpus-composition-sensitive weight shift" pattern
# already disclosed for AXIS_WEIGHTS itself.
#
# MIN_N_RECORDS_FOR_ADMIT=50 is a deliberately moderate choice, not the
# corpus-optimal one: raising it further keeps buying down the residual
# false-admit rate (n=100 -> 2/490 0.41%; n=200 -> 1/490 0.20%; n=350 ->
# 0/490 0.00%) but at a steepening cost to known_good's ADMIT rate (35/508
# 6.9% at n=50 -> 29/508 5.7% at n=100 -> 20/508 3.9% at n=200 -> 14/508
# 2.8% at n=350) -- see the full grid in
# calibration_gates_rescore_merged.csv's companion sensitivity table
# (Docs/02_Calibration_and_Validation, "ADMIT-eligibility floor" section).
# n=50 was chosen to align with A4's own pre-existing MIN_RELIABLE_N
# floor (the strictest of the five A1-A5 floors already in production
# use) rather than to specifically target these 4 residual cases, which a
# floor this size only catches one of (the smallest, n=46). Disclosed
# explicitly as a provisional prior of the same epistemic status as
# theta_admit/theta_reject/min_evidence_coverage/min_sample_sufficiency
# when each was first introduced -- NOT yet independently re-optimized
# against a held-out split, and a genuine, disclosed residual false-admit
# rate of ~0.6% (3/490) remains even at these defaults, because the
# count-floor never binds on this corpus and the record-count floor alone
# cannot distinguish "well-powered but mild corruption" from
# "well-powered and genuine" (see the 3 residual cases below).
#
# LIVE-CODE VERIFICATION (2026-07-21, post-implementation): the analysis
# above was done by simulating the gate in pandas against a pre-existing
# score dump. The actual DataCertifyAuditor.audit() code path (this file's
# defaults + decision.py's two new gate blocks) was then re-run against
# the full 998-dataset corpus+holdout from scratch (one dataset at a time,
# real records.csv -> real audit() call, no shortcuts) to confirm the
# simulation matched the real implementation exactly. It did: false-admit
# = 3/490 (0.6122%), Wilson 95% CI [0.21%, 1.78%] (down from the
# gate-free 19/490 (3.88%) CI [2.50%, 5.98%], and from the
# existing-gates-only 4/490 (0.82%)); known_good ADMIT rate = 32/508
# (6.30%, down from the gate-free 98/508 (19.29%) and the
# existing-gates-only 35/508 (6.89%)); known_good false-reject remains
# 0/508 throughout, unchanged by any of these gates (they only ever cap
# ADMIT down to CONDITIONAL, never touch REJECT). All 30 held-out
# adversarial (fabricated_level10) datasets remain CONDITIONAL (0 ADMIT),
# unaffected. Of the 4 residual false-admits identified in the grid
# search, exactly one (corrupt_real_miyazaki_2024-2025_magnitude_gr_
# violation_med, n=46) is caught by MIN_N_RECORDS_FOR_ADMIT=50; the other
# 3 (n=67, n=108, n=310) clear both new floors and remain genuine, disclosed
# residual false-admits -- see CHANGELOG.md's 2026-07-21 "ADMIT-eligibility
# gate" entry for the full reproduction and the six-question paper-readiness
# analysis this was done in response to.
MIN_N_RECORDS_FOR_ADMIT: int = 50
MIN_APPLICABLE_SUBTESTS_FOR_ADMIT: int = 8
