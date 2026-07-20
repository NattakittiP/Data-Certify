# -*- coding: utf-8 -*-
"""
bootstrap_ewm_stability.py -- Non-parametric bootstrap stability analysis of
the AHP x EWM blended weights (calibration/compute_ewm.py), to quantify how
much AXIS_WEIGHTS / WITHIN_A/P/C/I would plausibly shift under a different
but similarly-sized real-world sample from the same 73-dataset corpus.

Method: stratified bootstrap by corpus `category` (real / corrupted /
fabricated), preserving the corpus's own composition (50/19/4) in every
resample -- this asks "how much does sampling noise within each stratum
move the weights", holding the corpus's deliberate real:corrupted:fabricated
ratio fixed, which is the right null model for interpreting stability of a
corpus explicitly assembled with a chosen ratio between those three groups.

For each of B replicates:
  1. Resample each stratum's rows WITH replacement, same size as that stratum.
  2. Recombine into a 73-row resampled score matrix.
  3. Recompute axis-level A/P/C/I from sub-criteria (AHP-prior basis, exactly
     as compute_ewm.py does for its own EWM entropy calc).
  4. Run the real compute_group() axis-level and within-axis EWM+blend logic.
  5. Record every blended weight.

Reports: mean, std, 2.5/50/97.5 percentiles, and coefficient of variation
(std/mean) per weight, at both the axis level and within each axis.

WHY THIS EXISTS (2026-07-07): after the sixth calibration pass fixed the
theta_reject validation formula bug, a review of the paper-readiness of this
project's calibration numbers concluded that quoting point-estimate weights
(e.g. "A(D) weight = 0.7149") without any uncertainty quantification
overstates how settled these numbers are on a 73-dataset corpus -- the
weights had already moved measurably across six recalibration passes
whenever even 2 corpus rows changed. This script turns that qualitative
concern into a quantified, reproducible confidence interval per weight,
intended for a paper's validity/limitations section (see
bootstrap_stability_report.md for the numbers and
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Section 5.5 for
the narrative interpretation).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import (
    AXIS_WEIGHTS_AHP_PRIOR, WITHIN_A_AHP_PRIOR, WITHIN_P_AHP_PRIOR,
    WITHIN_C_AHP_PRIOR, WITHIN_I_AHP_PRIOR,
)
from calibration.compute_ewm import recompute_axis_columns_from_ahp_prior, compute_group

SCORE_MATRIX_PATH = Path(__file__).resolve().parent / "score_matrix.csv"
MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"
OUT_JSON = Path(__file__).resolve().parent / "bootstrap_stability_report.json"
OUT_MD = Path(__file__).resolve().parent / "bootstrap_stability_report.md"

N_BOOT = 2000
SEED = 20260707

GROUPS = {
    "axis": dict(AXIS_WEIGHTS_AHP_PRIOR),
    "within_A": dict(WITHIN_A_AHP_PRIOR),
    "within_P": dict(WITHIN_P_AHP_PRIOR),
    "within_C": dict(WITHIN_C_AHP_PRIOR),
    "within_I": dict(WITHIN_I_AHP_PRIOR),
}


def main():
    s = pd.read_csv(SCORE_MATRIX_PATH)
    m = pd.read_csv(MANIFEST_PATH)
    df = s.merge(m[["dataset_id", "category"]], on="dataset_id")
    df = recompute_axis_columns_from_ahp_prior(df)

    strata = {cat: sub.index.to_numpy() for cat, sub in df.groupby("category")}
    print("Corpus strata sizes:", {k: len(v) for k, v in strata.items()})

    rng = np.random.RandomState(SEED)

    samples = {g: {k: [] for k in w} for g, w in GROUPS.items()}

    point_estimate = {}
    for gname, ahp_w in GROUPS.items():
        r = compute_group(df, ahp_w, gname)
        point_estimate[gname] = r["blended_weights"]

    for b in range(N_BOOT):
        idx = np.concatenate([
            rng.choice(strata[cat], size=len(strata[cat]), replace=True)
            for cat in strata
        ])
        boot_df = df.loc[idx].reset_index(drop=True)
        for gname, ahp_w in GROUPS.items():
            r = compute_group(boot_df, ahp_w, gname)
            for k, v in r["blended_weights"].items():
                samples[gname][k].append(v)

    report = {}
    for gname, crit_samples in samples.items():
        report[gname] = {}
        for k, vals in crit_samples.items():
            arr = np.array(vals)
            mean = float(arr.mean())
            std = float(arr.std(ddof=1))
            p2_5, p50, p97_5 = np.percentile(arr, [2.5, 50, 97.5])
            report[gname][k] = {
                "point_estimate": point_estimate[gname][k],
                "bootstrap_mean": mean,
                "bootstrap_std": std,
                "cv_pct": (std / mean * 100.0) if mean > 0 else float("nan"),
                "ci95_low": float(p2_5),
                "ci95_median": float(p50),
                "ci95_high": float(p97_5),
            }

    with open(OUT_JSON, "w") as f:
        json.dump({"n_boot": N_BOOT, "seed": SEED, "results": report}, f, indent=2)
    print(f"JSON -> {OUT_JSON}")

    lines = [f"# EWM Weight Bootstrap Stability Report (N_boot={N_BOOT}, stratified by category)\n",
             f"Stratum sizes: {', '.join(f'{k}={len(v)}' for k,v in strata.items())}\n"]
    for gname, crit in report.items():
        lines.append(f"## {gname}\n")
        lines.append("| Criterion | Point est. | Bootstrap mean | Std | CV% | 95% CI |")
        lines.append("|---|---|---|---|---|---|")
        for k, r in crit.items():
            lines.append(f"| {k} | {r['point_estimate']:.4f} | {r['bootstrap_mean']:.4f} | "
                         f"{r['bootstrap_std']:.4f} | {r['cv_pct']:.1f}% | "
                         f"[{r['ci95_low']:.4f}, {r['ci95_high']:.4f}] |")
        lines.append("")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"MD -> {OUT_MD}")

    print("\n=== SUMMARY (axis level) ===")
    for k, r in report["axis"].items():
        print(f"  {k}: point={r['point_estimate']:.4f}  95% CI=[{r['ci95_low']:.4f}, {r['ci95_high']:.4f}]  CV={r['cv_pct']:.1f}%")


if __name__ == "__main__":
    main()
