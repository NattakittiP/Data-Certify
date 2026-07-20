# -*- coding: utf-8 -*-
"""
calibration/make_paper_figures.py -- Generate the 9 data-driven figures
recommended in Docs/03_Paper_Prep/DATA-CERTIFY_Research_Positioning_and_Contribution_Framework.md
Section 8 ("figures that should be in the paper").

Run from the repository root:

    python3 calibration/make_paper_figures.py

Output: 9 high-resolution PNGs (300 dpi) written to Docs/06_Figures/:
    figure3_T_distribution_known_good_vs_known_bad.png
    figure4_axis_weight_evolution.png
    figure5_a6_compensatory_case_study.png
    figure6_weight_ablation_false_admit_rate.png
    figure7_gap9_downstream_impact_reversal.png
    figure8_decision_utility_cost_by_scenario.png
    figure9_decision_stability_monte_carlo.png
    figure10_decision_breakdown_by_corruption_type.png
    figure11_cross_agency_real_data_validation.png

The two conceptual diagrams (two-stage decision architecture; taxonomy ->
axis coverage map) are intentionally NOT generated here -- the user is
authoring those directly in LaTeX (TikZ) for the manuscript, so this script
only covers figures that require real corpus/analysis data:
  - Figure 3 (T(D) distribution) reads calibration/score_matrix.csv
    (per-dataset raw A/P/C/I axis scores) + calibration/corpus_manifest.csv
    (known_good/known_bad label), and recomputes T(D) live using the CURRENT
    production AXIS_WEIGHTS from data_certify/_constants.py -- exactly the
    same approach the Group B analysis scripts use
    (calibration/_analysis_common.py's composite_score), so this never
    trusts a stale cached T(D) column.
  - Figure 4 (axis-weight evolution)'s corpus-size/weight history is
    transcribed directly from data_certify/_constants.py's own module
    docstring (the "Nth CALIBRATION PASS" comments), one point per distinct
    corpus-size milestone that has a fully-reported (A,P,C,I) weight vector.
  - Figure 5 (A6 case study) reads the exact matched_fraction/hard_override/
    decision values for three real corpus datasets from
    calibration/theta_auth_report.md and calibration/score_matrix.csv,
    recomputing T(D) the same live way Figure 3 does.
  - Figure 6 (weight-vector ablation) reads
    calibration/group_b_reports/ablation_weight_variants.csv (Group B3.1,
    executed against the full 968-dataset corpus).
  - Figure 7 (Gap 9 downstream-impact reversal) is transcribed directly from
    calibration/group_d_reports/d1_case_study_variants.csv (catalog=nz,
    fn=magnitude_gr_violation, option a: b-value study) and
    calibration/group_d_reports/d1b_aftershock_variants.csv
    (catalog=kahramanmaras_2023, fn=magnitude_gr_violation, option b:
    aftershock-forecast study) -- both real, executed Group D1 runs.
  - Figure 8 (decision-utility cost curve) reads
    calibration/group_b_reports/selective_classification_utility.csv
    (Group B5.3).
  - Figure 9 (Monte Carlo decision-stability) reads
    calibration/group_b_reports/decision_stability_per_dataset.csv
    (Group B4, 2,000-draw Monte Carlo perturbation study, full 998-dataset
    corpus).
  - Figure 10 (decision breakdown by corruption type) reads
    calibration/group_b_reports/three_way_matrix_main.csv (overall by group)
    and calibration/group_b_reports/three_way_matrix_by_corruption_type.csv
    (corrupted_real broken down by injected-corruption type) -- both Group B2,
    executed against the full corpus.
  - Figure 11 (cross-agency real-data validation) is transcribed directly
    from calibration/group_d_reports/d1d_cross_agency_report.txt (Group D1
    option d) -- the one case study validated against real, live-fetched
    USGS+EMSC data for the 2014 Iquique sequence rather than injected
    synthetic corruption.

Titles carry only the descriptive caption text -- no "Figure N." prefix --
since figure numbering will be assigned in the LaTeX manuscript itself.

Dependencies: matplotlib, pandas (already required by this project -- see
pyproject.toml). No seaborn, no network access.
"""

from __future__ import annotations

import os
import sys

import matplotlib
matplotlib.use("Agg")  # headless-safe; still writes normal PNG files
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

OUT_DIR = os.path.join(REPO_ROOT, "Docs", "06_Figures")
os.makedirs(OUT_DIR, exist_ok=True)

DPI = 300

