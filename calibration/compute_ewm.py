# -*- coding: utf-8 -*-
"""
calibration/compute_ewm.py -- Compute real Entropy Weight Method (EWM)
weights from the scored calibration corpus (calibration/score_matrix.csv)
and blend them with the FIXED AHP priors in data_certify/_constants.py,
per the exact formulas already specified in
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Sections 5.2
and 5.4:

    p_ij = x_ij / sum_k(x_kj)
    e_j  = -(1/ln(m)) * sum_i( p_ij * ln(p_ij) )
    d_j  = 1 - e_j
    w_j^EWM = d_j / sum_k(d_k)

    w_i  = (w_i^AHP * w_i^EWM) / sum_j(w_j^AHP * w_j^EWM)

Run at BOTH the 4-axis level (A, P, C, I) and the within-axis
sub-criterion level (A1-A5, P4-P9, C1-C4, I1-I5), per the user's explicit
choice when asked (both levels, not axis-only).

*** IMPORTANT: this script MUST import the *_AHP_PRIOR names, NOT
AXIS_WEIGHTS/WITHIN_A/etc. Once a calibration pass has run once,
_constants.py's AXIS_WEIGHTS/WITHIN_A/P/C/I hold the BLENDED (EWM-
adjusted) values -- re-running this script against those (instead of the
fixed AHP priors) would blend an already-blended weight a second time,
silently drifting the "AHP" input further from the actual AHP derivation
on every re-run. The *_AHP_PRIOR constants never change regardless of
calibration and are always the correct input here. ***

MISSING-DATA POLICY (disclosed, not silently handled): several
sub-criteria depend on OPTIONAL schema fields (tsunami_flag,
rupture_length_km/area/displacement, seismic_moment_n_m, mmi/
station_distance_km, event_uid_source) that this corpus -- built
entirely from real public earthquake-catalog exports -- never or almost
never populates (P4/P5/P6/P8/P9 are NaN for every single dataset; I4 is
non-NaN for only a handful). EWM cannot be honestly computed from zero
or near-zero observations. The rule applied here: a sub-criterion needs
at least MIN_EWM_N=20 non-NaN scores across the corpus to get its own
recalibrated w^EWM; below that, it RETAINS its original AHP weight
unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import (
    AXIS_WEIGHTS_AHP_PRIOR as AXIS_WEIGHTS,
    WITHIN_A_AHP_PRIOR as WITHIN_A,
    WITHIN_P_AHP_PRIOR as WITHIN_P,
    WITHIN_C_AHP_PRIOR as WITHIN_C,
    WITHIN_I_AHP_PRIOR as WITHIN_I,
)

SCORE_MATRIX_PATH = Path(__file__).resolve().parent / "score_matrix.csv"
REPORT_JSON_PATH = Path(__file__).resolve().parent / "ewm_report.json"
REPORT_MD_PATH = Path(__file__).resolve().parent / "ewm_report.md"

MIN_EWM_N = 20  # minimum non-NaN observations required to compute w^EWM for a criterion


def entropy_weights_ragged(columns: Dict[str, np.ndarray]) -> Dict[str, float]:
    """
    EWM per Master Reference Section 5.2, applied independently per
    criterion (each criterion's own m_j is however many non-NaN
    observations it has across the corpus -- criteria are allowed to
    have different m_j, since the entropy formula only needs a single
    column's own values and their own sum, not a shared row set across
    criteria).

    Returns {criterion_name: w^EWM}, summing to 1 across the given criteria.
    """
    d: Dict[str, float] = {}
    for name, x in columns.items():
        x = np.asarray(x, dtype=float)
        x = x[np.isfinite(x)]
        m = len(x)
        if m < 2:
            d[name] = 0.0
            continue
        s = float(x.sum())
        if s <= 0:
            d[name] = 0.0
            continue
        p = x / s
        with np.errstate(divide="ignore", invalid="ignore"):
            plogp = np.where(p > 0, p * np.log(p), 0.0)
        e = -1.0 / np.log(m) * float(plogp.sum())
        d[name] = 1.0 - e
    total_d = sum(d.values())
    if total_d <= 0:
        n = len(columns)
        return {k: 1.0 / n for k in columns}
    return {k: v / total_d for k, v in d.items()}


def blend_ahp_ewm(ahp: Dict[str, float], ewm: Dict[str, float]) -> Dict[str, float]:
    """w_i = (w_i^AHP * w_i^EWM) / sum_j(w_j^AHP * w_j^EWM) -- Section 5.4."""
    raw = {k: ahp[k] * ewm[k] for k in ahp}
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}


def compute_group(df: pd.DataFrame, ahp_weights: Dict[str, float], group_name: str) -> Dict:
    """
    Compute EWM + AHP-EWM blend for one weight group (either the 4 axes,
    or the within-axis sub-criteria of a single axis). Criteria with
    fewer than MIN_EWM_N non-NaN observations RETAIN their exact original
    AHP weight, unmodified, rather than being assigned a data-driven
    weight computed from too little data.

    CORRECTNESS NOTE on how "retain the AHP weight" is implemented: an
    earlier draft of this function gave retained criteria a neutral
    ewm=1.0 and put them through the SAME blend-and-renormalize step as
    the computable criteria. That is wrong -- it does not actually leave
    the retained criterion's weight unchanged, because renormalizing a
    mix of "real, usually <1 entropy weights" against a flat 1.0 for the
    retained criterion inflates the retained criterion's SHARE of the
    total whenever the computable criteria's own entropy weights happen
    to be small (which is common: e.g. within-I's I5 had almost no score
    variance across the corpus, giving it a tiny w^EWM, which would have
    let I4 -- retained with only 4/71 observations -- balloon to ~47% of
    the whole I-axis budget purely as an artefact of I5's low entropy,
    not because of any actual I4 evidence). The fix: split the group's
    total AHP budget into a RETAINED share (sum of the retained criteria's
    AHP weights, kept byte-for-byte as their final weight) and a
    COMPUTABLE share (the remainder, 1 minus the retained share), then
    run the AHP x EWM blend ONLY among the computable criteria (their AHP
    weights renormalised to sum to 1 among themselves first) and scale
    the result back down by the computable share. This guarantees a
    retained criterion's final weight is EXACTLY its original AHP value,
    and the computable criteria still compete fairly only against each
    other for the remaining budget.
    """
    n_obs = {k: int(df[k].notna().sum()) for k in ahp_weights}
    computable = [k for k in ahp_weights if n_obs[k] >= MIN_EWM_N]
    retained = [k for k in ahp_weights if k not in computable]

    ewm_computable = entropy_weights_ragged({k: df[k].dropna().values for k in computable}) if computable else {}

    retained_budget = sum(ahp_weights[k] for k in retained)
    computable_budget = 1.0 - retained_budget

    blended: Dict[str, float] = {k: ahp_weights[k] for k in retained}
    if computable:
        ahp_sub_total = sum(ahp_weights[k] for k in computable)
        ahp_sub = {k: ahp_weights[k] / ahp_sub_total for k in computable}
        blended_sub = blend_ahp_ewm(ahp_sub, ewm_computable)
        for k in computable:
            blended[k] = blended_sub[k] * computable_budget

    return {
        "group": group_name,
        "n_obs": n_obs,
        "computable": computable,
        "retained_ahp_only": retained,
        "retained_budget": retained_budget,
        "ahp_weights": ahp_weights,
        "ewm_weights_raw_on_computable": ewm_computable,
        "blended_weights": blended,
    }


def recompute_axis_columns(df: pd.DataFrame, groups: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """
    Recompute the axis-level aggregate columns (A, P, C, I) from the
    per-criterion sub-scores (A1-A5, P4-P9, C1-C4, I1-I5) using an
    EXPLICIT, caller-supplied set of within-axis weights, rather than
    trusting whatever A/P/C/I score_matrix.csv already contains (those
    columns were originally computed by calibration/run_scoring.py calling
    the production score_authenticity()/etc. functions, which combine
    sub-criteria using whatever WITHIN_A/P/C/I happens to be LIVE in
    data_certify/_constants.py at call time -- see
    recompute_axis_columns_from_ahp_prior's docstring below for why that is
    unsafe to trust directly). The per-criterion sub-scores themselves are
    pure statistical computations, independent of any weight, so they are
    always safe to reuse as-is; only the axis-level aggregation is redone
    here, with the exact same renormalized-weighted-average-of-applicable-
    sub-criteria formula the production axis modules use.

    `groups` maps each axis letter to the {criterion: weight} mapping to
    aggregate with -- callers choose which weight basis matters for their
    use case (see the two named wrappers below).
    """
    df = df.copy()
    for axis_letter, weights in groups.items():
        crits = list(weights.keys())
        out = pd.Series(np.nan, index=df.index, dtype=float)
        for i, row in df.iterrows():
            applicable = {k: row[k] for k in crits if pd.notna(row[k])}
            if applicable:
                w_sum = sum(weights[k] for k in applicable)
                out.iloc[df.index.get_loc(i)] = sum(weights[k] * v for k, v in applicable.items()) / w_sum
        df[axis_letter] = out
    return df


def recompute_axis_columns_from_ahp_prior(df: pd.DataFrame) -> pd.DataFrame:
    """
    *** CRITICAL CORRECTNESS FIX (found during a 2026-07-05 independent
    re-verification pass) ***

    calibration/run_scoring.py's score_one() computes the axis-level
    aggregate columns (A, P, C, I) by calling the production
    score_authenticity()/score_plausibility()/score_completeness()/
    score_instrumentation() functions directly. Those functions -- by
    design, for PRODUCTION audits -- combine their sub-criteria using
    whatever WITHIN_A/P/C/I happens to be LIVE in data_certify/_constants.py
    at call time (data_certify/axis_authenticity.py line ~505:
    `w_sum = sum(WITHIN_A[k] for k in applicable_intrinsic)`, and the
    analogous lines in the other three axis modules).

    This is correct for production use (an audit should use the current,
    best-calibrated weights) but creates a genuine circularity for
    CALIBRATION: if _constants.py's WITHIN_A/P/C/I already hold a
    previously-calibrated BLENDED value (as they do, by design, after the
    very first calibration pass -- see _constants.py's own module
    docstring), then re-running run_scoring.py to rebuild score_matrix.csv
    bakes that PRIOR round's blended weights into the axis-level A/P/C/I
    columns, rather than the neutral AHP-prior combination the axis-level
    EWM entropy calculation needs as its input. Concretely: this was
    caught when 2 new datasets were added to the corpus mid-session and
    scored while _constants.py's WITHIN_A already held a blended value
    from earlier that same session -- their axis-level columns were
    computed under DIFFERENT effective weights than the other 71 datasets
    (which were originally scored back when WITHIN_A still held the pure
    AHP prior), silently corrupting the axis-level EWM input's consistency
    across rows.

    IMPORTANT SCOPE NOTE (added during a 2026-07-06 fifth-pass sanity
    check, using a live `run_audit.py` run rather than trusting this
    script's own report): this AHP-prior recomputation is the CORRECT,
    neutral basis for the EWM ENTROPY calculation specifically (measuring
    each criterion's cross-dataset variance needs a weight basis that does
    not itself depend on a prior calibration round). It is NOT a valid
    stand-in for what PRODUCTION actually computes once a blended weight
    set is written to _constants.py -- production combines sub-criteria
    using the BLENDED WITHIN_A/P/C/I, not the AHP prior, and for
    high-variance criteria like A1 (Benford) whose blended weight (~53%)
    is far larger than its AHP prior (~30%), the two formulas can produce
    materially different axis scores for the same dataset (chile: ~0.49
    under the AHP-prior recomputation this function performs, ~0.24 under
    the blended weights production actually uses -- confirmed via a direct
    `score_authenticity()` call and cross-checked against a live
    `run_audit.py --dataset chile` run). calibration/calibrate_thresholds.py
    therefore does NOT use this function for its own threshold validation
    -- see its own module docstring and `recompute_axis_columns_from_blended`
    below for the function it uses instead, which matches production
    exactly.

    The per-CRITERION sub-scores (A1-A5, P4-P9, C1-C4, I1-I5) are NOT
    affected -- they are pure statistical computations independent of any
    weight -- confirmed identical regardless of _constants.py's live
    state. So the fix is to IGNORE whatever A/P/C/I score_matrix.csv
    happens to already contain, and unconditionally RECOMPUTE them here,
    from the (trustworthy) sub-criteria columns, using the FIXED
    AHP_PRIOR weights (imported above as WITHIN_A/P/C/I) and the exact
    same renormalized-weighted-average-of-applicable-sub-criteria formula
    the production axis modules use. This makes compute_ewm.py
    self-correcting and immune to whatever calibration state _constants.py
    was in when score_matrix.csv was generated -- the axis-level EWM
    calculation is now guaranteed to run against a uniformly AHP-prior-
    anchored set of axis columns, regardless of scoring history.
    """
    groups = {"A": WITHIN_A, "P": WITHIN_P, "C": WITHIN_C, "I": WITHIN_I}
    return recompute_axis_columns(df, groups)


def recompute_axis_columns_from_blended(df: pd.DataFrame, blended_within: Dict[str, Dict[str, float]]) -> pd.DataFrame:
    """
    *** SIXTH-PASS ADDITION (2026-07-06): the function that
    calibration/calibrate_thresholds.py actually uses to validate
    theta_admit/theta_reject against, added after discovering that
    validating against recompute_axis_columns_from_ahp_prior's output (as
    every prior pass did) does NOT match what a live audit run actually
    computes once the blended weights below are written to
    data_certify/_constants.py -- see that function's "IMPORTANT SCOPE
    NOTE" above for the concrete chile example that surfaced this. This
    function recomputes the SAME axis columns using the FINAL BLENDED
    within-axis weights this calibration pass is about to write to
    _constants.py (`blended_within` = {"A": WITHIN_A blended dict, "P":
    WITHIN_P blended dict, ...}, typically read straight from this run's
    own ewm_report.json), so the resulting A/P/C/I -- and therefore T(D)
    -- is mathematically IDENTICAL to what `DataCertifyAuditor.audit()`
    will compute once those weights are live. This is the only axis-column
    recomputation that is valid evidence for "does theta_reject/theta_admit
    hold against production," as opposed to "does it hold against a
    hypothetical AHP-prior-only version of production."
    """
    return recompute_axis_columns(df, blended_within)


def main() -> None:
    df = pd.read_csv(SCORE_MATRIX_PATH)
    print(f"Loaded score matrix: {len(df)} datasets.")

    df = recompute_axis_columns_from_ahp_prior(df)
    print("Axis-level A/P/C/I columns recomputed from sub-criteria under fixed "
          "AHP-prior weights (see recompute_axis_columns_from_ahp_prior docstring) "
          "-- score_matrix.csv's own A/P/C/I columns are NOT trusted as-is.")

    results = {}

    results["axis"] = compute_group(df, dict(AXIS_WEIGHTS), "axis (A,P,C,I)")
    results["within_A"] = compute_group(df, dict(WITHIN_A), "within-A (A1-A5)")
    results["within_P"] = compute_group(df, dict(WITHIN_P), "within-P (P4-P9)")
    results["within_C"] = compute_group(df, dict(WITHIN_C), "within-C (C1-C4)")
    results["within_I"] = compute_group(df, dict(WITHIN_I), "within-I (I1-I5)")

    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(results, f, indent=2)
    print(f"JSON report -> {REPORT_JSON_PATH}")

    lines = [f"# EWM Computation Report (real {len(df)}-dataset calibration corpus)\n"]
    for key, r in results.items():
        lines.append(f"## {r['group']}\n")
        lines.append("| Criterion | n_obs | AHP | EWM (raw) | Blended (AHP x EWM) |")
        lines.append("|---|---|---|---|---|")
        for k in r["ahp_weights"]:
            ewm_disp = (f"{r['ewm_weights_raw_on_computable'][k]:.4f}" if k in r["computable"]
                        else f"n/a ({r['n_obs'][k]}/{len(df)} obs < {MIN_EWM_N}, AHP retained)")
            lines.append(f"| {k} | {r['n_obs'][k]} | {r['ahp_weights'][k]:.4f} | {ewm_disp} | "
                         f"{r['blended_weights'][k]:.4f} |")
        lines.append("")
    with open(REPORT_MD_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Markdown report -> {REPORT_MD_PATH}")

    print("")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for key, r in results.items():
        print("")
        print(f"{r['group']}:")
        for k in r["ahp_weights"]:
            print(f"  {k:4s}  AHP={r['ahp_weights'][k]:.4f}  ->  blended={r['blended_weights'][k]:.4f}"
                  f"  (n_obs={r['n_obs'][k]})")


if __name__ == "__main__":
    main()
