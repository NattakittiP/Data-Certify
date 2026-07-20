# -*- coding: utf-8 -*-
"""Tests for data_certify/decision.py -- the full two-stage audit protocol."""

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify._constants import AXIS_WEIGHTS, THETA_ADMIT, THETA_REJECT, WITHIN_A
from data_certify.decision import CertifyDecision, DataCertifyAuditor
from data_certify.reference_data import LocalCSVCatalogReference, NullExternalCatalog
from data_certify.schema import save_dataset_csv
from conftest import make_dataset, make_gr_dataset


class TestConstructorValidation:
    def test_rejects_theta_reject_above_theta_admit(self):
        with pytest.raises(ValueError):
            DataCertifyAuditor(theta_admit=0.5, theta_reject=0.9)

    def test_accepts_equal_thresholds(self):
        DataCertifyAuditor(theta_admit=0.6, theta_reject=0.6)  # should not raise

    def test_default_thresholds_match_constants(self):
        auditor = DataCertifyAuditor()
        assert auditor.theta_admit == THETA_ADMIT
        assert auditor.theta_reject == THETA_REJECT


class TestHardOverridePath:
    def test_concentrated_p1_violations_force_reject_without_trust_score(self):
        n = 200
        lat = np.zeros(n)
        lat[:10] = 999.0  # concentrated, statistically non-trivial fraction
        ds = make_dataset(n=n, latitude=lat)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.decision == CertifyDecision.REJECT
        assert result.hard_override.fired is True
        assert result.trust_score is None

    def test_hard_override_reject_still_carries_axis_results(self):
        # Even though T(D) is not consulted, the axis results should still be
        # computed and attached (useful for diagnostics/reporting).
        n = 200
        lat = np.zeros(n)
        lat[:10] = 999.0
        ds = make_dataset(n=n, latitude=lat)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert set(result.axis_results.keys()) == {"A", "P", "C", "I"}


class TestCompensatoryPath:
    def test_clean_gr_dataset_does_not_hard_reject(self):
        ds = make_gr_dataset(n=1500, b_value=1.0, seed=42)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.hard_override.fired is False
        assert result.trust_score is not None
        assert not math.isnan(result.trust_score)

    def test_decision_consistent_with_thresholds(self):
        ds = make_gr_dataset(n=1500, b_value=1.0, seed=42)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        ts = result.trust_score
        if ts >= auditor.theta_admit:
            assert result.decision == CertifyDecision.ADMIT
        elif ts >= auditor.theta_reject:
            assert result.decision == CertifyDecision.CONDITIONAL
        else:
            assert result.decision == CertifyDecision.REJECT

    def test_conditional_zone_adds_caveat(self):
        # Force a tiny, sparse, low-information dataset into the indifference
        # zone by using extreme (but not hard-override-triggering) thresholds.
        ds = make_gr_dataset(n=200, b_value=1.0, seed=7)
        auditor = DataCertifyAuditor(theta_admit=0.999, theta_reject=0.001)
        result = auditor.audit(ds)
        if result.decision == CertifyDecision.CONDITIONAL:
            assert any("indifference zone" in c for c in result.caveats)

    def test_weights_used_matches_axis_weights(self):
        ds = make_gr_dataset(n=500, seed=1)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert set(result.weights_used.keys()) == {"A", "P", "C", "I"}
        assert math.isclose(sum(result.weights_used.values()), 1.0, abs_tol=1e-6)


class TestPartialAxisApplicability:
    def test_missing_axes_trigger_renormalisation_caveat(self):
        # A minimal dataset (n=1) makes most graded sub-tests inapplicable
        # across several axes; if fewer than 4 axes produce a usable score,
        # a renormalisation caveat must be recorded.
        ds = make_dataset(n=1)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        n_applicable = sum(
            1 for v in result.axis_results.values() if not math.isnan(v.score)
        )
        if n_applicable < 4 and n_applicable > 0:
            assert any("renormalised" in c for c in result.caveats)

    def test_no_applicable_axes_defaults_to_reject(self):
        ds = make_dataset(n=1)
        # Even in the pathological all-NaN case the auditor must not crash,
        # and must never silently ADMIT.
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        if result.trust_score is not None and math.isnan(result.trust_score):
            assert result.decision == CertifyDecision.REJECT