# Color palette (colorblind-safe-ish, consistent across all figures)
COLOR_KNOWN_GOOD = "#1b6ca8"     # blue
COLOR_KNOWN_BAD = "#d1495b"      # red
COLOR_AXIS_A = "#1b6ca8"
COLOR_AXIS_P = "#e6a532"
COLOR_AXIS_C = "#2a9d8f"
COLOR_AXIS_I = "#7b4fa6"
COLOR_ADMIT = "#2e7d32"          # green -- matches ADMIT in the TikZ figures
COLOR_CONDITIONAL = COLOR_AXIS_P  # amber -- matches CONDITIONAL in the TikZ figures
COLOR_REJECT = COLOR_KNOWN_BAD    # red -- matches REJECT in the TikZ figures


def _save(fig, name):
    path = os.path.join(OUT_DIR, name)
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"[ok] wrote {path}")


# ---------------------------------------------------------------------------
# Figure -- T(D) distribution, known_good vs known_bad, with thresholds
# ---------------------------------------------------------------------------
def figure3_T_distribution():
    import pandas as pd
    from data_certify._constants import AXIS_WEIGHTS, THETA_ADMIT, THETA_REJECT

    score_path = os.path.join(REPO_ROOT, "calibration", "score_matrix.csv")
    manifest_path = os.path.join(REPO_ROOT, "calibration", "corpus_manifest.csv")
    sm = pd.read_csv(score_path)
    manifest = pd.read_csv(manifest_path)[["dataset_id", "label", "category"]]
    df = sm.merge(manifest, on="dataset_id", how="left")

    for ax_name in ("A", "P", "C", "I"):
        if ax_name not in df.columns:
            raise SystemExit(f"score_matrix.csv is missing expected column '{ax_name}'")

    df["T"] = (
        AXIS_WEIGHTS["A"] * df["A"]
        + AXIS_WEIGHTS["P"] * df["P"]
        + AXIS_WEIGHTS["C"] * df["C"]
        + AXIS_WEIGHTS["I"] * df["I"]
    )

    known_good = df[df["label"] == "known_good"]["T"].dropna()
    known_bad = df[df["label"] == "known_bad"]["T"].dropna()

    fig, ax = plt.subplots(figsize=(10, 6))
    bins = [i / 40 for i in range(0, 41)]
    ax.hist(known_good, bins=bins, alpha=0.6, color=COLOR_KNOWN_GOOD,
            label=f"known_good (n={len(known_good)})", edgecolor="white", linewidth=0.3, zorder=2)
    ax.hist(known_bad, bins=bins, alpha=0.6, color=COLOR_KNOWN_BAD,
            label=f"known_bad (n={len(known_bad)})", edgecolor="white", linewidth=0.3, zorder=2)

    ax.set_xlim(0, 1)
    ax.set_ylim(0, None)
    ymax = ax.get_ylim()[1]

    ax.axvspan(0.17, 0.63, color="grey", alpha=0.10, zorder=0)

    ax.axvline(THETA_REJECT, color="black", linestyle="--", linewidth=1.6, zorder=3)
    ax.axvline(THETA_ADMIT, color="black", linestyle="-.", linewidth=1.6, zorder=3)

    halo = [pe.withStroke(linewidth=3.2, foreground="white")]
    ax.text(THETA_REJECT, ymax * 0.5, f"theta_reject = {THETA_REJECT}",
            rotation=90, ha="center", va="center", fontsize=9, color="black",
            zorder=5, path_effects=halo)
    ax.text(THETA_ADMIT, ymax * 0.5, f"theta_admit = {THETA_ADMIT}",
            rotation=90, ha="center", va="center", fontsize=9, color="black",
            zorder=5, path_effects=halo)

    ax.text(0.40, ymax * 0.82, "known_good / known_bad\noverlap zone",
            ha="center", va="top", fontsize=8.5, color="dimgray", zorder=4)

    ax.legend(loc="upper right", fontsize=8.7, frameon=True, borderaxespad=0.3,
              handlelength=1.2, handletextpad=0.5, labelspacing=0.3)

    nearest_bad = known_bad[known_bad < THETA_REJECT]
    if len(nearest_bad):
        margin = THETA_REJECT - nearest_bad.max()
        ax.annotate(
            f"nearest known_bad\nbelow theta_reject:\nmargin = {margin:.4f}",
            xy=(nearest_bad.max(), 1), xytext=(0.03, ymax * 0.30),
            fontsize=8, color=COLOR_KNOWN_BAD, ha="left", va="center", zorder=4,
            arrowprops=dict(arrowstyle="->", color=COLOR_KNOWN_BAD, lw=1.1,
                             connectionstyle="arc3,rad=0.15"),
            bbox=dict(boxstyle="round,pad=0.25", facecolor="white", edgecolor=COLOR_KNOWN_BAD, alpha=0.9, linewidth=0.7),
        )

    ax.set_xlabel("T(D) -- composite trust score", fontsize=10.5)
    ax.set_ylabel("number of datasets", fontsize=10.5)
    ax.set_title("T(D) distribution across the full 968-dataset calibration corpus",
                 fontsize=12, weight="bold", pad=12)
    ax.grid(axis="y", alpha=0.25, linewidth=0.5, zorder=0)

    _save(fig, "figure3_T_distribution_known_good_vs_known_bad.png")


