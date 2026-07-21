# -*- coding: utf-8 -*-
"""
calibration/analysis_three_way_matrix.py -- Group B2 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B): the full
decision confusion matrix -- group (known_good / corrupted_real / fabricated / held_out_adversarial)
x decision (ADMIT / CONDITIONAL / REJECT), with hard-override-fired
reported separately (hard-override is a REJECT-causing GATE, not a fourth
decision value -- decision.py only ever emits ADMIT/CONDITIONAL/REJECT;
folding hard-override into the matrix as if it were a 4th column would
double-count against REJECT), every rate reported with a Wilson 95% CI,
broken down overall and then by corruption_type / fabrication style /
n_records bucket.

T(D) and decision are ALWAYS recomputed live via
_analysis_common.composite_score()/assign_decision() under the CURRENT
production weights (WEIGHT_VARIANTS['blended_current']) -- never read from
score_matrix.csv's cached trust_score_ahp_only/decision_ahp_only columns,
per this project's LEGACY_STALE_COLUMNS convention (see
_analysis_common.py's module-level comment for why those columns can be
stale even when the code is correct).

GATE-AWARENESS FIX (2026-07-21): this report previously used ONLY
_analysis_common.assign_decision() (Stage 1 hard override + Stage 2
theta_admit/theta_reject threshold logic), which does NOT reproduce what a
real user of DataCertifyAuditor.audit() experiences -- production also
applies two weight-fraction safety gates (min_evidence_coverage,
min_sample_sufficiency) and, as of this same date, two count-based
ADMIT-eligibility floors (min_n_records_for_admit,
min_applicable_subtests_for_admit). The false-admit rate this report had
previously disclosed as 19/490 (3.9%) was measured under threshold logic
alone, not the real, fully-gated decision path. This report now computes
BOTH: `decision_ungated` (the original Stage-1+2-only logic, kept for
transparency/history) and `decision` (the REAL, fully-gated production
decision, via _analysis_common.assign_decision_gated()) -- every headline
rate below is now reported under BOTH, side by side, so this staleness
gap cannot recur silently. See CHANGELOG.md's 2026-07-21
"ADMIT-eligibility gate + gate-aware re-audit" entry for the full story.

Prerequisite: run calibration/score_adversarial_holdout.py first if you
want the held_out_adversarial group included (recommended -- this is the
group that most directly covers the held-out/adversarial verification
item in DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B).
This script still runs and produces a complete report without
it, with an explicit note that the group is missing.

Usage:
    python3 calibration/analysis_three_way_matrix.py

Output:
    calibration/group_b_reports/three_way_matrix_report.txt   (full report, human-readable)
    calibration/group_b_reports/three_way_matrix_main.csv     (group x decision counts + rates + CIs)
    calibration/group_b_reports/three_way_matrix_by_corruption_type.csv
    calibration/group_b_reports/three_way_matrix_by_n_records_bucket.csv
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

GROUPS_ORDER = ["known_good", "corrupted_real", "fabricated", "held_out_adversarial"]
DECISIONS_ORDER = ["ADMIT", "CONDITIONAL", "REJECT"]

N_RECORDS_BUCKETS = [
    (0, 50, "1-49"),
    (50, 200, "50-199"),
    (200, 1000, "200-999"),
    (1000, 10000, "1000-9999"),
    (10000, float("inf"), "10000+"),
]


def bucket_n_records(n: float) -> str:
    for lo, hi, label in N_RECORDS_BUCKETS:
        if lo <= n < hi:
            return label
    return "unknown"


def fabrication_style(notes: str) -> str:
    """Best-effort sub-category for the fabricated group, derived from
    corpus_manifest.csv's free-text `notes` column (there is no dedicated
    structured field for fabrication style/level -- disclosed explicitly
    in the report rather than silently presented as a clean category)."""
    if not isinstance(notes, str):
        return "unknown"
    n = notes.lower()
    if "naive" in n:
        return "naive"
    if "sophisticated" in n:
        return "sophisticated"
    return "other/unspecified"


def build_matrix(df: pd.DataFrame, group_col: str = "group", decision_col: str = "decision") -> pd.DataFrame:
    rows = []
    for g in [x for x in GROUPS_ORDER if x in df[group_col].unique()]:
        sub = df[df[group_col] == g]
        n = len(sub)
        row = {"group": g, "n": n}
        for d in DECISIONS_ORDER:
            k = int((sub[decision_col] == d).sum())
            row[f"{d}_k"] = k
            row[f"{d}_rate"] = k / n if n else float("nan")
            lo, hi = ac.wilson_ci(k, n)
            row[f"{d}_ci_lo"] = lo
            row[f"{d}_ci_hi"] = hi
        k_ho = int(sub["hard_override_fired"].fillna(False).astype(bool).sum())
        row["hard_override_k"] = k_ho
        row["hard_override_rate"] = k_ho / n if n else float("nan")
        lo, hi = ac.wilson_ci(k_ho, n)
        row["hard_override_ci_lo"] = lo
        row["hard_override_ci_hi"] = hi
        rows.append(row)
    return pd.DataFrame(rows)


def fmt_matrix_text(mat: pd.DataFrame) -> str:
    lines = []
    header = f"{'group':<22s} {'n':>5s} " + " ".join(f"{d:>28s}" for d in DECISIONS_ORDER) + f" {'hard_override':>28s}"
    lines.append(header)
    lines.append("-" * len(header))
    for _, r in mat.iterrows():
        cells = []
        for d in DECISIONS_ORDER:
            cells.append(ac.fmt_rate_ci(int(r[f"{d}_k"]), int(r["n"])).rjust(28))
        ho_cell = ac.fmt_rate_ci(int(r["hard_override_k"]), int(r["n"])).rjust(28)
        lines.append(f"{r['group']:<22s} {int(r['n']):>5d} " + " ".join(cells) + f" {ho_cell}")
    return "\n".join(lines)


def main() -> None:
    include_adv = ac.ADVERSARIAL_SCORE_MATRIX_PATH.exists()
    df = ac.load_corpus(include_adversarial=True)
    t_d = ac.composite_score(df, ac.AXIS_WEIGHTS, ac.WITHIN)
    df = df.copy()
    df["T_D"] = t_d
    df["decision_ungated"] = ac.assign_decision(t_d, df["hard_override_fired"])
    try:
        df["decision"] = ac.assign_decision_gated(df, t_d)
        gated_available = True
    except KeyError as e:
        print(f"WARNING: {e}", file=sys.stderr)
        df["decision"] = df["decision_ungated"]
        gated_available = False

    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("Group B2: Three-way decision confusion matrix")
    report_lines.append("(Group B post-hoc verification analysis)")
    report_lines.append("=" * 100)
    report_lines.append("")
    report_lines.append(f"T(D) and decision computed LIVE via current production weights "
                         f"(WEIGHT_VARIANTS['blended_current']), not read from score_matrix.csv's "
                         f"cached columns -- see _analysis_common.py's LEGACY_STALE_COLUMNS note.")
    report_lines.append("")
    if gated_available:
        report_lines.append(
            "GATE-AWARENESS (2026-07-21): 'decision' below is the REAL, fully-gated "
            "production decision (Stage 1 hard override + Stage 2 thresholds + "
            "min_evidence_coverage/min_sample_sufficiency safety gates + "
            "min_n_records_for_admit/min_applicable_subtests_for_admit ADMIT-eligibility "
            "floors -- exactly what DataCertifyAuditor.audit() actually returns). "
            "'decision_ungated' is the ORIGINAL Stage-1+2-threshold-only logic this report "
            "used exclusively before this date, kept for direct before/after comparison, "
            "NOT as an equally-valid alternative reading -- 'decision' is the one that "
            "matches real production behavior. See CHANGELOG.md's 2026-07-21 entry."
        )
    else:
        report_lines.append(
            "*** WARNING: score_matrix.csv predates the 2026-07-21 gate-awareness fix "
            "(missing evidence_coverage/sample_sufficiency/n_applicable_subtests columns) "
            "-- 'decision' below falls back to Stage-1+2-threshold-only logic, identical "
            "to 'decision_ungated'. Re-run calibration/run_scoring.py (and "
            "calibration/score_adversarial_holdout.py) to regenerate score_matrix.csv "
            "with the columns needed for a real gate-aware report before trusting the "
            "numbers below as representative of production behavior. ***"
        )
    report_lines.append("")
    if not include_adv:
        report_lines.append(
            "*** NOTE: score_matrix_adversarial_holdout.csv not found -- the "
            "held_out_adversarial group is EXCLUDED from this report. Run "
            "calibration/score_adversarial_holdout.py first (Group B1) and "
            "re-run this script to include it. ***"
        )
        report_lines.append("")

    # ---- Main matrix (gated -- the real production decision) ----
    main_mat = build_matrix(df, decision_col="decision")
    report_lines.append("--- Overall matrix: group x decision (Wilson 95% CI) -- GATED (real production) ---")
    report_lines.append(fmt_matrix_text(main_mat))
    report_lines.append("")
    main_mat.to_csv(OUT_DIR / "three_way_matrix_main.csv", index=False)

    # ---- Same matrix under the ORIGINAL ungated (Stage-1+2-only) logic, for
    # direct before/after comparison -- this is the exact table this report
    # used to publish as its ONLY matrix; kept so the size of the gate's
    # effect is visible in the report itself, not just in CHANGELOG.md. ----
    main_mat_ungated = build_matrix(df, decision_col="decision_ungated")
    report_lines.append(
        "--- Same matrix, UNGATED (Stage-1+2 threshold logic only -- the ORIGINAL "
        "logic this report used exclusively before 2026-07-21; kept for comparison, "
        "NOT representative of real DataCertifyAuditor.audit() behavior) ---"
    )
    report_lines.append(fmt_matrix_text(main_mat_ungated))
    report_lines.append("")
    main_mat_ungated.to_csv(OUT_DIR / "three_way_matrix_main_ungated.csv", index=False)

    # ---- Headline false-admit / false-reject rates ----
    known_good = df[df["group"] == "known_good"]
    known_bad = df[df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"])]

    k_false_reject = int((known_good["decision"] == "REJECT").sum())
    n_known_good = len(known_good)
    k_false_admit = int((known_bad["decision"] == "ADMIT").sum())
    n_known_bad = len(known_bad)
    k_false_conditional_or_admit = int((known_bad["decision"] != "REJECT").sum())
    k_known_good_admit = int((known_good["decision"] == "ADMIT").sum())

    k_false_admit_ungated = int((known_bad["decision_ungated"] == "ADMIT").sum())
    k_false_reject_ungated = int((known_good["decision_ungated"] == "REJECT").sum())
    k_known_good_admit_ungated = int((known_good["decision_ungated"] == "ADMIT").sum())

    report_lines.append("--- Headline rates (GATED -- real production behavior) ---")
    report_lines.append(
        f"False-reject rate on known_good (n={n_known_good}): "
        f"{ac.fmt_rate_ci(k_false_reject, n_known_good)}"
    )
    report_lines.append(
        f"False-admit rate on known_bad, pooled corrupted+fabricated"
        f"{'+held_out_adversarial' if include_adv else ''} (n={n_known_bad}): "
        f"{ac.fmt_rate_ci(k_false_admit, n_known_bad)}"
    )
    report_lines.append(
        f"known_good ADMIT rate (n={n_known_good}): "
        f"{ac.fmt_rate_ci(k_known_good_admit, n_known_good)}"
    )
    report_lines.append(
        f"NOT-rejected rate (ADMIT or CONDITIONAL) on known_bad (n={n_known_bad}): "
        f"{ac.fmt_rate_ci(k_false_conditional_or_admit, n_known_bad)}"
    )
    report_lines.append(
        "Note: CONDITIONAL is a 'flag for manual review' outcome, not an "
        "autonomous acceptance -- the false-admit rate above (ADMIT only) is "
        "the safety-critical number; the NOT-rejected rate is a looser upper "
        "bound useful for gauging analyst review burden."
    )
    report_lines.append("")
    report_lines.append(
        "--- Same headline rates, UNGATED (Stage-1+2 threshold logic only -- "
        "for comparison; NOT what a real DataCertifyAuditor.audit() user "
        "experiences) ---"
    )
    report_lines.append(
        f"False-reject rate on known_good (n={n_known_good}): "
        f"{ac.fmt_rate_ci(k_false_reject_ungated, n_known_good)}"
    )
    report_lines.append(
        f"False-admit rate on known_bad (n={n_known_bad}): "
        f"{ac.fmt_rate_ci(k_false_admit_ungated, n_known_bad)}"
    )
    report_lines.append(
        f"known_good ADMIT rate (n={n_known_good}): "
        f"{ac.fmt_rate_ci(k_known_good_admit_ungated, n_known_good)}"
    )
    report_lines.append("")

    # ---- Breakdown by corruption_type (corrupted_real only -- fabricated
    # datasets are all labeled corruption_type='full_fabrication' in the
    # manifest, uninformative on its own; see fabrication_style breakdown
    # below instead) ----
    corrupted = df[df["group"] == "corrupted_real"].copy()
    by_ctype_rows = []
    for ctype in sorted(corrupted["corruption_type"].dropna().unique()):
        sub = corrupted[corrupted["corruption_type"] == ctype]
        n = len(sub)
        row = {"corruption_type": ctype, "n": n}
        for d in DECISIONS_ORDER:
            k = int((sub["decision"] == d).sum())
            row[f"{d}_k"] = k
            row[f"{d}_rate"] = k / n if n else float("nan")
        by_ctype_rows.append(row)
    by_ctype = pd.DataFrame(by_ctype_rows)
    by_ctype.to_csv(OUT_DIR / "three_way_matrix_by_corruption_type.csv", index=False)

    report_lines.append("--- corrupted_real, broken down by corruption_type (GATED decision) ---")
    report_lines.append(by_ctype.to_string(index=False))
    report_lines.append("")

    # Also break down corrupted_real by severity (low/med/high)
    by_severity_rows = []
    for sev in ["low", "med", "high"]:
        sub = corrupted[corrupted["severity"] == sev]
        n = len(sub)
        if n == 0:
            continue
        row = {"severity": sev, "n": n}
        for d in DECISIONS_ORDER:
            k = int((sub["decision"] == d).sum())
            row[f"{d}_k"] = k
            row[f"{d}_rate"] = round(k / n, 4) if n else float("nan")
        by_severity_rows.append(row)
    by_severity = pd.DataFrame(by_severity_rows)
    report_lines.append("--- corrupted_real, broken down by severity (GATED decision) ---")
    report_lines.append(by_severity.to_string(index=False))
    report_lines.append("")

    # ---- Breakdown by fabrication style (naive vs sophisticated, text-derived) ----
    fabricated = df[df["group"] == "fabricated"].copy()
    fabricated["fab_style"] = fabricated["notes"].apply(fabrication_style)
    by_style_rows = []
    for style in sorted(fabricated["fab_style"].unique()):
        sub = fabricated[fabricated["fab_style"] == style]
        n = len(sub)
        row = {"fabrication_style": style, "n": n}
        for d in DECISIONS_ORDER:
            k = int((sub["decision"] == d).sum())
            row[f"{d}_k"] = k
            row[f"{d}_rate"] = round(k / n, 4) if n else float("nan")
        by_style_rows.append(row)
    by_style = pd.DataFrame(by_style_rows)
    report_lines.append(
        "--- fabricated, broken down by fabrication style (GATED decision; DERIVED from "
        "corpus_manifest.csv's free-text `notes` column via substring match "
        "on 'naive'/'sophisticated' -- NOT a structured field; treat as "
        "indicative, not authoritative) ---"
    )
    report_lines.append(by_style.to_string(index=False))
    report_lines.append("")

    # ---- Breakdown by n_records bucket, across all groups ----
    df["n_records_bucket"] = df["n_records"].apply(bucket_n_records)
    by_bucket_rows = []
    bucket_labels = [b[2] for b in N_RECORDS_BUCKETS]
    for g in [x for x in GROUPS_ORDER if x in df["group"].unique()]:
        for bucket in bucket_labels:
            sub = df[(df["group"] == g) & (df["n_records_bucket"] == bucket)]
            n = len(sub)
            if n == 0:
                continue
            row = {"group": g, "n_records_bucket": bucket, "n": n}
            for d in DECISIONS_ORDER:
                k = int((sub["decision"] == d).sum())
                row[f"{d}_k"] = k
                row[f"{d}_rate"] = round(k / n, 4) if n else float("nan")
            by_bucket_rows.append(row)
    by_bucket = pd.DataFrame(by_bucket_rows)
    by_bucket.to_csv(OUT_DIR / "three_way_matrix_by_n_records_bucket.csv", index=False)

    report_lines.append("--- All groups, broken down by n_records bucket (GATED decision) ---")
    report_lines.append(by_bucket.to_string(index=False))
    report_lines.append("")

    report_text = "\n".join(report_lines)
    print(report_text)
    (OUT_DIR / "three_way_matrix_report.txt").write_text(report_text, encoding="utf-8")
    print(f"\nReports written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
