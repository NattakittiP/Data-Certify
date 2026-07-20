# -*- coding: utf-8 -*-
"""Tests for data_certify/stats.py -- shared statistical primitives."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify import stats


class TestBenford:
    def test_leading_digit_basic(self):
        assert stats.leading_digit(123.45) == 1
        assert stats.leading_digit(9.99) == 9
        assert stats.leading_digit(0.00456) == 4
        assert stats.leading_digit(50000) == 5

    def test_leading_digit_edge_cases(self):
        assert stats.leading_digit(0.0) is None
        assert stats.leading_digit(float("nan")) is None
        assert stats.leading_digit(float("inf")) is None

    def test_benford_conforming_data_scores_high(self):
        # Genuine Benford-distributed sample: 10^Uniform(0, 6).
        rng = np.random.RandomState(0)
        values = 10 ** rng.uniform(0, 6, size=5000)
        chi2, dof, n = stats.benford_chi_square(values)
        assert dof == 8
        assert n == 5000
        score = stats.benford_score(chi2, n)
        assert score > 0.7

    def test_benford_non_conforming_data_scores_low(self):
        # Uniformly distributed leading digits (not log-scaled) should fail hard.
        rng = np.random.RandomState(0)
        # Force each leading digit to appear equally often.
        digits = np.tile(np.arange(1, 10), 2000)
        values = digits.astype(float) * 1000  # leading digit preserved
        chi2, dof, n = stats.benford_chi_square(values)
        score = stats.benford_score(chi2, n)
        assert score < 0.5

    def test_benford_empty_input(self):
        chi2, dof, n = stats.benford_chi_square([])
        assert n == 0
        assert math.isnan(chi2)
        assert stats.benford_score(chi2, n) == 1.0


class TestGutenbergRichter:
    def test_recovers_known_b_value(self):
        rng = np.random.RandomState(1)
        true_b = 1.0
        beta = true_b * math.log(10)
        mc = 3.0
        mags = mc + rng.exponential(1.0 / beta, size=2000)
        b_hat = stats.gr_b_value_aki(mags, mc)
        assert abs(b_hat - true_b) < 0.15

    def test_shi_bolt_se_positive(self):
        rng = np.random.RandomState(1)
        mags = 3.0 + rng.exponential(1.0, size=500)
        b_hat = stats.gr_b_value_aki(mags, 3.0)
        se = stats.gr_b_value_shi_bolt_se(mags, b_hat)
        assert se > 0

    def test_insufficient_data_returns_nan(self):
        assert math.isnan(stats.gr_b_value_aki([3.0], 3.0))
        assert math.isnan(stats.gr_b_value_aki([], 3.0))


class TestMaximumCurvature:
    def test_recovers_approximate_mc(self):
        rng = np.random.RandomState(2)
        true_mc = 3.5
        mags = np.concatenate([
            rng.uniform(1.0, true_mc, 200),   # incomplete tail below Mc
            true_mc + rng.exponential(1.0, 3000),
        ])
        mc_hat = stats.maximum_curvature_mc(mags)
        assert abs(mc_hat - true_mc) < 0.5

    def test_exact_bin_on_clean_quantized_data(self):
        """
        Regression test for the 2026-07-16 floating-point bin-edge bug
        (discovered during Group D1(d) independent re-verification): the
        previous implementation built histogram bin edges with
        `np.arange(lo, hi + bin_width, bin_width)`, whose accumulated
        floating-point drift could push an edge a few ULPs past the exact
        magnitude value it was meant to sit at, silently misclassifying
        every event at that value into the wrong bin. The tolerant
        `test_recovers_approximate_mc` test above (< 0.5 magnitude units)
        is far too loose to catch a single-bin (0.1) misclassification --
        that is exactly why this bug shipped undetected and went on to
        affect the computed Mc for 53.5% of the 985-dataset calibration
        corpus. This test uses a small, exactly-quantized, unambiguous
        (non-tied) peak that the old implementation is known to get wrong,
        and asserts the exact expected bin -- not just "close enough."
        """
        # 84 events at 3.5, 69 at 3.6, 64 at 3.7, 49 at 3.8 (real counts
        # from the D1(d) EMSC Iquique dataset that exposed the bug): the
        # true peak is unambiguously 3.5. The old np.arange/np.histogram
        # implementation returned 3.7 here (it silently merged the 3.7 and
        # 3.8 counts into the "3.7" bin due to edge drift).
        mags = np.concatenate([
            np.full(84, 3.5), np.full(69, 3.6), np.full(64, 3.7), np.full(49, 3.8),
        ])
        mc_hat = stats.maximum_curvature_mc(mags)
        assert mc_hat == pytest.approx(3.5, abs=1e-9)

    def test_no_float_drift_across_many_bin_offsets(self):
        """
        The float-drift bug's manifestation depends on how far a bin edge
        is from `lo` (error accumulates with the number of `np.arange`
        steps), so a single fixed example is not enough to be confident the
        underlying mechanism is fixed, not just one lucky case. Sweeps a
        range of `lo` offsets and bin counts, each with a single, exactly-
        quantized, unambiguous (unique, untied) peak bin, and asserts the
        peak is always recovered exactly.
        """
        rng = np.random.RandomState(7)
        for lo in [0.0, 1.0, 1.3, 2.7, 3.5, 5.05]:
            for n_bins in [5, 20, 47, 90]:
                peak_bin = int(rng.randint(0, n_bins))
                mags = []
                for b in range(n_bins):
                    count = 10 if b == peak_bin else rng.randint(1, 9)
                    mags.append(np.round(lo + b * 0.1, 10).repeat(count))
                mags = np.concatenate(mags)
                expected = round(lo + peak_bin * 0.1, 10)
                mc_hat = stats.maximum_curvature_mc(mags)
                assert mc_hat == pytest.approx(expected, abs=1e-6), (
                    f"lo={lo} n_bins={n_bins} peak_bin={peak_bin}: "
                    f"expected {expected}, got {mc_hat}"
                )


class TestClopperPearson:
    def test_no_violations_gives_p_near_one(self):
        p = stats.clopper_pearson_upper_tail(0, 1000, 0.001)
        assert p == 1.0

    def test_large_violation_fraction_is_significant(self):
        p = stats.clopper_pearson_upper_tail(50, 200, 0.001)
        assert p < 0.001

    def test_matches_deep_dive_06_worked_example_large_n(self):
        # n=5,000,000, k=3, epsilon_tol=0.001 -> p ~ 1 (isolated error)
        p = stats.clopper_pearson_upper_tail(3, 5_000_000, 0.001)
        assert p > 0.99

    def test_matches_deep_dive_06_worked_example_small_n(self):
        # n=200, k=5, epsilon_tol=0.001 -> overwhelmingly significant
        p = stats.clopper_pearson_upper_tail(5, 200, 0.001)
        assert p < 1e-5

    def test_k_cannot_exceed_n(self):
        with pytest.raises(ValueError):
            stats.clopper_pearson_upper_tail(10, 5, 0.001)


class TestKSStatistic:
    def test_identical_samples_give_zero(self):
        a = np.linspace(0, 1, 100)
        assert stats.ks_statistic_2sample(a, a) == pytest.approx(0.0, abs=1e-9)

    def test_disjoint_samples_give_one(self):
        a = np.zeros(50)
        b = np.ones(50)
        assert stats.ks_statistic_2sample(a, b) == pytest.approx(1.0)

    def test_bounded_in_0_1(self):
        rng = np.random.RandomState(3)
        a = rng.normal(0, 1, 200)
        b = rng.normal(0.5, 1.5, 200)
        d = stats.ks_statistic_2sample(a, b)
        assert 0.0 <= d <= 1.0


class TestCorrelationDimension:
    def test_uniform_2d_points_near_embedding_dimension(self):
        rng = np.random.RandomState(4)
        points = rng.uniform(0, 1, size=(2000, 2))
        dc = stats.correlation_dimension(points)
        assert 1.5 < dc < 2.3

    def test_clustered_points_lower_dimension(self):
        rng = np.random.RandomState(4)
        # Points confined near a 1-D line -> Dc should trend toward ~1.
        t = rng.uniform(0, 1, 2000)
        noise = rng.normal(0, 0.001, 2000)
        points = np.column_stack([t, noise])
        dc = stats.correlation_dimension(points)
        assert dc < 1.5

    def test_too_few_points_returns_nan(self):
        assert math.isnan(stats.correlation_dimension(np.zeros((5, 2))))


class TestMannKendallAndSen:
    def test_detects_clear_upward_trend(self):
        x = np.arange(200, dtype=float) + np.random.RandomState(5).normal(0, 0.1, 200)
        mk = stats.mann_kendall_test(x)
        assert mk["trend_detected"]
        assert mk["z"] > 0

    def test_no_trend_in_pure_noise(self):
        rng = np.random.RandomState(6)
        x = rng.normal(0, 1, 300)
        mk = stats.mann_kendall_test(x)
        assert not mk["trend_detected"]

    def test_sen_slope_recovers_true_slope(self):
        rng = np.random.RandomState(7)
        x = np.arange(300, dtype=float)
        y = 2.0 * x + rng.normal(0, 1, 300)
        slope = stats.sen_slope(x, y)
        assert abs(slope - 2.0) < 0.2

    def test_large_n_does_not_hang(self):
        # Regression test: both functions must subsample for large N
        # (data_certify.stats.MAX_TREND_N) rather than being O(N^2).
        rng = np.random.RandomState(8)
        n = 50_000
        x = np.arange(n, dtype=float)
        y = 0.5 * x + rng.normal(0, 5, n)
        mk = stats.mann_kendall_test(y)
        slope = stats.sen_slope(x, y)
        assert mk["trend_detected"]
        assert slope > 0


class TestFellegiSunter:
    def test_close_pair_scores_high(self):
        p = stats.fellegi_sunter_match_prob(0.0, 0.0, 0.0)
        assert p > 0.9

    def test_far_pair_scores_low(self):
        p = stats.fellegi_sunter_match_prob(1e6, 1e6, 10.0)
        assert p < 0.01

    def test_probability_at_least_one_match_bounded(self):
        # Regression test for Gap-Remediation Addendum Section 7.2's fix:
        # must stay in [0,1] even with many high-probability candidates.
        probs = [0.9, 0.8, 0.95, 0.99, 0.7]
        p = stats.probability_at_least_one_match(probs)
        assert 0.0 <= p <= 1.0

    def test_empty_candidates_gives_zero(self):
        assert stats.probability_at_least_one_match([]) == 0.0


class TestHaversine:
    def test_same_point_is_zero(self):
        assert stats.haversine_km(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_approx(self):
        # Roughly London to Paris, ~344 km.
        d = stats.haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
        assert 330 < d < 360

    def test_nan_input_gives_nan(self):
        assert math.isnan(stats.haversine_km(float("nan"), 0, 0, 0))


class TestProjectLonLatToLocalKm:
    """
    Regression tests for the 2026-07-21 A4 bugfix: `correlation_dimension`
    previously received raw (lat, lon) in DEGREES, so Euclidean distance was
    computed directly on degree values -- wrong both near the poles (a
    degree of longitude shrinks by cos(latitude)) and across the +/-180
    antimeridian (179.9 and -179.9 degrees are ~11km apart on the real
    sphere but ~359.8 degrees apart in raw coordinates). These tests check
    `project_lonlat_to_local_km` directly, independent of A4's scoring.
    """

    def test_antimeridian_adjacent_points_project_close_together(self):
        # Two points ~11km apart in reality (straddling the dateline),
        # ~1,700km apart on the equator if the antimeridian wrap were
        # ignored (0.002 degrees jump treated as a ~359.998-degree jump).
        lat = np.array([0.0, 0.0])
        lon = np.array([179.999, -179.999])
        pts = stats.project_lonlat_to_local_km(lat, lon)
        dist = float(np.hypot(*(pts[0] - pts[1])))
        expected = stats.haversine_km(0.0, 179.999, 0.0, -179.999)
        assert dist < 20.0, (
            f"antimeridian-adjacent points projected {dist:.1f}km apart -- "
            f"expected ~{expected:.2f}km (the unwrapping fix appears broken)."
        )
        assert dist == pytest.approx(expected, rel=0.05)

    def test_high_latitude_longitude_spacing_is_shrunk_by_cosine(self):
        # At 80 degrees latitude, 1 degree of longitude spans far fewer km
        # than at the equator (shrunk by cos(80deg) ~= 0.174). A raw-degree
        # Euclidean distance would treat these two separations as equal.
        lat_eq = np.array([0.0, 0.0])
        lon_eq = np.array([0.0, 1.0])
        lat_hi = np.array([80.0, 80.0])
        lon_hi = np.array([0.0, 1.0])
        d_eq = np.hypot(*(stats.project_lonlat_to_local_km(lat_eq, lon_eq)[0]
                           - stats.project_lonlat_to_local_km(lat_eq, lon_eq)[1]))
        d_hi = np.hypot(*(stats.project_lonlat_to_local_km(lat_hi, lon_hi)[0]
                           - stats.project_lonlat_to_local_km(lat_hi, lon_hi)[1]))
        assert d_hi < d_eq * 0.3, (
            "1 degree of longitude at 80N should project to a much smaller "
            "km distance than at the equator -- cos(latitude) scaling "
            "appears missing."
        )

    def test_nan_coordinates_propagate_to_nan(self):
        lat = np.array([0.0, float("nan")])
        lon = np.array([0.0, 1.0])
        pts = stats.project_lonlat_to_local_km(lat, lon)
        assert math.isnan(pts[1, 0]) and math.isnan(pts[1, 1])