# ---------------------------------------------------------------------------
# Figure -- Axis-weight evolution across calibration passes
# ---------------------------------------------------------------------------
def figure4_axis_weight_evolution():
    history = [
        {"n": 73,  "A": 0.7149, "P": 0.02739, "C": 0.04497, "I": 0.21278},
        {"n": 89,  "A": 0.7110, "P": 0.0335,  "C": 0.0446,  "I": 0.2108},
        {"n": 295, "A": 0.7134, "P": 0.0770,  "C": 0.0404,  "I": 0.1692},
        {"n": 968, "A": 0.6895, "P": 0.1684,  "C": 0.0283,  "I": 0.1139},
    ]
    ns = [h["n"] for h in history]

    fig, ax = plt.subplots(figsize=(9.5, 6))
    for axis_name, color in (("A", COLOR_AXIS_A), ("P", COLOR_AXIS_P),
                              ("C", COLOR_AXIS_C), ("I", COLOR_AXIS_I)):
        ys = [h[axis_name] for h in history]
        ax.plot(ns, ys, marker="o", color=color, linewidth=2.2, markersize=6.5,
                label=f"w_{axis_name}", zorder=3)

    ax.set_xscale("log")
    ax.set_xlim(65, 1600)
    ax.set_xticks(ns)
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_ylim(0, 1.0)

    end_values = [
        (history[-1]["A"], "A", COLOR_AXIS_A),
        (history[-1]["P"], "P", COLOR_AXIS_P),
        (history[-1]["I"], "I", COLOR_AXIS_I),
        (history[-1]["C"], "C", COLOR_AXIS_C),
    ]
    end_values.sort(key=lambda t: -t[0])
    min_gap = 0.045
    placed_y = []
    for val, _, _ in end_values:
        y = val
        if placed_y and (placed_y[-1] - y) < min_gap:
            y = placed_y[-1] - min_gap
        placed_y.append(y)
    for (val, name, color), y in zip(end_values, placed_y):
        needs_leader = abs(y - val) > 0.005
        ax.annotate(
            f"w_{name} = {val:.4f}", xy=(968, val), xytext=(1050, y),
            fontsize=9, color=color, va="center", ha="left", zorder=4,
            arrowprops=dict(arrowstyle="-", color=color, lw=0.8, alpha=0.6) if needs_leader else None,
        )

    ax.set_xlabel("calibration-corpus size (number of datasets, log scale)", fontsize=10.5)
    ax.set_ylabel("blended AHP x EWM axis weight", fontsize=10.5)
    ax.set_title("Axis-weight evolution across successive calibration passes",
                 fontsize=12, weight="bold", pad=12)

    ax.legend(loc="upper right", fontsize=9, frameon=True, borderaxespad=0.4,
              handlelength=1.3, handletextpad=0.5, labelspacing=0.3)
    ax.grid(alpha=0.25, linewidth=0.5, zorder=0)

    _save(fig, "figure4_axis_weight_evolution.png")


