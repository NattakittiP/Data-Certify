# -*- coding: utf-8 -*-
"""
data_certify/hard_override.py -- Stage-1 non-compensable veto gate.

Implements the hard-override structural constraints from
DATA-CERTIFY_Theoretical_Framework.md Section 5, precisely as corrected in
DATA-CERTIFY_06_Gap_Remediation_and_Robustness_Addendum.md Sections 2 and 7.1:

  1. P1-P3 physical-impossibility violations on a NON-TRIVIAL fraction of
     records -> REJECT, regardless of T(D). "Non-trivial" is operationalised
     via a Clopper-Pearson (1934) exact one-sided binomial test against a
     disclosed provisional tolerance `epsilon_tol`, at a FIXED, pre-registered
     family of exactly m=3 tests (one each for P1, P2, P3), Bonferroni-
     corrected (Dunn 1961) rather than shrinking power via an
     implementer-chosen, unbounded number of regional/temporal sub-tests
     (Gap-Remediation Addendum Section 7.1's central argument: fix the
     family size, not the alpha-per-arbitrary-split).

  2. A6 external cross-validation (when feasible) three-state verdict
     (Group C3, 2026-07-12 -- see `axis_authenticity._score_a6_external()`
     and `_constants.py`'s A6_CONTRADICTED_* block): only a confirmed
     "Externally contradicted" verdict -> REJECT, regardless of T(D). A
     single-source non-match is "Externally unverifiable", NOT grounds for
     REJECT on its own -- reaching "contradicted" requires >=2 independent
     reference sources, none of which matched, confirmed via a statistical
     test on the resulting sub-stratum, not a bare matched_fraction<theta_auth
     comparison.

This module deliberately contains NO compensatory scoring logic -- it is
Stage 1 of the two-stage lexicographic-conjunctive-then-compensatory
decision architecture (Deep-Dive 01, Section 3). If either check fires,
Stage 2 (decision.py's composite T(D)) is not consulted at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from . import stats
from ._constants import ALPHA_CORRECTED, EPSILON_TOL, HARD_OVERRIDE_FAMILY_SIZE, THETA_AUTH
from .axis_plausibility import p1_violation_mask, p2_violation_mask, p3_violation_mask
from .schema import CertifyDataset


@dataclass
class HardOverrideResult:
    fired: bool
    reasons: List[str] = field(default_factory=list)
    p_tests: Dict[str, Dict[str, float]] = field(default_factory=dict)  # {"P1": {"k":.., "n":.., "p_value":..}, ...}
    a6_check: Optional[Dict[str, float]] = None
    quarantined_indices: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "fired": self.fired,
            "reasons": list(self.reasons),
            "p_tests": self.p_tests,
            "a6_check": self.a6_check,
            "n_quarantined": len(self.quarantined_indices),
        }


def _clopper_pearson_p1_p3(dataset: CertifyDataset) -> Dict[str, Dict[str, float]]:
    """
    Run the fixed, m=3 family of Clopper-Pearson tests (one per P1, P2, P3),
    each Bonferroni-corrected to ALPHA_CORRECTED = ALPHA / 3
    (Gap-Remediation Addendum Section 7.1).
    """
    n = dataset.n
    masks = {"P1": p1_violation_mask(dataset),
              "P2": p2_violation_mask(dataset),
              "P3": p3_violation_mask(dataset)}
    out = {}
    for name, mask in masks.items():
        k = int(mask.sum())
        p_value = stats.clopper_pearson_upper_tail(k, n, EPSILON_TOL) if n > 0 else float("nan")
        out[name] = {"k": k, "n": n, "p_value": p_value,
                      "non_trivial": bool(p_value < ALPHA_CORRECTED) if n > 0 else False}
    return out


def check_hard_override(
    dataset: CertifyDataset,
    a6_matched_fraction: Optional[float] = None,
    a6_n_stratum: Optional[int] = None,
    a6_hard_reject: Optional[bool] = None,
    a6_hard_reject_reason: Optional[str] = None,
) -> HardOverrideResult:
    """
    Evaluate both Stage-1 hard-override conditions.

    Args:
        dataset:                The catalog under audit.
        a6_matched_fraction:    A6's matched_fraction on the records it
                                 actually formed a verdict on (reporting only
                                 -- see a6_hard_reject for the actual gate).
        a6_n_stratum:           Number of reference-complete-stratum records
                                 (reporting only).
        a6_hard_reject:         THE authoritative A6 three-state verdict
                                 (Group C3, 2026-07-12): True iff
                                 axis_authenticity.score_authenticity()'s A6
                                 sub-test confirmed "Externally contradicted"
                                 (queried against >=A6_CONTRADICTED_MIN_SOURCES
                                 independent sources, none matched, confirmed
                                 via a Clopper-Pearson lower-tail test -- see
                                 `_score_a6_external()`'s docstring). This
                                 function no longer independently re-derives
                                 a matched_fraction/theta_auth comparison --
                                 score_authenticity() is the SINGLE authoritative
                                 computation, passed straight through here by
                                 decision.py, precisely so the reported
                                 AxisResult.hard_reject flag and the actual
                                 Stage-1 veto can never silently disagree (the
                                 former SYNC NOTE duplication this replaces).
        a6_hard_reject_reason:  Human-readable reason string, if fired.

    Returns:
        HardOverrideResult. If `fired` is True, the caller (decision.py)
        MUST return REJECT without computing/consulting T(D).
    """
    p_tests = _clopper_pearson_p1_p3(dataset)
    reasons: List[str] = []
    fired = False

    non_trivial_tests = [name for name, r in p_tests.items() if r["non_trivial"]]
    if non_trivial_tests:
        fired = True
        for name in non_trivial_tests:
            r = p_tests[name]
            reasons.append(
                f"{name}: {r['k']}/{r['n']} violations is statistically "
                f"non-trivial (Clopper-Pearson p={r['p_value']:.2e} < "
                f"alpha_corrected={ALPHA_CORRECTED:.5f} for epsilon_tol={EPSILON_TOL})."
            )

    # Individual-record violations are quarantined regardless of whether the
    # aggregate fires REJECT (Gap-Remediation Addendum Section 2.2: isolated
    # violations are excluded from downstream use even when not "non-trivial").
    p1_mask = p1_violation_mask(dataset)
    p2_mask = p2_violation_mask(dataset)
    p3_mask = p3_violation_mask(dataset)
    quarantined = sorted(set(np.where(p1_mask | p2_mask | p3_mask)[0].tolist()))

    a6_check = None
    if a6_hard_reject is not None:
        a6_check = {"matched_fraction": a6_matched_fraction, "n_stratum": a6_n_stratum,
                    "theta_auth": THETA_AUTH,
                    "fired": bool(a6_hard_reject)}
        if a6_hard_reject:
            fired = True
            reasons.append(a6_hard_reject_reason or (
                f"A6: 'Externally contradicted' floor triggered "
                f"(matched_fraction={a6_matched_fraction}, n_stratum={a6_n_stratum})."
            ))

    return HardOverrideResult(
        fired=fired, reasons=reasons, p_tests=p_tests, a6_check=a6_check,
        quarantined_indices=quarantined,
    )
