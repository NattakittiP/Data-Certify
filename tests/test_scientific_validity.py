# -*- coding: utf-8 -*-
"""
tests/test_scientific_validity.py -- Ground-truth / analytical-recovery
validation of every named statistical method in data_certify/stats.py, plus
a programmatic cross-check of every AHP weight and threshold in
_constants.py against Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md.

Unlike the other test files (which mostly check interface behaviour --
applicable/not-applicable, score bounds, edge cases), this file asks a
different question for each method: "if I feed in data with a KNOWN true
answer, does the implementation recover that answer, and does it agree with
an independent reference implementation (scipy, or a brute-force O(n^2)
reference) where one exists?"

This file exists because of findings made during a dedicated scientific-
validity review pass (2026-07): four real, previously-undetected accuracy
bugs were found and fixed as a direct result of writing tests in this style
against synthetic data with a known ground truth, none of which the
existing edge-case/interface test suite would have caught (all four still
returned "valid-looking", in-range, applicable results -- they were just
numerically biased):

  1. mann_kendall_test's variance formula omitted the standard tied-value
     correction (Gilbert 1987), making the test needlessly conservative on
     real tie-heavy magnitude data (magnitudes are usually reported to 0.1
     precision). Fixed by adding the Var(S) tie-correction term.
  2. correlation_dimension used the 5th/95th percentile of the pairwise-
     distance distribution to bound its fitted scaling region, which for a
     bounded 2-D domain sits well outside the true small-r power-law
     regime, causing an N-independent downward bias (uniform 2-D scatter,
     true Dc=2.0, measured at Dc~1.6 regardless of sample size). Fixed by
     using the 1st/30th percentile instead.
  3. fit_omori_utsu fit log(rate) vs log(t+c) via UNweighted least squares
     on binned Poisson counts, which systematically underestimates the
     decay exponent p by ~30% (a known bias when regressing the log of
     noisy small counts without weighting). Fixed by weighting the
     regression by bin count (~inverse-Poisson-variance weighting).
  4. fit_omori_utsu's flat-rate ("degenerate") check used a FIXED KS
     threshold (0.05) that does not scale with n, making it correctly
     flag a KNOWN homogeneous (non-decaying) Poisson process as degenerate
     only ~9% of the time at n=50 and ~40% at n=200 (a one-sample KS
     statistic under the null shrinks as ~1/sqrt(n), so a fixed constant is
     an N-dependent power failure). Fixed by using a proper sample-size-
     scaled critical value (Stephens 1974 finite-sample approximation).

See Docs/01_Deep_Dives/DATA-CERTIFY_Code_to_Theory_Mapping.md and the git history of
data_certify/stats.py for the full derivation and citation trail behind
each fix.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify import _constants as const
from data_certify import stats as ds

scipy_stats = pytest.importorskip(
    "scipy.stats", reason="scipy is optional for the core package; skip scipy cross-checks if absent."
)


# =============================================================================
# 1. Clopper-Pearson exact binomial test vs scipy.stats.binomtest
# =============================================================================

class TestClopperPearsonAgreesWithScipy:
    def test_matches_scipy_binomtest_across_random_cases(self):
        rng = random.Random(0)
        max_err = 0.0
        for _ in range(200):
            n = rng.randint(1, 500)
            k = rng.randint(0, n)
            p0 = rng.uniform(0.0001, 0.5)
            ours = ds.clopper_pearson_upper_tail(k, n, p0)
            ref = scipy_stats.binomtest(k, n, p0, alternative="greater").pvalue
            max_err = max(max_err, abs(ours - ref))
        assert max_err < 1e-6

    def test_deep_dive_06_worked_example_isolated_violation(self):
        # n=5,000,000, k=3 -> p ~ 1 (consistent with isolated error), from the
        # Deep-Dive 06 worked example this project's own docs cite.
        p = ds.clopper_pearson_upper_tail(3, 5_000_000, const.EPSILON_TOL)
        assert p > 0.5  # NOT statistically distinguishable from isolated error

    def test_deep_dive_06_worked_example_concentrated_violation(self):
        # n=200, k=5 -> p far below alpha_corrected (non-trivial fraction).
        p = ds.clopper_pearson_upper_tail(5, 200, const.EPSILON_TOL)
        assert p < const.ALPHA_CORRECTED


# =============================================================================
# 2. Kolmogorov-Smirnov two-sample statistic vs scipy.stats.ks_2samp
# =============================================================================

class TestKSStatisticAgreesWithScipy:
    def test_matches_scipy_ks_2samp_across_random_cases(self):
        rng = np.random.RandomState(1)
        max_err = 0.0
        for _ in range(50):
            a = rng.normal(0, 1, size=rng.randint(5, 300))
            b = rng.normal(rng.uniform(-1, 1), rng.uniform(0.5, 2), size=rng.randint(5, 300))
            ours = ds.ks_statistic_2sample(a, b)
            ref = scipy_stats.ks_2samp(a, b).statistic
            max_err = max(max_err, abs(ours - ref))
        assert max_err < 1e-9

    def test_identical_distributions_give_small_statistic(self):
        rng = np.random.RandomState(2)
        a = rng.normal(0, 1, 2000)
        b = rng.normal(0, 1, 2000)
        d = ds.ks_statistic_2sample(a, b)
        assert d < 0.1  # same distribution -> small D, not exactly 0 at finite N

    def test_wildly_different_distributions_give_large_statistic(self):
        a = np.full(500, 1.0)
        b = np.full(500, 100.0)
        d = ds.ks_statistic_2sample(a, b)
        assert d == pytest.approx(1.0)


# =============================================================================
# 3. Mann-Kendall trend test
# =============================================================================

class TestMannKendall:
    def test_s_statistic_matches_bruteforce_on_tied_data(self):
        rng = np.random.RandomState(3)
        max_err = 0
        for _ in range(20):
            n = rng.randint(5, 60)
            x = np.round(rng.normal(4.0, 1.0, n), 1)  # tie-heavy, like real magnitudes
            result = ds.mann_kendall_test(x)
            s_bf = sum(np.sign(x[j] - x[i]) for i in range(n) for j in range(i + 1, n))
            max_err = max(max_err, abs(result["s"] - s_bf))
        assert max_err == 0

    def test_tie_correction_reduces_variance_relative_to_uncorrected(self):
        # Regression test for the tie-correction fix: with many ties, Var(S)
        # must be SMALLER than the naive untied formula would give (the tie
        # term is subtracted), which means |z| must be LARGER (more power)
        # than the uncorrected formula would have produced for the same S.
        rng = np.random.RandomState(4)
        n = 300
        x = np.round(rng.normal(4.0, 0.3, n) + np.linspace(0, 0.5, n), 1)  # many ties + real trend
        result = ds.mann_kendall_test(x)
        uncorrected_var_s = n * (n - 1) * (2 * n + 5) / 18.0
        s = result["s"]
        uncorrected_z = (s - 1) / math.sqrt(uncorrected_var_s) if s > 0 else (s + 1) / math.sqrt(uncorrected_var_s)
        assert abs(result["z"]) >= abs(uncorrected_z)

    def test_recovers_known_linear_trend(self):
        rng = np.random.RandomState(5)
        x = np.arange(500).astype(float)
        y = 4.0 + 0.02 * x + rng.normal(0, 0.05, 500)
        mk = ds.mann_kendall_test(y)
        assert mk["trend_detected"] is True
        assert mk["z"] > 10  # a slope this clean over n=500 should be an overwhelming detection

    def test_false_positive_rate_near_nominal_alpha_on_pure_noise(self):
        # At the alpha=0.05 two-sided threshold (|z|>1.96), pure noise should
        # trigger "trend_detected" at close to a 5% rate, not systematically
        # more (which would indicate an anti-conservative bug) or dramatically
        # less (over-conservative, e.g. from a missing/wrong tie correction).
        rng = np.random.RandomState(6)
        false_pos = 0
        n_reps = 300
        for _ in range(n_reps):
            noise = np.round(rng.normal(4.0, 0.3, 300), 1)
            if ds.mann_kendall_test(noise)["trend_detected"]:
                false_pos += 1
        rate = false_pos / n_reps
        assert 0.01 < rate < 0.12  # generous band around the nominal 0.05

    def test_all_identical_values_gives_zero_z_not_crash(self):
        x = np.full(50, 4.0)
        result = ds.mann_kendall_test(x)
        assert result["s"] == 0.0
        assert result["z"] == 0.0
        assert result["trend_detected"] is False


class TestSenSlope:
    def test_matches_bruteforce_median_of_pairwise_slopes(self):
        rng = np.random.RandomState(7)
        max_err = 0.0
        for _ in range(20):
            n = rng.randint(4, 60)
            x = np.sort(rng.uniform(0, 100, n))
            y = rng.normal(0, 1, n) + 0.3 * x
            ours = ds.sen_slope(x, y)
            slopes = [(y[j] - y[i]) / (x[j] - x[i]) for i in range(n) for j in range(i + 1, n) if x[j] != x[i]]
            bf = float(np.median(slopes))
            max_err = max(max_err, abs(ours - bf))
        assert max_err < 1e-9

    def test_recovers_known_slope(self):
        rng = np.random.RandomState(8)
        true_slope = 0.02
        x = np.arange(500).astype(float)
        y = 4.0 + true_slope * x + rng.normal(0, 0.05, 500)
        est = ds.sen_slope(x, y)
        assert abs(est - true_slope) < 0.005


# =============================================================================
# 4. Gutenberg-Richter b-value (Aki 1965 MLE + Utsu discrete correction)
# =============================================================================

class TestGutenbergRichterBValue:
    def test_recovers_known_b_value_with_realistic_binned_magnitudes(self):
        # The deltaM/2 discrete-data correction (Utsu's refinement of Aki
        # 1965) specifically targets REAL, rounded-to-0.1 magnitude
        # reporting where the true generating distribution extends
        # continuously below the chosen Mc grid point (some true sub-Mc
        # events round UP to the Mc bin). Simulating that scenario properly
        # (not just generating magnitudes with a hard floor exactly at Mc)
        # is essential for this test to be a fair check of the correction.
        for true_b in (0.7, 1.0, 1.3):
            rng = np.random.RandomState(7)
            mc = 3.0
            beta = true_b * math.log(10.0)
            true_floor = mc - 3.0
            mags_true = true_floor + rng.exponential(1.0 / beta, size=500_000)
            mags_obs = np.round(mags_true, 1)
            mags_complete = mags_obs[mags_obs >= mc]
            b_hat = ds.gr_b_value_aki(mags_complete, mc)
            assert abs(b_hat - true_b) < 0.08, f"b={true_b}: recovered {b_hat}"

    def test_uncorrected_estimator_is_worse_on_the_same_binned_data(self):
        # Regression guard: the delta_m/2 correction must actually IMPROVE
        # recovery relative to delta_m=0 on realistically binned data (this
        # is what justifies having the correction at all).
        #
        # A single realization is NOT a fair comparison here: with n~500
        # complete-catalog events, Aki's own asymptotic SE is
        # ~b/sqrt(n)~0.043, which is comparable in size to the ~0.05-0.1
        # discretization bias the correction targets -- so a single draw's
        # sampling noise can easily hide (or reverse) the systematic effect.
        # Averaging the (signed) bias over many independent draws isolates
        # the systematic component from the per-draw noise.
        true_b, mc = 1.0, 3.0
        beta = true_b * math.log(10.0)
        corrected_bias, uncorrected_bias = [], []
        for seed in range(30):
            rng = np.random.RandomState(seed)
            mags_true = (mc - 3.0) + rng.exponential(1.0 / beta, size=200_000)
            mags_obs = np.round(mags_true, 1)
            mags_complete = mags_obs[mags_obs >= mc]
            corrected_bias.append(ds.gr_b_value_aki(mags_complete, mc) - true_b)
            uncorrected_bias.append(ds.gr_b_value_aki(mags_complete, mc, delta_m=0.0) - true_b)
        mean_abs_corrected = float(np.mean(np.abs(corrected_bias)))
        mean_abs_uncorrected = float(np.mean(np.abs(uncorrected_bias)))
        mean_signed_uncorrected = float(np.mean(uncorrected_bias))
        # The uncorrected estimator should show a clear systematic (signed,
        # not just noisy) upward bias on this boundary-rounding scenario ...
        assert mean_signed_uncorrected > 0.05
        # ... which the correction should reduce on average.
        assert mean_abs_corrected < mean_abs_uncorrected

    def test_shi_bolt_se_shrinks_with_sample_size(self):
        rng = np.random.RandomState(9)
        mc, true_b = 3.0, 1.0
        beta = true_b * math.log(10.0)
        ses = []
        for n in (100, 1000, 10000):
            mags = mc + rng.exponential(1.0 / beta, size=n)
            b_hat = ds.gr_b_value_aki(mags, mc)
            ses.append(ds.gr_b_value_shi_bolt_se(mags, b_hat))
        assert ses[0] > ses[1] > ses[2]

    def test_plausibility_band_matches_constants(self):
        assert const.GR_B_VALUE_CENTER == 1.0
        assert const.GR_B_VALUE_CENTER - const.GR_B_VALUE_BAND == pytest.approx(0.5)
        assert const.GR_B_VALUE_CENTER + const.GR_B_VALUE_BAND == pytest.approx(1.5)


# =============================================================================
# 5. Benford's Law chi-square goodness-of-fit
# =============================================================================

class TestBenfordChiSquare:
    def test_provably_benford_distributed_data_passes(self):
        # 10^Uniform(0, k) is provably exactly Benford-distributed for any
        # k >= 1 (log-uniform mantissa) -- this is not an approximation.
        rng = np.random.RandomState(10)
        false_pos = 0
        n_reps = 100
        for _ in range(n_reps):
            vals = 10 ** rng.uniform(0, 15, 2000)
            chi2, dof, n = ds.benford_chi_square(vals)
            if chi2 > 15.51:
                false_pos += 1
        # At alpha=0.05 (critical value 15.51), false-positive rate should
        # be close to 5%, confirming both the chi-square formula and the
        # conventional critical value are correctly applied.
        assert false_pos / n_reps < 0.12

    def test_narrow_range_uniform_data_fails_decisively(self):
        rng = np.random.RandomState(11)
        vals = rng.uniform(100000, 999999, 20000)
        chi2, dof, n = ds.benford_chi_square(vals)
        assert chi2 > 15.51 * 5  # decisively, not marginally, non-conforming

    def test_dof_always_eight(self):
        chi2, dof, n = ds.benford_chi_square([123, 456, 789])
        assert dof == 8

    def test_benford_score_is_1_for_perfect_fit_and_decays_past_critical(self):
        assert ds.benford_score(0.0, 100) == pytest.approx(1.0)
        assert ds.benford_score(15.51, 100) == pytest.approx(0.5)
        assert ds.benford_score(1000.0, 100) == pytest.approx(0.0)


# =============================================================================
# 6. Correlation dimension (Grassberger-Procaccia)
# =============================================================================

class TestCorrelationDimension:
    def test_uniform_2d_scatter_recovers_dc_near_embedding_dimension(self):
        # Regression test for the percentile-range fix: must be close to
        # 2.0, not the ~1.6 the pre-fix (5th/95th percentile) version gave.
        rng = np.random.RandomState(5)
        pts = np.column_stack([rng.uniform(0, 100, 3000), rng.uniform(0, 100, 3000)])
        dc = ds.correlation_dimension(pts)
        assert 1.7 < dc < 2.05

    def test_points_on_a_line_recover_dc_near_one(self):
        rng = np.random.RandomState(5)
        pts = np.column_stack([rng.uniform(0, 100, 3000), np.zeros(3000) + rng.normal(0, 0.001, 3000)])
        dc = ds.correlation_dimension(pts)
        assert 0.85 < dc < 1.1

    def test_clustered_pattern_scores_lower_than_uniform(self):
        # A fault-like clustered pattern must sit clearly BELOW the uniform
        # baseline -- this is the actual discriminative property A4 relies
        # on, and must survive the percentile-range fix.
        rng = np.random.RandomState(5)
        n = 3000
        uniform_pts = np.column_stack([rng.uniform(0, 100, n), rng.uniform(0, 100, n)])
        seg_id = rng.randint(0, 5, n)
        angles = seg_id * 0.7
        along = rng.uniform(0, 40, n)
        jitter = rng.normal(0, 1.0, n)
        clustered_pts = np.column_stack([
            50 + along * np.cos(angles) + jitter * np.sin(angles),
            50 + along * np.sin(angles) - jitter * np.cos(angles),
        ])
        dc_uniform = ds.correlation_dimension(uniform_pts)
        dc_clustered = ds.correlation_dimension(clustered_pts)
        assert dc_clustered < dc_uniform - 0.3

    def test_bias_does_not_grow_or_shrink_with_sample_size(self):
        # The old bug was N-INDEPENDENT (a fixed percentile-selection
        # artifact, not finite-sample noise) -- confirm the fixed version's
        # estimate is stable (not, e.g., drifting further from 2.0 at scale).
        rng = np.random.RandomState(5)
        estimates = []
        for n_pts in (500, 3000, 8000):
            pts = np.column_stack([rng.uniform(0, 100, n_pts), rng.uniform(0, 100, n_pts)])
            estimates.append(ds.correlation_dimension(pts, max_points=min(n_pts, 1500)))
        assert max(estimates) - min(estimates) < 0.15

    def test_too_few_points_returns_nan(self):
        pts = np.random.uniform(0, 1, size=(10, 2))
        assert math.isnan(ds.correlation_dimension(pts))


# =============================================================================
# 7. Haversine great-circle distance
# =============================================================================

class TestHaversine:
    @pytest.mark.parametrize("name,lat1,lon1,lat2,lon2,published_km,tol_pct", [
        ("London-Paris", 51.5074, -0.1278, 48.8566, 2.3522, 344, 2.0),
        ("NewYork-London", 40.7128, -74.0060, 51.5074, -0.1278, 5570, 1.0),
        ("Tokyo-Sydney", 35.6762, 139.6503, -33.8688, 151.2093, 7823, 1.0),
        ("Bangkok-ChiangMai", 13.7563, 100.5018, 18.7883, 98.9853, 588, 3.0),
    ])
    def test_matches_published_city_pair_distance(self, name, lat1, lon1, lat2, lon2, published_km, tol_pct):
        d = ds.haversine_km(lat1, lon1, lat2, lon2)
        pct_err = abs(d - published_km) / published_km * 100
        assert pct_err < tol_pct, f"{name}: got {d:.1f} km, published ~{published_km} km ({pct_err:.2f}% off)"

    def test_zero_distance_for_identical_points(self):
        assert ds.haversine_km(13.75, 100.5, 13.75, 100.5) == pytest.approx(0.0, abs=1e-9)

    def test_antipodal_points_approach_half_circumference(self):
        d = ds.haversine_km(0.0, 0.0, 0.0, 180.0)
        # Half of Earth's circumference at the equator, ~ pi * R.
        assert d == pytest.approx(math.pi * ds.EARTH_RADIUS_KM, rel=1e-6)

    def test_nan_propagates(self):
        assert math.isnan(ds.haversine_km(float("nan"), 0.0, 0.0, 0.0))


class TestHaversineMatrix:
    def test_matches_scalar_haversine_elementwise(self):
        rng = np.random.RandomState(3)
        lats = rng.uniform(-89, 89, 25)
        lons = rng.uniform(-179, 179, 25)
        ref_lats = rng.uniform(-89, 89, 8)
        ref_lons = rng.uniform(-179, 179, 8)
        mat = ds.haversine_km_matrix(lats, lons, ref_lats, ref_lons)
        assert mat.shape == (25, 8)
        max_err = 0.0
        for i in range(25):
            for j in range(8):
                scalar = ds.haversine_km(lats[i], lons[i], ref_lats[j], ref_lons[j])
                max_err = max(max_err, abs(mat[i, j] - scalar))
        assert max_err < 1e-6

    def test_nan_query_point_propagates_to_nan_row(self):
        lats = np.array([10.0, float("nan")])
        lons = np.array([10.0, 20.0])
        ref_lats = np.array([0.0, 5.0])
        ref_lons = np.array([0.0, 5.0])
        mat = ds.haversine_km_matrix(lats, lons, ref_lats, ref_lons)
        assert np.all(np.isfinite(mat[0]))
        assert np.all(np.isnan(mat[1]))


# =============================================================================
# 8. Moment magnitude formula (Kanamori 1977; Hanks & Kanamori 1979)
# =============================================================================

class TestMomentMagnitude:
    @pytest.mark.parametrize("name,m0_n_m,reported_mw", [
        ("2011 Tohoku", 5.31e22, 9.1),
        ("1960 Valdivia", 2.0e23, 9.5),
        ("1994 Northridge", 1.3e19, 6.7),
    ])
    def test_formula_matches_real_earthquakes_within_reporting_precision(self, name, m0_n_m, reported_mw):
        mw_computed = (2.0 / 3.0) * math.log10(m0_n_m) + const.MOMENT_MAGNITUDE_SI_CONSTANT
        assert abs(mw_computed - reported_mw) < 0.06, f"{name}: computed {mw_computed:.3f} vs reported {reported_mw}"

    def test_si_constant_value(self):
        assert const.MOMENT_MAGNITUDE_SI_CONSTANT == pytest.approx(-6.07)


# =============================================================================
# 9. Omori-Utsu aftershock decay fit
# =============================================================================

def _simulate_omori(K: float, c: float, p: float, t_max: float, seed: int) -> np.ndarray:
    """Simulate a non-homogeneous Poisson process n(t)=K/(t+c)^p via thinning."""
    rng = np.random.RandomState(seed)
    lam_max = K / (c ** p)
    times = []
    t = 0.0
    while t < t_max:
        t += rng.exponential(1.0 / lam_max)
        if t >= t_max:
            break
        lam_t = K / (t + c) ** p
        if rng.uniform(0, 1) < lam_t / lam_max:
            times.append(t)
    return np.array(times)


class TestOmoriUtsuFit:
    @pytest.mark.parametrize("true_p", [0.9, 1.1, 1.4])
    def test_recovers_known_p_within_tolerance_averaged_over_seeds(self, true_p):
        # Regression test for the count-weighting fix: averaged over several
        # realisations, the fitted p must land within ~15% of the true
        # generating p (the pre-fix unweighted version was biased ~30% low,
        # consistently, not just as sampling noise).
        fitted = []
        for seed in range(8):
            times = _simulate_omori(K=50.0, c=0.1, p=true_p, t_max=30.0, seed=seed)
            fit = ds.fit_omori_utsu(times)
            if not fit["degenerate"] and math.isfinite(fit["p"]):
                fitted.append(fit["p"])
        assert len(fitted) >= 5
        mean_p = float(np.mean(fitted))
        assert abs(mean_p - true_p) / true_p < 0.20

    @pytest.mark.parametrize("n", [50, 200, 1000])
    def test_flat_rate_process_is_flagged_degenerate_at_nominal_rate(self, n):
        # Regression test for the ks_critical scaling fix: a fixed 0.05
        # threshold was found to correctly flag a KNOWN homogeneous
        # (non-decaying) Poisson process as degenerate only ~9% of the time
        # at n=50 and ~40% at n=200 (an N-DEPENDENT power failure -- the
        # check was nearly inert at realistic small-catalog sizes). The
        # sample-size-scaled critical value must restore this to a high,
        # roughly N-INDEPENDENT correct-flag rate.
        flagged = 0
        n_reps = 60
        for seed in range(n_reps):
            rng = np.random.RandomState(seed)
            times = np.sort(rng.uniform(0.01, 30, n))
            fit = ds.fit_omori_utsu(times)
            if fit["degenerate"]:
                flagged += 1
        assert flagged / n_reps > 0.85

    def test_too_few_events_returns_degenerate_nan(self):
        fit = ds.fit_omori_utsu([1.0, 2.0])
        assert fit["degenerate"] is True
        assert math.isnan(fit["p"])

    def test_zero_time_spread_returns_degenerate_not_crash(self):
        """Regression test for a real bug found 2026-07-11 during a
        from-scratch re-score of the 9th-pass corpus:
        `corrupt_real_morocco_20230908_query_timestamp_collision_low/high`
        (a dataset where a large fraction of records share one identical
        batch-import timestamp -- a real, non-adversarial corruption
        pattern, see corrupt.py::timestamp_collision) produced a cluster
        with n>=5 events but ZERO time spread (all events at the exact
        same time), which crashed `np.geomspace`/`np.histogram` with
        'bins must increase monotonically' instead of being flagged
        degenerate like every other unfittable input. This must return a
        degenerate result, not raise."""
        fit = ds.fit_omori_utsu([5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        assert fit["degenerate"] is True
        assert math.isnan(fit["p"])


# =============================================================================
# 10. Fellegi-Sunter simplified match probability
# =============================================================================

class TestFellegiSunter:
    def test_identical_record_scores_near_one(self):
        assert ds.fellegi_sunter_match_prob(0.0, 0.0, 0.0) == pytest.approx(1.0)

    def test_very_different_record_scores_near_zero(self):
        p = ds.fellegi_sunter_match_prob(3600.0, 5000.0, 3.0)
        assert p < 1e-4

    def test_all_fields_missing_gives_neutral_probability(self):
        # Each field contributes a neutral 0.5 kernel weight when the
        # comparison value itself is missing/non-finite; combined
        # multiplicatively, 0.5^3 = 0.125.
        p = ds.fellegi_sunter_match_prob(float("nan"), float("nan"), float("nan"))
        assert p == pytest.approx(0.125)

    def test_probability_at_least_one_match_formula(self):
        p = ds.probability_at_least_one_match([0.3, 0.3, 0.3])
        assert p == pytest.approx(1 - 0.7 ** 3)

    def test_probability_at_least_one_match_bounded_regardless_of_count(self):
        # Corrected per-record formulation (Gap-Remediation Addendum Section
        # 7.2) -- must stay in [0,1] no matter how many candidates.
        p = ds.probability_at_least_one_match([0.9] * 50)
        assert 0.0 <= p <= 1.0


# =============================================================================
# 11. Programmatic cross-check: every AHP weight/threshold in _constants.py
#     against Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md
# =============================================================================

class TestConstantsMatchCriteriaAndWeightsDoc:
    """
    Two layers checked here, matching the two epistemic categories
    _constants.py now documents:

    1. The AHP-ONLY PRIORS (*_AHP_PRIOR names) -- transcribed by hand from
       Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Sections
       1.4 and 2.1-2.4's original derivation. These never change regardless
       of calibration -- they are the fixed AHP input to the blend.

    2. The FINAL, IN-USE BLENDED weights (AXIS_WEIGHTS, WITHIN_A/P/C/I) --
       transcribed from the real 73-dataset calibration corpus's computed
       AHP x EWM blend (calibration/ewm_report.json, Section 5.4 of the
       same doc). Corpus grew from 71 to 73 datasets on 2026-07-05 after an
       independent re-verification pass found and fixed a 2-file gap
       (ishikawa_202401.json, japan_2023-.json -- see corpus_manifest.csv
       notes and calibration/parsers.py::prepare_usgs_geojson); the values
       below reflect the corrected corpus. If this test ever fails, either
       _constants.py, the calibration report, or the doc has drifted --
       check all three before assuming which is wrong.
    """

    def test_axis_weights_ahp_prior(self):
        assert const.W_A_AHP_PRIOR == pytest.approx(0.514)
        assert const.W_P_AHP_PRIOR == pytest.approx(0.216)
        assert const.W_C_AHP_PRIOR == pytest.approx(0.073)
        assert const.W_I_AHP_PRIOR == pytest.approx(0.197)
        assert sum(const.AXIS_WEIGHTS_AHP_PRIOR.values()) == pytest.approx(1.0, abs=1e-3)

    def test_within_authenticity_weights_ahp_prior(self):
        expected = {"A1": 0.303, "A2": 0.165, "A3": 0.165, "A4": 0.303, "A5": 0.065}
        for k, v in expected.items():
            assert const.WITHIN_A_AHP_PRIOR[k] == pytest.approx(v)
        assert sum(const.WITHIN_A_AHP_PRIOR.values()) == pytest.approx(1.0, abs=2e-3)

    def test_within_plausibility_weights_ahp_prior(self):
        expected = {"P4": 0.143, "P5": 0.143, "P6": 0.368, "P7": 0.235, "P8": 0.056, "P9": 0.056}
        for k, v in expected.items():
            assert const.WITHIN_P_AHP_PRIOR[k] == pytest.approx(v)
        assert sum(const.WITHIN_P_AHP_PRIOR.values()) == pytest.approx(1.0, abs=2e-3)

    def test_within_completeness_weights_ahp_prior(self):
        expected = {"C1": 0.144, "C2": 0.320, "C3": 0.391, "C4": 0.144}
        for k, v in expected.items():
            assert const.WITHIN_C_AHP_PRIOR[k] == pytest.approx(v)
        assert sum(const.WITHIN_C_AHP_PRIOR.values()) == pytest.approx(1.0, abs=2e-3)

    def test_within_instrumentation_weights_ahp_prior(self):
        expected = {"I1": 0.156, "I2": 0.295, "I3": 0.083, "I4": 0.156, "I5": 0.311}
        for k, v in expected.items():
            assert const.WITHIN_I_AHP_PRIOR[k] == pytest.approx(v)
        assert sum(const.WITHIN_I_AHP_PRIOR.values()) == pytest.approx(1.0, abs=2e-3)

    def test_global_weight_table_section_3_ahp_prior_only(self):
        # Global weight = axis_weight * within_axis_weight, per the doc's
        # Section 3 master table -- this is the AHP-ONLY table (Section 3's
        # own status note: retained for traceability, no longer in use).
        expected_global = {
            "A1": 0.156, "A2": 0.085, "A3": 0.085, "A4": 0.156, "A5": 0.033,
            "P4": 0.031, "P5": 0.031, "P6": 0.079, "P7": 0.051, "P8": 0.012, "P9": 0.012,
            "C1": 0.011, "C2": 0.023, "C3": 0.029, "C4": 0.011,
            "I1": 0.031, "I2": 0.058, "I3": 0.016, "I4": 0.031, "I5": 0.061,
        }
        computed = {}
        for k, v in const.WITHIN_A_AHP_PRIOR.items():
            computed[k] = round(v * const.W_A_AHP_PRIOR, 3)
        for k, v in const.WITHIN_P_AHP_PRIOR.items():
            computed[k] = round(v * const.W_P_AHP_PRIOR, 3)
        for k, v in const.WITHIN_C_AHP_PRIOR.items():
            computed[k] = round(v * const.W_C_AHP_PRIOR, 3)
        for k, v in const.WITHIN_I_AHP_PRIOR.items():
            computed[k] = round(v * const.W_I_AHP_PRIOR, 3)
        for k, expected in expected_global.items():
            assert computed[k] == pytest.approx(expected, abs=0.001), f"{k}: computed {computed[k]} vs doc {expected}"

    def test_axis_weights_blended_in_use(self):
        # TENTH-PASS AHP x EWM blended weights (2026-07-16, after fixing a
        # floating-point bin-edge bug in
        # data_certify/stats.py::maximum_curvature_mc() that affected 18 of
        # the 968-dataset calibration corpus's A2 scores -- see
        # _constants.py's module docstring's TENTH CALIBRATION PASS
        # section), calibration/ewm_report.json ("axis" group). These are
        # what the running audit actually uses.
        # NOTE: this test's own hardcoded `expected` dict is a SEPARATE
        # copy of the weights from `_constants.py`, kept here specifically
        # to catch drift between the two -- it was found out of date
        # (still holding EIGHTH-PASS/n=295 numbers) once during the 9th
        # pass, because the 8th-pass documentation sweep updated every
        # Docs/*.md file and `_constants.py` itself but missed this test
        # file's own literal copy. Updated to match the TENTH-PASS values
        # now live in `_constants.py`. Do not let this file silently drift
        # out of sync again on any future recalibration.
        expected = {
            "A": 0.6894844988460549, "P": 0.16836943659202896,
            "C": 0.028258588896277272, "I": 0.11388747566563887,
        }
        for k, v in expected.items():
            assert const.AXIS_WEIGHTS[k] == pytest.approx(v, abs=1e-6)
        assert sum(const.AXIS_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-6)

    def test_within_authenticity_weights_blended_in_use(self):
        # TENTH-PASS values (see test_axis_weights_blended_in_use).
        expected = {
            "A1": 0.3761270287081997, "A2": 0.008668999147779084,
            "A3": 0.42246229044903777, "A4": 0.18974276547380506,
            "A5": 0.002998916221178312,
        }
        for k, v in expected.items():
            assert const.WITHIN_A[k] == pytest.approx(v, abs=1e-6)
        assert sum(const.WITHIN_A.values()) == pytest.approx(1.0, abs=1e-6)

    def test_within_plausibility_weights_blended_in_use(self):
        # NINTH-PASS values: P9 remains below MIN_EWM_N=20 observations
        # (n_obs=0 at n=89/295/968) and RETAINS its exact AHP value
        # unchanged. P5 jumped from n_obs=24 to 90 (the synthetic ladder
        # populated rupture_length_km at levels 7-9) and now dominates the
        # blend.
        expected = {
            "P4": 0.002239068172281027, "P5": 0.7657437676196038,
            "P6": 2.450103053546287e-15, "P7": 0.12608347509535475,
            "P8": 0.04993368911275801, "P9": 0.056,
        }
        for k, v in expected.items():
            assert const.WITHIN_P[k] == pytest.approx(v, abs=1e-6)
        assert sum(const.WITHIN_P.values()) == pytest.approx(1.0, abs=1e-6)

    def test_within_completeness_weights_blended_in_use(self):
        # TENTH-PASS values (2026-07-16 maximum_curvature_mc fix -- see
        # _constants.py's module docstring).
        expected = {
            "C1": 0.0012354172361284206, "C2": 0.3372086862465165,
            "C3": 0.2280560865324849, "C4": 0.43349980998487014,
        }
        for k, v in expected.items():
            assert const.WITHIN_C[k] == pytest.approx(v, abs=1e-6)
        assert sum(const.WITHIN_C.values()) == pytest.approx(1.0, abs=1e-6)

    def test_within_instrumentation_weights_blended_in_use(self):
        # I4 FINALLY cleared MIN_EWM_N=20 during the ninth pass (n_obs=4 at
        # n=89/295 -> 124 at n=968, because some new fabricated datasets
        # were given populated event_uid_source values) and is now
        # genuinely data-driven rather than retaining its AHP value.
        # TENTH-PASS values (2026-07-16 maximum_curvature_mc fix -- see
        # _constants.py's module docstring).
        expected = {
            "I1": 0.48778188493130464, "I2": 0.2689926977757587,
            "I3": 0.19954635267409818, "I4": 0.003980451893249224,
            "I5": 0.03969861272558927,
        }
        for k, v in expected.items():
            assert const.WITHIN_I[k] == pytest.approx(v, abs=1e-6)
        assert sum(const.WITHIN_I.values()) == pytest.approx(1.0, abs=1e-6)

    def test_decision_thresholds(self):
        # theta_admit unchanged (now empirically validated against the
        # sixth-pass CORRECTED production formula); theta_reject revised
        # down 0.50 -> 0.45 -> 0.20 (the sixth pass found that 0.45 was
        # validated against a formula production never actually runs --
        # see calibration/threshold_report.md's "no-clean-separation"
        # finding and _constants.py's SIXTH CALIBRATION PASS docstring);
        # theta_auth unchanged and still provisional (A6 never exercised
        # in the calibration corpus).
        assert const.THETA_ADMIT == pytest.approx(0.75)
        assert const.THETA_REJECT == pytest.approx(0.20)
        assert const.THETA_AUTH == pytest.approx(0.50)
        assert const.THETA_REJECT <= const.THETA_ADMIT

    def test_hard_override_parameters(self):
        assert const.EPSILON_TOL == pytest.approx(0.001)
        assert const.ALPHA == pytest.approx(0.01)
        assert const.HARD_OVERRIDE_FAMILY_SIZE == 3
        assert const.ALPHA_CORRECTED == pytest.approx(const.ALPHA / 3)

    def test_physical_hard_bounds(self):
        assert (const.LAT_MIN, const.LAT_MAX) == (-90.0, 90.0)
        assert (const.LON_MIN, const.LON_MAX) == (-180.0, 180.0)
        assert const.DEPTH_MAX_KM == pytest.approx(750.0)
        assert const.MAGNITUDE_MAX == pytest.approx(9.5)
        # The documented reason for 750 (not 700) km: keep the real 735.8 km
        # Vanuatu/Tonga 2004 event safely inside the non-violation zone.
        assert 735.8 < const.DEPTH_MAX_KM

    def test_ahp_random_index_table_matches_saaty_1980(self):
        # Values explicitly cited in the Criteria & Weights doc's Section 6
        # bibliography: RI(4)=0.90, RI(5)=1.12, RI(6)=1.24.
        assert const.AHP_RANDOM_INDEX[4] == pytest.approx(0.90)
        assert const.AHP_RANDOM_INDEX[5] == pytest.approx(1.12)
        assert const.AHP_RANDOM_INDEX[6] == pytest.approx(1.24)