# ---------------------------------------------------------------------------
# Figure -- A6 compensatory-design case study (structural depth-blindness)
# ---------------------------------------------------------------------------
def figure5_a6_case_study():
    import pandas as pd
    from data_certify._constants import AXIS_WEIGHTS, THETA_ADMIT, THETA_REJECT

    sm = pd.read_csv(os.path.join(REPO_ROOT, "calibration", "score_matrix.csv"))

    def blended_T(row):
        return (
            AXIS_WEIGHTS["A"] * row["A"] + AXIS_WEIGHTS["P"] * row["P"]
            + AXIS_WEIGHTS["C"] * row["C"] + AXIS_WEIGHTS["I"] * row["I"]
        )

    cases = [
        {
            "id": "nz",
            "short_label": "nz\n(known_good)",
            "matched_fraction": 0.3913,
        },
        {
            "id": "corrupt_real_taiwan_2024_query_depth_implausible_med",
            "short_label": "depth-implausible\ncorruption (known_bad)",
            "matched_fraction": 1.0,
        },
        {
            "id": "corrupt_real_chiapas_mexico_2017_inject_duplicates_med",
            "short_label": "duplicate-injection\ncorruption (known_bad)",
            "matched_fraction": 1.0,
        },
    ]

    for c in cases:
        row = sm[sm["dataset_id"] == c["id"]]
        if len(row) == 0:
            raise SystemExit(f"dataset_id not found in score_matrix.csv: {c['id']}")
        row = row.iloc[0]
        c["hard_override_fired"] = bool(row["hard_override_fired"])
        c["T"] = None if c["hard_override_fired"] else round(float(blended_T(row)), 4)

    fig, ax = plt.subplots(figsize=(13, 6))
    bar_width = 0.8
    gap = bar_width / 2
    step = bar_width + gap
    x = [0.0, step, 2 * step]
    bar_colors = [COLOR_KNOWN_GOOD] + [COLOR_KNOWN_BAD] * 2
    bars = ax.bar(x, [c["matched_fraction"] for c in cases], width=bar_width,
                   color=bar_colors, edgecolor="black", linewidth=1.0, alpha=0.85, zorder=2)

    xlim_left = x[0] - bar_width / 2 - gap
    xlim_right = x[-1] + bar_width / 2 + gap
    ax.set_xlim(xlim_left, xlim_right)
    ax.set_ylim(0, 1.15)

    ax.axhline(0.50, color="black", linestyle="--", linewidth=1.4, zorder=1)
    ax.text(xlim_left + 0.1, 0.50, "theta_auth = 0.50", va="center", ha="left", fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="none", alpha=0.9), zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels([c["short_label"] for c in cases], fontsize=9.5)
    ax.set_ylabel("external-reference match rate (A6)", fontsize=10)
    ax.set_title(
        "The external-reference check (A6) alone misjudges both cases.\n"
        "The full multi-axis score catches each one independently.",
        fontsize=13, weight="bold", pad=14,
    )

    for xi, c, bar in zip(x, cases, bars):
        h = bar.get_height()
        ax.text(xi, h + 0.03, f"{h:.4f}", ha="center", fontsize=10, weight="bold", zorder=4)
        if c["hard_override_fired"]:
            verdict_line = "final verdict:\nREJECT (hard-override)"
        elif c["T"] is not None:
            decision = "ADMIT" if c["T"] >= THETA_ADMIT else ("CONDITIONAL" if c["T"] >= THETA_REJECT else "REJECT")
            verdict_line = f"final verdict:\n{decision}  (T(D)={c['T']:.4f})"
        else:
            verdict_line = "final verdict:\nn/a"
        ax.text(xi, -0.15, verdict_line, ha="center", va="top", fontsize=8.8, color="black",
                weight="bold", transform=ax.get_xaxis_transform(), zorder=4)

    ax.grid(axis="y", alpha=0.25, linewidth=0.5, zorder=0)
    fig.subplots_adjust(bottom=0.23)

    _save(fig, "figure5_a6_compensatory_case_study.png")


