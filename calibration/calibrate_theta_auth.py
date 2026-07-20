# -*- coding: utf-8 -*-
"""
calibration/calibrate_theta_auth.py -- Empirically calibrate theta_auth
(A6's confirmed-fabrication matched_fraction floor) from a full-corpus,
live-reference A6 run, using the exact same methodology style already
applied to theta_admit/theta_reject (calibration/calibrate_thresholds.py):
inspect where genuine known_good and known_bad datasets actually land on
the matched_fraction scale, then set the boundary so it tracks that
empirical separation -- not a number chosen in the abstract.

WHY THIS SCRIPT EXISTS, AND ITS EXECUTION HISTORY:
theta_admit/theta_reject could be calibrated locally because
calibration/run_scoring.py's A1-A5/P4-P9/C1-C4/I1-I5 sub-tests are all
pure, local computations over each dataset's own records.csv. A6 is
different by design -- it needs a LIVE (or manually-fetched-and-cached)
query against an external reference catalog (USGS ComCat, EMSC, ISC, or a
multi-source AND-gate). That reference-dependent run is
calibration/run_a6_scoring.py (or, for the full-corpus pass actually
executed, calibration/debug_diagnostics/run_a6_scoring_from_manual_fetch.py plus
calibration/debug_diagnostics/score_missing_16_datasets.py against manually-downloaded USGS
ComCat CSVs -- the sandbox this project's agent runs in has no outbound
network access, so a human manually fetched the reference data instead of
running a live query). This script is the DOWNSTREAM half: it reads
whatever `calibration/score_matrix_a6.csv` the upstream scoring step
produced.

UPDATE (2026-07-07/08): this pre-step HAS now been run to completion
across the FULL 89-dataset corpus (61 real known_good, 23 disclosed
synthetic corruptions, 5 fabrications -- not a 73-dataset or pilot
subset), against a real, manually-fetched USGS ComCat reference. The
result is documented in calibration/theta_auth_report.md /
theta_auth_report.json and in
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Section 4's
THETA_AUTH row: a genuine, confirmed STRUCTURAL overlap (see item 4 of
the METHODOLOGY below) between the known-good "nz" dataset
(matched_fraction=0.3913) and two known-bad corrupted datasets that score
a perfect matched_fraction=1.0000 -- not a data-volume gap that more
datasets would resolve. THETA_AUTH was therefore left unchanged at its
original a-priori value (0.50) as a confirmed, evidence-based non-change:
both problem datasets are still caught by the full two-stage decision
via mechanisms OTHER than A6 alone (P2's depth-implausibility hard-REJECT;
A5's near-duplicate detection), so this is the multi-axis compensatory
design working as intended, not an unexamined gap. See
data_certify/_constants.py's THETA_AUTH comment block for the full
disclosure.

This produces calibration/score_matrix_a6.csv (89 rows: dataset_id,
label, n_records, a6_applicable, matched_fraction, n_stratum, mc_ref,
mc_ref_is_default, hard_reject_would_fire, elapsed_sec, note).

METHODOLOGY (mirrors calibrate_thresholds.py's theta_reject logic, since
theta_auth plays an analogous "floor" role in A6's own hard-override
gate -- Deep-Dive 05 Section 2.2's majority-vote framing: "if fewer than
half of a sampled set of records can be independently matched to an
authoritative catalog, the balance of evidence favors 'not what it
claims to be'"):

  1. Restrict to rows where A6 was actually feasible for that dataset
     (a6_applicable == True, n_stratum > 0) -- a dataset with NO
     reference-complete-stratum events simply has no A6 evidence either
     way, and is excluded from the calibration set entirely (not treated
     as either a pass or a fail).
  2. Among the remaining known_good datasets, find the LOWEST
     matched_fraction (the worst case DATA-CERTIFY must not
     false-positive on) and among known_bad datasets, find the HIGHEST
     matched_fraction (the best case DATA-CERTIFY must still catch).
  3. If the known_good minimum is comfortably ABOVE the known_bad
     maximum, theta_auth can be set to a clean value strictly between
     them, with a reported margin on both sides -- exactly analogous to
     the theta_reject derivation.
  4. If the two distributions OVERLAP (a known_bad dataset scores higher
     than some known_good dataset), there is NO single threshold that
     cleanly separates them, and this script does NOT silently pick a
     compromise value. It reports the overlap explicitly, names the
     specific dataset(s) on each side of the crossover, and leaves
     THETA_AUTH unchanged -- consistent with this project's CONFIRMED
     finding (Docs/..._Master_Reference.md Section 4's theta_auth row,
     closed 2026-07-08 against the full 89-dataset corpus) that "nz"
     scores 0.3913 while corrupt_real_chiapas_mexico_2017_inject_duplicates_med
     and corrupt_real_taiwan_2024_query_depth_implausible_med both score a
     perfect 1.0000 -- a genuine, permanent structural overlap (A6 checks
     time/lat/lon/magnitude only, never depth, and a duplicated real
     record still individually matches), not a data-volume gap. This was
     surfaced, not papered over, and both problem datasets are confirmed
     caught elsewhere in the full decision pipeline (P2 hard-REJECT; A5
     near-duplicate detection) -- see _constants.py's THETA_AUTH comment.

This script never edits data_certify/_constants.py directly (unlike, say,
blindly propagating an EWM blend) -- theta_auth is a hard-override gate,
not a compensatory weight, and a wrong value here has an asymmetric,
non-compensable cost (Deep-Dive 05 Section 2.1). Recommended values are
printed and written to the report for a human to review and apply by
hand, the same way theta_admit/theta_reject's recommendations were
reviewed before being copied into _constants.py.

Output: calibration/theta_auth_report.json + calibration/theta_auth_report.md

Usage:
    python3 calibration/calibrate_theta_auth.py
    python3 calibration/calibrate_theta_auth.py --input calibration/score_matrix_a6_emsc.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import THETA_AUTH as CURRENT_THETA_AUTH

MANIFEST_PATH = HERE / "corpus_manifest.csv"
DEFAULT_INPUT_PATH = HERE / "score_matrix_a6.csv"
REPORT_JSON_PATH = HERE / "theta_auth_report.json"
REPORT_MD_PATH = HERE / "theta_auth_report.md"

# Candidate clean round values to test, in descending order, matching the
# style of theta_admit/theta_reject's "largest/cleanest value that still
# satisfies the empirical constraint" approach.
CANDIDATE_THETA_AUTH_VALUES = [0.60, 0.55, 0.50, 0.45, 0.40, 0.35, 0.30, 0.25, 0.20]


def load_a6_corpus(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(
            f"{input_path} not found. This script requires a completed, FULL-CORPUS "
            f"(not --only pilot) run of calibration/run_a6_scoring.py first -- that "
            f"script needs live network access to an external reference catalog "
            f"(USGS ComCat / EMSC / ISC), which this calibration script does not "
            f"perform itself. See this file's module docstring for the exact command."
        )
    df = pd.read_csv(input_path)
    manifest = pd.read_csv(MANIFEST_PATH)
    df = df.merge(manifest[["dataset_id", "label"]], on="dataset_id", suffixes=("", "_manifest"))
    # Prefer the manifest's label if the a6 file's own label column disagrees
    # (score_matrix_a6.csv already carries a label column from run_a6_scoring.py,
    # but the manifest is the canonical source of truth).
    if "label_manifest" in df.columns:
        df["label"] = df["label_manifest"]
        df = df.drop(columns=["label_manifest"])
    return df


def feasible_subset(df: pd.DataFrame) -> pd.DataFrame:
    """Rows where A6 actually had reference-complete-stratum evidence to judge."""
    mask = (df["a6_applicable"] == True) & (df["n_stratum"].fillna(0) > 0)  # noqa: E712
    return df[mask].copy()


def confusion_at(df: pd.DataFrame, theta_auth: float) -> dict:
    good = df[df.label == "known_good"]
    bad = df[df.label == "known_bad"]
    return {
        "theta_auth": theta_auth,
        "n_known_good_evaluated": int(len(good)),
        "n_known_bad_evaluated": int(len(bad)),
        "good_wrongly_hard_rejected": int((good.matched_fraction < theta_auth).sum()),
        "bad_correctly_hard_rejected": int((bad.matched_fraction < theta_auth).sum()),
        "bad_missed_by_a6_alone": int((bad.matched_fraction >= theta_auth).sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH,
                         help="Path to a completed run_a6_scoring.py output "
                              "(default: calibration/score_matrix_a6.csv, the USGS run).")
    args = parser.parse_args()

    full_df = load_a6_corpus(args.input)
    df = feasible_subset(full_df)

    n_excluded = len(full_df) - len(df)
    good = df[df.label == "known_good"].sort_values("matched_fraction")
    bad = df[df.label == "known_bad"].sort_values("matched_fraction", ascending=False)

    if len(good) == 0 or len(bad) == 0:
        raise RuntimeError(
            f"Cannot calibrate theta_auth: only {len(good)} known_good and {len(bad)} "
            f"known_bad datasets had A6-feasible (a6_applicable=True, n_stratum>0) rows "
            f"in {args.input}. Need at least one of each. Check whether the reference "
            f"catalog actually returned data (reference.is_feasible() may have been False "
            f"for this run -- see run_a6_scoring.py's own printed diagnostics)."
        )

    good_min = good.iloc[0]
    bad_max = bad.iloc[0]

    overlap = bool(bad_max["matched_fraction"] >= good_min["matched_fraction"])

    recommended = None
    if not overlap:
        # Largest candidate strictly below good_min and strictly above bad_max.
        for candidate in CANDIDATE_THETA_AUTH_VALUES:
            if bad_max["matched_fraction"] < candidate < good_min["matched_fraction"]:
                recommended = candidate
                break
        if recommended is None:
            # No clean round number fits in the gap -- fall back to the
            # arithmetic midpoint, rounded to 3 decimals, and say so.
            recommended = round((good_min["matched_fraction"] + bad_max["matched_fraction"]) / 2, 3)

    report = {
        "input_file": str(args.input),
        "current_theta_auth": CURRENT_THETA_AUTH,
        "n_datasets_total_in_input": int(len(full_df)),
        "n_datasets_a6_feasible": int(len(df)),
        "n_datasets_excluded_a6_not_applicable": int(n_excluded),
        "known_good_matched_fraction_sorted": good[["dataset_id", "matched_fraction", "n_stratum"]].to_dict("records"),
        "known_bad_matched_fraction_sorted_desc": bad[["dataset_id", "matched_fraction", "n_stratum"]].to_dict("records"),
        "known_good_minimum": {
            "dataset_id": good_min["dataset_id"],
            "matched_fraction": float(good_min["matched_fraction"]),
        },
        "known_bad_maximum": {
            "dataset_id": bad_max["dataset_id"],
            "matched_fraction": float(bad_max["matched_fraction"]),
        },
        "overlap_found": overlap,
        "recommended_theta_auth": recommended,
        "confusion_at_current_theta_auth": confusion_at(df, CURRENT_THETA_AUTH),
        "confusion_at_recommended_theta_auth": confusion_at(df, recommended) if recommended is not None else None,
    }

    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    lines = []
    lines.append("# theta_auth Calibration Report\n")
    lines.append(f"Input: `{args.input}` ({len(full_df)} total datasets, "
                  f"{len(df)} A6-feasible / {n_excluded} excluded as not-applicable).\n")
    lines.append(f"Current `THETA_AUTH` (provisional prior): **{CURRENT_THETA_AUTH}**\n")
    lines.append("## known_good matched_fraction (ascending -- worst case first)\n")
    lines.append("| dataset_id | matched_fraction | n_stratum |\n|---|---|---|")
    for _, r in good.iterrows():
        lines.append(f"| {r['dataset_id']} | {r['matched_fraction']:.4f} | {int(r['n_stratum'])} |")
    lines.append("\n## known_bad matched_fraction (descending -- best case first)\n")
    lines.append("| dataset_id | matched_fraction | n_stratum |\n|---|---|---|")
    for _, r in bad.iterrows():
        lines.append(f"| {r['dataset_id']} | {r['matched_fraction']:.4f} | {int(r['n_stratum'])} |")

    lines.append("\n## Result\n")
    if overlap:
        lines.append(
            f"**OVERLAP FOUND -- no single threshold cleanly separates known_good from "
            f"known_bad.** The known_bad dataset `{bad_max['dataset_id']}` scores "
            f"{bad_max['matched_fraction']:.4f}, which is >= the known_good dataset "
            f"`{good_min['dataset_id']}`'s {good_min['matched_fraction']:.4f}. "
            f"`THETA_AUTH` is **NOT** recommended to change automatically here -- "
            f"any value that admits `{good_min['dataset_id']}` would also admit "
            f"`{bad_max['dataset_id']}`, and any value that rejects "
            f"`{bad_max['dataset_id']}` would also wrongly hard-reject "
            f"`{good_min['dataset_id']}`. This needs a human decision: either "
            f"investigate `{good_min['dataset_id']}` further for a real, undiscovered "
            f"data bug (the same way chile's three stacked bugs were found), or accept "
            f"this as a genuine, disclosed limitation of a single-external-reference A6 "
            f"check and leave `{good_min['dataset_id']}` to be manually reviewed via the "
            f"CONDITIONAL/disclosed-caveat path rather than fully automated ADMIT."
        )
    else:
        lines.append(
            f"**Clean separation found.** known_good minimum = "
            f"`{good_min['dataset_id']}` at {good_min['matched_fraction']:.4f}; "
            f"known_bad maximum = `{bad_max['dataset_id']}` at "
            f"{bad_max['matched_fraction']:.4f}. Recommended `THETA_AUTH` = "
            f"**{recommended}** (margin: {good_min['matched_fraction'] - recommended:.4f} "
            f"above known_good minimum, {recommended - bad_max['matched_fraction']:.4f} "
            f"below known_bad maximum)."
        )
    lines.append(f"\nConfusion at CURRENT theta_auth ({CURRENT_THETA_AUTH}):\n```\n"
                 f"{json.dumps(report['confusion_at_current_theta_auth'], indent=2)}\n```")
    if recommended is not None:
        lines.append(f"\nConfusion at RECOMMENDED theta_auth ({recommended}):\n```\n"
                     f"{json.dumps(report['confusion_at_recommended_theta_auth'], indent=2)}\n```")

    with open(REPORT_MD_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"JSON report -> {REPORT_JSON_PATH}")
    print(f"Markdown report -> {REPORT_MD_PATH}")
    print()
    print("=" * 70)
    if overlap:
        print(f"OVERLAP: {bad_max['dataset_id']} ({bad_max['matched_fraction']:.4f}) >= "
              f"{good_min['dataset_id']} ({good_min['matched_fraction']:.4f}) -- "
              f"THETA_AUTH left UNCHANGED, human review needed.")
    else:
        print(f"theta_auth: {CURRENT_THETA_AUTH} -> RECOMMENDED {recommended}")
    print("=" * 70)


if __name__ == "__main__":
    main()
