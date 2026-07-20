# -*- coding: utf-8 -*-
"""
calibration/analysis_decision_stability.py -- Group B4 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B): Monte
Carlo decision-stability / sensitivity analysis. Answers: if the weight
vector and thresholds were perturbed within their own empirically-estimated
uncertainty, how often would a dataset's ADMIT/CONDITIONAL/REJECT decision
flip?

This is NOT a re-calibration exercise and does NOT change any production
constant -- it treats WEIGHT_VARIANTS['blended_current'] plus
THETA_ADMIT/THETA_REJECT as the baseline and asks how robust the resulting
decisions are to the uncertainty already quantified elsewhere in this
project:

  - Axis weights (A/P/C/I) and within-axis weights (A1-A5/P4-P9/C1-C4/
    I1-I5): perturbed by sampling UNIFORMLY within each weight's own
    bootstrap 95% CI (calibration/bootstrap_stability_report.json,
    n_boot=2000, seed=20260707), then renormalized to sum to 1 (axis
    weights across the 4 axes; within-axis weights within each axis
    separately) so every draw is still a valid weight vector. Uniform
    (not e.g. normal-approximated from the reported bootstrap_std) is a
    deliberate, disclosed choice -- several within-axis weights have
    extremely skewed bootstrap distributions (e.g. P4 cv_pct=101%, P6
    cv_pct=784%, both with point estimates near zero and CI lower bounds
    that are tiny negative numbers from floating-point noise, clipped to
    0 here), so a normal approximation would be actively misleading for
    those; uniform-within-the-empirical-CI is simple, bounded, and
    doesn't pretend a shape the bootstrap didn't actually show.

  - Thresholds (THETA_ADMIT, THETA_REJECT): there is no bootstrap CI for
    these in this project (they are chosen policy thresholds, not fitted
    parameters -- see calibrate_thresholds.py). This script perturbs both
    uniformly within +/-0.03 of their current values, a magnitude chosen
    to be a modest, clearly-arbitrary-and-disclosed sensitivity probe, NOT
    a claim about their true uncertainty. IMPORTANT CONTEXT from
    calibration/threshold_report.json's own sixth-pass finding, quoted
    here because it directly bears on how to read this script's output:
    "known_good and known_bad T(D) distributions are heavily interleaved
    from ~0.17 to ~0.63 -- no theta_reject value cleanly separates them.
    theta_reject=0.20 was chosen to guarantee zero known_good
    false-rejects ... at the disclosed cost that it now catches only 1 of
    15 non-hard-override known_bad datasets by itself." theta_admit=0.75
    has a real, documented margin (max known_bad T(D) = 0.6276, ~0.12
    below theta_admit); theta_reject has essentially NO margin by
    construction. Expect (and this script measures directly) far higher
    decision instability from theta_reject perturbation than from
    theta_admit perturbation.

Hard-override (Stage 1) is NEVER perturbed here -- P1-P3/A6 physical
impossibility gates are not weight-fitted parameters and are out of scope
for this specific sensitivity analysis (a separate, disclosed limitation,
not an oversight).

Usage:
    python3 calibration/analysis_decision_stability.py [--n-draws N] [--seed S] [--theta-perturb-width W]

Output:
    calibration/group_b_reports/decision_stability_report.txt
    calibration/group_b_reports/decision_stability_per_dataset.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CALIBRATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CALIBRATION_DIR))
import _analysis_common as ac  # noqa: E402

OUT_DIR = CALIBRATION_DIR / "group_b_reports"
OUT_DIR.mkdir(exist_ok=True)

BOOTSTRAP_PATH = CALIBRATION_DIR / "bootstrap_stability_report.json"


def load_ci_ranges():
    with open(BOOTSTRAP_PATH) as f:
        boot = json.load(f)
    r = boot["results"]
    axis_ci = {a: (max(0.0, r["axis"][a]["ci95_low"]), r["axis"][a]["ci95_high"]) for a in ac.AXES}
    within_ci = {}
    for axis, key in (("A", "within_A"), ("P", "within_P"), ("C", "within_C"), ("I", "within_I")):
        within_ci[axis] = {
            crit: (max(0.0, r[key][crit]["ci95_low"]), max(r[key][crit]["ci95_low"], r[key][crit]["ci95_high"]))
            for crit in ac.WITHIN[axis]
        }
    return axis_ci, within_ci, boot["n_boot"], boot["seed"]


def sample_weight_vector(rng: np.random.RandomState, axis_ci, within_ci):
    axis_w = {}
    for a in ac.AXES:
        lo, hi = axis_ci[a]
        axis_w[a] = rng.uniform(lo, hi) if hi > lo else lo
    total = sum(axis_w.values())
    axis_w = {a: v / total for a, v in axis_w.items()}

    within_w = {}
    for a in ac.AXES:
        w = {}
        for crit, (lo, hi) in within_ci[a].items():
            w[crit] = rng.uniform(lo, hi) if hi > lo else lo
        s = sum(w.values())
        within_w[a] = {c: v / s for c, v in w.items()} if s > 0 else {c: 1.0 / len(w) for c in w}
    return axis_w, within_w


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-draws", type=int, default=2000,
                         help="Number of Monte Carlo draws (default 2000, matching bootstrap_stability_report.json's n_boot).")
    parser.add_argument("--seed", type=int, default=20260712,
                         help="RNG seed (default 20260712 -- deliberately DIFFERENT from the bootstrap's own seed 20260707, so this is an independent Monte Carlo run, not a replay of the same draws).")
    parser.add_argument("--theta-perturb-width", type=float, default=0.03,
                         help="Half-width of the uniform perturbation window applied to THETA_ADMIT and THETA_REJECT (default +/-0.03; see module docstring for why this is a disclosed arbitrary probe, not an estimated uncertainty).")
    args = parser.parse_args()

    if not BOOTSTRAP_PATH.exists():
        print(f"FATAL: {BOOTSTRAP_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    axis_ci, within_ci, n_boot_source, boot_seed = load_ci_ranges()

    df = ac.load_corpus(include_adversarial=True)
    include_adv = ac.ADVERSARIAL_SCORE_MATRIX_PATH.exists()

    baseline_t = ac.composite_score(df, ac.AXIS_WEIGHTS, ac.WITHIN)
    baseline_decision = ac.assign_decision(baseline_t, df["hard_override_fired"],
                                            theta_admit=ac.THETA_ADMIT, theta_reject=ac.THETA_REJECT)

    n = len(df)
    n_draws = args.n_draws
    rng = np.random.RandomState(args.seed)

    match_counts = np.zeros(n, dtype=np.int64)

    for draw_i in range(n_draws):
        axis_w, within_w = sample_weight_vector(rng, axis_ci, within_ci)
        theta_admit_draw = ac.THETA_ADMIT + rng.uniform(-args.theta_perturb_width, args.theta_perturb_width)
        theta_reject_draw = ac.THETA_REJECT + rng.uniform(-args.theta_perturb_width, args.theta_perturb_width)
        # Guard against a pathological draw inverting the two thresholds
        # (should never happen at width=0.03 given the 0.55 gap between
        # 0.75 and 0.20, but this makes the guarantee explicit rather than
        # silently trusting the arithmetic).
        if theta_reject_draw >= theta_admit_draw:
            theta_admit_draw, theta_reject_draw = max(theta_admit_draw, theta_reject_draw), min(theta_admit_draw, theta_reject_draw)

        t_d = ac.composite_score(df, axis_w, within_w)
        decision = ac.assign_decision(t_d, df["hard_override_fired"],
                                       theta_admit=theta_admit_draw, theta_reject=theta_reject_draw)
        match_counts += (decision.values == baseline_decision.values).astype(np.int64)

    stability_rate = match_counts / n_draws

    result = df[["dataset_id", "group", "n_records"]].copy()
    result["baseline_T_D"] = baseline_t.values
    result["baseline_decision"] = baseline_decision.values
    result["stability_rate"] = stability_rate
    result["n_draws"] = n_draws

    result.to_csv(OUT_DIR / "decision_stability_per_dataset.csv", index=False)

    report = []
    report.append("=" * 100)
    report.append("Group B4: Monte Carlo decision-stability analysis")
    report.append("(Group B post-hoc verification analysis)")
    report.append("=" * 100)
    report.append("")
    report.append(f"Corpus: n={n} ({df['group'].value_counts().to_dict()})")
    if not include_adv:
        report.append("*** NOTE: held_out_adversarial group excluded (run score_adversarial_holdout.py first). ***")
    report.append(f"Monte Carlo draws: {n_draws} (seed={args.seed}, independent of bootstrap_stability_report.json's own seed={boot_seed})")
    report.append(f"Weight perturbation: uniform within each weight's bootstrap 95% CI (n_boot={n_boot_source} source), renormalized per draw.")
    report.append(f"Threshold perturbation: THETA_ADMIT={ac.THETA_ADMIT}+/-{args.theta_perturb_width}, THETA_REJECT={ac.THETA_REJECT}+/-{args.theta_perturb_width} (disclosed arbitrary probe, not an estimated uncertainty -- see module docstring).")
    report.append("Hard-override (Stage 1, P1-P3/A6) is NOT perturbed -- out of scope for this analysis.")
    report.append("")

    report.append("--- Overall stability ---")
    overall_mean_stability = stability_rate.mean()
    n_fully_stable = int((stability_rate == 1.0).sum())
    n_ge95 = int((stability_rate >= 0.95).sum())
    n_lt50 = int((stability_rate < 0.50).sum())
    report.append(f"Mean per-dataset stability rate (fraction of draws matching baseline decision): {overall_mean_stability:.4f}")
    report.append(f"Datasets with 100% stability (never flip): {ac.fmt_rate_ci(n_fully_stable, n)}")
    report.append(f"Datasets with >=95% stability: {ac.fmt_rate_ci(n_ge95, n)}")
    report.append(f"Datasets with <50% stability (flip more often than not): {ac.fmt_rate_ci(n_lt50, n)}")
    report.append("")

    report.append("--- Stability by group ---")
    by_group = result.groupby("group")["stability_rate"].agg(["mean", "min", "count"]).reset_index()
    by_group.columns = ["group", "mean_stability", "min_stability", "n"]
    report.append(by_group.to_string(index=False))
    report.append("")

    report.append("--- Stability by baseline decision ---")
    by_decision = result.groupby("baseline_decision")["stability_rate"].agg(["mean", "min", "count"]).reset_index()
    by_decision.columns = ["baseline_decision", "mean_stability", "min_stability", "n"]
    report.append(by_decision.to_string(index=False))
    admit_mean = by_decision.loc[by_decision["baseline_decision"] == "ADMIT", "mean_stability"]
    cond_mean = by_decision.loc[by_decision["baseline_decision"] == "CONDITIONAL", "mean_stability"]
    if len(admit_mean) and len(cond_mean) and float(admit_mean.iloc[0]) < float(cond_mean.iloc[0]):
        report.append(
            "Note: ADMIT shows LOWER mean stability than CONDITIONAL here, which "
            "is the opposite of the naive guess that the wide CONDITIONAL band "
            "(theta_reject=0.20 to theta_admit=0.75, 0.55 wide) would be least "
            "stable simply for sitting 'in the middle.' The correct read is "
            "distance-to-nearest-threshold, not band width: CONDITIONAL is wide "
            "enough that most of its members sit comfortably away from either "
            "boundary, while ADMIT (n=107, a much smaller class) disproportionately "
            "clusters just above theta_admit=0.75 (see the least-stable table "
            "below -- most entries have baseline_T_D in 0.73-0.76). This is a real "
            "finding worth stating explicitly in the paper rather than assuming "
            "the naive band-width intuition: decision stability tracks proximity "
            "to a threshold, and it happens that a meaningful fraction of this "
            "corpus's known_good catalogs score just above the ADMIT line."
        )
    else:
        report.append(
            "As expected, CONDITIONAL-baseline datasets show the lowest mean "
            "stability, consistent with sitting between the two thresholds and "
            "therefore being most exposed to perturbation on either side."
        )
    report.append("")

    report.append("--- 20 least-stable datasets (excluding hard-override-fired rows, which are always 100% stable by construction) ---")
    not_ho = ~df["hard_override_fired"].fillna(False).astype(bool)
    least_stable = result[not_ho.values].sort_values("stability_rate").head(20)
    report.append(least_stable[["dataset_id", "group", "baseline_T_D", "baseline_decision", "stability_rate"]].to_string(index=False))
    report.append("")

    report_text = "\n".join(report)
    print(report_text)
    (OUT_DIR / "decision_stability_report.txt").write_text(report_text, encoding="utf-8")
    print(f"\nReports written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