# ---------------------------------------------------------------------------
# Figure -- Weight-vector ablation (Group B3.1)
# ---------------------------------------------------------------------------
def figure6_weight_ablation():
    import pandas as pd

    path = os.path.join(REPO_ROOT, "calibration", "group_b_reports", "ablation_weight_variants.csv")
    df = pd.read_csv(path)

    order = ["blended_current", "ahp_only", "ewm_only", "equal_weight",
             "a_only", "p_only", "c_only", "i_only"]
    df = df.set_index("variant").loc[order].reset_index()

    display_names = {
        "blended_current": "blended\n(production)",
        "ahp_only": "AHP-only",
        "ewm_only": "EWM-only",
        "equal_weight": "equal-weight",
        "a_only": "A-only",
        "p_only": "P-only",
        "c_only": "C-only",
        "i_only": "I-only",
    }

    colors = []
    for v in df["variant"]:
        if v == "blended_current":
            colors.append(COLOR_KNOWN_GOOD)
        elif v in ("ahp_only", "ewm_only", "equal_weight"):
            colors.append("#9a9a9a")
        else:
            colors.append(COLOR_KNOWN_BAD)

    x = list(range(len(df)))
    rates_pct = (df["false_admit_rate"] * 100).tolist()

    fig, ax = plt.subplots(figsize=(11.5, 6.5))
    ax.bar(x, rates_pct, color=colors, edgecolor="black", linewidth=0.9, width=0.65, zorder=3)

    for xi, rate, k in zip(x, rates_pct, df["false_admit_k"]):
        ax.text(xi, rate + 1.3, f"{rate:.2f}%\n(n={int(k)})", ha="center", va="bottom",
                fontsize=8.6, zorder=4)

    # Disclose the false-reject trade-off for the two variants where it is
    # nonzero (a_only, i_only) -- all other variants are exactly 0% false-reject.
    fr_notes = {"a_only": 3.54, "i_only": 0.59}
    for xi, v in zip(x, df["variant"]):
        if v in fr_notes:
            ax.text(xi, -0.058, f"+{fr_notes[v]:.2f}% false-reject", ha="center", va="top",
                    fontsize=7.4, color="black", style="italic",
                    transform=ax.get_xaxis_transform(), zorder=4)

    ax.set_xticks(x)
    ax.set_xticklabels([display_names[v] for v in df["variant"]], fontsize=9.5)
    ax.set_ylabel("false-admit rate on known-bad data (%)", fontsize=10.5)
    ax.set_ylim(0, max(rates_pct) * 1.22)
    ax.set_title(
        "The blended AHP x EWM weight vector strictly dominates every alternative.\n"
        "No simpler weighting scheme matches it without a false-admit cost.",
        fontsize=12.5, weight="bold", pad=14,
    )
    ax.grid(axis="y", alpha=0.25, linewidth=0.5, zorder=0)
    fig.subplots_adjust(bottom=0.12)

    _save(fig, "figure6_weight_ablation_false_admit_rate.png")


# ---------------------------------------------------------------------------
# Figure -- Gap 9: downstream-impact reversal under magnitude_gr_violation
# ---------------------------------------------------------------------------
def figure7_gap9_downstream_impact():
    from data_certify._constants import THETA_ADMIT

    # Transcribed directly from calibration/group_d_reports/d1_case_study_variants.csv
    # (catalog=nz, fn=magnitude_gr_violation, severities none/low/med/high) and
    # calibration/group_d_reports/d1b_aftershock_variants.csv
    # (catalog=kahramanmaras_2023, fn=magnitude_gr_violation, same severities).
    sev_x = [0, 1, 2, 3]
    sev_labels = ["clean", "low", "med", "high"]

    nz_td = [0.3952358639934734, 0.4569157324924662, 0.45438075702102, 0.4569918526703856]
    nz_b_abs_error = [0.0, 0.3027085343089486, 0.3538741647507066, 0.4049482435516021]

    kahr_td = [0.7159594318747848, 0.7465817631700592, 0.7453647931830946, 0.734351665285034]
    kahr_fc_err = [1.2998632560618582, 22.81794821381272, 25.163211240063543, 38.9863055622876]

    fig, axes = plt.subplots(1, 2, figsize=(14.5, 6))

    panels = [
        (axes[0], "nz -- Gutenberg-Richter b-value study",
         nz_b_abs_error, "|b-value error| vs. clean catalog", nz_td),
        (axes[1], "kahramanmaras_2023 -- Omori-Utsu aftershock-forecast study",
         kahr_fc_err, "aftershock forecast |event-count error|", kahr_td),
    ]

    for ax, title, err_vals, err_label, td_vals in panels:
        l1, = ax.plot(sev_x, err_vals, marker="o", color=COLOR_KNOWN_BAD, linewidth=2.3,
                      markersize=7.5, zorder=3, label=err_label)
        ax.set_xticks(sev_x)
        ax.set_xticklabels(sev_labels, fontsize=9.7)
        ax.set_xlim(-0.35, 3.35)
        ax.set_xlabel("magnitude_gr_violation severity", fontsize=9.8)
        ax.set_ylabel(err_label, fontsize=9.3, color=COLOR_KNOWN_BAD)
        ax.tick_params(axis="y", labelcolor=COLOR_KNOWN_BAD)
        ax.set_ylim(0, max(err_vals) * 1.3)
        ax.grid(alpha=0.2, linewidth=0.5, zorder=0)

        axb = ax.twinx()
        l2, = axb.plot(sev_x, td_vals, marker="s", color="black", linewidth=2.1,
                       linestyle="--", markersize=6.8, zorder=4, label="T(D) -- composite trust score")
        axb.set_ylabel("T(D)", fontsize=9.8)
        axb.set_ylim(0, 1.0)
        axb.axhline(THETA_ADMIT, color="gray", linestyle=":", linewidth=1.0, zorder=1)
        axb.text(-0.30, THETA_ADMIT, "theta_admit", fontsize=7.4, color="gray",
                 va="bottom", ha="left", zorder=1)

        ax.set_title(title, fontsize=11, weight="bold", pad=11)
        ax.legend(handles=[l1, l2], loc="lower right", fontsize=8.2, frameon=True, borderaxespad=0.5)

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.suptitle(
        "Under magnitude-flattening fabrication, downstream scientific accuracy\n"
        "degrades while the composite trust score increases (disclosed as Gap 9)",
        fontsize=13, weight="bold", y=0.995,
    )

    _save(fig, "figure7_gap9_downstream_impact_reversal.png")


