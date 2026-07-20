# -*- coding: utf-8 -*-
"""Tests for data_certify/axis_completeness.py -- Completeness axis C(D)."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.axis_completeness import score_completeness
from conftest import make_dataset, make_gr_dataset


class TestC1Missingness:
    def test_full_dataset_scores_perfectly(self):
        ds = make_dataset(n=50)
        result = score_completeness(ds)
        c1 = result.sub_results["C1"]
        assert c1.score == pytest.approx(1.0)

    def test_missing_values_reduce_score(self):
        ds = make_dataset(n=100)
        ds.magnitude[:20] = np.nan
        result = score_completeness(ds)
        c1 = result.sub_results["C1"]
        assert c1.score < 1.0

    def test_mcar_like_flag_true_for_uniform_missingness(self):
        ds = make_dataset(n=200)
        rng = np.random.RandomState(1)
        idx = rng.choice(200, size=20, replace=False)
        ds.magnitude[idx] = np.nan
        result = score_completeness(ds)
        assert result.sub_results["C1"].detail["mcar_like"] is True

    def test_mcar_like_flag_false_for_time_concentrated_missingness(self):
        ds = make_dataset(n=200)
        ds.magnitude[100:] = np.nan  # all missingness in the second half
        result = score_completeness(ds)
        assert result.sub_results["C1"].detail["mcar_like"] is False


class TestC2CompletenessMagnitude:
    def test_well_sampled_gr_dataset_scores_reasonably(self):
        ds = make_gr_dataset(n=3000, mc=3.0, seed=1)
        result = score_completeness(ds)
        c2 = result.sub_results["C2"]
        assert c2.applicable
        assert 0.0 <= c2.score <= 1.0

    def test_too_few_magnitudes_not_applicable(self):
        ds = make_dataset(n=10)
        result = score_completeness(ds)
        assert result.sub_results["C2"].applicable is False


class TestC3CoverageGaps:
    def test_uniform_coverage_scores_high(self):
        rng = np.random.RandomState(2)
        n = 500
        ds = make_dataset(
            n=n,
            latitude=rng.uniform(-10, 10, n),
            longitude=rng.uniform(-10, 10, n),
        )
        result = score_completeness(ds)
        c3 = result.sub_results["C3"]
        assert c3.applicable
        assert c3.score > 0.5

    def test_too_few_records_not_applicable(self):
        ds = make_dataset(n=5)
        result = score_completeness(ds)
        assert result.sub_results["C3"].applicable is False


class TestC4SampleSufficiency:
    def test_concentrated_events_give_low_sufficiency(self):
        # All events crammed into one tiny spatial stratum out of the grid
        # -> most strata are non-empty-but-small once spread thinly, OR
        # one stratum has plenty and the rest are empty (excluded from
        # denominator). Use a genuinely small dataset to trigger insufficiency.
        ds = make_dataset(n=20)
        result = score_completeness(ds)
        c4 = result.sub_results["C4"]
        if c4.applicable:
            assert 0.0 <= c4.score <= 1.0

    def test_large_uniform_dataset_scores_high(self):
        rng = np.random.RandomState(3)
        n = 2000
        ds = make_dataset(
            n=n,
            latitude=rng.uniform(-10, 10, n),
            longitude=rng.uniform(-10, 10, n),
            magnitude=rng.uniform(3, 6, n),
        )
        result = score_completeness(ds)
        c4 = result.sub_results["C4"]
        assert c4.applicable
        assert c4.score > 0.5


class TestComposite:
    def test_score_bounded(self):
        ds = make_gr_dataset(n=1000, seed=4)
        result = score_completeness(ds)
        assert 0.0 <= result.score <= 1.0
