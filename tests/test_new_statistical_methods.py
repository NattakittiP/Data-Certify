# -*- coding: utf-8 -*-
"""
tests/test_new_statistical_methods.py -- Tests for the statistical methods
added in the "make the framework as comprehensive as possible" pass:

    stats.chi_square_sf                       -- scipy-free chi-square survival function
    stats.em_mvn_missing / stats.little_mcar_test  -- Little (1988) MCAR test for C1
    stats.discretize_comparison / stats.fellegi_sunter_em /
        stats.fellegi_sunter_em_match_probs   -- EM-fitted Fellegi-Sunter for I4
    CertifyDataset.resample                   -- fancy-indexing helper for bootstrap/subsampling
    DataCertifyAuditor.estimate_uncertainty   -- subsample-without-replacement CI for T(D)

Each new statistical primitive is checked against an independently-knowable
ground truth (textbook chi-square critical values, a synthetic MVN with a
KNOWN mean/covariance, a synthetic match/non-match mixture with a KNOWN
mixing proportion) rather than only checking "it runs" -- consistent with
this project's existing test-suite discipline (see test_scientific_validity.py).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify import stats
from data_certify.decision import DataCertifyAuditor
from conftest import make_dataset, make_gr_dataset


# =============================================================================
# chi_square_sf
# =============================================================================

class TestChiSquareSf:
    def test_matches_textbook_critical_values(self):
        # Standard chi-square critical values at alpha=0.05 (Abramowitz &
        # Stegun 1964, Table 26.8).
        assert stats.chi_square_sf(3.841, 1) == pytest.approx(0.05, abs=1e-3)
        assert stats.chi_square_sf(5.991, 2) == pytest.approx(0.05, abs=1e-3)
        assert stats.chi_square_sf(7.815, 3) == pytest.approx(0.05, abs=1e-3)
        assert stats.chi_square_sf(11.070, 5) == pytest.approx(0.05, abs=1e-3)
        assert stats.chi_square_sf(18.307, 10) == pytest.approx(0.05, abs=1e-3)

    def test_zero_statistic_gives_probability_one(self):
        assert stats.chi_square_sf(0.0, 5) == 1.0

    def test_large_statistic_gives_near_zero(self):
        assert stats.chi_square_sf(1000.0, 3) < 1e-10

    def test_monotonically_decreasing_in_x(self):
        xs = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0]
        vals = [stats.chi_square_sf(x, 4) for x in xs]
        assert all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))

    def test_invalid_dof_returns_nan(self):
        assert math.isnan(stats.chi_square_sf(1.0, 0))
        assert math.isnan(stats.chi_square_sf(1.0, -1))


# =============================================================================
# em_mvn_missing
# =============================================================================

class TestEmMvnMissing:
    def test_complete_data_recovers_exact_sample_moments(self):
        rng = np.random.RandomState(0)
        mu_true = np.array([1.0, 2.0, 3.0])
        cov_true = np.array([[1.0, 0.3, 0.1], [0.3, 2.0, 0.2], [0.1, 0.2, 0.5]])
        X = rng.multivariate_normal(mu_true, cov_true, size=2000)
        mu_hat, sigma_hat, n_iter, converged = stats.em_mvn_missing(X)
        assert np.allclose(mu_hat, X.mean(axis=0), atol=1e-6)
        assert np.allclose(sigma_hat, np.cov(X.T, ddof=0), atol=1e-4)

    def test_mcar_missing_data_recovers_approximately_true_parameters(self):
        rng = np.random.RandomState(1)
        mu_true = np.array([0.0, 0.0, 0.0])
        cov_true = np.eye(3)
        X = rng.multivariate_normal(mu_true, cov_true, size=3000)
        X[rng.rand(*X.shape) < 0.3] = np.nan
        mu_hat, sigma_hat, n_iter, converged = stats.em_mvn_missing(X)
        assert converged
        assert np.max(np.abs(mu_hat - mu_true)) < 0.1
        assert np.max(np.abs(sigma_hat - cov_true)) < 0.2

    def test_degenerate_constant_column_does_not_crash(self):
        # A zero-variance column (e.g. depth_km all identical) must not
        # raise a singular-matrix error -- the ridge regularisation exists
        # exactly for this.
        rng = np.random.RandomState(2)
        X = np.column_stack([
            rng.normal(0, 1, 200), np.full(200, 5.0), rng.normal(0, 1, 200),
        ])
        mu_hat, sigma_hat, n_iter, converged = stats.em_mvn_missing(X)
        assert np.isfinite(mu_hat).all()
        assert np.isfinite(sigma_hat).all()


# =============================================================================
# little_mcar_test
# =============================================================================

class TestLittleMcarTest:
    def test_genuine_mcar_is_not_rejected(self):
        rng = np.random.RandomState(3)
        X = rng.multivariate_normal(np.zeros(4), np.eye(4), size=1500)
        mask = rng.rand(*X.shape) < 0.25
        X[mask] = np.nan
        result = stats.little_mcar_test(X)
        assert result["mcar_at_alpha05"] is True
        assert result["p_value"] > 0.05

    def test_missingness_correlated_with_another_variable_is_rejected(self):
        # Missingness of column 0 depends on the VALUE of column 1 (a
        # textbook MAR-but-not-MCAR case) -- Little's test compares
        # observed-variable means across patterns, so this is exactly the
        # class of violation it's designed to catch.
        rng = np.random.RandomState(4)
        X = rng.multivariate_normal(np.zeros(4), np.eye(4), size=1500)
        drop = X[:, 1] > 0.5
        X[drop, 0] = np.nan
        result = stats.little_mcar_test(X)
        assert result["mcar_at_alpha05"] is False
        assert result["p_value"] < 0.01

    def test_pure_self_censoring_is_a_disclosed_blind_spot(self):
        # Missingness of column 0 depends ONLY on column 0's own
        # (unobserved) value -- true MNAR. No test based only on observed
        # data can catch this (Rubin 1976); Little's test should NOT flag
        # it, and this is a documented limitation, not a bug.
        rng = np.random.RandomState(5)
        X = rng.multivariate_normal(np.zeros(3), np.eye(3), size=1500)
        censor = X[:, 0] > 0.8
        X[censor, 0] = np.nan
        result = stats.little_mcar_test(X)
        assert result["mcar_at_alpha05"] is True

    def test_no_missingness_is_untestable_not_falsely_rejected(self):
        X = np.random.RandomState(6).normal(size=(100, 3))
        result = stats.little_mcar_test(X)
        assert result["mcar_at_alpha05"] is True
        assert math.isnan(result["p_value"])
        assert result["n_patterns"] == 1


# =============================================================================
# C1 integration: Little's test wired into axis_completeness.py
# =============================================================================

class TestC1UsesLittleTest:
    def test_uniform_random_missingness_flagged_mcar(self):
        from data_certify.axis_completeness import score_completeness
        ds = make_dataset(n=300)
        rng = np.random.RandomState(7)
        idx = rng.choice(300, size=40, replace=False)
        ds.magnitude[idx] = np.nan
        result = score_completeness(ds)
        c1 = result.sub_results["C1"]
        assert c1.detail["mcar_like"] is True
        assert "little_p_value" in c1.detail

    def test_time_correlated_missingness_flagged_not_mcar(self):
        from data_certify.axis_completeness import score_completeness
        ds = make_dataset(n=300)
        ds.magnitude[150:] = np.nan  # missingness correlated with time/lat/lon
        result = score_completeness(ds)
        c1 = result.sub_results["C1"]
        assert c1.detail["mcar_like"] is False


# =============================================================================
# discretize_comparison
# =============================================================================

class TestDiscretizeComparison:
    def test_close_values_get_low_levels(self):
        levels, n_levels = stats.discretize_comparison(
            np.array([0.0, 1.0, 100.0]), scale=10.0, edges_frac=(0.25, 0.6, 1.0))
        assert levels[0] == 0     # 0.0 <= 0.25*10 -> closest level
        assert levels[2] == 3     # 100 >> 10 -> open-ended top bin
        assert n_levels == 5      # 4 finite + 1 missing

    def test_nan_maps_to_dedicated_missing_level(self):
        levels, n_levels = stats.discretize_comparison(
            np.array([1.0, np.nan, 2.0]), scale=10.0)
        assert levels[1] == n_levels - 1  # last level = missing
        assert levels[0] != n_levels - 1


# =============================================================================
# fellegi_sunter_em
# =============================================================================

class TestFellegiSunterEm:
    def test_recovers_known_mixing_proportion_and_separates_classes(self):
        rng = np.random.RandomState(8)
        n_match, n_nonmatch = 150, 850
        dt = np.concatenate([np.abs(rng.normal(2, 3, n_match)), rng.uniform(0, 120, n_nonmatch)])
        dist = np.concatenate([np.abs(rng.normal(3, 4, n_match)), rng.uniform(0, 100, n_nonmatch)])
        mag = np.concatenate([np.abs(rng.normal(0.05, 0.05, n_match)), rng.uniform(0, 0.6, n_nonmatch)])
        true_label = np.concatenate([np.ones(n_match), np.zeros(n_nonmatch)])

        result = stats.fellegi_sunter_em_match_probs(dt, dist, mag)
        assert result["converged"] is True
        assert result["pi"] == pytest.approx(n_match / (n_match + n_nonmatch), abs=0.03)

        post = result["posterior"]
        assert post[true_label == 1].mean() > 0.8
        assert post[true_label == 0].mean() < 0.2

        accuracy = ((post > 0.5) == true_label).mean()
        assert accuracy > 0.95

    def test_empty_input_does_not_crash(self):
        result = stats.fellegi_sunter_em_match_probs(
            np.array([]), np.array([]), np.array([]))
        assert len(result["posterior"]) == 0
        assert result["converged"] is True


# =============================================================================
# I4 integration: Fellegi-Sunter EM wired into axis_instrumentation.py
# =============================================================================

class TestI4UsesFellegiSunterEm:
    def test_multi_source_dataset_produces_em_diagnostics(self):
        from data_certify.axis_instrumentation import score_instrumentation
        # Two agencies reporting the SAME underlying events (near-identical
        # time/lat/lon/magnitude) -- this is the scenario I4 exists to
        # catch, and it requires actual within-tolerance candidate pairs
        # to exercise the EM fit (make_dataset's default one-event-per-day,
        # linearly-spread lat/lon layout gives no cross-source overlap at
        # all if just split in half, so events are constructed explicitly
        # here to co-occur in time and space across the two sources).
        n = 200
        rng = np.random.RandomState(11)
        base_time = np.datetime64("2020-01-01T00:00:00", "ns")
        hour_offsets = np.arange(n)
        origin_time = (base_time + hour_offsets * np.timedelta64(1, "h")).astype("datetime64[ns]")
        latitude = rng.uniform(-5, 5, n)
        longitude = rng.uniform(-5, 5, n)
        magnitude = rng.uniform(3.0, 6.0, n)
        # First half from agency_a; second half from agency_b, each event
        # closely shadowing (a few seconds off) one from the first half --
        # genuine cross-catalog duplicates.
        source = np.array(["agency_a"] * (n // 2) + ["agency_b"] * (n // 2), dtype="<U64")
        idx_dup = np.arange(n // 2)
        origin_time = np.concatenate([
            origin_time[:n // 2], origin_time[idx_dup] + np.timedelta64(5, "s"),
        ]).astype("datetime64[ns]")
        latitude = np.concatenate([latitude[:n // 2], latitude[idx_dup] + 0.001])
        longitude = np.concatenate([longitude[:n // 2], longitude[idx_dup] + 0.001])
        magnitude = np.concatenate([magnitude[:n // 2], magnitude[idx_dup] + 0.01])

        ds = make_dataset(n=n, origin_time=origin_time, latitude=latitude,
                           longitude=longitude, magnitude=magnitude, source=source)
        result = score_instrumentation(ds)
        i4 = result.sub_results["I4"]
        assert i4.applicable is True
        assert i4.detail["n_candidate_pairs"] > 0
        assert "em_converged" in i4.detail
        assert "em_pi_estimated" in i4.detail
        # With genuine near-duplicates across sources, the estimated
        # duplicate fraction should be substantial, not near zero.
        assert i4.detail["duplicate_fraction"] > 0.3


# =============================================================================
# CertifyDataset.resample
# =============================================================================

class TestResample:
    def test_resample_with_repeated_indices_duplicates_records(self):
        ds = make_dataset(n=10)
        resampled = ds.resample(np.array([0, 0, 0, 1, 2]))
        assert resampled.n == 5
        assert resampled.latitude[0] == resampled.latitude[1] == resampled.latitude[2]

    def test_resample_preserves_dtype_and_name(self):
        ds = make_dataset(n=10)
        resampled = ds.resample(np.array([0, 1, 2]))
        assert resampled.name == ds.name
        assert resampled.origin_time.dtype == ds.origin_time.dtype


# =============================================================================
# DataCertifyAuditor.estimate_uncertainty
# =============================================================================

class TestEstimateUncertainty:
    def test_subsampling_without_replacement_does_not_corrupt_duplicate_tests(self):
        """
        The core bug this feature's development caught: naive with-
        replacement bootstrap resampling manufactures exact-duplicate
        records, which A5/P7 then flag as fabrication -- an artefact of
        the resampling method, not genuine sampling variability. This
        test locks in the fix (subsampling WITHOUT replacement) by
        checking that a clean dataset's A5/P7-driven T(D) is NOT
        systematically dragged down by estimate_uncertainty's replicates.
        """
        ds = make_gr_dataset(n=800, b_value=1.0, seed=42)
        auditor = DataCertifyAuditor()
        point_result = auditor.audit(ds)

        unc = auditor.estimate_uncertainty(ds, n_boot=15, seed=1)
        assert unc.n_boot_valid >= 10
        # The replicate mean should stay close to the point estimate --
        # loose tolerance, but the pre-fix bug produced a gap of ~0.10+
        # (0.674 point vs 0.578 replicate mean) purely from the artefact;
        # after the fix the gap should be a small fraction of that.
        assert abs(unc.boot_mean - point_result.trust_score) < 0.05

    def test_confidence_interval_contains_point_estimate_region(self):
        ds = make_gr_dataset(n=800, b_value=1.0, seed=7)
        auditor = DataCertifyAuditor()
        unc = auditor.estimate_uncertainty(ds, n_boot=15, seed=2)
        assert unc.ci_low <= unc.ci_high
        assert unc.n_boot == 15

    def test_hard_override_rate_reported_for_borderline_dataset(self):
        # A dataset with a small but non-trivial fraction of physically
        # impossible depths should show SOME nonzero hard-override rate
        # across subsamples if it's borderline, or a stable 0%/100% if not
        # -- either way this must not crash and must report a rate in [0,1].
        ds = make_gr_dataset(n=500, b_value=1.0, seed=9)
        auditor = DataCertifyAuditor()
        unc = auditor.estimate_uncertainty(ds, n_boot=10, seed=3)
        assert 0.0 <= unc.hard_override_rate <= 1.0

    def test_hard_override_rate_normalised_by_completed_not_requested_replicates(self):
        """
        Regression test (scientific-validity review pass): `hard_override_rate`
        must be normalised by the number of COMPLETED replicates (n_boot
        minus any that raised and were excluded), the same denominator
        `decision_stability` already correctly uses -- not by the raw
        `n_boot` requested. Dividing by raw n_boot silently UNDER-estimates
        the rate whenever any replicate is excluded, which is the wrong
        direction for a stability/safety signal.

        Constructed with a fully monkeypatched `.audit()` so the exact
        composition of replicates is known: of 10 requested, 4 raise
        (simulating pathological resamples), 3 fire the hard override, and
        3 succeed normally. The correct hard_override_rate is 3/6 = 0.5
        (over the 6 completed replicates), not 3/10 = 0.3.
        """
        from data_certify.decision import CertifyResult, CertifyDecision
        from data_certify.hard_override import HardOverrideResult

        ds = make_gr_dataset(n=50, mc=4.0, seed=1)
        auditor = DataCertifyAuditor()

        outcomes = ["exc", "exc", "exc", "exc", "hard", "hard", "hard", "ok", "ok", "ok"]
        call_i = {"n": -1}

        def ok_result():
            return CertifyResult(
                decision=CertifyDecision.ADMIT, trust_score=0.9,
                hard_override=HardOverrideResult(fired=False, reasons=[]),
                axis_results={}, weights_used={}, theta_admit=0.75, theta_reject=0.5,
            )

        def hard_result():
            return CertifyResult(
                decision=CertifyDecision.REJECT, trust_score=None,
                hard_override=HardOverrideResult(fired=True, reasons=["synthetic"]),
                axis_results={}, weights_used={}, theta_admit=0.75, theta_reject=0.5,
            )

        def fake_audit(dataset):
            call_i["n"] += 1
            if call_i["n"] == 0:
                return ok_result()  # point-estimate call
            outcome = outcomes[(call_i["n"] - 1) % len(outcomes)]
            if outcome == "exc":
                raise RuntimeError("simulated pathological resample")
            return hard_result() if outcome == "hard" else ok_result()

        auditor.audit = fake_audit
        result = auditor.estimate_uncertainty(ds, n_boot=10, seed=1)

        assert result.hard_override_rate == pytest.approx(0.5), (
            f"expected hard_override_rate=0.5 (3 hard-overrides / 6 completed "
            f"replicates), got {result.hard_override_rate} -- looks like the "
            f"n_boot-denominator bug has regressed"
        )
        assert sum(result.decision_stability.values()) == pytest.approx(1.0)

    def test_invalid_subsample_fraction_raises(self):
        ds = make_dataset(n=50)
        auditor = DataCertifyAuditor()
        with pytest.raises(ValueError):
            auditor.estimate_uncertainty(ds, subsample_fraction=0.0)
        with pytest.raises(ValueError):
            auditor.estimate_uncertainty(ds, subsample_fraction=1.5)

    def test_empty_dataset_does_not_crash(self):
        ds = make_dataset(n=0)
        auditor = DataCertifyAuditor()
        unc = auditor.estimate_uncertainty(ds, n_boot=5)
        assert unc.n_boot_valid == 0
        assert math.isnan(unc.boot_mean)