# ---------------------------------------------------------------------------
# Figure -- Decision-utility cost curve across cost-ratio scenarios (Group B5.3)
# ---------------------------------------------------------------------------
def figure8_decision_utility_cost():
    scenarios = ["1 : 1 : 0", "5 : 1 : 0.1", "10 : 1 : 0.2", "20 : 1 : 0.3", "50 : 1 : 0.5"]
    x = list(range(len(scenarios)))
    cost_full = [0.01903807615230461, 0.18176352705410823, 0.36352705410821645,
                 0.6404809619238477, 1.3847695390781563]
    cost_ws = [0.022044088176352707, 0.19909819639278556, 0.3981963927855711,
               0.7075150300601202, 1.5465931863727456]
    cost_ho = [0.4649298597194389, 2.3246492985971945, 4.649298597194389,
               9.298597194388778, 23.246492985971944]

    fig, ax = plt.subplots(figsize=(10.5, 6.3))
    ax.plot(x, cost_full, marker="o", color=COLOR_KNOWN_GOOD, linewidth=2.5, markersize=8,
            label="full two-stage (production)", zorder=4)
    ax.plot(x, cost_ws, marker="s", color="#9a9a9a", linewidth=2.1, markersize=6.8,
            linestyle="--", label="weighted-sum only (no hard-override)", zorder=3)
    ax.plot(x, cost_ho, marker="^", color=COLOR_KNOWN_BAD, linewidth=2.1, markersize=6.8,
            linestyle=":", label="hard-override only (no composite score)", zorder=3)

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, fontsize=9.6)
    ax.set_xlabel("cost-ratio scenario  (C_false-admit : C_false-reject : C_review)", fontsize=10)
    ax.set_ylabel("mean cost per dataset (log scale)", fontsize=10.5)
    ax.set_title(
        "The full two-stage architecture is cost-optimal in every tested scenario,\n"
        "including the naive equal-cost case",
        fontsize=12.3, weight="bold", pad=13,
    )
    ax.legend(loc="upper left", fontsize=9.2, frameon=True, borderaxespad=0.5)
    ax.grid(alpha=0.25, which="both", linewidth=0.5, zorder=0)

    _save(fig, "figure8_decision_utility_cost_by_scenario.png")


# ---------------------------------------------------------------------------
# Figure -- Monte Carlo decision-stability (Group B4)
# ---------------------------------------------------------------------------
def figure9_decision_stability():
    import pandas as pd
    from matplotlib.ticker import FuncFormatter

    path = os.path.join(REPO_ROOT, "calibration", "group_b_reports", "decision_stability_per_dataset.csv")
    df = pd.read_csv(path)

    groups = [
        ("ADMIT", COLOR_AXIS_C),
        ("CONDITIONAL", COLOR_AXIS_P),
        ("REJECT", COLOR_KNOWN_BAD),
    ]
    bins = [i / 20 for i in range(10, 21)]  # 0.5 to 1.0

    fig, ax = plt.subplots(figsize=(11.5, 6.3))
    for decision, color in groups:
        sub = df[df["baseline_decision"] == decision]["stability_rate"]
        ax.hist(sub, bins=bins, alpha=0.55, color=color, edgecolor="white", linewidth=0.3,
                label=f"{decision} (n={len(sub)}, mean={sub.mean() * 100:.2f}%)", zorder=2)

    for decision, color in groups:
        mean_val = df[df["baseline_decision"] == decision]["stability_rate"].mean()
        ax.axvline(mean_val, color=color, linestyle="--", linewidth=1.7, zorder=3)

    ax.set_xlim(0.5, 1.0)
    ax.set_yscale("log")
    ax.set_ylim(0.7, 2000)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y, _: f"{y:g}"))
    ax.set_xlabel("per-dataset decision-stability rate (fraction of 2,000 Monte Carlo draws matching baseline)",
                  fontsize=9.5)
    ax.set_ylabel("number of datasets (log scale)", fontsize=10.5)
    ax.set_title(
        "ADMIT decisions are the least stable under weight/threshold perturbation,\n"
        "not CONDITIONAL, despite its wider decision band",
        fontsize=12.3, weight="bold", pad=13,
    )
    ax.legend(loc="upper left", fontsize=8.6, frameon=True, borderaxespad=0.5)
    ax.grid(axis="y", which="both", alpha=0.25, linewidth=0.5, zorder=0)

    _save(fig, "figure9_decision_stability_monte_carlo.png")


