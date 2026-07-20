# -*- coding: utf-8 -*-
"""
calibration/refit_full_corpus.py -- Group C2 STAGE 2.

METHODOLOGY (per explicit user sign-off, 2026-07-12): "B" -- use the
dev/validation/locked-test split (calibration/split_corpus.py, Stage 1) to
PROVE the methodology generalizes (the locked-test numbers are the
generalization evidence cited in the paper), then refit the FINAL
PRODUCTION weights from the FULL 968-dataset corpus -- standard ML practice
(report held-out performance from a split, ship a model trained on all
available data, since there is no reason to discard 30% of a small,
expensively-curated corpus once the split has already done its job of
proving the methodology is not overfit).

THIS SCRIPT IS READ-ONLY / REPORT-ONLY, same posture as split_corpus.py's
Stage 1: it computes what the full-corpus refit WOULD be and reports the
exact diff against the CURRENT data_certify/_constants.py values. It does
NOT write to _constants.py itself -- that edit is applied separately (by a
human reviewing this report), specifically so a change this consequential
(it can alter every downstream ADMIT/CONDITIONAL/REJECT decision in the
whole framework) always has an explicit, reviewed, auditable diff rather
than a script silently rewriting its own governing constants.

WHAT THIS SCRIPT DOES:
  1. Refits (axis_weights, within_weights) from the ENTIRE 968-dataset
     corpus, using EXACTLY compute_ewm.py's own methodology (reused
     directly via split_corpus.py's refit_weights(), not reimplemented).
  2. Picks (theta_admit, theta_reject) from the SAME full corpus under
     those refit weights, using EXACTLY the same grid-search rule
     split_corpus.py's Stage 1 used for its validation split
     (pick_thresholds(), reused directly).
  3. Reports the full diff: every axis weight, every within-axis weight,
     both thresholds, current vs. refit, plus the resulting false-admit/
     false-reject rates on the full corpus under each weight set.
  4. Writes calibration/group_c_reports/refit_full_corpus_report.json/.txt.

WHY THIS SHOULD (IN THE COMMON CASE) REPRODUCE CURRENT PRODUCTION ALMOST
EXACTLY: data_certify/_constants.py's current AXIS_WEIGHTS/WITHIN_*/
THETA_ADMIT/THETA_REJECT were themselves already calibrated against this
exact 968-dataset corpus (calibration/compute_ewm.py + calibrate_
thresholds.py's own prior runs) -- so if nothing about the corpus or the
per-sub-criterion raw scores has changed since that calibration pass, this
script's refit should reproduce those same numbers (up to grid-step
resolution on the thresholds, since this script's pick_thresholds() is a
mechanical 0.005-step grid search, while the ORIGINAL theta_admit=0.75/
theta_reject=0.20 in _constants.py were picked by hand-inspecting the T(D)
distribution against "clean round values," not a mechanical grid). A large
divergence would indicate either the corpus changed since the last
calibration pass, or a genuine bug in one of the two independent
implementations -- either way, worth a close look before touching anything.

Usage:
    python3 calibration/refit_full_corpus.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(CALIBRATION_DIR) not in sys.path:
    sys.path.insert(0, str(CALIBRATION_DIR))

from _analysis_common import (  # noqa: E402
    AXES, composite_score, assign_decision, fmt_rate_ci, load_corpus,
)
from split_corpus import refit_weights, pick_thresholds  # noqa: E402
from data_certify._constants import (  # noqa: E402
    AXIS_WEIGHTS, WITHIN_A, WITHIN_P, WITHIN_C, WITHIN_I, THETA_ADMIT, THETA_REJECT,
)

WITHIN_PRODUCTION = {"A": WITHIN_A, "P": WITHIN_P, "C": WITHIN_C, "I": WITHIN_I}
REPORT_DIR = CALIBRATION_DIR / "group_c_reports"


def main() -> None:
    REPORT_DIR.mkdir(exist_ok=True)
    df = load_corpus(include_adversarial=False)
    print("=" * 100)
    print("Group C2 STAGE 2: full-corpus (n=968) production refit -- REPORT ONLY, does not write _constants.py")
    print("=" * 100)
    print(f"Corpus: n={len(df)}")
    print()

    axis_w, within_w, diag = refit_weights(df)
    print("--- Axis weights: current production vs. full-corpus refit ---")
    axis_diffs = {}
    for k in AXES:
        cur, new = AXIS_WEIGHTS[k], axis_w[k]
        axis_diffs[k] = new - cur
        print(f"  {k}: current={cur:.6f}  refit={new:.6f}  diff={new - cur:+.6f}")
    print()

    print("--- Within-axis weights: nonzero diffs (>1e-4) ---")
    within_diffs = {}
    any_diff = False
    for axis in AXES:
        for k in within_w[axis]:
            v = within_w[axis][k] - WITHIN_PRODUCTION[axis][k]
            within_diffs[f"{axis}.{k}"] = v
            if abs(v) > 1e-4:
                any_diff = True
                print(f"  {axis}.{k}: current={WITHIN_PRODUCTION[axis][k]:.6f} "
                      f"refit={within_w[axis][k]:.6f} diff={v:+.6f}")
    if not any_diff:
        print("  (none -- within-axis weights match current production to within 1e-4)")
    print()

    theta_admit, theta_reject = pick_thresholds(df, axis_w, within_w)
    print("--- Thresholds: current production vs. full-corpus refit ---")
    print(f"  theta_admit:  current={THETA_ADMIT}  refit={theta_admit}")
    print(f"  theta_reject: current={THETA_REJECT}  refit={theta_reject}")
    print()

    t_d_refit = composite_score(df, axis_w, within_w)
    hof = df["hard_override_fired"].fillna(False).astype(bool)
    dec_refit = assign_decision(t_d_refit, hof, theta_admit, theta_reject)

    t_d_prod = composite_score(df, AXIS_WEIGHTS, WITHIN_PRODUCTION)
    dec_prod = assign_decision(t_d_prod, hof, THETA_ADMIT, THETA_REJECT)

    good = df["label"] == "known_good"
    bad = df["label"] == "known_bad"

    def _rates(dec):
        fa = int(((dec == "ADMIT") & bad).sum())
        fr = int(((dec == "REJECT") & good).sum())
        return {"false_admit": fmt_rate_ci(fa, int(bad.sum())),
                "false_reject": fmt_rate_ci(fr, int(good.sum())),
                "false_admit_k": fa, "false_reject_k": fr}

    refit_rates = _rates(dec_refit)
    prod_rates = _rates(dec_prod)
    print("--- False-admit/false-reject on the full corpus, under each weight set ---")
    print(f"  refit      : false_admit={refit_rates['false_admit']}  false_reject={refit_rates['false_reject']}")
    print(f"  production : false_admit={prod_rates['false_admit']}  false_reject={prod_rates['false_reject']}")
    print()

    agree = (dec_refit.values == dec_prod.values)
    n_disagree = int((~agree).sum())
    print(f"--- Decision agreement, refit vs. current production (same full corpus) ---")
    print(f"  agreement_rate={agree.mean():.6f}  n_disagree={n_disagree}/{len(df)}")
    if n_disagree > 0:
        disagree_df = df.loc[~agree, ["dataset_id", "label", "group"]].copy()
        disagree_df["decision_refit"] = dec_refit.loc[~agree].values
        disagree_df["decision_production"] = dec_prod.loc[~agree].values
        print(disagree_df.to_string(index=False))
        disagree_records = disagree_df.to_dict(orient="records")
    else:
        disagree_records = []
    print()

    max_axis_diff = max(abs(v) for v in axis_diffs.values())
    max_within_diff = max(abs(v) for v in within_diffs.values()) if within_diffs else 0.0
    threshold_changed = (abs(theta_admit - THETA_ADMIT) > 1e-9) or (abs(theta_reject - THETA_REJECT) > 1e-9)
    materially_different = (max_axis_diff > 0.001) or (max_within_diff > 0.001) or threshold_changed or (n_disagree > 0)

    print("=" * 100)
    if materially_different:
        print("RESULT: the full-corpus refit DIFFERS from current production. Review the diff above "
              "before applying it to data_certify/_constants.py.")
    else:
        print("RESULT: the full-corpus refit REPRODUCES current production (within numerical tolerance). "
              "No change to data_certify/_constants.py is needed -- this is a positive validation finding: "
              "the grouped-split, locked-test-set-validated methodology (Stage 1) independently confirms "
              "the weights already in production, rather than producing different numbers.")
    print("=" * 100)

    report = {
        "corpus_n": len(df),
        "axis_weights_current": dict(AXIS_WEIGHTS),
        "axis_weights_refit": {k: float(v) for k, v in axis_w.items()},
        "axis_diffs": {k: float(v) for k, v in axis_diffs.items()},
        "within_weights_refit": {a: {k: float(v) for k, v in within_w[a].items()} for a in AXES},
        "within_diffs": {k: float(v) for k, v in within_diffs.items()},
        "theta_admit_current": THETA_ADMIT, "theta_admit_refit": theta_admit,
        "theta_reject_current": THETA_REJECT, "theta_reject_refit": theta_reject,
        "false_admit_reject_refit": refit_rates,
        "false_admit_reject_production": prod_rates,
        "decision_agreement_rate": float(agree.mean()),
        "n_disagree": n_disagree,
        "disagreeing_datasets": disagree_records,
        "materially_different": materially_different,
    }
    (REPORT_DIR / "refit_full_corpus_report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nFull report written to {REPORT_DIR / 'refit_full_corpus_report.json'}")


if __name__ == "__main__":
    main()
