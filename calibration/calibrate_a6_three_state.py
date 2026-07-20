# -*- coding: utf-8 -*-
"""
calibration/calibrate_a6_three_state.py -- Group C3:
validate the A6 three-state semantics redesign (Externally corroborated /
Externally unverifiable / Externally contradicted -- see
data_certify/axis_authenticity.py's _score_a6_external() docstring and
data_certify/_constants.py's A6_CONTRADICTED_* block) against real corpus
data, and check whether the PROVISIONAL starting constants
(A6_CONTRADICTED_MIN_SOURCES=2, A6_CONTRADICTED_MIN_N_STRATUM=20,
A6_CONTRADICTED_ALPHA=0.01) hold up, the same "diagnose against the real
corpus before touching anything" posture as
calibration/calibrate_theta_auth.py and calibration/refit_full_corpus.py
before it.

WHY THIS NEEDS A LIVE, MULTI-SOURCE RUN: A6_CONTRADICTED_MIN_SOURCES=2
means the "Externally contradicted" state (the only one that can fire the
hard-override) is UNREACHABLE with a single reference source by design.
This script therefore requires `calibration/run_a6_scoring.py` to have
been run with `--reference-source multi --min-corroborating-sources 1`
(or `weighted-multi`) against >=2 independently-reachable sources
(USGS + EMSC recommended -- ISC has looser rate limits, see
run_a6_scoring.py's --timeout note) -- a single-source score_matrix_a6.csv
has every row's n_contradicted_eligible=0 by construction and this script
will refuse to run a misleading "calibration" against it.

WHAT THIS SCRIPT CHECKS (three questions, each answerable straight from
run_a6_scoring.py's per-dataset three-state columns, no re-scoring needed):

  1. FALSE-POSITIVE CHECK (the whole reason Group C3 exists): does any
     known_good dataset reach a CONFIRMED "Externally contradicted"
     verdict? This is the failure Group C3 was built to prevent (the
     disclosed "nz" false-positive under the old binary rule). Any
     known_good dataset with contradicted_confirmed=True here is a
     genuine regression and MUST be investigated before this redesign is
     considered safe to rely on -- this script treats it as the single
     most important number it reports.

  2. SECURITY-PROPERTY CHECK: does the known_bad population (specifically
     any fully-fabricated / gamed-fabrication-style datasets, which is
     what A6's hard-override exists to catch -- see
     tests/test_adversarial.py) still reach "Externally contradicted"
     when queried against >=2 sources, restoring the security property
     that a single-source non-match alone can no longer provide? Reports
     the known_bad contradicted-confirmation rate.

  3. THRESHOLD SENSITIVITY: for datasets that landed in "Externally
     unverifiable" specifically because n_contradicted_eligible fell just
     short of A6_CONTRADICTED_MIN_N_STRATUM=20, or where
     contradicted_p_value was close to (but not below) A6_CONTRADICTED_
     ALPHA=0.01, reports how sensitive the current PROVISIONAL constants
     are -- i.e. whether a small, defensible change to either constant
     would flip the verdict for any real dataset, which is exactly the
     kind of evidence a human should review before treating these
     starting values as final.

This script is READ-ONLY / REPORT-ONLY, same posture as every other
calibration diagnostic in this project: it never writes to
data_certify/_constants.py. Output:
  calibration/group_c_reports/a6_three_state_report.json/.md

Usage:
    # Prerequisite (run first, live network, multi-source):
    python3 calibration/run_a6_scoring.py --reference-source multi --min-corroborating-sources 1
    # (produces calibration/score_matrix_a6_multi.csv)

    python3 calibration/calibrate_a6_three_state.py
    python3 calibration/calibrate_a6_three_state.py --input calibration/score_matrix_a6_weighted-multi.csv
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

from data_certify._constants import (  # noqa: E402
    A6_CONTRADICTED_MIN_SOURCES, A6_CONTRADICTED_MIN_N_STRATUM, A6_CONTRADICTED_ALPHA,
    THETA_AUTH,
)

MANIFEST_PATH = HERE / "corpus_manifest.csv"
DEFAULT_INPUT_PATH = HERE / "score_matrix_a6_multi.csv"
REPORT_DIR = HERE / "group_c_reports"


def load_corpus(input_path: Path) -> pd.DataFrame:
    if not input_path.exists():
        raise FileNotFoundError(
            f"{input_path} not found. This script requires a completed MULTI-SOURCE "
            f"run of calibration/run_a6_scoring.py first (single-source runs cannot "
            f"exercise the 'Externally contradicted' path by design -- see this "
            f"script's module docstring): \n\n"
            f"    python3 calibration/run_a6_scoring.py --reference-source multi "
            f"--min-corroborating-sources 1\n"
        )
    df = pd.read_csv(input_path)

    required_cols = {"n_corroborated", "n_contradicted_eligible", "n_unverifiable",
                      "contradicted_confirmed", "contradicted_p_value"}
    missing = required_cols - set(df.columns)
    if missing:
        raise RuntimeError(
            f"{input_path} is missing three-state columns {sorted(missing)} -- this file "
            f"predates the Group C3 redesign (run_a6_scoring.py v3, 2026-07-12) and was "
            f"generated by an OLDER version of the script. Re-run "
            f"`python3 calibration/run_a6_scoring.py --reference-source multi "
            f"--min-corroborating-sources 1` (or delete this stale file and re-run) to "
            f"regenerate it with the current code before calibrating against it."
        )

    manifest = pd.read_csv(MANIFEST_PATH)
    df = df.merge(manifest[["dataset_id", "label"]], on="dataset_id", suffixes=("", "_manifest"))
    if "label_manifest" in df.columns:
        df["label"] = df["label_manifest"]
        df = df.drop(columns=["label_manifest"])

    n_any_eligible = int((df["n_contradicted_eligible"].fillna(0) > 0).sum())
    if n_any_eligible == 0:
        raise RuntimeError(
            f"{input_path} has n_contradicted_eligible=0 on EVERY row -- this looks "
            f"like a single-source run (or every dataset happened to fall below "
            f"A6_CONTRADICTED_MIN_SOURCES={A6_CONTRADICTED_MIN_SOURCES} independent "
            f"sources). Re-run run_a6_scoring.py with --reference-source multi "
            f"(or weighted-multi) against >=2 independently-reachable sources."
        )
    return df


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH,
                         help="Path to a completed MULTI-SOURCE run_a6_scoring.py "
                              "output (default: calibration/score_matrix_a6_multi.csv).")
    args = parser.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)
    df = load_corpus(args.input)

    print("=" * 100)
    print("Group C3: A6 three-state semantics validation")
    print("=" * 100)
    print(f"Input: {args.input} ({len(df)} datasets)")
    print(f"Provisional constants under test: A6_CONTRADICTED_MIN_SOURCES={A6_CONTRADICTED_MIN_SOURCES}, "
          f"A6_CONTRADICTED_MIN_N_STRATUM={A6_CONTRADICTED_MIN_N_STRATUM}, "
          f"A6_CONTRADICTED_ALPHA={A6_CONTRADICTED_ALPHA}, THETA_AUTH={THETA_AUTH}")
    print()

    a6_applicable = df[df["a6_applicable"] == True].copy()  # noqa: E712
    good = df[df.label == "known_good"]
    bad = df[df.label == "known_bad"]

    # --- Question 1: false-positive check (the most important number) ---
    good_contradicted = good[good["contradicted_confirmed"] == True]  # noqa: E712
    print("--- Q1: FALSE-POSITIVE CHECK (known_good reaching 'Externally contradicted') ---")
    if len(good_contradicted) == 0:
        print("  NONE. No known_good dataset reached a confirmed 'Externally contradicted' "
              "verdict under the provisional constants -- this is the expected, safe result.")
    else:
        print(f"  *** {len(good_contradicted)} known_good dataset(s) reached 'Externally "
              f"contradicted' -- THIS IS A REGRESSION, review before relying on this redesign: ***")
        for _, r in good_contradicted.iterrows():
            print(f"    {r['dataset_id']}: n_contradicted_eligible={r['n_contradicted_eligible']}, "
                  f"p={r['contradicted_p_value']:.2e}")
    print()

    # --- Question 2: security-property check (known_bad still caught) ---
    bad_eligible = bad[bad["n_contradicted_eligible"].fillna(0) > 0]
    bad_confirmed = bad[bad["contradicted_confirmed"] == True]  # noqa: E712
    print("--- Q2: SECURITY-PROPERTY CHECK (known_bad reaching 'Externally contradicted') ---")
    print(f"  {len(bad_eligible)}/{len(bad)} known_bad datasets had >=1 contradicted-eligible "
          f"record (queried against >={A6_CONTRADICTED_MIN_SOURCES} sources, matched none).")
    print(f"  {len(bad_confirmed)}/{len(bad_eligible) if len(bad_eligible) else 1} of those were "
          f"CONFIRMED (cleared A6_CONTRADICTED_MIN_N_STRATUM and the Clopper-Pearson test) -- "
          f"these fire the hard-override; the multi-source configuration restores A6's "
          f"strongest security property for them.")
    print()

    # --- Question 3: threshold sensitivity ---
    near_miss_n = bad[
        (bad["n_contradicted_eligible"].fillna(0) > 0)
        & (bad["n_contradicted_eligible"].fillna(0) < A6_CONTRADICTED_MIN_N_STRATUM)
    ]
    near_miss_p = bad[
        (bad["contradicted_p_value"].notna())
        & (bad["contradicted_p_value"] >= A6_CONTRADICTED_ALPHA)
        & (bad["contradicted_p_value"] < A6_CONTRADICTED_ALPHA * 10)
    ]
    print("--- Q3: THRESHOLD SENSITIVITY ---")
    print(f"  {len(near_miss_n)} known_bad dataset(s) had a nonzero but sub-"
          f"A6_CONTRADICTED_MIN_N_STRATUM={A6_CONTRADICTED_MIN_N_STRATUM} contradicted-eligible "
          f"stratum (would need a lower MIN_N_STRATUM to ever reach 'contradicted').")
    print(f"  {len(near_miss_p)} known_bad dataset(s) had contradicted_p_value within 10x of "
          f"A6_CONTRADICTED_ALPHA={A6_CONTRADICTED_ALPHA} without clearing it (close calls worth "
          f"a human look, not necessarily a problem).")
    print()

    report = {
        "input_file": str(args.input),
        "n_datasets": len(df),
        "n_a6_applicable": int(len(a6_applicable)),
        "constants_under_test": {
            "A6_CONTRADICTED_MIN_SOURCES": A6_CONTRADICTED_MIN_SOURCES,
            "A6_CONTRADICTED_MIN_N_STRATUM": A6_CONTRADICTED_MIN_N_STRATUM,
            "A6_CONTRADICTED_ALPHA": A6_CONTRADICTED_ALPHA,
            "THETA_AUTH": THETA_AUTH,
        },
        "q1_false_positive_check": {
            "n_known_good_contradicted": int(len(good_contradicted)),
            "datasets": good_contradicted[["dataset_id", "n_contradicted_eligible",
                                            "contradicted_p_value"]].to_dict("records"),
        },
        "q2_security_property_check": {
            "n_known_bad_total": int(len(bad)),
            "n_known_bad_contradicted_eligible": int(len(bad_eligible)),
            "n_known_bad_confirmed": int(len(bad_confirmed)),
            "confirmed_dataset_ids": bad_confirmed["dataset_id"].tolist(),
        },
        "q3_threshold_sensitivity": {
            "near_miss_min_n_stratum": near_miss_n[["dataset_id", "n_contradicted_eligible"]].to_dict("records"),
            "near_miss_alpha": near_miss_p[["dataset_id", "contradicted_p_value"]].to_dict("records"),
        },
        "safe_to_rely_on": bool(len(good_contradicted) == 0),
    }
    (REPORT_DIR / "a6_three_state_report.json").write_text(json.dumps(report, indent=2, default=str))

    lines = ["# Group C3: A6 Three-State Semantics Validation Report\n",
             f"Input: `{args.input}` ({len(df)} datasets)\n",
             f"Constants under test: `A6_CONTRADICTED_MIN_SOURCES={A6_CONTRADICTED_MIN_SOURCES}`, "
             f"`A6_CONTRADICTED_MIN_N_STRATUM={A6_CONTRADICTED_MIN_N_STRATUM}`, "
             f"`A6_CONTRADICTED_ALPHA={A6_CONTRADICTED_ALPHA}`\n",
             "## Q1: False-positive check\n",
             (f"No known_good dataset reached 'Externally contradicted' -- safe."
              if len(good_contradicted) == 0 else
              f"**{len(good_contradicted)} known_good dataset(s) reached 'Externally contradicted' "
              f"-- REGRESSION, needs review.**"),
             "\n## Q2: Security-property check (known_bad)\n",
             f"{len(bad_eligible)}/{len(bad)} known_bad datasets had a contradicted-eligible "
             f"stratum; {len(bad_confirmed)} were confirmed and fire the hard-override.\n",
             "## Q3: Threshold sensitivity\n",
             f"{len(near_miss_n)} known_bad dataset(s) near the MIN_N_STRATUM cutoff; "
             f"{len(near_miss_p)} near the ALPHA cutoff.\n",
             f"\nFull data: `{REPORT_DIR / 'a6_three_state_report.json'}`\n"]
    (REPORT_DIR / "a6_three_state_report.md").write_text("\n".join(lines))

    print("=" * 100)
    if len(good_contradicted) == 0:
        print("RESULT: SAFE. No known_good false-positive found under the provisional constants.")
    else:
        print("RESULT: REGRESSION FOUND. Do not rely on this redesign until reviewed -- see Q1 above.")
    print("=" * 100)
    print(f"\nReports written to {REPORT_DIR}/a6_three_state_report.json / .md")


if __name__ == "__main__":
    main()
