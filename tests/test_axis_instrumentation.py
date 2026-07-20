# -*- coding: utf-8 -*-
"""Tests for data_certify/axis_instrumentation.py -- Instrumentation axis I(D)."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.axis_instrumentation import score_instrumentation
from conftest import make_dataset, make_gr_dataset


class TestI1TemporalDrift:
    def test_no_drift_scores_high(self):
        rng = np.random.RandomState(1)
        n = 500
        ds = make_dataset(n=n, magnitude=4.0 + rng.normal(0, 0.1, n))
        result = score_instrumentation(ds)
        i1 = result.sub_results["I1"]
        assert i1.applicable
        assert i1.score > 0.5

    def test_strong_drift_detected(self):
        n = 500
        rng = np.random.RandomState(2)
        drift = np.linspace(0, 2.0, n)  # strong upward drift over the series
        ds = make_dataset(n=n, magnitude=4.0 + drift + rng.normal(0, 0.05, n))
        result = score_instrumentation(ds)
        i1 = result.sub_results["I1"]
        assert i1.applicable
        assert i1.detail["trend_detected"] is True

    def test_too_few_records_not_applicable(self):
        ds = make_dataset(n=5)
        result = score_instrumentation(ds)
        assert result.sub_results["I1"].applicable is False


class TestI2Clipping:
    def test_genuine_gr_tail_scores_reasonably(self):
        ds = make_gr_dataset(n=3000, mc=3.0, seed=3)
        result = score_instrumentation(ds)
        i2 = result.sub_results["I2"]
        if i2.applicable:
            assert 0.0 <= i2.score <= 1.0

    def test_clipped_tail_scores_lower(self):
        rng = np.random.RandomState(4)
        n = 3000
        mc = 3.0
        mags = mc + rng.exponential(1.0, n)
        # Simulate large-event saturation/clipping by silently DROPPING
        # (not clamping -- clamping would pile events at the cutoff and
        # artificially inflate the tail count) 90% of events above the
        # 90th percentile, mimicking under-detection of the largest events.
        cutoff = np.percentile(mags, 90)
        above = mags > cutoff
        keep_mask = np.ones(n, dtype=bool)
        above_idx = np.where(above)[0]
        drop_idx = rng.choice(above_idx, size=int(len(above_idx) * 0.9), replace=False)
        keep_mask[drop_idx] = False
        mags_clipped = mags[keep_mask]
        ds_normal = make_dataset(n=n, magnitude=mags)
        ds_clipped = make_dataset(n=len(mags_clipped), magnitude=mags_clipped)
        r_normal = score_instrumentation(ds_normal)
        r_clipped = score_instrumentation(ds_clipped)
        if r_normal.sub_results["I2"].applicable and r_clipped.sub_results["I2"].applicable:
            assert r_clipped.sub_results["I2"].score <= r_normal.sub_results["I2"].score + 1e-6


class TestI3RevisionFlag:
    def test_all_flagged_scores_perfectly(self):
        ds = make_dataset(n=10, revision_status=np.array(["final"] * 10, dtype="<U16"))
        result = score_instrumentation(ds)
        assert result.sub_results["I3"].score == pytest.approx(1.0)

    def test_none_flagged_scores_zero(self):
        ds = make_dataset(n=10)
        result = score_instrumentation(ds)
        assert result.sub_results["I3"].score == pytest.approx(0.0)


class TestI4CrossCatalogDedup:
    def test_single_source_not_applicable(self):
        ds = make_dataset(n=20)
        result = score_instrumentation(ds)
        assert result.sub_results["I4"].applicable is False

    def test_multi_source_with_duplicates_flags_them(self):
        n = 20
        ds = make_dataset(n=n)
        source = np.array(["USGS"] * 10 + ["EMSC"] * 10, dtype="<U64")
        ds.source[:] = source
        # Make record 10 (EMSC) a near-duplicate of record 0 (USGS).
        ds.origin_time[10] = ds.origin_time[0] + np.timedelta64(5, "s")
        ds.latitude[10] = ds.latitude[0] + 0.01
        ds.longitude[10] = ds.longitude[0] + 0.01
        ds.magnitude[10] = ds.magnitude[0] + 0.05
        result = score_instrumentation(ds)
        i4 = result.sub_results["I4"]
        assert i4.applicable
        assert i4.detail["duplicate_fraction"] > 0.0


class TestI5TemporalDistributionDrift:
    def test_stable_distribution_scores_high(self):
        rng = np.random.RandomState(5)
        n = 200
        ds = make_dataset(n=n, magnitude=4.0 + rng.normal(0, 0.3, n))
        result = score_instrumentation(ds)
        i5 = result.sub_results["I5"]
        assert i5.applicable
        assert i5.score > 0.5

    def test_step_change_detected(self):
        n = 200
        rng = np.random.RandomState(6)
        early = rng.normal(4.0, 0.2, n // 2)
        late = rng.normal(6.0, 0.2, n // 2)
        mags = np.concatenate([early, late])
        ds = make_dataset(n=n, magnitude=mags)
        result = score_instrumentation(ds)
        i5 = result.sub_results["I5"]
        assert i5.applicable
        assert i5.detail["ks_statistic"] > 0.5


class TestComposite:
    def test_score_bounded(self):
        ds = make_gr_dataset(n=1000, seed=7)
        result = score_instrumentation(ds)
        assert 0.0 <= result.score <= 1.0