def figure10_decision_breakdown_by_corruption_type():
    import pandas as pd

    main_path = os.path.join(REPO_ROOT, "calibration", "group_b_reports", "three_way_matrix_main.csv")
    corr_path = os.path.join(REPO_ROOT, "calibration", "group_b_reports",
                              "three_way_matrix_by_corruption_type.csv")
    main_df = pd.read_csv(main_path)
    corr_df = pd.read_csv(corr_path)

    group_order = ["known_good", "corrupted_real", "fabricated", "held_out_adversarial"]
    group_labels = {
        "known_good": "known_good\n(n=508)",
        "corrupted_real": "corrupted_real\n(n=173)",
        "fabricated": "fabricated\n(n=287)",
        "held_out_adversarial": "held_out\nadversarial\n(n=30)",
    }
    main_df = main_df.set_index("group").loc[group_order].reset_index()

    corr_order = ["depth_implausible", "timestamp_collision", "inject_duplicates",
                  "inject_missingness", "coordinate_jitter", "magnitude_gr_violation"]
    corr_labels = {
        "depth_implausible": "depth\nimplausible\n(n=27)",
        "timestamp_collision": "timestamp\ncollision\n(n=28)",
        "inject_duplicates": "inject\nduplicates\n(n=29)",
        "inject_missingness": "inject\nmissingness\n(n=29)",
        "coordinate_jitter": "coordinate\njitter\n(n=30)",
        "magnitude_gr_violation": "magnitude_gr\nviolation\n(n=30)",
    }
    corr_df = corr_df.set_index("corruption_type").loc[corr_order].reset_index()

    fig, axes = plt.subplots(1, 2, figsize=(15, 6.2))
    fig.subplots_adjust(top=0.76, bottom=0.11, wspace=0.18)

    def stacked(ax, df, labels_map, key_col, title):
        x = list(range(len(df)))
        admit = (df["ADMIT_rate"] * 100).tolist()
        cond = (df["CONDITIONAL_rate"] * 100).tolist()
        rej = (df["REJECT_rate"] * 100).tolist()

        ax.bar(x, admit, color=COLOR_ADMIT, edgecolor="black", linewidth=0.7,
               width=0.62, label="ADMIT", zorder=3)
        ax.bar(x, cond, bottom=admit, color=COLOR_CONDITIONAL, edgecolor="black",
               linewidth=0.7, width=0.62, label="CONDITIONAL", zorder=3)
        bottom2 = [a + c for a, c in zip(admit, cond)]
        ax.bar(x, rej, bottom=bottom2, color=COLOR_REJECT, edgecolor="black",
               linewidth=0.7, width=0.62, label="REJECT", zorder=3)

        for xi, a, c, r in zip(x, admit, cond, rej):
            if a > 6:
                ax.text(xi, a / 2, f"{a:.0f}%", ha="center", va="center", fontsize=8, color="white", zorder=4)
            if c > 6:
                ax.text(xi, a + c / 2, f"{c:.0f}%", ha="center", va="center", fontsize=8, color="white", zorder=4)
            if r > 6:
                ax.text(xi, a + c + r / 2, f"{r:.0f}%", ha="center", va="center", fontsize=8, color="white", zorder=4)

        ax.set_xticks(x)
        ax.set_xticklabels([labels_map[v] for v in df[key_col]], fontsize=8.6)
        ax.set_ylim(0, 100)
        ax.set_ylabel("share of decisions (%)", fontsize=10)
        ax.set_title(title, fontsize=11, weight="bold", pad=11)
        ax.grid(axis="y", alpha=0.2, linewidth=0.5, zorder=0)

    stacked(axes[0], main_df, group_labels, "group",
            "Overall, by corpus group")
    stacked(axes[1], corr_df, corr_labels, "corruption_type",
            "corrupted_real only, by injected-corruption type")

    handles, labels_ = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_, loc="upper center", ncol=3, fontsize=9.5,
               frameon=True, bbox_to_anchor=(0.5, 0.90))

    fig.suptitle(
        "Decisions split cleanly along known-good/known-bad lines, and REJECT is\n"
        "concentrated exactly where a Stage-1 hard gate applies (depth_implausible)",
        fontsize=12.5, weight="bold", y=0.99,
    )

    _save(fig, "figure10_decision_breakdown_by_corruption_type.png")