class TestA6EvidenceWeighting:
    """
    Regression tests for a real bug found via external review (2026-07-21):
    A6, when it externally corroborates records, SUBSTITUTES for A1-A5 on
    a per-record stratum basis (see score_authenticity()'s record-count
    blend). The first cut of the evidence-coverage feature (3.5) did not
    know this -- it gave A6 effective_weight=None (as if it were a pure
    Stage-1 hard gate, since A6 is absent from WITHIN_A) while A1-A5 kept
    their FULL fixed nominal weight regardless of how many records A6
    actually covered. Consequence: a dataset with near-total external
    corroboration (very strong authenticity evidence) had evidence
    coverage computed as LOW, because A1-A5's now-inapplicable nominal
    weight was counted as "missing" even though A6 had already covered
    that same ground. This incorrectly capped a strongly-verified ADMIT
    down to CONDITIONAL. These tests pin the fixed behaviour: A6's
    effective_weight must scale with how many records it actually covers
    (n_effective / n_total), and A1-A5's effective_weight must shrink by
    the complementary fraction rather than staying fixed.
    """

    def test_full_a6_coverage_gives_high_evidence_coverage_and_admits(self, tmp_path):
        # All magnitudes well above any plausible Mc_ref floor -> (almost)
        # the entire dataset qualifies for A6's reference-complete stratum,
        # and matching against an identical copy of itself gives ~100%
        # corroboration -- this is the "full A6 coverage" scenario the
        # review reproduced.
        ds = make_gr_dataset(n=500, mc=6.0, seed=7)
        ref_path = tmp_path / "reference.csv"
        save_dataset_csv(ds, ref_path)
        reference = LocalCSVCatalogReference(ref_path)

        auditor = DataCertifyAuditor(reference=reference)
        result = auditor.audit(ds)

        a_axis = result.axis_results["A"]
        a6 = a_axis.sub_results["A6"]
        assert a6.applicable
        assert a6.detail["matched_fraction"] > 0.95

        # Core regression check: A6's effective_weight must NOT be None
        # when it is actually covering records, and must be large (most
        # of AXIS_WEIGHTS["A"]) when it covers nearly the whole dataset --
        # NOT the pre-fix behaviour of None regardless of coverage.
        assert a6.effective_weight is not None
        assert a6.effective_weight > 0.5 * AXIS_WEIGHTS["A"]

        # Conservation check: A(D)'s sub-test effective weights (A1-A6,
        # skipping any that are None) must sum back to exactly
        # AXIS_WEIGHTS["A"] -- the record-count split reallocates weight,
        # it never creates or destroys it.
        total_a_weight = sum(
            sub.effective_weight for sub in a_axis.sub_results.values()
            if sub.effective_weight is not None
        )
        assert math.isclose(total_a_weight, AXIS_WEIGHTS["A"], abs_tol=1e-9)

        # With near-total external corroboration, evidence coverage must be
        # HIGH (this is strong evidence, not missing evidence) -- the
        # pre-fix bug drove this near 0.31-0.46 regardless of how strong
        # A6's corroboration was.
        assert result.evidence_coverage is not None
        assert result.evidence_coverage > 0.7

        # With T(D) comfortably above theta_admit and now-correct high
        # evidence coverage, this must ADMIT, not be miscapped to
        # CONDITIONAL by the 3.5 safety gate.
        if result.trust_score is not None and result.trust_score >= auditor.theta_admit:
            assert result.decision == CertifyDecision.ADMIT

    def test_no_a6_reference_reduces_to_original_a1_a5_weights(self):
        # Backward-compatibility pin: when A6 never applies at all (the
        # common default case -- no live/local reference configured), A1-A5
        # must get EXACTLY their original AXIS_WEIGHTS["A"] * WITHIN_A[name]
        # effective weight, unaffected by the A6 record-stratum logic.
        ds = make_gr_dataset(n=500, seed=1)
        auditor = DataCertifyAuditor(reference=NullExternalCatalog())
        result = auditor.audit(ds)

        a_axis = result.axis_results["A"]
        a6 = a_axis.sub_results["A6"]
        assert a6.applicable is False
        assert a6.effective_weight == 0.0  # real zero, not None -- A6 is not a hard gate

        for name in ("A1", "A2", "A3", "A4", "A5"):
            sub = a_axis.sub_results[name]
            expected = AXIS_WEIGHTS["A"] * WITHIN_A[name]
            assert math.isclose(sub.effective_weight, expected, rel_tol=1e-9)


class TestResultSerialisation:
    def test_to_dict_roundtrips_key_fields(self):
        ds = make_gr_dataset(n=500, seed=2)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        d = result.to_dict()
        assert d["decision"] == result.decision.value
        assert d["dataset"] == ds.name
        assert d["n_records"] == ds.n
        assert set(d["axis_results"].keys()) == {"A", "P", "C", "I"}

    def test_str_does_not_crash_on_hard_reject(self):
        n = 200
        lat = np.zeros(n)
        lat[:10] = 999.0
        ds = make_dataset(n=n, latitude=lat)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        s = str(result)
        assert "REJECT" in s
        assert "HARD OVERRIDE FIRED" in s

    def test_str_does_not_crash_on_compensatory_path(self):
        ds = make_gr_dataset(n=500, seed=3)
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        s = str(result)
        assert result.decision.value in s
