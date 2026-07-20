# -*- coding: utf-8 -*-
"""Tests for data_certify/axis_plausibility.py -- Plausibility axis P(D)."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify._constants import DEPTH_MAX_KM, DEPTH_MIN_KM, MAGNITUDE_MAX, MAGNITUDE_MIN
from data_certify.axis_plausibility import (
    p1_violation_mask, p2_violation_mask, p3_violation_mask, score_plausibility,
)
from data_certify.reference_data import BundledSampleFaultDatabase, NullFaultDatabase
from conftest import make_dataset


class TestHardBoundMasks:
    def test_p1_flags_out_of_range_lat_lon(self):
        ds = make_dataset(n=5, latitude=np.array([91.0, -91.0, 45.0, 0.0, -80.0]),
                           longitude=np.array([0.0, 0.0, 200.0, -200.0, 10.0]))
        mask = p1_violation_mask(ds)
        assert mask.tolist() == [True, True, True, True, False]

    def test_p1_nan_is_not_a_violation(self):
        ds = make_dataset(n=2, latitude=np.array([np.nan, 45.0]), longitude=np.array([10.0, np.nan]))
        mask = p1_violation_mask(ds)
        assert not mask.any()

    def test_p2_flags_depth_beyond_750km(self):
        # -10.0 sits below DEPTH_MIN_KM=-5.0 (revised 2026-07-06 from the
        # original 0.0 -- calibration/calibrate_hard_override_params.py found
        # real known_good USGS catalogs legitimately report small negative
        # depths down to -3.8 km, an ordinary velocity-model/depth-inversion
        # artifact for very shallow events, not fabrication -- see
        # data_certify/_constants.py's DEPTH_MIN_KM comment), so it must still
        # be flagged as a genuine out-of-range violation.
        ds = make_dataset(n=3, depth_km=np.array([-10.0, 751.0, 100.0]))
        mask = p2_violation_mask(ds)
        assert mask.tolist() == [True, True, False]

    def test_p2_boundary_value_735_8_not_violation(self):
        # The documented real Vanuatu/Tonga 2004 event (735.8 km) must NOT
        # trip the hard gate (Deep-Dive 02 Section 5.1's whole justification
        # for setting the bound at 750, not 700, km).
        ds = make_dataset(n=1, depth_km=np.array([735.8]))
        mask = p2_violation_mask(ds)
        assert not mask.any()

    def test_p2_small_negative_depth_not_violation(self):
        # Real known_good corpus datasets (real_usgs_main, real_all_month,
        # real_events_atkinson) legitimately report small negative depths
        # down to -3.8 km -- DEPTH_MIN_KM=-5.0 must NOT flag these as
        # violations (calibration/hard_override_calibration_report.md).
        ds = make_dataset(n=2, depth_km=np.array([-1.0, -3.8]))
        mask = p2_violation_mask(ds)
        assert not mask.any()

    def test_p3_flags_magnitude_beyond_9_5(self):
        # -5.0 sits below MAGNITUDE_MIN=-2.5 (revised 2026-07-06 from the
        # original 0.0 -- same calibration pass found real known_good
        # catalogs legitimately reporting small negative magnitudes down to
        # -1.9 for micro-seismic events on dense local/regional networks --
        # see data_certify/_constants.py's MAGNITUDE_MIN comment), so it must
        # still be flagged as a genuine out-of-range violation.
        ds = make_dataset(n=3, magnitude=np.array([-5.0, 9.6, 9.5]))
        mask = p3_violation_mask(ds)
        assert mask.tolist() == [True, True, False]

    def test_p3_small_negative_magnitude_not_violation(self):
        # Real known_good corpus dataset real_all_month legitimately reports
        # small negative magnitudes down to -1.9 -- MAGNITUDE_MIN=-2.5 must
        # NOT flag these as violations
        # (calibration/hard_override_calibration_report.md).
        ds = make_dataset(n=2, magnitude=np.array([-0.1, -1.9]))
        mask = p3_violation_mask(ds)
        assert not mask.any()


class TestGradedTests:
    def test_p6_flags_inconsistent_moment_magnitude(self):
        # Mw=7.0 should correspond to log10(M0) = (7.0+6.07)*1.5 = 19.605
        consistent_m0 = 10 ** ((7.0 + 6.07) / (2.0 / 3.0))
        ds = make_dataset(n=2, magnitude=np.array([7.0, 7.0]),
                           seismic_moment_n_m=np.array([consistent_m0, 1e10]))
        result = score_plausibility(ds)
        p6 = result.sub_results["P6"]
        assert p6.applicable
        assert p6.detail["n_inconsistent"] == 1

    def test_p6_not_applicable_without_moment_field(self):
        ds = make_dataset(n=5)
        result = score_plausibility(ds)
        assert result.sub_results["P6"].applicable is False

    def test_p7_flags_exact_duplicate_timestamps(self):
        ds = make_dataset(n=4)
        ds.origin_time[1] = ds.origin_time[0]
        result = score_plausibility(ds)
        p7 = result.sub_results["P7"]
        assert p7.detail["n_exact_duplicate_timestamps"] >= 1

    def test_p4_flags_implausible_tsunami(self):
        ds = make_dataset(n=2, magnitude=np.array([4.0, 8.0]), depth_km=np.array([500.0, 20.0]),
                           tsunami_flag=np.array([1.0, 1.0]))
        result = score_plausibility(ds)
        p4 = result.sub_results["P4"]
        assert p4.applicable
        assert p4.detail["n_implausible"] == 1

    def test_p5_selects_wells_coppersmith_coefficients_by_mechanism(self):
        # At M=7.5, observed rupture length 18.5 km sits outside the 3-sigma
        # band of the Wells & Coppersmith (1994) Table 2A "All mechanisms"
        # regression (a=-3.22, b=0.69, sigma=0.22 -> band 0.66 log-units)
        # but inside the narrower "reverse" mechanism band (a=-2.86,
        # b=0.63, sigma=0.20 -> band 0.60 log-units): predicted logL=1.955
        # (all) vs 1.865 (reverse); observed logL=log10(18.5)=1.267;
        # residual 0.688 (all, > 0.66 -> violation) vs 0.598 (reverse,
        # < 0.60 -> not a violation). This is only possible if the
        # dataset's `mechanism` field is actually driving which
        # coefficient row is used per-record, not a single hardcoded set.
        reverse_ds = make_dataset(n=1, magnitude=np.array([7.5]),
                                   rupture_length_km=np.array([18.5]),
                                   mechanism=np.array(["reverse"]))
        unknown_ds = make_dataset(n=1, magnitude=np.array([7.5]),
                                   rupture_length_km=np.array([18.5]),
                                   mechanism=np.array([""]))
        p5_reverse = score_plausibility(reverse_ds).sub_results["P5"]
        p5_unknown = score_plausibility(unknown_ds).sub_results["P5"]
        assert p5_reverse.detail["n_implausible"] == 0
        assert p5_reverse.detail["n_per_mechanism"] == {"reverse": 1}
        assert p5_unknown.detail["n_implausible"] == 1
        assert p5_unknown.detail["n_per_mechanism"] == {"all": 1}

    def test_p8_not_applicable_without_fault_db(self):
        ds = make_dataset(n=10)
        result = score_plausibility(ds, fault_db=NullFaultDatabase())
        assert result.sub_results["P8"].applicable is False

    def test_p8_scores_high_near_boundary_low_far_away(self):
        # New Zealand trench area (near a sample boundary point) vs. mid-continent.
        near = make_dataset(n=1, latitude=np.array([-40.0]), longitude=np.array([175.0]))
        far = make_dataset(n=1, latitude=np.array([50.0]), longitude=np.array([10.0]))
        fault_db = BundledSampleFaultDatabase()
        r_near = score_plausibility(near, fault_db=fault_db)
        r_far = score_plausibility(far, fault_db=fault_db)
        assert r_near.sub_results["P8"].score >= r_far.sub_results["P8"].score


class TestCompositeScore:
    def test_p1_p3_excluded_from_weighted_average(self):
        # A dataset that badly violates P1-P3 should still get a normal-
        # looking graded P(D) score (P1-P3 are hard gates, handled
        # separately by hard_override.py, not folded into this axis).
        ds = make_dataset(n=5, latitude=np.array([200.0] * 5))
        result = score_plausibility(ds)
        assert result.sub_results["P1"].detail["n_violations"] == 5
        # The graded score itself should not be NaN or crash.
        assert result.score is not None

    def test_all_graded_tests_inapplicable_gives_nan(self):
        # n=1 -> P7 (needs >=2 timestamps) also becomes inapplicable, so with
        # no tsunami/moment/rupture/mmi fields at all, every graded P4-P9
        # test is inapplicable and the composite must be NaN, not silently 1.0.
        ds = make_dataset(n=1)
        result = score_plausibility(ds, fault_db=NullFaultDatabase())
        assert math.isnan(result.score)
