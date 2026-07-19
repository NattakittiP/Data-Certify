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

from ._constants import AXIS_WEIGHTS, THETA_ADMIT, THETA_REJECT
from .axis_authenticity import score_authenticity
from .axis_completeness import score_completeness
from .axis_instrumentation import score_instrumentation
from .axis_plausibility import score_plausibility
from .hard_override import HardOverrideResult, check_hard_override
from .reference_data import ExternalCatalogReference, FaultDatabaseReference
from .results import AxisResult
from .schema import CertifyDataset


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset_name,
            "n_records": self.n_records,
            "decision": self.decision.value,
            "trust_score": self.trust_score,
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
    """

    def __init__(
        self,
        theta_admit: float = THETA_ADMIT,
        theta_reject: float = THETA_REJECT,
        reference: Optional[ExternalCatalogReference] = None,
        fault_db: Optional[FaultDatabaseReference] = None,
        reference_dc: Optional[float] = None,
    ) -> None:
        if theta_reject > theta_admit:
            raise ValueError(
                f"DataCertifyAuditor: theta_reject={theta_reject} must be <= "
                f"theta_admit={theta_admit}."
            )
        self.theta_admit = theta_admit
        self.theta_reject = theta_reject
        self.reference = reference
        self.fault_db = fault_db
        self.reference_dc = reference_dc

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
