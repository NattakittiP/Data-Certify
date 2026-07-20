# -*- coding: utf-8 -*-
"""
calibration/split_corpus.py -- Group C2 STAGE 1.

STAGE 1 ONLY, per explicit sign-off: this script builds the grouped
dev/validation/locked-test split and runs three Leave-One-X-Out
cross-validation schemes, and REPORTS what a refit would look like -- it
does NOT write anything to data_certify/_constants.py, does NOT overwrite
score_matrix.csv, and does NOT change any currently-published calibration
number. The actual production refit (Stage 2) is a deliberate, separate
follow-up decision after the CV results here have been reviewed, exactly as
agreed: "build split framework first, show CV results, THEN refit for real."

PREREQUISITE: calibration/corpus_manifest.csv must already have the
`parent_catalog` column (run calibration/derive_parent_catalog.py first,
Group C1). This script refuses to run without it rather than silently
grouping by dataset_id (which would defeat the entire point -- a parent
catalog and its corrupted derivatives would then end up in different
splits, exactly what grouping exists to prevent).

WHAT THIS SCRIPT DOES
======================

(1) Grouped split (70/15/15 dev / validation / locked-test, by dataset
    COUNT, group boundaries respected):
      - Every row sharing a `parent_catalog` value is assigned to the SAME
        split -- a real catalog and every corrupted derivative built from it
        always land together, never split across dev/val/test.
      - Assignment uses a seeded (SPLIT_SEED) greedy longest-processing-time
        balancing over parent_catalog groups (shuffled once, then each group
        assigned to whichever of {dev, val, test} is currently furthest
        below its target row-count fraction) -- this hits close to, but will
        not hit EXACTLY, 70/15/15 by row count, because groups are
        atomic and vary in size (up to 4 rows here); the achieved fractions
        are reported, not silently assumed.
      - dev: used to refit EWM axis + within-axis weights (blended with the
        FIXED AHP prior, exactly compute_ewm.py's own methodology).
      - validation: used to pick theta_admit/theta_reject under the dev-fit
        weights, replicating calibrate_thresholds.py's own documented rule
        (theta_admit = largest grid value admitting zero known_bad;
        theta_reject = below every known_good, above at least the worst
        known_bad) on the validation split specifically.
      - locked test: evaluated EXACTLY ONCE, using the dev-fit weights and
        validation-fit thresholds, to report what the paper's headline
        false-admit/false-reject numbers would look like under this
        methodology. Never touched during weight-fitting or threshold
        selection -- that is the entire point of a locked test set.

(2) Three Leave-One-X-Out cross-validation schemes (robustness checks, not
    used to pick any final number):
      (a) Leave-One-Parent-Catalog-Out: for each parent_catalog group,
          refit weights on every OTHER group's pooled rows, then check
          whether the held-out group's rows get the SAME decision under the
          refit weights as under current production weights + thresholds.
      (b) Leave-One-Region/Network-Out: same idea, grouped by a coarser,
          HEURISTICALLY-derived `region_key` (stripped of known corruption-
          derivation prefixes and _early/_recent temporal suffixes -- see
          `derive_region_key()` docstring for the exact rule and its
          disclosed limitations; this is NOT an authoritative field, same
          spirit as Group B2's fabrication_style disclosure).
      (c) Leave-One-Corruption-Family-Out: for each of the 6 corruption_type
          families, refit weights EXCLUDING that family's rows entirely,
          then check whether that family's rows are still correctly not
          ADMITted under weights that never saw that corruption type during
          fitting -- this is the most direct test of "does the architecture
          generalize to an unseen corruption pattern."

Usage:
    python3 calibration/split_corpus.py [--seed 20260712] [--lopco-sample N]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(CALIBRATION_DIR) not in sys.path:
    sys.path.insert(0, str(CALIBRATION_DIR))

from _analysis_common import (  # noqa: E402
    AXES, WITHIN, composite_score, assign_decision, wilson_ci, fmt_rate_ci, load_corpus,
)
from compute_ewm import (  # noqa: E402
    recompute_axis_columns_from_ahp_prior, compute_group, MIN_EWM_N,
)
from data_certify._constants import (  # noqa: E402
    AXIS_WEIGHTS_AHP_PRIOR, WITHIN_A_AHP_PRIOR, WITHIN_P_AHP_PRIOR,
    WITHIN_C_AHP_PRIOR, WITHIN_I_AHP_PRIOR, AXIS_WEIGHTS, WITHIN_A, WITHIN_P,
    WITHIN_C, WITHIN_I, THETA_ADMIT, THETA_REJECT,
)

WITHIN_AHP_PRIOR = {"A": WITHIN_A_AHP_PRIOR, "P": WITHIN_P_AHP_PRIOR,
                     "C": WITHIN_C_AHP_PRIOR, "I": WITHIN_I_AHP_PRIOR}
WITHIN_PRODUCTION = {"A": WITHIN_A, "P": WITHIN_P, "C": WITHIN_C, "I": WITHIN_I}

REPORT_DIR = CALIBRATION_DIR / "group_c_reports"
SPLIT_SEED = 20260712
TARGET_FRACS = {"dev": 0.70, "validation": 0.15, "locked_test": 0.15}
THETA_GRID_STEP = 0.005


# =============================================================================
# (1) Grouped split
# =============================================================================

def build_grouped_split(df: pd.DataFrame, seed: int = SPLIT_SEED) -> pd.Series:
    """Greedy longest-processing-time-style balancing over parent_catalog
    groups. Returns a Series (indexed like df) of 'dev'/'validation'/
    'locked_test' labels. Deterministic given `seed`."""
    if "parent_catalog" not in df.columns:
        raise RuntimeError(
            "corpus_manifest.csv has no parent_catalog column -- run "
            "calibration/derive_parent_catalog.py (Group C1) first."
        )
    group_sizes = df.groupby("parent_catalog").size()
    n_total = len(df)
    targets = {k: v * n_total for k, v in TARGET_FRACS.items()}
    current = {k: 0 for k in TARGET_FRACS}

    rng = np.random.RandomState(seed)
    parent_ids = group_sizes.index.tolist()
    order = rng.permutation(len(parent_ids))
    parent_ids = [parent_ids[i] for i in order]

    assignment: Dict[str, str] = {}
    for pid in parent_ids:
        size = int(group_sizes[pid])
        # Assign to whichever split is furthest BELOW its target (in
        # absolute row count), i.e. the split with the largest remaining
        # deficit -- a standard greedy balancing heuristic for bin-packing
        # atomic (non-splittable) groups of varying size.
        deficits = {k: targets[k] - current[k] for k in TARGET_FRACS}
        chosen = max(deficits, key=lambda k: deficits[k])
        assignment[pid] = chosen
        current[chosen] += size

    split = df["parent_catalog"].map(assignment)
    split.name = "split"
    return split


# =============================================================================
# Weight refitting (reuses compute_ewm.py's own, already-validated functions)
# =============================================================================

def refit_weights(df_subset: pd.DataFrame) -> Tuple[Dict[str, float], Dict[str, Dict[str, float]], Dict]:
    """Refit (axis_weights, within_weights) from df_subset only, using
    EXACTLY compute_ewm.py's own methodology (AHP-prior-anchored axis
    recomputation, then compute_group's retained-vs-computable MIN_EWM_N
    split). Returns (axis_weights, within_weights, diagnostics)."""
    df_ahp_axis = recompute_axis_columns_from_ahp_prior(df_subset)
    axis_result = compute_group(df_ahp_axis, dict(AXIS_WEIGHTS_AHP_PRIOR), "axis")
    axis_weights = axis_result["blended_weights"]

    within_weights = {}
    within_diag = {}
    for axis in AXES:
        ahp_prior = WITHIN_AHP_PRIOR[axis]
        result = compute_group(df_subset, dict(ahp_prior), f"within-{axis}")
        within_weights[axis] = result["blended_weights"]
        within_diag[axis] = {"n_obs": result["n_obs"], "computable": result["computable"],
                              "retained_ahp_only": result["retained_ahp_only"]}

    diagnostics = {"n_rows": len(df_subset), "axis_n_obs": axis_result["n_obs"],
                    "axis_retained_ahp_only": axis_result["retained_ahp_only"],
                    "within": within_diag}
    return axis_weights, within_weights, diagnostics


def pick_thresholds(df_val: pd.DataFrame, axis_weights: Dict[str, float],
                     within_weights: Dict[str, Dict[str, float]]) -> Tuple[float, float]:
    """Replicates calibrate_thresholds.py's documented rule on df_val:
    theta_admit = largest THETA_GRID_STEP-spaced value such that ZERO
    known_bad (hard-override-fired excluded, since those are already
    caught by Stage 1 regardless of T(D)) clears it; theta_reject = largest
    grid value strictly BELOW every known_good T(D) (so no real known_good
    catalog in this split would be auto-REJECTed by T(D) alone)."""
    t_d = composite_score(df_val, axis_weights, within_weights)
    good = t_d[df_val["label"] == "known_good"]
    bad_soft = t_d[(df_val["label"] == "known_bad") & (~df_val["hard_override_fired"].fillna(False).astype(bool))]

    grid = np.arange(0.0, 1.0 + THETA_GRID_STEP, THETA_GRID_STEP)

    # theta_admit = the SMALLEST grid value that already excludes every
    # known_bad score (maximizes the ADMIT zone for known_good while still
    # admitting zero known_bad) -- NOT the largest such value: once a
    # threshold clears every bad score, EVERY larger threshold trivially
    # clears it too (monotonic), so "largest" would degenerate toward 1.0
    # and admit almost nothing. Scan upward and stop at the first g where
    # the condition holds. (Matches production's actual calibrated value,
    # theta_admit=0.75 -- a tight, practical bound, not a maximal one.)
    theta_admit = 1.0
    for g in grid:
        if bad_soft.empty or (bad_soft < g).all():
            theta_admit = float(g)
            break

    theta_reject = 0.0
    good_min = float(good.min()) if not good.empty else 1.0
    for g in grid:
        if g < good_min:
            theta_reject = float(g)
        else:
            break

    if theta_reject > theta_admit:
        theta_reject = theta_admit  # degenerate-split guard; disclosed via caller's diagnostics
    return theta_admit, theta_reject


def evaluate(df: pd.DataFrame, axis_weights: Dict[str, float],
             within_weights: Dict[str, Dict[str, float]],
             theta_admit: float, theta_reject: float) -> Dict:
    t_d = composite_score(df, axis_weights, within_weights)
    hof = df["hard_override_fired"].fillna(False).astype(bool)
    decision = assign_decision(t_d, hof, theta_admit, theta_reject)

    good_mask = df["label"] == "known_good"
    bad_mask = df["label"] == "known_bad"
    false_reject = int(((decision == "REJECT") & good_mask).sum())
    false_admit = int(((decision == "ADMIT") & bad_mask).sum())
    n_good, n_bad = int(good_mask.sum()), int(bad_mask.sum())
    return {
        "n": len(df), "n_known_good": n_good, "n_known_bad": n_bad,
        "false_reject_rate": fmt_rate_ci(false_reject, n_good) if n_good else "n/a",
        "false_admit_rate": fmt_rate_ci(false_admit, n_bad) if n_bad else "n/a",
        "false_reject_k": false_reject, "false_admit_k": false_admit,
        "decision_counts": decision.value_counts().to_dict(),
    }


# =============================================================================
# (2) Leave-One-X-Out CV
# =============================================================================

_EARLY_RECENT_RE = re.compile(r"_(early|recent)$")
_CORRUPT_PREFIX_RE = re.compile(
    r"^corrupt_real_(.+?)_(coordinate_jitter|depth_implausible|inject_duplicates|"
    r"inject_missingness|magnitude_gr_violation|timestamp_collision)_(low|med|high)$"
)


def derive_region_key(parent_catalog_id: str) -> str:
    """
    HEURISTIC, non-authoritative regional/network grouping key, coarser than
    parent_catalog -- collapses e.g. real_china_yunnan_general,
    real_china_yunnan_general_early, and real_china_yunnan_general_recent
    (three DIFFERENT parent_catalog values, same underlying region/network,
    different time windows of the same real network's reporting) into one
    'china_yunnan_general' region_key, and strips corrupted rows' full
    corrupt_real_<parent>_<type>_<severity> naming down to the same
    <parent>-derived key their real parent would get.

    DISCLOSED LIMITATION: this is a string-pattern heuristic over dataset_id/
    parent_catalog naming conventions actually used when this corpus was
    built, not a structured, independently-sourced network/region field (no
    such field exists anywhere in this corpus). It is good enough to
    meaningfully diversify Leave-One-Region-Out folds beyond
    Leave-One-Parent-Catalog-Out's finer grain, but should not be presented
    as an authoritative geographic/network taxonomy -- same disclosure
    posture as Group B2's fabrication_style heuristic.
    """
    key = parent_catalog_id
    m = _CORRUPT_PREFIX_RE.match(key)
    if m:
        key = m.group(1)
    key = key[len("real_"):] if key.startswith("real_") else key
    key = _EARLY_RECENT_RE.sub("", key)
    return key


def leave_one_x_out(df: pd.DataFrame, group_key: str, sample_n: int = None,
                     seed: int = SPLIT_SEED) -> List[Dict]:
    """For each distinct value of `group_key` (a column already present in
    df), refit weights on every OTHER row, then compare the held-out
    group's decisions under the refit weights (CURRENT production
    thresholds -- re-picking thresholds from 1-4 held-out points per fold
    would not be meaningful) against the decisions under current PRODUCTION
    weights+thresholds. Reports per-fold agreement rate. If sample_n is
    given and there are more groups than that, a seeded random sample of
    groups is evaluated instead of all of them (disclosed in the output),
    to keep runtime bounded for the finest-grained grouping."""
    groups = df[group_key].dropna().unique().tolist()
    sampled = False
    if sample_n is not None and len(groups) > sample_n:
        rng = np.random.RandomState(seed)
        groups = list(rng.choice(groups, size=sample_n, replace=False))
        sampled = True

    baseline_t_d = composite_score(df, AXIS_WEIGHTS, WITHIN_PRODUCTION)
    baseline_decision = assign_decision(
        baseline_t_d, df["hard_override_fired"].fillna(False).astype(bool),
        THETA_ADMIT, THETA_REJECT,
    )

    results = []
    for g in groups:
        held_out_mask = df[group_key] == g
        train_df = df[~held_out_mask]
        held_out_df = df[held_out_mask]
        if len(train_df) < 50 or held_out_df.empty:
            continue  # too few rows left to fit anything meaningful

        axis_w, within_w, _ = refit_weights(train_df)
        refit_t_d = composite_score(held_out_df, axis_w, within_w)
        refit_decision = assign_decision(
            refit_t_d, held_out_df["hard_override_fired"].fillna(False).astype(bool),
            THETA_ADMIT, THETA_REJECT,  # current production thresholds, deliberately not re-picked per fold
        )
        agree = (refit_decision.values == baseline_decision.loc[held_out_df.index].values)
        results.append({
            "group": str(g), "n_held_out": len(held_out_df),
            "agreement_rate": float(np.mean(agree)),
            "n_disagree": int((~agree).sum()),
            "disagreeing_dataset_ids": held_out_df.loc[~agree, "dataset_id"].tolist()
                                        if "dataset_id" in held_out_df.columns else [],
        })

    return results, sampled


def summarize_lopco(results: List[Dict], sampled: bool, scheme_name: str) -> str:
    if not results:
        return f"{scheme_name}: no folds evaluated (all groups too small)."
    total_held_out = sum(r["n_held_out"] for r in results)
    total_disagree = sum(r["n_disagree"] for r in results)
    weighted_agree = 1.0 - (total_disagree / total_held_out if total_held_out else 0.0)
    sample_note = f" (sampled {len(results)} folds, not exhaustive)" if sampled else f" ({len(results)} folds, exhaustive)"
    lines = [f"{scheme_name}{sample_note}: {total_held_out} held-out rows across all folds, "
             f"{total_disagree} decision disagreements vs. current production weights "
             f"(row-weighted agreement rate = {weighted_agree:.4f})."]
    worst = sorted(results, key=lambda r: r["agreement_rate"])[:5]
    lines.append("  Worst 5 folds by agreement rate:")
    for r in worst:
        lines.append(f"    {r['group']}: {r['agreement_rate']:.4f} agreement "
                      f"(n_held_out={r['n_held_out']}, n_disagree={r['n_disagree']})")
    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=SPLIT_SEED)
    parser.add_argument("--lopco-sample", type=int, default=150,
                         help="Cap on number of Leave-One-Parent-Catalog-Out folds actually run "
                              "(there are ~795 parent_catalog groups; refitting weights for every "
                              "single one is safe but slow). Set to 0 to disable sampling (run all).")
    args = parser.parse_args()

    REPORT_DIR.mkdir(exist_ok=True)

    df = load_corpus(include_adversarial=False)  # held-out adversarial set stays untouched, as always
    if "parent_catalog" not in df.columns:
        print("ERROR: corpus_manifest.csv has no parent_catalog column.\n"
              "Run calibration/derive_parent_catalog.py first (Group C1) -- this script refuses "
              "to fabricate a fallback grouping, since silently grouping by dataset_id instead "
              "would let a parent catalog and its corrupted derivatives land in different splits, "
              "defeating the entire purpose of this exercise.", file=sys.stderr)
        sys.exit(1)

    print("=" * 100)
    print("Group C2 STAGE 1: grouped split + Leave-One-X-Out cross-validation")
    print("(Framework + CV report only -- NOT a production refit. See module docstring.)")
    print("=" * 100)
    print(f"Corpus: n={len(df)}, {df['parent_catalog'].nunique()} distinct parent_catalog groups.")
    print()

    # --- (1) grouped split ---
    split = build_grouped_split(df, seed=args.seed)
    df = df.assign(split=split)
    split_counts = df["split"].value_counts()
    print("--- Split sizes (target 70/15/15 by row count, group boundaries respected) ---")
    for name in ["dev", "validation", "locked_test"]:
        n = int(split_counts.get(name, 0))
        print(f"  {name:12s}: {n:4d} rows ({n / len(df):.1%}), "
              f"target {TARGET_FRACS[name]:.0%}")
    print()

    dev_df = df[df["split"] == "dev"]
    val_df = df[df["split"] == "validation"]
    test_df = df[df["split"] == "locked_test"]

    for name, d in [("dev", dev_df), ("validation", val_df), ("locked_test", test_df)]:
        n_good = int((d["label"] == "known_good").sum())
        n_bad = int((d["label"] == "known_bad").sum())
        print(f"  {name:12s}: known_good={n_good}, known_bad={n_bad}")
    print()

    # --- refit on dev, pick thresholds on validation, evaluate ONCE on locked_test ---
    print("--- Refitting weights on dev split ---")
    axis_w, within_w, fit_diag = refit_weights(dev_df)
    print(f"  Axis weights (dev-refit): {axis_w}")

    print("--- Picking thresholds on validation split (dev-refit weights) ---")
    theta_admit, theta_reject = pick_thresholds(val_df, axis_w, within_w)
    print(f"  theta_admit={theta_admit:.3f}, theta_reject={theta_reject:.3f} "
          f"(current production: {THETA_ADMIT}/{THETA_REJECT})")

    print("--- Evaluating ONCE on locked test split ---")
    test_result = evaluate(test_df, axis_w, within_w, theta_admit, theta_reject)
    print(f"  n={test_result['n']}, false_admit={test_result['false_admit_rate']}, "
          f"false_reject={test_result['false_reject_rate']}")
    print(f"  decision_counts={test_result['decision_counts']}")

    # For comparison: what does CURRENT PRODUCTION (weights+thresholds fit on
    # the FULL corpus, no split) score on this same locked_test subset?
    prod_result = evaluate(test_df, AXIS_WEIGHTS, WITHIN_PRODUCTION, THETA_ADMIT, THETA_REJECT)
    print(f"  (for comparison) current production weights on the same locked_test rows: "
          f"false_admit={prod_result['false_admit_rate']}, false_reject={prod_result['false_reject_rate']}")
    print()

    # --- (2) Leave-One-X-Out CV ---
    print("--- Leave-One-Parent-Catalog-Out ---")
    lopco_n = None if args.lopco_sample == 0 else args.lopco_sample
    lopco_results, lopco_sampled = leave_one_x_out(df, "parent_catalog", sample_n=lopco_n, seed=args.seed)
    print(summarize_lopco(lopco_results, lopco_sampled, "Leave-One-Parent-Catalog-Out"))
    print()

    print("--- Leave-One-Region/Network-Out (heuristic region_key -- see derive_region_key docstring) ---")
    df["region_key"] = df["parent_catalog"].apply(derive_region_key)
    print(f"  {df['region_key'].nunique()} distinct region_key groups derived from "
          f"{df['parent_catalog'].nunique()} parent_catalog groups.")
    lorno_results, lorno_sampled = leave_one_x_out(df, "region_key", sample_n=lopco_n, seed=args.seed)
    print(summarize_lopco(lorno_results, lorno_sampled, "Leave-One-Region/Network-Out"))
    print()

    print("--- Leave-One-Corruption-Family-Out ---")
    corruption_families = sorted(df.loc[df["label"] == "known_bad", "corruption_type"].dropna().unique())
    print(f"  Families: {corruption_families}")
    lofco_results = []
    baseline_t_d = composite_score(df, AXIS_WEIGHTS, WITHIN_PRODUCTION)
    baseline_decision = assign_decision(
        baseline_t_d, df["hard_override_fired"].fillna(False).astype(bool), THETA_ADMIT, THETA_REJECT,
    )
    for family in corruption_families:
        held_out_mask = df["corruption_type"] == family
        train_df = df[~held_out_mask]
        held_out_df = df[held_out_mask]
        axis_w_f, within_w_f, _ = refit_weights(train_df)
        refit_t_d = composite_score(held_out_df, axis_w_f, within_w_f)
        refit_decision = assign_decision(
            refit_t_d, held_out_df["hard_override_fired"].fillna(False).astype(bool),
            THETA_ADMIT, THETA_REJECT,
        )
        # The question that matters for this scheme specifically: are these
        # held-out-family rows still correctly kept OUT of ADMIT (the
        # scientifically dangerous error) under weights that never saw this
        # corruption type during fitting? Not-ADMIT here includes
        # CONDITIONAL and REJECT, both non-autonomous-acceptance outcomes.
        not_admitted = int((refit_decision != "ADMIT").sum())
        agree = (refit_decision.values == baseline_decision.loc[held_out_df.index].values)
        lofco_results.append({
            "family": family, "n_held_out": len(held_out_df),
            "not_admitted_rate": not_admitted / len(held_out_df) if len(held_out_df) else float("nan"),
            "agreement_rate": float(np.mean(agree)) if len(agree) else float("nan"),
        })
        print(f"  {family:24s} n={len(held_out_df):3d}  "
              f"not_admitted_rate={lofco_results[-1]['not_admitted_rate']:.4f}  "
              f"agreement_vs_production={lofco_results[-1]['agreement_rate']:.4f}")
    print()

    # --- write reports ---
    full_report = {
        "split_seed": args.seed,
        "split_sizes": {k: int(split_counts.get(k, 0)) for k in TARGET_FRACS},
        "dev_refit_axis_weights": axis_w,
        "dev_refit_within_weights": within_w,
        "validation_picked_thresholds": {"theta_admit": theta_admit, "theta_reject": theta_reject},
        "locked_test_result_under_refit": test_result,
        "locked_test_result_under_current_production": prod_result,
        "leave_one_parent_catalog_out": {"sampled": lopco_sampled, "n_folds": len(lopco_results),
                                          "results": lopco_results},
        "leave_one_region_out": {"sampled": lorno_sampled, "n_folds": len(lorno_results),
                                  "results": lorno_results},
        "leave_one_corruption_family_out": lofco_results,
    }
    (REPORT_DIR / "split_corpus_report.json").write_text(json.dumps(full_report, indent=2, default=str))
    print(f"Full report written to {REPORT_DIR / 'split_corpus_report.json'}")
    print()
    print("=" * 100)
    print("STAGE 1 COMPLETE. This did NOT modify data_certify/_constants.py, score_matrix.csv, "
          "or any published number. Review these CV results before deciding whether/how to "
          "proceed to a real production refit (Stage 2, a separate, deliberate follow-up).")
    print("=" * 100)


if __name__ == "__main__":
    main()
