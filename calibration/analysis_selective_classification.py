# -*- coding: utf-8 -*-
"""
calibration/analysis_selective_classification.py -- Group B5 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B): frames
DATA-CERTIFY's three-way decision (ADMIT/CONDITIONAL/REJECT) explicitly as
a SELECTIVE CLASSIFIER (El-Yaniv & Wiener, 2010, "On the Foundations of
Noise-free Selective Classification," JMLR 11:1605-1637) -- CONDITIONAL is
the abstention/reject-to-human option, ADMIT/REJECT are the two confident
autonomous decisions -- and reports the standard metrics that framing
implies (coverage, selective risk, a full risk-coverage curve, AURC), plus
decision-utility calculations under several disclosed cost-ratio scenarios.

All decisions recomputed LIVE via _analysis_common.composite_score()/
assign_decision() under current production weights -- never read from
score_matrix.csv's cached columns (LEGACY_STALE_COLUMNS convention).

Definitions used throughout (stated explicitly since "coverage" and "risk"
are overloaded terms across the selective-classification and information-
retrieval literatures):
  - Coverage = fraction of the corpus NOT deferred to CONDITIONAL (manual
    review), i.e. (n_ADMIT + n_REJECT) / n_total.
  - Selective risk = error rate WITHIN the covered (non-abstained) subset
    only: (false_admit + false_reject) / (n_ADMIT + n_REJECT). This is the
    standard selective-classification risk definition -- it does NOT
    penalize CONDITIONAL calls as errors (deferring to a human is treated
    as a correct, safe action, not a miss), which is the entire point of
    having an abstention option in a safety-oriented architecture.

Usage:
    python3 calibration/analysis_selective_classification.py

Output:
    calibration/group_b_reports/selective_classification_report.txt
    calibration/group_b_reports/selective_classification_risk_coverage_curve.csv
    calibration/group_b_reports/selective_classification_utility.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

CALIBRATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CALIBRATION_DIR))
import _analysis_common as ac  # noqa: E402

OUT_DIR = CALIBRATION_DIR / "group_b_reports"
OUT_DIR.mkdir(exist_ok=True)


def compute_operating_point(df: pd.DataFrame, decision: pd.Series) -> dict:
    known_good = df["group"] == "known_good"
    known_bad = df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"])
    n = len(df)

    covered = decision != "CONDITIONAL"
    n_covered = int(covered.sum())
    coverage = n_covered / n

    false_admit = (decision == "ADMIT") & known_bad
    false_reject = (decision == "REJECT") & known_good
    n_errors_covered = int((false_admit & covered).sum()) + int((false_reject & covered).sum())
    selective_risk = n_errors_covered / n_covered if n_covered else float("nan")

    return {
        "n": n, "n_covered": n_covered, "coverage": coverage,
        "n_errors_covered": n_errors_covered, "selective_risk": selective_risk,
        "n_conditional": int((decision == "CONDITIONAL").sum()),
        "n_false_admit": int(false_admit.sum()), "n_false_reject": int(false_reject.sum()),
    }


def build_risk_coverage_curve(df: pd.DataFrame, t_d: pd.Series, n_points: int = 41) -> pd.DataFrame:
    """Standard selective-classification risk-coverage curve: rank every
    instance by a confidence score, then sweep the covered fraction from
    100% down to a small floor, computing selective risk at each level.

    Confidence score: hard-override-fired rows get the MAXIMUM possible
    confidence (a categorical, non-compensable REJECT signal, not a T(D)
    magnitude comparison -- see Docs/01_Deep_Dives/..._Hard_Override_Proofs.md
    for why these are treated as a qualitatively different kind of
    evidence). All other rows get confidence = |T(D) - midpoint|, where
    midpoint = (THETA_ADMIT + THETA_REJECT) / 2 -- distance from the
    midpoint of the two-threshold gap is the natural confidence measure
    for a system whose only decision statistic is T(D) itself. The
    resulting binary call for each non-hard-override row (used only for
    this curve, NOT the production 3-way decision) is ADMIT if
    T(D) >= midpoint else REJECT.
    """
    midpoint = (ac.THETA_ADMIT + ac.THETA_REJECT) / 2.0
    hof = df["hard_override_fired"].fillna(False).astype(bool)

    confidence = np.where(hof, np.inf, np.abs(t_d.fillna(midpoint).values - midpoint))
    binary_call = np.where(hof, "REJECT", np.where(t_d.fillna(midpoint).values >= midpoint, "ADMIT", "REJECT"))

    known_good = (df["group"] == "known_good").values
    known_bad = df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"]).values
    is_error = ((binary_call == "ADMIT") & known_bad) | ((binary_call == "REJECT") & known_good)

    order = np.argsort(-confidence)  # most confident first
    is_error_sorted = is_error[order]
    n = len(df)

    rows = []
    for frac in np.linspace(1.0, 0.05, n_points):
        k = max(1, int(round(frac * n)))
        risk_k = is_error_sorted[:k].mean()
        rows.append({"coverage": k / n, "n_covered": k, "selective_risk": risk_k})
    curve = pd.DataFrame(rows)

    # AURC via trapezoidal integration over the curve as computed (coverage
    # descending in the loop above but we sort ascending for a clean integral).
    curve_sorted = curve.sort_values("coverage")
    trapz_fn = getattr(np, "trapezoid", None) or np.trapz  # numpy >=2.0 renamed trapz -> trapezoid
    aurc = float(trapz_fn(curve_sorted["selective_risk"], curve_sorted["coverage"]))
    return curve, aurc


def main() -> None:
    df = ac.load_corpus(include_adversarial=True)
    include_adv = ac.ADVERSARIAL_SCORE_MATRIX_PATH.exists()

    t_d = ac.composite_score(df, ac.AXIS_WEIGHTS, ac.WITHIN)
    # GATE-AWARENESS FIX (2026-07-21): use the REAL, fully-gated production
    # decision -- this variable is reused below as BOTH the "current
    # production operating point" AND the "full_two_stage (production)"
    # utility-analysis policy, so fixing it here fixes both at once. Coherent
    # here specifically because ac.AXIS_WEIGHTS/ac.WITHIN IS the production
    # weight basis that evidence_coverage/sample_sufficiency were computed
    # under (see assign_decision_gated()'s docstring for why this does NOT
    # generalize to an arbitrary weight vector).
    decision = ac.assign_decision_gated(df, t_d)

    report = []
    report.append("=" * 100)
    report.append("Group B5: Selective-classification framing & decision-utility analysis")
    report.append("(Group B post-hoc verification analysis)")
    report.append("=" * 100)
    report.append("")
    report.append(f"Corpus: n={len(df)} ({df['group'].value_counts().to_dict()})")
    if not include_adv:
        report.append("*** NOTE: held_out_adversarial group excluded (run score_adversarial_holdout.py first). ***")
    report.append("")
    report.append(
        "Framing: CONDITIONAL = abstention/defer-to-human-review (El-Yaniv & "
        "Wiener 2010 selective classification). ADMIT/REJECT = confident "
        "autonomous decisions. Coverage = fraction NOT deferred. Selective "
        "risk = error rate WITHIN the confident (non-deferred) subset only."
    )
    report.append("")

    # ---- Current production operating point, overall + by group ----
    report.append(
        "GATE-AWARENESS (2026-07-21): 'decision' throughout this report is now "
        "the REAL, fully-gated production decision (Stage 1+2 thresholds + "
        "min_evidence_coverage/min_sample_sufficiency safety gates + "
        "min_n_records_for_admit/min_applicable_subtests_for_admit "
        "ADMIT-eligibility floors) -- NOT the Stage-1+2-threshold-only logic "
        "this report used before this date (which reported false_admit=19 in "
        "the operating point below; the real, gated figure is 3). See "
        "CHANGELOG.md's 2026-07-21 entries."
    )
    report.append("")
    report.append("--- Current production operating point (blended_current weights, thresholds as-is, GATED) ---")
    op = compute_operating_point(df, decision)
    report.append(f"Coverage: {op['coverage']:.4f} ({op['n_covered']}/{op['n']})")
    report.append(f"Selective risk (errors within covered subset): {ac.fmt_rate_ci(op['n_errors_covered'], op['n_covered'])}")
    report.append(f"  of which false_admit={op['n_false_admit']}, false_reject={op['n_false_reject']}")
    report.append(f"CONDITIONAL (abstained) count: {op['n_conditional']} ({op['n_conditional']/op['n']:.4f} of corpus)")
    report.append("")

    report.append("--- Operating point by group ---")
    op_rows = []
    for g in df["group"].unique():
        mask = df["group"] == g
        sub_op = compute_operating_point(df[mask].reset_index(drop=True), decision[mask].reset_index(drop=True))
        sub_op["group"] = g
        op_rows.append(sub_op)
    op_df = pd.DataFrame(op_rows)[["group", "n", "coverage", "n_covered", "selective_risk", "n_errors_covered", "n_conditional"]]
    report.append(op_df.to_string(index=False))
    report.append("")

    # ---- Risk-coverage curve ----
    curve, aurc = build_risk_coverage_curve(df, t_d)
    curve.to_csv(OUT_DIR / "selective_classification_risk_coverage_curve.csv", index=False)
    report.append("--- Risk-coverage curve (binary ADMIT/REJECT-at-midpoint ranking, NOT the production 3-way decision -- see build_risk_coverage_curve()'s docstring) ---")
    report.append(f"AURC (area under risk-coverage curve, trapezoidal, lower=better): {aurc:.6f}")
    report.append("Risk at selected coverage levels:")
    for target in [1.00, 0.95, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30, 0.20, 0.10]:
        idx = (curve["coverage"] - target).abs().idxmin()
        row = curve.loc[idx]
        report.append(f"  coverage~={target:.2f} (actual {row['coverage']:.4f}, n={int(row['n_covered'])}): selective_risk={row['selective_risk']:.4f}")
    report.append(
        "Reading guide: this curve answers 'if we were willing to defer MORE "
        "(or less) of the corpus to manual review than the current CONDITIONAL "
        "zone does, how would the error rate on the remaining autonomous "
        "decisions change?' A curve that drops steeply as coverage decreases "
        "from 100% indicates the least-confident instances really are "
        "disproportionately the erroneous ones (T(D) confidence is doing real "
        "work); a flat curve would mean T(D)'s distance from the midpoint "
        "carries little information about correctness."
    )
    report.append("")

    # ---- Decision-utility under multiple cost-ratio scenarios ----
    report.append("-" * 100)
    report.append("Decision-utility analysis under disclosed cost-ratio scenarios")
    report.append("-" * 100)
    report.append(
        "Cost model: total_cost = C_FA * n_false_admit + C_FR * n_false_reject "
        "+ C_review * n_conditional, normalized to cost PER DATASET (divide by "
        "n). C_FR is fixed at 1.0 as the reference unit in every scenario. "
        "These cost ratios are illustrative policy assumptions, NOT derived "
        "from any real operational cost data DATA-CERTIFY has access to -- "
        "disclosed as such, not presented as measured costs. The seismology "
        "domain rationale for C_FA >> C_FR: admitting fabricated/corrupted "
        "data into a hazard database can propagate into downstream hazard "
        "models silently, while a false reject just costs one analyst's "
        "manual review time -- but the EXACT ratio is a policy choice this "
        "script deliberately does not presume to fix, hence the sweep."
    )
    report.append("")

    scenarios = [
        {"name": "C_FA=1, C_FR=1, C_review=0 (naive equal-cost, no review friction)", "c_fa": 1.0, "c_fr": 1.0, "c_review": 0.0},
        {"name": "C_FA=5, C_FR=1, C_review=0.1", "c_fa": 5.0, "c_fr": 1.0, "c_review": 0.1},
        {"name": "C_FA=10, C_FR=1, C_review=0.2", "c_fa": 10.0, "c_fr": 1.0, "c_review": 0.2},
        {"name": "C_FA=20, C_FR=1, C_review=0.3", "c_fa": 20.0, "c_fr": 1.0, "c_review": 0.3},
        {"name": "C_FA=50, C_FR=1, C_review=0.5", "c_fa": 50.0, "c_fr": 1.0, "c_review": 0.5},
    ]

    # Three policies to compare, reusing the same mechanism-ablation arms as B3:
    hof = df["hard_override_fired"].fillna(False).astype(bool)
    policies = {}
    policies["full_two_stage (production)"] = decision
    ws_only_t = ac.composite_score(df, ac.AXIS_WEIGHTS, ac.WITHIN)
    policies["weighted_sum_only"] = ac.assign_decision_gated(df, ws_only_t, respect_hard_override=False)
    policies["hard_override_only"] = pd.Series(np.where(hof, "REJECT", "ADMIT"), index=df.index)

    known_good = df["group"] == "known_good"
    known_bad = df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"])
    n = len(df)

    utility_rows = []
    for scen in scenarios:
        for pname, pdecision in policies.items():
            n_fa = int(((pdecision == "ADMIT") & known_bad).sum())
            n_fr = int(((pdecision == "REJECT") & known_good).sum())
            n_cond = int((pdecision == "CONDITIONAL").sum())
            total_cost = scen["c_fa"] * n_fa + scen["c_fr"] * n_fr + scen["c_review"] * n_cond
            utility_rows.append({
                "scenario": scen["name"], "policy": pname,
                "n_false_admit": n_fa, "n_false_reject": n_fr, "n_conditional": n_cond,
                "total_cost": total_cost, "cost_per_dataset": total_cost / n,
            })
    utility_df = pd.DataFrame(utility_rows)
    utility_df.to_csv(OUT_DIR / "selective_classification_utility.csv", index=False)

    for scen in scenarios:
        report.append(f"--- Scenario: {scen['name']} ---")
        sub = utility_df[utility_df["scenario"] == scen["name"]].sort_values("cost_per_dataset")
        report.append(sub[["policy", "n_false_admit", "n_false_reject", "n_conditional", "cost_per_dataset"]].to_string(index=False))
        best = sub.iloc[0]["policy"]
        report.append(f"  -> lowest cost_per_dataset under this scenario: {best}")
        report.append("")

    report.append(
        "Reading guide: if 'full_two_stage (production)' is cost-optimal (or "
        "near it) across ALL scenarios above, that is a strong, robust "
        "argument for the two-stage architecture independent of exactly which "
        "cost ratio a reader personally finds plausible. If a different "
        "policy wins at extreme cost ratios, that identifies precisely which "
        "assumption would need to hold for a simpler architecture to be "
        "preferable -- report that honestly rather than only the scenarios "
        "favorable to production."
    )

    report_text = "\n".join(report)
    print(report_text)
    (OUT_DIR / "selective_classification_report.txt").write_text(report_text, encoding="utf-8")
    print(f"\nReports written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
