# -*- coding: utf-8 -*-
"""
Cross-module edge-case and boundary-condition tests for the DATA-CERTIFY
pipeline: empty datasets, singleton datasets, all-missing fields, exact
boundary values, and malformed CSV inputs. These exercise interactions
between schema.py, the axis modules, hard_override.py, and decision.py
that single-module test files don't reach.
"""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify._constants import DEPTH_MAX_KM, MAGNITUDE_MAX
from data_certify.decision import CertifyDecision, DataCertifyAuditor
from data_certify.schema import ALL_FIELDS, load_dataset_csv, save_dataset_csv
from conftest import make_dataset, make_gr_dataset


class TestEmptyDataset:
    """Regression tests for the n=0 vacuous-ADMIT bug found while writing
    this file: A5 ('fewer than 2 records -> no duplicates possible') was
    vacuously applicable=True/score=1.0 even for n=0, which alone was
    enough to drive T(D) to 1.0 and ADMIT a catalog with zero records.
    decision.py now special-cases n=0 to REJECT before any axis scoring."""

    def test_in_memory_empty_dataset_rejects(self):
        ds = make_dataset(n=0)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.decision == CertifyDecision.REJECT
        assert math.isnan(result.trust_score)
        assert result.axis_results == {}

    def test_subset_to_empty_via_mask_rejects(self):
        ds = make_dataset(n=20)
        empty = ds.subset(np.zeros(20, dtype=bool))
        assert empty.n == 0
        auditor = DataCertifyAuditor()
        result = auditor.audit(empty)
        assert result.decision == CertifyDecision.REJECT

    def test_empty_dataset_does_not_crash_str_or_to_dict(self):
        ds = make_dataset(n=0)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        s = str(result)
        assert "REJECT" in s
        d = result.to_dict()
        assert d["n_records"] == 0

    def test_load_zero_row_csv_raises(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text(",".join(ALL_FIELDS) + "\n")
        with pytest.raises(ValueError):
            load_dataset_csv(path)


class TestSingletonDataset:
    def test_single_record_does_not_crash_full_pipeline(self):
        ds = make_dataset(n=1)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )

    def test_single_record_all_axes_nan_or_trivial(self):
        ds = make_dataset(n=1)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        for axis in result.axis_results.values():
            assert math.isnan(axis.score) or (0.0 <= axis.score <= 1.0)


class TestAllMissingRequiredField:
    def test_all_nan_magnitude_does_not_crash(self):
        n = 50
        ds = make_dataset(n=n, magnitude=np.full(n, np.nan))
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)  # must not raise
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )

    def test_all_nat_origin_time_does_not_crash(self):
        n = 30
        ds = make_dataset(n=n, origin_time=np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]"))
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )

    def test_all_nan_coordinates_does_not_crash(self):
        n = 30
        ds = make_dataset(n=n, latitude=np.full(n, np.nan), longitude=np.full(n, np.nan))
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )


class TestZeroVarianceDataset:
    def test_identical_records_do_not_crash(self):
        n = 100
        ds = make_dataset(
            n=n,
            latitude=np.zeros(n), longitude=np.zeros(n),
            depth_km=np.full(n, 10.0), magnitude=np.full(n, 4.0),
        )
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)  # must not raise (div-by-zero, etc.)
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )


class TestExactBoundaryValues:
    """P1-P3 hard gates use strict-inequality violation tests; values
    exactly AT the documented bound must NOT be flagged as violations
    (see test_axis_plausibility.py's Vanuatu/Tonga 735.8 km regression,
    which exercises the same DEPTH_MAX_KM=750 boundary from the other
    side). Here we check the exact-equality edge for depth and magnitude."""

    def test_depth_exactly_at_max_not_a_violation(self):
        from data_certify.axis_plausibility import p2_violation_mask
        ds = make_dataset(n=1, depth_km=np.array([DEPTH_MAX_KM]))
        assert not p2_violation_mask(ds).any()

    def test_magnitude_exactly_at_max_not_a_violation(self):
        from data_certify.axis_plausibility import p3_violation_mask
        ds = make_dataset(n=1, magnitude=np.array([MAGNITUDE_MAX]))
        assert not p3_violation_mask(ds).any()

    def test_latitude_exactly_at_poles_not_a_violation(self):
        from data_certify.axis_plausibility import p1_violation_mask
        ds = make_dataset(n=2, latitude=np.array([90.0, -90.0]), longitude=np.array([180.0, -180.0]))
        assert not p1_violation_mask(ds).any()


class TestCsvRoundTrip:
    def test_save_then_load_preserves_record_count_and_values(self, tmp_path):
        ds = make_gr_dataset(n=200, seed=11)
        path = tmp_path / "roundtrip.csv"
        save_dataset_csv(ds, path)
        loaded = load_dataset_csv(path, name="roundtrip")
        assert loaded.n == ds.n
        np.testing.assert_allclose(loaded.magnitude, ds.magnitude, rtol=1e-6)
        np.testing.assert_allclose(loaded.latitude, ds.latitude, rtol=1e-6)

    def test_load_missing_required_column_raises(self, tmp_path):
        path = tmp_path / "bad.csv"
        # Missing 'magnitude' entirely.
        path.write_text("origin_time,latitude,longitude,depth_km\n2020-01-01T00:00:00,0,0,10\n")
        with pytest.raises(ValueError):
            load_dataset_csv(path)

    def test_load_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_dataset_csv(tmp_path / "does_not_exist.csv")

    def test_roundtrip_preserves_full_hard_reject_pathway(self, tmp_path):
        n = 200
        lat = np.zeros(n)
        lat[:10] = 999.0
        ds = make_dataset(n=n, latitude=lat)
        path = tmp_path / "bad_dataset.csv"
        save_dataset_csv(ds, path)
        loaded = load_dataset_csv(path, name="bad_dataset")
        auditor = DataCertifyAuditor()
        result = auditor.audit(loaded)
        assert result.decision == CertifyDecision.REJECT
        assert result.hard_override.fired is True


class TestLargeNPerformance:
    def test_full_pipeline_completes_quickly_on_large_dataset(self):
        # Regression guard for the O(N^2) Mann-Kendall/Sen's-slope bug fixed
        # earlier via MAX_TREND_N subsampling -- the full audit pipeline on a
        # dataset well above that cap must still complete promptly.
        import time
        ds = make_gr_dataset(n=25_000, seed=99)
        auditor = DataCertifyAuditor()
        start = time.time()
        result = auditor.audit(ds)
        elapsed = time.time() - start
        assert elapsed < 30.0
        assert result.decision in (
            CertifyDecision.ADMIT, CertifyDecision.CONDITIONAL, CertifyDecision.REJECT,
        )
