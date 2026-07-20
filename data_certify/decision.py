# -*- coding: utf-8 -*-
"""
data_certify/decision.py -- The DATA-CERTIFY audit protocol: composite
trust score T(D) and the three-way ADMIT / CONDITIONAL / REJECT decision.

Implements DATA-CERTIFY_Theoretical_Framework.md Section 5, and the
lexicographic-conjunctive-then-compensatory two-stage architecture argued
in DATA-CERTIFY_01_Epistemic_and_Decision_Theory_Foundations.md Section 3
and proven non-compensable in
DATA-CERTIFY_05_Composite_Score_and_Hard_Override_Proofs.md Section 1:

    Stage 1 (hard_override.py):  P1-P3 non-trivial-fraction veto, A6 floor veto.
                                  If EITHER fires -> REJECT. T(D) is not consulted.

    Stage 2 (this module):       T(D) = w_A.A(D) + w_P.P(D) + w_C.C(D) + w_I.I(D)
                                  ADMIT       if T(D) >= theta_admit
                                  CONDITIONAL if theta_reject <= T(D) < theta_admit
                                  REJECT      if T(D) < theta_reject
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np

from ._constants import (
    AXIS_WEIGHTS, MIN_RELIABLE_N, THETA_ADMIT, THETA_REJECT,
    WITHIN_A, WITHIN_C, WITHIN_I, WITHIN_P,
)
from .axis_authenticity import score_authenticity
from .axis_completeness import score_completeness
from .axis_instrumentation import score_instrumentation
from .axis_plausibility import score_plausibility
from .hard_override import HardOverrideResult, check_hard_override
from .reference_data import ExternalCatalogReference, FaultDatabaseReference
from .results import AxisResult
from .schema import CertifyDataset

# Per-axis within-axis weight tables, keyed the same way as AXIS_WEIGHTS, used
# by `_assign_effective_weights` below to compute each sub-test's NOMINAL
# effective_weight = AXIS_WEIGHTS[axis] * WITHIN_<axis>[sub_test_name].
# Sub-tests not present in the relevant WITHIN_* table (P1-P3, the Stage-1
# hard-gate tests) are Stage-1, non-compensable checks -- they are
# deliberately left with effective_weight=None rather than 0.0, since 0.0
# would misleadingly suggest "counts for nothing" rather than "operates
# outside the weighted sum entirely, as an unconditional veto" (review
# point 3.4, "effective weight concentration"). A6 is deliberately NOT in
# this simple per-axis table -- see `_assign_effective_weights_axis_a`
# below for why it needs its own, record-count-proportional treatment.
_WITHIN_BY_AXIS: Dict[str, Dict[str, float]] = {
    "A": WITHIN_A, "P": WITHIN_P, "C": WITHIN_C, "I": WITHIN_I,
}


def _assign_effective_weights_axis_a(
    axis_result: AxisResult, axis_weight: float, n_records: int,
) -> None:
    """
    Assigns `effective_weight` across A(D)'s sub-tests (A1-A6).

    BUGFIX (2026-07-21, found by external review): A(D) is NOT a simple
    fixed-share blend of A1-A6 the way P/C/I are blends of their own
    sub-tests. A6, when it applies, SUBSTITUTES for A1-A5 on a PER-RECORD
    stratum basis -- `score_authenticity()` in axis_authenticity.py
    computes A(D) as a record-count-weighted blend:

        A(D) = (n_a6_stratum * A6_score + n_intrinsic * intrinsic_score)
               / (n_a6_stratum + n_intrinsic)

    (or A(D) = A6_score alone when A6 covers the entire dataset, i.e.
    n_intrinsic == 0). The first version of `_assign_effective_weights`
    did not know this: it treated A6 like a pure Stage-1 hard gate
    (effective_weight=None, since A6 is absent from WITHIN_A -- WITHIN_A
    only ever covered A1-A5), while A1-A5 kept their FULL fixed nominal
    weight (axis_weight * WITHIN_A[name]) regardless of how many records
    A6 actually covered. The practical consequence, confirmed with a
    reproduction (500-record synthetic catalog, A6 externally corroborates
    486/500 records at matched_fraction=1.0, A(D)=0.972, T(D)=0.925 --
    comfortably above theta_admit=0.75): the evidence-coverage gate (3.5)
    counted essentially all of A1-A5's ~69% nominal axis weight as
    "missing evidence", capping evidence_coverage near 31-46% and
    incorrectly downgrading a strongly, externally-verified ADMIT down to
    CONDITIONAL -- exactly backwards, since strong A6 corroboration is
    itself very strong authenticity evidence, not an absence of it.

    Fix: allocate axis_weight across A6 and (A1-A5) in proportion to how
    many records each stratum actually covers -- i.e. EXACTLY the same
    record-count blend `score_authenticity()` already uses to combine
    their SCORES into A(D), now also applied to their WEIGHTS:

        w_A6,eff = axis_weight * (n_a6_stratum / n_records)
        w_Ai,eff = axis_weight * (n_intrinsic  / n_records) * WITHIN_A[Ai]   (Ai in A1..A5)

    When A6 does not apply at all (offline/infeasible/nothing reached a
    corroborated-or-confirmed-contradicted verdict -- the common default
    case), n_a6_stratum=0 and this reduces EXACTLY to the original,
    pre-3.4 A1-A5 weighting (axis_weight * WITHIN_A[Ai]) -- fully
    backward-compatible with every audit that never engages A6. When A6
    covers the whole dataset, n_intrinsic=0 and A1-A5 correctly get
    effective_weight=0.0 -- a real, intentional zero ("this audit's A(D)
    has zero designed weight resting on A1-A5"), NOT None/"hard gate":
    A6 in its corroborating role is a normal, compensable sub-test, not a
    Stage-1 veto (only A6's separate "externally contradicted" state is a
    hard gate, handled entirely by hard_override.py, untouched by this).
    """
    a6_sub = axis_result.sub_results.get("A6")
    n_a6_stratum = 0
    if a6_sub is not None and a6_sub.applicable:
        n_a6_stratum = int(a6_sub.detail.get("n_effective", 0) or 0)
    n_a6_stratum = max(0, min(n_a6_stratum, n_records))  # defensive clamp
    n_intrinsic = max(0, n_records - n_a6_stratum)

    if n_records > 0:
        frac_a6 = n_a6_stratum / n_records
        frac_intrinsic = n_intrinsic / n_records
    else:
        frac_a6 = frac_intrinsic = 0.0

    if a6_sub is not None:
        a6_sub.effective_weight = axis_weight * frac_a6

    for sub_name in ("A1", "A2", "A3", "A4", "A5"):
        sub = axis_result.sub_results.get(sub_name)
        if sub is None:
            continue
        within_weight = WITHIN_A.get(sub_name)
        sub.effective_weight = (
            None if within_weight is None
            else axis_weight * frac_intrinsic * within_weight
        )


def _assign_effective_weights(axis_results: Dict[str, AxisResult], n_records: int) -> None:
    """
    Mutates each SubTestResult in `axis_results` in place, setting its
    `effective_weight` field to the NOMINAL (as-calibrated) contribution
    that sub-test makes to T(D).

    For P, C, and I this is the simple AXIS_WEIGHTS[axis] * WITHIN_<axis>[name]
    product. For A, see `_assign_effective_weights_axis_a` -- A6's
    record-stratum-substitution design means it needs record-count-
    proportional treatment instead of a fixed share.

    This directly surfaces the "effective weight concentration" point
    raised in the 2026-07 external review (Section 3.4): the framework's
    24 sub-tests are NOT equally weighted -- e.g. A1+A3+A4 alone account
    for ~68% of T(D)'s nominal weight in the common intrinsic-only case
    (no live A6 corroboration), and +P5 for ~81%. Previously this was only
    discoverable by manually multiplying AXIS_WEIGHTS by the relevant
    WITHIN_* table; it is now reported directly on every audit result
    (CLI --verbose output and JSON export alike) so a reader does not have
    to reconstruct it from source.

    Deliberately does NOT change T(D), the axis scores, or any
    renormalisation behaviour -- this is purely additive, diagnostic
    metadata attached to already-computed SubTestResult objects.
    """
    for axis_name, axis_result in axis_results.items():
        axis_weight = AXIS_WEIGHTS.get(axis_name)
        if axis_weight is None:
            continue

        if axis_name == "A":
            _assign_effective_weights_axis_a(axis_result, axis_weight, n_records)
            continue

        within = _WITHIN_BY_AXIS.get(axis_name, {})
        for sub_name, sub in axis_result.sub_results.items():
            within_weight = within.get(sub_name)
            if within_weight is None:
                sub.effective_weight = None  # hard gate (P1-P3) or unknown
            else:
                sub.effective_weight = axis_weight * within_weight


def _compute_evidence_coverage(
    axis_results: Dict[str, AxisResult],
) -> "tuple[Optional[float], List[Tuple[str, float]]]":
    """
    Diagnostic "evidence coverage" metric (review point 3.5, "renormalisation
    treats absence of evidence as evidence not needed"): what FRACTION of
    T(D)'s total NOMINAL (as-calibrated) weight was actually backed by an
    applicable, computable sub-test in THIS specific audit -- as opposed to
    a missing field or an inapplicable test whose weight was silently
    folded into the other tests via renormalisation.

    Built directly on top of `effective_weight` (3.4): every sub-test with
    a defined effective_weight (i.e. every non-hard-gate sub-test across
    all 4 axes) contributes its nominal weight to the denominator; only
    APPLICABLE sub-tests with a computable (non-NaN) score contribute to
    the numerator. By construction (AXIS_WEIGHTS and each WITHIN_* table
    are each individually normalised to sum to 1.0), the denominator is
    very close to 1.0 for a full, unmodified calibration -- computed here
    directly rather than hard-coded, so this stays correct even if the
    calibrated weights are ever revised.

    This is DIAGNOSTIC ONLY where per-axis "N/4 axes applicable" and
    "N/5 tests applicable" caveats already existed -- those counts treat
    every axis/sub-test as equally important, which is exactly what 3.4
    showed is not true (e.g. losing A3 alone drops ~29% of nominal weight,
    while losing A5 drops ~0.3%). Coverage answers "how much of T(D)'s
    DESIGNED weight is this specific number actually resting on", a
    strictly more informative version of the same question.

    Returns:
        (coverage, missing) where `coverage` is in [0, 1] (None if the
        nominal weight total is zero/undefined, e.g. no axes computed at
        all), and `missing` is a list of (sub_test_name, nominal_weight)
        pairs for every non-hard-gate sub-test that did NOT contribute to
        the numerator, sorted by nominal_weight descending -- i.e. exactly
        which missing evidence is costing the most designed weight, for
        use in a human-readable caveat.
    """
    total_weight = 0.0
    covered_weight = 0.0
    missing: List[Tuple[str, float]] = []
    for axis_result in axis_results.values():
        for sub_name, sub in axis_result.sub_results.items():
            if sub.effective_weight is None:
                continue  # hard gate (P1-P3 only, as of the 2026-07-21 A6 fix) -- outside the compensatory sum entirely
            total_weight += sub.effective_weight
            is_covered = sub.applicable and not (
                isinstance(sub.score, float) and math.isnan(sub.score)
            )
            if is_covered:
                covered_weight += sub.effective_weight
            else:
                missing.append((sub_name, sub.effective_weight))
    if total_weight <= 0.0:
        return None, missing
    missing.sort(key=lambda pair: pair[1], reverse=True)
    return covered_weight / total_weight, missing


def _compute_sample_sufficiency(
    axis_results: Dict[str, AxisResult],
) -> "tuple[Optional[float], List[Tuple[str, float, Optional[int], int]]]":
    """
    Diagnostic "sample sufficiency" metric (2026-07-21, external review --
    a distinct gap from evidence coverage above, not a duplicate of it):
    `_compute_evidence_coverage` answers "did an applicable sub-test run
    and produce a score at all". It does NOT answer a separate question --
    "was that sub-test's own underlying sample size (`n_used`, e.g. A3's
    number of independent aftershock clusters, or A1's smallest per-field
    Benford sample) actually large enough that the resulting score should
    be trusted". A3 can be "applicable" and "covered" from a single fitted
    cluster; a score built from n=1 is not remotely as trustworthy as one
    built from a few hundred, even though evidence_coverage cannot see the
    difference. This was the motivating false-admit finding in the
    external review: small catalogs (24-29 records) where only A3 and A5
    were applicable at all, each backed by a tiny underlying sample.

    Built on the same `effective_weight` / `MIN_RELIABLE_N` machinery: of
    the sub-tests that evidence_coverage already counts as COVERED
    (applicable, non-NaN score), what fraction of THEIR combined nominal
    weight rests on an n_used that meets or exceeds that sub-test's
    disclosed `MIN_RELIABLE_N` floor. Sub-tests with no entry in
    `MIN_RELIABLE_N` (any P/C/I sub-test, and A6 -- which already has its
    own dedicated n_stratum/n_effective three-state logic, Group C3,
    2026-07-12) are treated as always-sufficient here; this is a
    deliberate, disclosed SCOPE LIMIT of the initial rollout (axis A,
    A1-A5 only), not a claim that every other sub-test's sample size is
    unconditionally trustworthy -- extending `MIN_RELIABLE_N` to P/C/I is
    future work, same as evidence_coverage itself started axis-A-only-in-
    spirit before generalising.

    A sub-test that is NOT covered (missing/inapplicable) is excluded from
    both the numerator and denominator here -- it is evidence_coverage's
    job to flag that absence; sample_sufficiency only asks, CONDITIONAL ON
    evidence being present at all, whether there was enough of it.

    Returns:
        (sufficiency, insufficient) where `sufficiency` is in [0, 1] (None
        if no covered sub-test carries a defined effective_weight at all),
        and `insufficient` is a list of (sub_test_name, nominal_weight,
        n_used, min_required) tuples for every covered sub-test whose
        n_used fell short of its MIN_RELIABLE_N floor (or was altogether
        absent from `detail`), sorted by nominal_weight descending.
    """
    total_weight = 0.0
    sufficient_weight = 0.0
    insufficient: List[Tuple[str, float, Optional[int], int]] = []
    for axis_result in axis_results.values():
        for sub_name, sub in axis_result.sub_results.items():
            if sub.effective_weight is None:
                continue  # hard gate -- outside the compensatory sum entirely
            is_covered = sub.applicable and not (
                isinstance(sub.score, float) and math.isnan(sub.score)
            )
            if not is_covered:
                continue  # evidence_coverage's concern, not this gate's
            min_required = MIN_RELIABLE_N.get(sub_name)
            total_weight += sub.effective_weight
            if min_required is None:
                # No disclosed floor yet for this sub-test (scope limit,
                # see docstring above) -- counted as sufficient by default.
                sufficient_weight += sub.effective_weight
                continue
            n_used = sub.detail.get("n_used") if isinstance(sub.detail, dict) else None
            if n_used is not None and n_used >= min_required:
                sufficient_weight += sub.effective_weight
            else:
                insufficient.append((sub_name, sub.effective_weight, n_used, min_required))
    if total_weight <= 0.0:
        return None, insufficient
    insufficient.sort(key=lambda t: t[1], reverse=True)
    return sufficient_weight / total_weight, insufficient


class CertifyDecision(str, Enum):
    """
    ADMIT       -- T(D) >= theta_admit and no hard override fired. Certified
                   fit-for-use, with the full per-axis audit envelope.
    CONDITIONAL -- theta_reject <= T(D) < theta_admit. Usable only with
                   explicit, documented caveats (Deep-Dive 01 Section 2.2).
    REJECT      -- T(D) < theta_reject, OR any hard override fired. Not
                   fit for use in any downstream disaster-response model.
    """
    ADMIT = "ADMIT"
    CONDITIONAL = "CONDITIONAL"
    REJECT = "REJECT"


@dataclass
class CertifyResult:
    """Complete, JSON-serialisable output of the DATA-CERTIFY audit protocol."""
    decision: CertifyDecision
    trust_score: Optional[float]           # T(D); None if hard override fired (irrelevant, per Section 4 of Deep-Dive 05)
    hard_override: HardOverrideResult
    axis_results: Dict[str, AxisResult]    # {"A":..., "P":..., "C":..., "I":...}
    weights_used: Dict[str, float]
    theta_admit: float
    theta_reject: float
    caveats: List[str] = field(default_factory=list)
    dataset_name: str = ""
    n_records: int = 0
    # Diagnostic evidence-coverage metric (review point 3.5) -- see
    # `_compute_evidence_coverage`'s docstring. None when no axis produced
    # any non-hard-gate sub-test at all (e.g. the n==0 degenerate case).
    evidence_coverage: Optional[float] = None
    # Diagnostic sample-sufficiency metric (2026-07-21, external review) --
    # see `_compute_sample_sufficiency`'s docstring. Distinct from
    # evidence_coverage: this asks whether covered sub-tests' own
    # underlying sample sizes (n_used) were large enough to trust, not
    # merely whether they ran at all. None under the same conditions as
    # evidence_coverage (no covered sub-test carries a defined weight).
    sample_sufficiency: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "n_records": self.n_records,
            "decision": self.decision.value,
            "trust_score": self.trust_score,
            "evidence_coverage": self.evidence_coverage,
            "sample_sufficiency": self.sample_sufficiency,
            "hard_override": self.hard_override.to_dict(),
            "axis_results": {k: v.to_dict() for k, v in self.axis_results.items()},
            "weights_used": self.weights_used,
            "theta_admit": self.theta_admit,
            "theta_reject": self.theta_reject,
            "caveats": list(self.caveats),
        }

    def __str__(self) -> str:
        lines = [
            "=" * 65,
            f"  DATA-CERTIFY AUDIT RESULT: {self.decision.value}",
            "=" * 65,
        ]
        if self.hard_override.fired:
            lines.append("  HARD OVERRIDE FIRED -- composite score is not consulted.")
            for r in self.hard_override.reasons:
                lines.append(f"    - {r}")
        else:
            ts = self.trust_score
            lines.append(f"  Trust score T(D) = {ts:.4f}" if ts is not None and not math.isnan(ts)
                         else "  Trust score T(D) = N/A (insufficient applicable tests)")
            lines.append(f"  theta_admit={self.theta_admit}  theta_reject={self.theta_reject}")
        if self.evidence_coverage is not None:
            lines.append(f"  Evidence coverage = {self.evidence_coverage:.1%} of T(D)'s nominal "
                         f"calibrated weight was backed by applicable evidence in this audit.")
        if self.sample_sufficiency is not None:
            lines.append(f"  Sample sufficiency = {self.sample_sufficiency:.1%} of covered "
                         f"evidence's nominal weight rests on a sub-test sample size meeting "
                         f"its disclosed MIN_RELIABLE_N floor.")
        lines.append("")
        lines.append("  Per-axis scores:")
        for axis_name in ("A", "P", "C", "I"):
            axis = self.axis_results.get(axis_name)
            if axis is not None:
                score_str = "N/A" if math.isnan(axis.score) else f"{axis.score:.4f}"
                w = self.weights_used.get(axis_name, float("nan"))
                lines.append(f"    {axis_name}(D) = {score_str:<8}  (weight {w:.3f})  [{axis.mode}]" if axis.mode
                             else f"    {axis_name}(D) = {score_str:<8}  (weight {w:.3f})")
        if self.caveats:
            lines.append("")
            lines.append("  Caveats:")
            for c in self.caveats:
                lines.append(f"    - {c}")
        lines.append("=" * 65)
        return "\n".join(lines)


@dataclass
class UncertaintyResult:
    """
    Nonparametric resampling uncertainty estimate for T(D) (subsampling
    WITHOUT replacement -- Politis, Romano & Wolf 1999 -- applied to the
    ENTIRE four-axis audit pipeline as a single black-box statistic of the
    data; see `DataCertifyAuditor.estimate_uncertainty`'s docstring both
    for why this whole-pipeline approach was chosen over deriving a
    bespoke analytic standard error for each of the ~24 individual
    sub-tests, AND for why subsampling without replacement is used instead
    of the textbook with-replacement bootstrap -- the latter was found to
    manufacture artefactual exact-duplicate records that this framework's
    own A5/P7 duplicate-detection tests then flag, biasing T(D) downward
    for reasons unrelated to genuine sampling variability).
    """
    point_estimate: float                  # T(D) on the full, non-resampled dataset
    boot_mean: float                       # mean T(D) across valid resampling replicates
    boot_se: float                         # resampling standard error of T(D)
    ci_low: float                          # lower bound of the percentile interval
    ci_high: float                         # upper bound of the percentile interval
    ci_level: float                        # nominal interval coverage, e.g. 0.90
    n_boot: int                            # total resampling replicates requested
    n_boot_valid: int                      # replicates where T(D) was computable (no hard override)
    hard_override_rate: float              # fraction of replicates where the hard override fired
    decision_stability: Dict[str, float]   # fraction of replicates landing in each decision

    def to_dict(self) -> Dict[str, Any]:
        return {
            "point_estimate": None if math.isnan(self.point_estimate) else self.point_estimate,
            "boot_mean": None if math.isnan(self.boot_mean) else self.boot_mean,
            "boot_se": None if math.isnan(self.boot_se) else self.boot_se,
            "ci_low": None if math.isnan(self.ci_low) else self.ci_low,
            "ci_high": None if math.isnan(self.ci_high) else self.ci_high,
            "ci_level": self.ci_level,
            "n_boot": self.n_boot,
            "n_boot_valid": self.n_boot_valid,
            "hard_override_rate": self.hard_override_rate,
            "decision_stability": dict(self.decision_stability),
        }

    def __str__(self) -> str:
        lines = ["  Resampling (subsample-without-replacement) uncertainty on T(D):"]
        if math.isnan(self.boot_mean):
            lines.append(f"    Insufficient valid replicates ({self.n_boot_valid}/{self.n_boot}) "
                          f"to estimate a confidence interval.")
        else:
            pct = int(round(self.ci_level * 100))
            lines.append(f"    T(D) point estimate = {self.point_estimate:.4f}")
            lines.append(f"    Replicate mean = {self.boot_mean:.4f}, SE = {self.boot_se:.4f}")
            lines.append(f"    {pct}% percentile interval = [{self.ci_low:.4f}, {self.ci_high:.4f}] "
                          f"({self.n_boot_valid}/{self.n_boot} valid replicates)")
        if self.hard_override_rate > 0:
            lines.append(f"    Hard override fired in {self.hard_override_rate:.1%} of replicates "
                          f"-- the ADMIT/CONDITIONAL/REJECT decision is UNSTABLE near this boundary.")
        if self.decision_stability:
            stability_str = ", ".join(f"{k}={v:.1%}" for k, v in self.decision_stability.items())
            lines.append(f"    Decision stability across replicates: {stability_str}")
        return "\n".join(lines)


def _tally_decisions(decisions: List[str], total: int) -> Dict[str, float]:
    if total == 0:
        return {}
    counts = Counter(decisions)
    return {k: counts.get(k, 0) / total for k in ("ADMIT", "CONDITIONAL", "REJECT")}


class DataCertifyAuditor:
    """
    The DATA-CERTIFY audit protocol.

    Usage:
        auditor = DataCertifyAuditor()
        result  = auditor.audit(dataset)
        print(result)

    Args:
        theta_admit:   ADMIT threshold. Default: THETA_ADMIT (0.75, empirically
                       calibrated against the real 89-dataset corpus --
                       see calibration/threshold_report.md).
        theta_reject:  REJECT threshold. Default: THETA_REJECT (0.20, empirically
                       calibrated; revised down across successive corpus-expansion
                       passes from an earlier 0.50 provisional prior -- see
                       calibration/threshold_report.md).
        reference:     Optional ExternalCatalogReference for A6.
        fault_db:      Optional FaultDatabaseReference for P8.
        reference_dc:  Optional reference correlation dimension for A4.
        min_evidence_coverage: Additive safety gate (review point 3.5,
                       "renormalisation treats absence of evidence as
                       evidence not needed"): if T(D) would otherwise ADMIT
                       but less than this fraction of T(D)'s NOMINAL
                       calibrated weight (see `effective_weight`,
                       `_compute_evidence_coverage`) was actually backed
                       by applicable evidence in this specific audit, the
                       decision is capped down to CONDITIONAL rather than
                       ADMIT -- an ADMIT resting mostly on renormalised-
                       away missing evidence is not the same claim as an
                       ADMIT resting on a full battery of applicable
                       tests, even when both produce the same T(D) number.
                       Never upgrades a decision (CONDITIONAL/REJECT are
                       unaffected either way) and never overrides a Stage-1
                       hard override. Default 0.5 is a disclosed, pragmatic
                       choice -- like theta_admit/theta_reject's own
                       pre-calibration provisional values -- NOT itself
                       empirically calibrated against the 968-dataset
                       corpus; set to 0.0 to disable this gate entirely
                       and reproduce the pre-3.5 behaviour exactly.
        min_sample_sufficiency: Additive safety gate (2026-07-21, external
                       review -- the small-N / statistical-power gap
                       distinct from evidence_coverage above): if T(D)
                       would otherwise ADMIT but less than this fraction
                       of the COVERED evidence's nominal weight (see
                       `_compute_sample_sufficiency`) rests on a sub-test
                       whose own underlying sample size (`n_used`) met its
                       disclosed `MIN_RELIABLE_N` floor, the decision is
                       capped down to CONDITIONAL rather than ADMIT -- a
                       score built mostly from thin samples (e.g. a single
                       fitted aftershock cluster) is not the same strength
                       of claim as one built from a well-powered battery,
                       even at an identical T(D). Never upgrades a
                       decision and never overrides a Stage-1 hard
                       override; applies independently of, and in addition
                       to, min_evidence_coverage. Default 0.5 is a
                       disclosed, pragmatic, NOT-yet-corpus-calibrated
                       provisional prior -- same status as
                       min_evidence_coverage's own default; set to 0.0 to
                       disable this gate entirely. Currently scoped to
                       axis A (A1-A5) only, since `MIN_RELIABLE_N` has no
                       entries yet for P/C/I sub-tests -- a disclosed
                       scope limit, not a claim of full coverage.
    """

    def __init__(
        self,
        theta_admit: float = THETA_ADMIT,
        theta_reject: float = THETA_REJECT,
        reference: Optional[ExternalCatalogReference] = None,
        fault_db: Optional[FaultDatabaseReference] = None,
        reference_dc: Optional[float] = None,
        min_evidence_coverage: float = 0.5,
        min_sample_sufficiency: float = 0.5,
    ) -> None:
        if theta_reject > theta_admit:
            raise ValueError(
                f"DataCertifyAuditor: theta_reject={theta_reject} must be <= "
                f"theta_admit={theta_admit}."
            )
        if not (0.0 <= min_evidence_coverage <= 1.0):
            raise ValueError(
                f"DataCertifyAuditor: min_evidence_coverage={min_evidence_coverage} "
                f"must be in [0, 1]."
            )
        if not (0.0 <= min_sample_sufficiency <= 1.0):
            raise ValueError(
                f"DataCertifyAuditor: min_sample_sufficiency={min_sample_sufficiency} "
                f"must be in [0, 1]."
            )
        self.theta_admit = theta_admit
        self.theta_reject = theta_reject
        self.reference = reference
        self.fault_db = fault_db
        self.reference_dc = reference_dc
        self.min_evidence_coverage = min_evidence_coverage
        self.min_sample_sufficiency = min_sample_sufficiency

    def audit(self, dataset: CertifyDataset) -> CertifyResult:
        """Run the full two-stage DATA-CERTIFY audit protocol on `dataset`."""

        # -- Degenerate empty-dataset guard --------------------------------
        # Several intrinsic sub-tests (e.g. A5 "fewer than 2 records -> no
        # duplicates possible") are vacuously TRUE on an empty catalog, which
        # would otherwise let a single vacuous sub-test drive T(D) to 1.0 and
        # ADMIT a dataset containing zero records. A dataset with nothing in
        # it can never be certified fit-for-use, so this is handled as an
        # explicit REJECT before any axis scoring is attempted.
        if dataset.n == 0:
            empty_hard_override = check_hard_override(dataset)
            return CertifyResult(
                decision=CertifyDecision.REJECT,
                trust_score=float("nan"),
                hard_override=empty_hard_override,
                axis_results={},
                weights_used=dict(AXIS_WEIGHTS),
                theta_admit=self.theta_admit,
                theta_reject=self.theta_reject,
                caveats=["Dataset contains 0 records -- nothing to certify."],
                dataset_name=dataset.name,
                n_records=0,
            )

        # -- Compute all four axes first (needed both for T(D) and for the
        #    A6 stratum info that Stage 1's hard-override check consumes). --
        a_result = score_authenticity(dataset, reference=self.reference, reference_dc=self.reference_dc)
        p_result = score_plausibility(dataset, fault_db=self.fault_db)
        c_result = score_completeness(dataset)
        i_result = score_instrumentation(dataset)

        axis_results = {"A": a_result, "P": p_result, "C": c_result, "I": i_result}
        _assign_effective_weights(axis_results, dataset.n)
        evidence_coverage, missing_evidence = _compute_evidence_coverage(axis_results)
        sample_sufficiency, insufficient_samples = _compute_sample_sufficiency(axis_results)

        a6_sub = a_result.sub_results.get("A6")
        a6_matched_fraction = None
        a6_n_stratum = None
        a6_hard_reject = None
        a6_hard_reject_reason = None
        if a6_sub is not None and a6_sub.applicable:
            a6_matched_fraction = a6_sub.detail.get("matched_fraction")
            a6_n_stratum = a6_sub.detail.get("n_stratum")
            # a_result.hard_reject/hard_reject_reason are the SINGLE authoritative
            # A6 three-state verdict (Group C3, 2026-07-12), computed once inside
            # score_authenticity() -> _score_a6_external() and passed straight
            # through here -- check_hard_override() no longer independently
            # re-derives an A6 condition (see that function's docstring).
            a6_hard_reject = a_result.hard_reject
            a6_hard_reject_reason = a_result.hard_reject_reason

        # -- Stage 1: hard-override veto gate -----------------------------
        hard_override = check_hard_override(
            dataset, a6_matched_fraction=a6_matched_fraction, a6_n_stratum=a6_n_stratum,
            a6_hard_reject=a6_hard_reject, a6_hard_reject_reason=a6_hard_reject_reason,
        )

        caveats: List[str] = []
        for axis in axis_results.values():
            caveats.extend(axis.notes)

        if hard_override.fired:
            return CertifyResult(
                decision=CertifyDecision.REJECT,
                trust_score=None,
                hard_override=hard_override,
                axis_results=axis_results,
                weights_used=dict(AXIS_WEIGHTS),
                theta_admit=self.theta_admit,
                theta_reject=self.theta_reject,
                caveats=caveats,
                dataset_name=dataset.name,
                n_records=dataset.n,
                evidence_coverage=evidence_coverage,
                sample_sufficiency=sample_sufficiency,
            )

        # -- Stage 2: compensatory composite score ------------------------
        applicable_axes = {k: v for k, v in axis_results.items() if not math.isnan(v.score)}
        if not applicable_axes:
            trust_score = float("nan")
        else:
            w_sum = sum(AXIS_WEIGHTS[k] for k in applicable_axes)
            trust_score = sum(AXIS_WEIGHTS[k] * v.score for k, v in applicable_axes.items()) / w_sum
            if len(applicable_axes) < 4:
                missing = sorted(set(AXIS_WEIGHTS) - set(applicable_axes))
                caveats.append(
                    f"T(D) computed from {len(applicable_axes)}/4 axes (missing: {missing} "
                    f"-- no applicable sub-tests for that axis given available fields); "
                    f"weights renormalised over the applicable axes."
                )

        if math.isnan(trust_score):
            decision = CertifyDecision.REJECT
            caveats.append("No axis produced a usable score -- defaulting to REJECT "
                            "(insufficient data to certify).")
        elif trust_score >= self.theta_admit:
            decision = CertifyDecision.ADMIT
        elif trust_score >= self.theta_reject:
            decision = CertifyDecision.CONDITIONAL
            caveats.append(
                f"T(D)={trust_score:.4f} falls in the indifference zone "
                f"[{self.theta_reject}, {self.theta_admit}) -- usable only with the "
                f"specific per-axis caveats listed above (Deep-Dive 01 Section 2.2)."
            )
        else:
            decision = CertifyDecision.REJECT

        # -- Additive evidence-coverage safety gate (review point 3.5) ----
        # Only ever CAPS an ADMIT down to CONDITIONAL -- never touches an
        # already-CONDITIONAL or REJECT decision, and never runs at all if
        # Stage 1 already fired (handled by the early return above). See
        # `_compute_evidence_coverage`'s docstring and this class's
        # `min_evidence_coverage` docstring for the full rationale: T(D)
        # can clear theta_admit while resting mostly on renormalised-away
        # missing evidence rather than actual applicable tests, and that is
        # not the same strength of claim as an ADMIT backed by a full
        # battery -- this makes that distinction visible in the decision
        # itself, not just in a buried caveat.
        if (decision == CertifyDecision.ADMIT
                and evidence_coverage is not None
                and evidence_coverage < self.min_evidence_coverage):
            top_missing = ", ".join(
                f"{name} ({weight:.1%} nominal weight)" for name, weight in missing_evidence[:3]
            )
            caveats.append(
                f"Evidence-coverage safety gate: T(D)={trust_score:.4f} cleared "
                f"theta_admit={self.theta_admit}, but only {evidence_coverage:.1%} of T(D)'s "
                f"nominal calibrated weight was backed by applicable evidence in this audit "
                f"(min_evidence_coverage={self.min_evidence_coverage:.1%}) -- capped down to "
                f"CONDITIONAL rather than ADMIT. Largest missing contributions: {top_missing}."
            )
            decision = CertifyDecision.CONDITIONAL

        # -- Additive sample-sufficiency safety gate (2026-07-21, external
        # review) -- structurally identical to the evidence-coverage gate
        # above (only ever caps ADMIT down to CONDITIONAL; independent of
        # it and applied in addition, not instead): T(D) can clear
        # theta_admit and have full evidence_coverage, yet still rest on
        # sub-tests whose own sample size was too thin to trust (e.g. a
        # single fitted Omori-Utsu cluster) -- see
        # `_compute_sample_sufficiency`'s docstring and this class's
        # `min_sample_sufficiency` docstring for the full rationale.
        if (decision == CertifyDecision.ADMIT
                and sample_sufficiency is not None
                and sample_sufficiency < self.min_sample_sufficiency):
            top_insufficient = ", ".join(
                f"{name} (n_used={n_used}, needs>={min_required}, "
                f"{weight:.1%} nominal weight)"
                for name, weight, n_used, min_required in insufficient_samples[:3]
            )
            caveats.append(
                f"Sample-sufficiency safety gate: T(D)={trust_score:.4f} cleared "
                f"theta_admit={self.theta_admit}, but only {sample_sufficiency:.1%} of covered "
                f"evidence's nominal weight rested on a sub-test sample size meeting its "
                f"disclosed MIN_RELIABLE_N floor (min_sample_sufficiency="
                f"{self.min_sample_sufficiency:.1%}) -- capped down to CONDITIONAL rather than "
                f"ADMIT. Thinnest-sampled contributions: {top_insufficient}."
            )
            decision = CertifyDecision.CONDITIONAL

        return CertifyResult(
            decision=decision,
            trust_score=trust_score,
            hard_override=hard_override,
            axis_results=axis_results,
            weights_used=dict(AXIS_WEIGHTS),
            theta_admit=self.theta_admit,
            theta_reject=self.theta_reject,
            caveats=caveats,
            dataset_name=dataset.name,
            n_records=dataset.n,
            evidence_coverage=evidence_coverage,
            sample_sufficiency=sample_sufficiency,
        )

    def estimate_uncertainty(
        self,
        dataset: CertifyDataset,
        n_boot: int = 100,
        seed: int = 42,
        ci_level: float = 0.90,
        subsample_fraction: float = 0.8,
        max_bootstrap_n: int = 20000,
    ) -> UncertaintyResult:
        """
        Nonparametric resampling confidence interval for T(D): resample the
        dataset `n_boot` times and re-run the FULL audit pipeline on each
        resample, rather than deriving an analytic standard error for T(D)
        from each of the ~24 individual sub-tests separately -- doing that
        would require a bespoke delta-method derivation per test (MLE
        b-values, KS statistics, quadrat counts, EM posteriors, ...), an
        error-prone undertaking given how heterogeneous the underlying
        statistics are. Treating the whole audit as a black-box statistic
        of the data sidesteps that entirely, at the cost of re-running the
        pipeline `n_boot` times.

        IMPORTANT DESIGN CHOICE -- subsampling WITHOUT replacement
        (Politis, Romano & Wolf 1999's "m-out-of-n" subsampling bootstrap),
        NOT the textbook resample-WITH-replacement bootstrap (Efron &
        Tibshirani 1993), and this is not a stylistic preference: the
        standard with-replacement bootstrap was tried first during
        development and found to be actively WRONG for this specific
        pipeline. Resampling n records with replacement mechanically
        produces repeated draws of the same record (~37% of a same-size
        with-replacement resample are exact duplicates of another record
        in that resample, by construction) -- and A5 (duplicate/near-
        duplicate detection) and P7 (duplicate-timestamp detection) then
        correctly flag those artefactual duplicates as fabrication
        evidence, since they cannot distinguish "duplicated because the
        resampling method happened to draw this record twice" from "an
        actual sign of copy-paste fabrication in the original data".
        Measured on a clean 1500-record synthetic catalog with A5=P7=1.0
        at the point estimate, a single with-replacement resample dropped
        A5 to 0.37 and P7 to 0.63 purely from this artefact, dragging
        T(D) down with it -- i.e. the naive bootstrap's dispersion would
        have been measuring its OWN resampling artefact, not the data's
        real sampling variability, and specifically contaminating exactly
        the two sub-tests this framework relies on to catch duplication-
        based fabrication. Subsampling a `subsample_fraction` (default
        80%) of records WITHOUT replacement never creates a record seen
        twice, so A5/P7 respond only to genuine duplicates already present
        in the data (confirmed: the same clean catalog holds A5=P7=1.0
        under 80%-subsampling, matching the point estimate). The
        corresponding, disclosed trade-off: subsampling answers "how much
        does T(D) vary across different `subsample_fraction`-sized slices
        of this dataset" rather than "what is T(D)'s exact sampling
        distribution at the full n" -- a related but not identical
        question, and (per Politis, Romano & Wolf) the resulting interval
        is not automatically on the same scale as a with-replacement
        bootstrap CI would be; it is reported here as a percentile
        interval over the subsample replicates themselves, which is
        sufficient for the practical use case (a stability/sensitivity
        signal for T(D)), not offered as a rescaled asymptotic CI for the
        full-sample T(D).

        NOT part of `.audit()`'s default path -- this is opt-in (see
        `run_audit.py --uncertainty`) precisely because of its cost:
        expect roughly `n_boot` times the runtime of a single `.audit()`
        call.

        Args:
            n_boot: Number of resampling replicates. 100 is a reasonable
                default for a percentile CI; like theta_admit/theta_reject
                themselves, this is disclosed as a pragmatic choice, not
                an empirically calibrated one.
            subsample_fraction: Fraction of records drawn WITHOUT
                replacement per replicate (default 0.8). Must be in
                (0, 1]; values close to 1.0 approach re-running the audit
                on the (almost) full dataset repeatedly, which still
                varies across replicates only through which records are
                excluded, and gives a narrower, less informative interval.
            max_bootstrap_n: If dataset.n exceeds this, the per-replicate
                subsample size is additionally capped at this many records
                (purely for tractability on very large catalogs -- mirrors
                the same disclosed performance-cap pattern already used by
                `stats.MAX_TREND_N` and `correlation_dimension`'s
                `max_points`).

        Returns:
            UncertaintyResult -- includes not just a T(D) confidence
            interval but also the hard-override firing RATE across
            replicates (a dataset sitting right at the hard-override
            boundary will show this as e.g. "fired in 8% of resamples",
            a genuinely useful stability signal T(D) alone cannot convey)
            and the fraction of replicates landing in each of
            ADMIT/CONDITIONAL/REJECT.
        """
        if not (0.0 < subsample_fraction <= 1.0):
            raise ValueError(f"estimate_uncertainty: subsample_fraction={subsample_fraction} "
                              f"must be in (0, 1].")

        point_result = self.audit(dataset)
        point_t = (point_result.trust_score if point_result.trust_score is not None
                   else float("nan"))

        rng = np.random.RandomState(seed)
        n = dataset.n
        resample_n = min(int(round(subsample_fraction * n)), max_bootstrap_n) if n > 0 else 0
        resample_n = max(resample_n, 1) if n > 0 else 0

        t_values: List[float] = []
        decisions: List[str] = []
        n_hard_override = 0

        for _ in range(n_boot):
            if resample_n == 0:
                continue
            # WITHOUT replacement (see docstring): avoids manufacturing
            # exact-duplicate records that A5/P7 would then (correctly,
            # but spuriously for this purpose) flag as fabrication.
            idx = rng.choice(n, size=resample_n, replace=False)
            boot_ds = dataset.resample(idx)
            try:
                boot_result = self.audit(boot_ds)
            except Exception:
                # A pathological resample (e.g. one that happens to be
                # degenerate in a way a real audit never hit) should not
                # abort the whole bootstrap -- it is simply excluded from
                # n_boot_valid, same as a hard-override replicate.
                continue

            decisions.append(boot_result.decision.value)
            if boot_result.hard_override.fired:
                n_hard_override += 1
                continue
            ts = boot_result.trust_score
            if ts is not None and math.isfinite(ts):
                t_values.append(ts)

        # BUGFIX (scientific-validity review pass): this must be normalised
        # by the number of COMPLETED replicates (len(decisions) -- i.e.
        # n_boot minus any pathological resamples that raised and were
        # `continue`d past above), not by the raw `n_boot` requested.
        # `decisions` already excludes exception replicates for exactly
        # this reason (see `decision_stability` below, which was already
        # correctly normalised this way). Dividing by raw `n_boot` instead
        # silently UNDER-estimates hard_override_rate whenever any
        # replicate raised an exception, since those replicates count
        # against the denominator without ever having a chance to
        # register in the numerator -- the wrong direction for a
        # stability/safety signal whose whole purpose is to warn when a
        # dataset sits close to the hard-override boundary. Confirmed with
        # a controlled reproduction (4 simulated exceptions + 3 hard-
        # override + 3 ok replicates out of 10 requested): the old
        # `n_hard_override / n_boot` reported 0.30 while the true rate
        # among the 6 completed replicates is 0.50.
        n_completed = len(decisions)
        hard_override_rate = (n_hard_override / n_completed) if n_completed else float("nan")
        decision_stability = _tally_decisions(decisions, n_completed)

        n_valid = len(t_values)
        if n_valid < 2:
            return UncertaintyResult(
                point_estimate=point_t, boot_mean=float("nan"), boot_se=float("nan"),
                ci_low=float("nan"), ci_high=float("nan"), ci_level=ci_level,
                n_boot=n_boot, n_boot_valid=n_valid,
                hard_override_rate=hard_override_rate,
                decision_stability=decision_stability,
            )

        arr = np.array(t_values)
        boot_mean = float(np.mean(arr))
        boot_se = float(np.std(arr, ddof=1))
        alpha = 1.0 - ci_level
        lo_pct, hi_pct = 100.0 * (alpha / 2.0), 100.0 * (1.0 - alpha / 2.0)
        ci_low, ci_high = float(np.percentile(arr, lo_pct)), float(np.percentile(arr, hi_pct))

        return UncertaintyResult(
            point_estimate=point_t, boot_mean=boot_mean, boot_se=boot_se,
            ci_low=ci_low, ci_high=ci_high, ci_level=ci_level,
            n_boot=n_boot, n_boot_valid=n_valid,
            hard_override_rate=hard_override_rate,
            decision_stability=decision_stability,
        )
