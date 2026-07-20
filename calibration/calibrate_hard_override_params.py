# -*- coding: utf-8 -*-
"""
calibration/calibrate_hard_override_params.py -- Empirically calibrate
epsilon_tol / alpha (the P1-P3 Clopper-Pearson "non-trivial fraction"
hard-override parameters, data_certify/hard_override.py) against the real
73-dataset calibration corpus, mirroring the methodology already used for
theta_admit/theta_reject (calibration/calibrate_thresholds.py) and
theta_auth (calibration/calibrate_theta_auth.py).

WHY THIS ONE CAN BE CALIBRATED LOCALLY, WITH NO LIVE NETWORK ACCESS:
unlike A6/theta_auth, the P1-P3 checks (data_certify/axis_plausibility.py:
p1_violation_mask/p2_violation_mask/p3_violation_mask) are pure, local
computations directly over each dataset's own records.csv -- exact
geometric/physical bounds (|lat|<=90, |lon|<=180, 0<=depth<=750km,
0<=magnitude<=9.5), no external catalog lookup involved. Every one of the
73 corpus datasets already has records.csv on disk, so k (violation count)
and n (record count) for P1, P2, P3 can be computed for the whole corpus
without any network call -- this is exactly the gap flagged in this
project's own disclosed limitations list ("epsilon_tol/alpha have no
calibration script written against them yet, unlike theta_admit/
theta_reject/theta_auth, which have all had a real calibration attempt").

METHODOLOGY:
  1. For every dataset in the corpus, compute k/n for P1, P2, P3 directly
     (Clopper-Pearson p-value and the current non_trivial flag at
     epsilon_tol=0.001, alpha_corrected=0.01/3, exactly as
     hard_override.py's _clopper_pearson_p1_p3 does it).
  2. Among known_good real datasets, find the MAXIMUM observed violation
     fraction per test -- the worst-case benign noise DATA-CERTIFY must
     NOT hard-reject. P1-P3 are deterministic impossibilities, so the
     a-priori expectation is that every genuine real dataset scores
     k=0 on all three; this script checks that expectation empirically
     rather than assuming it.
  3. Among known_bad datasets specifically engineered to trip a P1-P3
     bound (corpus_manifest.csv's corruption_type == "depth_implausible",
     which directly targets P2 -- see calibration/corrupt.py's own
     docstring: "directly the P1-P3 hard-gate on depth checks"), find the
     WEAKEST (lowest-fraction) case DATA-CERTIFY must still catch.
  4. Report whether the CURRENT (epsilon_tol=0.001, alpha=0.01) combination
     is empirically confirmed: zero known_good false non_trivial flags,
     and the weakest known-bad depth_implausible case still correctly
     flagged non_trivial with a comfortable p-value margin.
  5. Unlike theta_admit/theta_reject (which had a continuous T(D) score to
     find a clean boundary value for), P1-P3 violations are expected to be
     either ~0% (genuine data) or 5%-50% (deliberately injected, per
     corrupt.py's depth_implausible severity range) -- i.e. this corpus is
     NOT expected to contain any examples near the epsilon_tol=0.001
     boundary itself, only far below it (known_good) or far above it
     (known_bad). This script explicitly checks for and reports that gap,
     rather than manufacturing a false sense of fine-grained calibration
     the data doesn't support -- exactly the kind of honest "cannot be
     usefully tightened further from this corpus" finding already used
     elsewhere in this project (e.g. P9/I4's EWM AHP-prior retention).

This script never edits data_certify/_constants.py directly -- same
discipline as calibrate_theta_auth.py. Findings are printed and written to
a report for a human to review.

Output: calibration/hard_override_calibration_report.json +
        calibration/hard_override_calibration_report.md

Usage:
    python3 calibration/calibrate_hard_override_params.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import ALPHA, ALPHA_CORRECTED, EPSILON_TOL, HARD_OVERRIDE_FAMILY_SIZE
from data_certify.axis_plausibility import p1_violation_mask, p2_violation_mask, p3_violation_mask
from data_certify.schema import load_dataset_csv
from data_certify import stats

MANIFEST_PATH = HERE / "corpus_manifest.csv"
REPORT_JSON_PATH = HERE / "hard_override_calibration_report.json"
REPORT_MD_PATH = HERE / "hard_override_calibration_report.md"

# Candidate tighter epsilon_tol values to test for empirical justification,
# in descending order from the current provisional prior.
CANDIDATE_EPSILON_TOL_VALUES = [0.001, 0.0005, 0.0002, 0.0001, 0.00005, 0.00001]


def score_one(dataset_id: str, label: str) -> dict:
    ds_path = ROOT / "datasets" / dataset_id / "records.csv"
    ds = load_dataset_csv(ds_path, name=dataset_id)
    n = ds.n
    masks = {"P1": p1_violation_mask(ds), "P2": p2_violation_mask(ds), "P3": p3_violation_mask(ds)}
    row = {"dataset_id": dataset_id, "label": label, "n_records": n}
    any_non_trivial = False
    for name, mask in masks.items():
        k = int(mask.sum())
        frac = (k / n) if n > 0 else float("nan")
        p_value = stats.clopper_pearson_upper_tail(k, n, EPSILON_TOL) if n > 0 else float("nan")
        non_trivial = bool(p_value < ALPHA_CORRECTED) if n > 0 else False
        any_non_trivial = any_non_trivial or non_trivial
        row[f"{name}_k"] = k
        row[f"{name}_n"] = n
        row[f"{name}_frac"] = frac
        row[f"{name}_p_value"] = p_value
        row[f"{name}_non_trivial"] = non_trivial
    row["any_non_trivial"] = any_non_trivial
    return row


def main() -> None:
    manifest = pd.read_csv(MANIFEST_PATH)
    rows = []
    errors = []
    for _, r in manifest.iterrows():
        try:
            rows.append(score_one(r["dataset_id"], r["label"]))
        except Exception as e:
            errors.append({"dataset_id": r["dataset_id"], "error": f"{type(e).__name__}: {e}"})
    df = pd.DataFrame(rows)
    manifest_ct = manifest[["dataset_id", "corruption_type", "severity"]]
    df = df.merge(manifest_ct, on="dataset_id", how="left")

    good = df[df.label == "known_good"]
    bad = df[df.label == "known_bad"]
    depth_implausible = df[df["corruption_type"] == "depth_implausible"]

    # --- Empirical ceiling: worst (highest) benign violation fraction among
    # known_good, per test -- what epsilon_tol must clear to avoid a false
    # hard-reject on genuine data.
    good_worst = {}
    for name in ["P1", "P2", "P3"]:
        idx = good[f"{name}_frac"].idxmax()
        good_worst[name] = {
            "dataset_id": good.loc[idx, "dataset_id"],
            "k": int(good.loc[idx, f"{name}_k"]),
            "n": int(good.loc[idx, f"{name}_n"]),
            "frac": float(good.loc[idx, f"{name}_frac"]),
        }

    # --- Empirical floor: weakest deliberate P2 violation (depth_implausible
    # family) DATA-CERTIFY must still catch.
    bad_weakest_p2 = None
    if len(depth_implausible) > 0:
        idx = depth_implausible["P2_frac"].idxmin()
        bad_weakest_p2 = {
            "dataset_id": depth_implausible.loc[idx, "dataset_id"],
            "severity": depth_implausible.loc[idx, "severity"],
            "k": int(depth_implausible.loc[idx, "P2_k"]),
            "n": int(depth_implausible.loc[idx, "P2_n"]),
            "frac": float(depth_implausible.loc[idx, "P2_frac"]),
            "p_value": float(depth_implausible.loc[idx, "P2_p_value"]),
            "non_trivial": bool(depth_implausible.loc[idx, "P2_non_trivial"]),
        }

    # --- Does any known_good dataset get wrongly flagged non_trivial at the
    # CURRENT epsilon_tol/alpha? (False-hard-reject check.)
    good_false_positives = good[good["any_non_trivial"]]["dataset_id"].tolist()

    # --- Does every depth_implausible known_bad case get correctly flagged?
    bad_p2_missed = depth_implausible[~depth_implausible["P2_non_trivial"]]["dataset_id"].tolist() \
        if len(depth_implausible) > 0 else []

    # --- Is there any P1-P3 violation in this corpus AT ALL among known_good
    # real datasets? (Tells us whether the corpus has any informative signal
    # near the epsilon_tol boundary, vs. only far-below/far-above examples.)
    any_good_violation = bool((good[["P1_k", "P2_k", "P3_k"]].sum(axis=1) > 0).any())

    # --- Tightest candidate epsilon_tol that still produces zero known_good
    # false positives and zero missed depth_implausible known_bad cases
    # (only meaningful to report if the corpus actually has informative
    # examples near the boundary; otherwise every candidate will trivially
    # pass, which this script says explicitly rather than implying a
    # meaningful recalibration happened).
    candidate_results = []
    for cand in CANDIDATE_EPSILON_TOL_VALUES:
        gfp = []
        for _, r in good.iterrows():
            for name in ["P1", "P2", "P3"]:
                k, n = int(r[f"{name}_k"]), int(r[f"{name}_n"])
                if n > 0:
                    p = stats.clopper_pearson_upper_tail(k, n, cand)
                    if p < ALPHA_CORRECTED:
                        gfp.append((r["dataset_id"], name))
        bmissed = []
        for _, r in depth_implausible.iterrows():
            k, n = int(r["P2_k"]), int(r["P2_n"])
            p = stats.clopper_pearson_upper_tail(k, n, cand)
            if not (p < ALPHA_CORRECTED):
                bmissed.append(r["dataset_id"])
        candidate_results.append({
            "epsilon_tol": cand,
            "known_good_false_positives": gfp,
            "known_bad_depth_implausible_missed": bmissed,
            "clean": (len(gfp) == 0 and len(bmissed) == 0),
        })

    report = {
        "current_epsilon_tol": EPSILON_TOL,
        "current_alpha": ALPHA,
        "current_alpha_corrected": ALPHA_CORRECTED,
        "hard_override_family_size": HARD_OVERRIDE_FAMILY_SIZE,
        "n_known_good": int(len(good)),
        "n_known_bad": int(len(bad)),
        "n_depth_implausible_known_bad": int(len(depth_implausible)),
        "errors": errors,
        "known_good_worst_case_violation_fraction_per_test": good_worst,
        "known_bad_weakest_depth_implausible_case": bad_weakest_p2,
        "known_good_false_positives_at_current_params": good_false_positives,
        "known_bad_depth_implausible_missed_at_current_params": bad_p2_missed,
        "any_p1_p3_violation_among_known_good": any_good_violation,
        "candidate_epsilon_tol_sweep": candidate_results,
    }

    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    lines = []
    lines.append("# epsilon_tol / alpha (P1-P3 hard-override) Calibration Report\n")
    lines.append(f"Corpus: {len(df)} datasets scored locally (no live network required) "
                  f"-- {len(good)} known_good, {len(bad)} known_bad "
                  f"({len(depth_implausible)} of which specifically inject P1-P3 violations "
                  f"via the `depth_implausible` corruption, targeting P2).\n")
    lines.append(f"Current: `epsilon_tol = {EPSILON_TOL}`, `alpha = {ALPHA}` "
                  f"(Bonferroni-corrected to `{ALPHA_CORRECTED:.5f}` over the fixed m={HARD_OVERRIDE_FAMILY_SIZE} "
                  f"family {{P1, P2, P3}}).\n")

    lines.append("## Known-good worst-case violation fraction per test\n")
    lines.append("| Test | dataset_id | k | n | fraction |\n|---|---|---|---|---|")
    for name, d in good_worst.items():
        lines.append(f"| {name} | {d['dataset_id']} | {d['k']} | {d['n']} | {d['frac']:.6f} |")

    lines.append("\n## Known-bad `depth_implausible` cases (targets P2)\n")
    lines.append("| dataset_id | severity | k | n | fraction | p_value | non_trivial (correctly caught) |\n|---|---|---|---|---|---|---|")
    for _, r in depth_implausible.sort_values("P2_frac").iterrows():
        lines.append(f"| {r['dataset_id']} | {r['severity']} | {int(r['P2_k'])} | {int(r['P2_n'])} | "
                      f"{r['P2_frac']:.4f} | {r['P2_p_value']:.2e} | {r['P2_non_trivial']} |")

    lines.append("\n## Result\n")
    if not any_good_violation:
        lines.append(
            "**No known_good real dataset in this 73-dataset corpus exhibits ANY P1-P3 "
            "violation (k=0 for P1, P2, and P3 on every one of the known_good datasets).** "
            "This is the expected outcome for deterministic geometric/physical bounds on "
            "genuine data, but it also means this corpus contains **no informative examples "
            "near the epsilon_tol boundary itself** -- only zero-violation known_good "
            "datasets on one side and deliberately-injected 5%-50%-violation known_bad "
            "datasets on the other (see the depth_implausible table above), a gap of several "
            "orders of magnitude either side of any plausible epsilon_tol value. "
            "**Consequently, epsilon_tol/alpha cannot be usefully tightened OR loosened "
            "from this corpus** -- every candidate value swept below "
            f"(from {CANDIDATE_EPSILON_TOL_VALUES[0]} down to {CANDIDATE_EPSILON_TOL_VALUES[-1]}) "
            "produces an identical, clean result (zero known_good false positives, zero "
            "known_bad depth_implausible cases missed), because the real corpus data never "
            "actually lands near the boundary either parameter controls. This is the same "
            "kind of honest 'no informative signal to calibrate from' finding already "
            "disclosed elsewhere in this project for P9/I4 (EWM). "
            f"**`epsilon_tol = {EPSILON_TOL}` and `alpha = {ALPHA}` are left unchanged** -- "
            "empirically confirmed as producing zero false-positives/false-negatives on "
            "the current corpus, but still a provisional prior in the sense that no dataset "
            "with a genuinely marginal (neither ~0% nor ~5-50%) P1-P3 violation rate has "
            "ever been observed to test the boundary itself."
        )
    else:
        lines.append(
            "**At least one known_good dataset exhibits a nonzero P1-P3 violation rate** "
            "-- see the worst-case table above. This is new empirical information: it means "
            "epsilon_tol must be set at or above that observed rate to avoid a false "
            "hard-reject on genuine data. Review the worst-case entries above before "
            "changing epsilon_tol/alpha."
        )
    if good_false_positives:
        lines.append(f"\n**WARNING: known_good datasets wrongly flagged non_trivial at current "
                      f"params:** {good_false_positives}")
    if bad_p2_missed:
        lines.append(f"\n**WARNING: known_bad depth_implausible datasets NOT caught at current "
                      f"params:** {bad_p2_missed}")
    if not good_false_positives and not bad_p2_missed:
        lines.append(f"\n**Current params confirmed clean:** 0 known_good false-hard-rejects, "
                      f"0 known_bad `depth_implausible` cases missed.")

    lines.append("\n## Candidate epsilon_tol sweep (informational -- corpus has no boundary examples, "
                  "see Result above)\n")
    lines.append("| epsilon_tol | known_good false positives | known_bad depth_implausible missed | clean |\n|---|---|---|---|")
    for c in candidate_results:
        lines.append(f"| {c['epsilon_tol']} | {c['known_good_false_positives']} | "
                      f"{c['known_bad_depth_implausible_missed']} | {c['clean']} |")

    if errors:
        lines.append(f"\n## Errors ({len(errors)} datasets failed to load)\n")
        for e in errors:
            lines.append(f"- {e['dataset_id']}: {e['error']}")

    with open(REPORT_MD_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"JSON report -> {REPORT_JSON_PATH}")
    print(f"Markdown report -> {REPORT_MD_PATH}")
    print()
    print("=" * 70)
    if not any_good_violation and not good_false_positives and not bad_p2_missed:
        print(f"CONFIRMED CLEAN, NO BOUNDARY DATA: epsilon_tol={EPSILON_TOL}, alpha={ALPHA} "
              f"left UNCHANGED (empirically confirmed, but corpus has no examples near the "
              f"boundary either parameter controls).")
    elif good_false_positives or bad_p2_missed:
        print(f"PROBLEM FOUND: known_good false positives={good_false_positives}, "
              f"known_bad missed={bad_p2_missed} -- review before trusting current params.")
    print("=" * 70)


if __name__ == "__main__":
    main()
