# -*- coding: utf-8 -*-
"""Tests for data_certify/hard_override.py -- Stage-1 non-compensable veto gate."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify._constants import ALPHA_CORRECTED, EPSILON_TOL, THETA_AUTH
from data_certify.hard_override import check_hard_override
from conftest import make_dataset


class TestP1P3NonTrivialFraction:
    def test_isolated_violation_in_large_dataset_does_not_fire(self):
        # Deep-Dive 06 worked example: n=5,000,000, k=3 -> p ~ 1 (isolated error).
        # Use a smaller but still large n for test speed; the key property
        # (single-digit violations in a huge dataset are NOT non-trivial)
        # holds at n=100,000 too.
        n = 100_000
        lat = np.zeros(n)
        lat[0] = 999.0  # one impossible record
        ds = make_dataset(n=n, latitude=lat)
        result = check_hard_override(ds)
        assert result.fired is False
        assert 0 in result.quarantined_indices

    def test_concentrated_violations_in_small_dataset_fires(self):
        # Deep-Dive 06 worked example: n=200, k=5 -> p far below alpha.
        n = 200
        lat = np.zeros(n)
        lat[:5] = 999.0
        ds = make_dataset(n=n, latitude=lat)
        result = check_hard_override(ds)
        assert result.fired is True
        assert any("P1" in r for r in result.reasons)

    def test_no_violations_never_fires(self):
        ds = make_dataset(n=500)
        result = check_hard_override(ds)
        assert result.fired is False
        assert result.quarantined_indices == []

    def test_p_tests_report_all_three_gates(self):
        ds = make_dataset(n=100)
        result = check_hard_override(ds)
        assert set(result.p_tests.keys()) == {"P1", "P2", "P3"}
        for name, r in result.p_tests.items():
            assert r["k"] == 0
            assert r["non_trivial"] is False

    def test_quarantine_includes_p2_and_p3_violations(self):
        n = 50
        depth = np.full(n, 10.0)
        depth[0] = 800.0  # P2 violation
        mag = np.full(n, 4.0)
        mag[1] = 10.0     # P3 violation
        ds = make_dataset(n=n, depth_km=depth, magnitude=mag)
        result = check_hard_override(ds)
        assert 0 in result.quarantined_indices
        assert 1 in result.quarantined_indices


class TestA6Floor:
    """
    Group C3 (2026-07-12): check_hard_override() no longer independently
    derives its A6 verdict from a bare matched_fraction/theta_auth
    comparison -- that three-state "Externally corroborated / unverifiable /
    contradicted" classification now happens ONCE, authoritatively, inside
    axis_authenticity.score_authenticity() -> _score_a6_external() (see
    tests/test_axis_authenticity.py for that logic's own direct tests).
    This function's job is now just to fold the ALREADY-DECIDED
    `a6_hard_reject` verdict into the combined Stage-1 fired flag -- these
    tests check exactly that pass-through contract, not the classification
    logic itself.
    """

    def test_confirmed_contradicted_fires(self):
        ds = make_dataset(n=50)
        result = check_hard_override(
            ds, a6_matched_fraction=0.0, a6_n_stratum=50,
            a6_hard_reject=True, a6_hard_reject_reason="A6: Externally contradicted (test).",
        )
        assert result.fired is True
        assert result.a6_check["fired"] is True
        assert "Externally contradicted" in result.reasons[0] or any(
            "Externally contradicted" in r for r in result.reasons)

    def test_not_contradicted_does_not_fire(self):
        ds = make_dataset(n=50)
        result = check_hard_override(
            ds, a6_matched_fraction=0.8, a6_n_stratum=50,
            a6_hard_reject=False, a6_hard_reject_reason="",
        )
        assert result.fired is False
        assert result.a6_check["fired"] is False

    def test_unverifiable_single_source_non_match_does_not_fire(self):
        # The exact scenario Group C3 exists to fix: a single-source
        # non-match (e.g. matched_fraction=0.2, well below the old binary
        # THETA_AUTH=0.5 floor) must NOT fire on its own any more --
        # score_authenticity() would classify this "Externally unverifiable"
        # and pass a6_hard_reject=False.
        ds = make_dataset(n=50)
        result = check_hard_override(
            ds, a6_matched_fraction=0.2, a6_n_stratum=50,
            a6_hard_reject=False, a6_hard_reject_reason="",
        )
        assert result.fired is False
        assert result.a6_check["fired"] is False

    def test_no_a6_data_skips_check(self):
        ds = make_dataset(n=50)
        result = check_hard_override(ds, a6_matched_fraction=None, a6_n_stratum=None,
                                      a6_hard_reject=None, a6_hard_reject_reason=None)
        assert result.a6_check is None