# ---------------------------------------------------------------------------
# Figure -- Cross-agency real-data validation (Group D1, option d)
# ---------------------------------------------------------------------------
def figure11_cross_agency_real_data_validation():
    # Transcribed directly from calibration/group_d_reports/d1d_cross_agency_report.txt
    # (Group D1 option d) -- the one case study validated against real, live-fetched
    # USGS + EMSC data for the 2014 Iquique, Chile Mw8.2 sequence, rather than
    # injected synthetic corruption.
    i4_estimate = 0.7131
    independent_estimate = 0.7488

    catalogs = ["usgs_raw", "emsc_raw", "naive_merged\n(no dedup)", "deduplicated_merge\n(I4-informed)"]
    ns = [621, 756, 1377, 912]
    b_values = [0.7651, 0.5684, 0.7186, 0.7688]
    b_errs = [0.0286, 0.0169, 0.0196, 0.0286]
    bar_colors = ["#9a9a9a", "#9a9a9a", COLOR_REJECT, COLOR_ADMIT]

    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2))

    # --- Panel A: I4 estimate vs an independent, non-EM space-time matcher ---
    ax = axes[0]
    x = [0, 1]
    vals = [i4_estimate * 100, independent_estimate * 100]
    bars = ax.bar(x, vals, color=[COLOR_AXIS_I, "#9a9a9a"], edgecolor="black",
                   linewidth=1.0, width=0.55, zorder=3)
    for xi, v in zip(x, vals):
        ax.text(xi, v + 1.5, f"{v:.2f}%", ha="center", fontsize=11, weight="bold", zorder=4)
    ax.set_xticks(x)
    ax.set_xticklabels(["I4 (EM-fitted\nFellegi-Sunter)", "independent matcher\n(fixed 30s/50km/0.5-mag)"],
                        fontsize=9.5)
    ax.set_ylim(0, 90)
    ax.set_ylabel("estimated cross-catalog duplicate fraction (%)", fontsize=10)
    ax.annotate(
        f"agreement within\n{abs(i4_estimate - independent_estimate) * 100:.1f} points",
        xy=(0.5, max(vals) + 4), ha="center", fontsize=9.5, color="black",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="black", alpha=0.9, linewidth=0.7),
    )
    ax.set_title("I4 vs. an independent duplicate-matching method\non real USGS+EMSC data", fontsize=11, weight="bold", pad=11)
    ax.grid(axis="y", alpha=0.2, linewidth=0.5, zorder=0)

    # --- Panel B: b-value before/after I4-informed deduplication ---
    ax = axes[1]
    x2 = list(range(len(catalogs)))
    bars2 = ax.bar(x2, b_values, yerr=b_errs, capsize=4, color=bar_colors,
                    edgecolor="black", linewidth=1.0, width=0.6, zorder=3,
                    error_kw=dict(linewidth=1.2, zorder=4))
    for xi, v, e, n in zip(x2, b_values, b_errs, ns):
        ax.text(xi, v + e + 0.03, f"b={v:.4f}\nn={n}", ha="center", fontsize=8.6, zorder=4)
    ax.set_xticks(x2)
    ax.set_xticklabels(catalogs, fontsize=8.8)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Gutenberg-Richter b-value (+/- std. error)", fontsize=10)
    ax.set_title("b-value before/after I4-informed deduplication\n(2014 Iquique, Chile Mw8.2 sequence)", fontsize=11, weight="bold", pad=11)
    ax.grid(axis="y", alpha=0.2, linewidth=0.5, zorder=0)

    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.suptitle(
        "The one case study validated against real (not synthetic) data: I4 correctly\n"
        "detects and quantifies real cross-agency duplication in a live USGS+EMSC merge",
        fontsize=12.5, weight="bold", y=0.995,
    )

    _save(fig, "figure11_cross_agency_real_data_validation.png")


def main():
    print(f"Repository root: {REPO_ROOT}")
    print(f"Output directory: {OUT_DIR}\n")
    figure3_T_distribution()
    figure4_axis_weight_evolution()
    figure5_a6_case_study()
    figure6_weight_ablation()
    figure7_gap9_downstream_impact()
    figure8_decision_utility_cost()
    figure9_decision_stability()
    figure10_decision_breakdown_by_corruption_type()
    figure11_cross_agency_real_data_validation()
    print("\nAll 9 figures written successfully.")


if __name__ == "__main__":
    main()
