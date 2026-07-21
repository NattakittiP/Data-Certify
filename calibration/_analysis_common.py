# -*- coding: utf-8 -*-
"""
calibration/_analysis_common.py -- Shared utilities for the Group-B
post-hoc verification analysis scripts (see Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md,
Group B). All five analysis scripts import from here so that:

  (a) weight vectors, thresholds, and decision logic are defined ONCE and
      always match the real, current `data_certify._constants` values
      (imported directly, never hand-copied, so this file cannot silently
      drift out of sync with the production constants the way a
      copy-pasted number could);
  (b) the confidence-interval method and decision-assignment logic are
      identical across all five reports, so cross-report numbers are
      directly comparable;
  (c) every script reads the SAME underlying score data
      (`calibration/score_matrix.csv` + `calibration/corpus_manifest.csv`,
      plus `calibration/score_matrix_adversarial_holdout.csv` once
      `score_adversarial_holdout.py` has been run) rather than each
      re-implementing its own loading/merging logic with room for subtle
      inconsistencies to creep in between scripts.

This module does NOT touch `datasets/` or `datasets_adversarial/` raw CSVs
and does NOT call any `score_*` function from the `data_certify` package --
it operates entirely on the already-computed per-sub-criterion scores in
score_matrix.csv, so every script that imports only this module runs in
seconds, not minutes, regardless of corpus size.

Reproducibility note: every function that touches randomness (only
`analysis_decision_stability.py` does) takes an explicit `seed` argument
and this module sets no process-level RNG state itself.
"""
from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import (  # noqa: E402
    AXIS_WEIGHTS,
    AXIS_WEIGHTS_AHP_PRIOR,
    WITHIN_A,
    WITHIN_A_AHP_PRIOR,
    WITHIN_P,
    WITHIN_P_AHP_PRIOR,
    WITHIN_C,
    WITHIN_C_AHP_PRIOR,
    WITHIN_I,
    WITHIN_I_AHP_PRIOR,
    THETA_ADMIT,
    THETA_REJECT,
    MIN_N_RECORDS_FOR_ADMIT,
    MIN_APPLICABLE_SUBTESTS_FOR_ADMIT,
)

# Production defaults for the two weight-fraction safety gates
# (min_evidence_coverage, min_sample_sufficiency) -- these are
# DataCertifyAuditor.__init__'s own default ARGUMENT values, not
# data_certify._constants module-level constants (unlike theta_admit/
# theta_reject/MIN_N_RECORDS_FOR_ADMIT/MIN_APPLICABLE_SUBTESTS_FOR_ADMIT,
# which the auditor imports from _constants.py and so cannot drift).
# Hand-copied here, mirroring the disclosed pattern this project already
# uses for AXIS_WEIGHTS_EWM_ONLY below (a value not exposed as an
# importable constant). Because a hand-copied number CAN silently drift if
# decision.py's defaults are ever changed without updating this file too,
# `_self_check()` at the bottom of this module verifies these two against
# `inspect.signature(DataCertifyAuditor.__init__)` on every import and
# raises immediately if they no longer match -- the same
# fail-loud-on-import philosophy already used for AXIS_WEIGHTS_EWM_ONLY's
# n_obs/staleness checks elsewhere in this project's calibration scripts.
PRODUCTION_MIN_EVIDENCE_COVERAGE = 0.5
PRODUCTION_MIN_SAMPLE_SUFFICIENCY = 0.5

CALIBRATION_DIR = Path(__file__).resolve().parent
SCORE_MATRIX_PATH = CALIBRATION_DIR / "score_matrix.csv"
MANIFEST_PATH = CALIBRATION_DIR / "corpus_manifest.csv"
ADVERSARIAL_MANIFEST_PATH = CALIBRATION_DIR / "adversarial_corpus_manifest.csv"
ADVERSARIAL_SCORE_MATRIX_PATH = CALIBRATION_DIR / "score_matrix_adversarial_holdout.csv"

AXES = ("A", "P", "C", "I")
WITHIN = {"A": WITHIN_A, "P": WITHIN_P, "C": WITHIN_C, "I": WITHIN_I}
WITHIN_AHP_PRIOR = {
    "A": WITHIN_A_AHP_PRIOR, "P": WITHIN_P_AHP_PRIOR,
    "C": WITHIN_C_AHP_PRIOR, "I": WITHIN_I_AHP_PRIOR,
}

# EWM-only (raw, pre-blend) weights -- these are NOT in _constants.py (only
# the AHP prior and the final AHP*EWM blend are kept there; the raw EWM
# midpoint is intentionally not a production constant since it is never
# used directly by the audit). Copied here VERBATIM from
# calibration/ewm_report.json ("ewm_weights_raw_on_computable" keys),
# n=968 corpus, so the "EWM-only" ablation arm has a real, checkable
# source rather than being re-derived by this script (re-deriving it here
# would require re-running compute_ewm.py's entropy calculation over
# score_matrix.csv, which is unnecessary duplication of already-computed,
# already-reported numbers). If ewm_report.json is regenerated (e.g. after
# a Group-C corpus refit), these MUST be re-copied from the new file --
# there is no live import possible since the raw EWM step is not exposed
# as a constant.
AXIS_WEIGHTS_EWM_ONLY = {
    "A": 0.4337278921451253,
    "P": 0.25275089882110274,
    "C": 0.12454699784338152,
    "I": 0.18897421119039043,
}
WITHIN_A_EWM_ONLY = {
    "A1": 0.27454028484348325, "A2": 0.010497008715000478,
    "A3": 0.5662629802750339, "A4": 0.1384958508806923,
    "A5": 0.01020387528579014,
}
WITHIN_P_EWM_ONLY = {
    # P9 has n_obs=0 and is NOT in ewm_weights_raw_on_computable at all
    # (it is retained_ahp_only) -- for the "EWM-only" ablation arm we set
    # its weight to 0.0 rather than silently substituting its AHP prior,
    # since the whole point of this arm is "what would EWM alone say,"
    # and EWM alone says nothing about P9 (no data). This is disclosed
    # explicitly in analysis_ablation.py's report output.
    "P4": 0.0023030581512116922, "P5": 0.7876278389323359,
    "P6": 9.792873794610396e-16, "P7": 0.07891579440474965,
    "P8": 0.1311533085117018, "P9": 0.0,
}
WITHIN_C_EWM_ONLY = {
    "C1": 0.0018492166619663568, "C2": 0.22355359705696048,
    "C3": 0.12571918123117626, "C4": 0.6488780050498969,
}
WITHIN_I_EWM_ONLY = {
    "I1": 0.47317068488816616, "I2": 0.13983489032774285,
    "I3": 0.3638165596475651, "I4": 0.003861219956453243,
    "I5": 0.019316645180072686,
}
WITHIN_EWM_ONLY = {
    "A": WITHIN_A_EWM_ONLY, "P": WITHIN_P_EWM_ONLY,
    "C": WITHIN_C_EWM_ONLY, "I": WITHIN_I_EWM_ONLY,
}

SUB_CRITERIA = {axis: list(WITHIN[axis].keys()) for axis in AXES}


def equal_within_weights() -> Dict[str, Dict[str, float]]:
    """Equal weight across the applicable sub-criteria of each axis (not
    across all 20 globally -- an equal-weight BASELINE should still respect
    the axis structure, otherwise it isn't a meaningful comparison point
    for 'does AHP/EWM add value over the simplest possible within-axis
    scheme', it would just be a different, unrelated design)."""
    return {
        axis: {crit: 1.0 / len(WITHIN[axis]) for crit in WITHIN[axis]}
        for axis in AXES
    }


WEIGHT_VARIANTS: Dict[str, Dict[str, object]] = {
    "blended_current": {
        "axis": AXIS_WEIGHTS,
        "within": WITHIN,
        "label": "Current production weights (AHP x EWM blend, n=968)",
    },
    "ahp_only": {
        "axis": AXIS_WEIGHTS_AHP_PRIOR,
        "within": WITHIN_AHP_PRIOR,
        "label": "AHP-only prior (single-analyst pairwise comparison, no data)",
    },
    "ewm_only": {
        "axis": AXIS_WEIGHTS_EWM_ONLY,
        "within": WITHIN_EWM_ONLY,
        "label": "EWM-only (pure entropy/variance weighting, no AHP prior; P9=0)",
    },
    "equal_weight": {
        "axis": {a: 0.25 for a in AXES},
        "within": equal_within_weights(),
        "label": "Equal-weight baseline (0.25 per axis, uniform within axis)",
    },
}

for _axis in AXES:
    _w = {a: (1.0 if a == _axis else 0.0) for a in AXES}
    WEIGHT_VARIANTS[f"{_axis.lower()}_only"] = {
        "axis": _w,
        "within": WITHIN,  # irrelevant for the 3 zero-weighted axes
        "label": f"{_axis}-only (axis weight = 1.0 on {_axis}(D), 0 elsewhere; "
                 f"within-axis weights unchanged from current blend)",
    }


# LEGACY_STALE_COLUMNS: score_matrix.csv carries two kinds of columns.
# (1) Raw per-sub-criterion scores (A1-A5, P4-P9, C1-C4, I1-I5) and
#     hard_override_fired -- NONE of these depend on AXIS_WEIGHTS/WITHIN_*,
#     so they stay valid regardless of when score_matrix.csv was generated
#     relative to data_certify/_constants.py.
# (2) The four columns below -- computed by run_scoring.py by applying
#     WHATEVER AXIS_WEIGHTS/WITHIN_* were live in _constants.py at the
#     moment run_scoring.py was run, then baked into the CSV as static
#     numbers. If _constants.py is edited afterward (as confirmed for this
#     project on 2026-07-12: score_matrix.csv generated 2026-07-11 02:02,
#     _constants.py last edited 2026-07-11 03:13, ~70 min later, evidently
#     the final transcription of a recalibration pass -- see _self_check()
#     for the full timeline), these four columns silently go stale while
#     looking perfectly normal.
#
# Every Group-B script in this project MUST treat these four as
# informational/legacy only and MUST recompute T(D) and the decision via
# composite_score() + assign_decision() using LIVE weights from
# WEIGHT_VARIANTS (imported fresh from _constants.py every run) -- never
# read them directly as ground truth. This is enforced by convention, not
# by code (dropping the columns outright would break legitimate
# "what did the stale cache say" disclosure use), so any new script added
# to this project must follow the same rule.
LEGACY_STALE_COLUMNS = ("A", "P", "C", "I", "trust_score_ahp_only", "decision_ahp_only")


def load_corpus(include_adversarial: bool = True) -> pd.DataFrame:
    """Load score_matrix.csv, merge in corpus_manifest.csv's label/category/
    corruption_type/severity, and (if available and requested) append the
    30 held-out adversarial datasets scored by score_adversarial_holdout.py
    with a synthetic manifest row so they participate in every downstream
    analysis on equal footing. Adds a `group` column with four values used
    throughout: 'known_good', 'corrupted_real', 'fabricated',
    'held_out_adversarial'.

    IMPORTANT: the returned DataFrame's A/P/C/I/trust_score_ahp_only/
    decision_ahp_only columns (see LEGACY_STALE_COLUMNS above) may be stale
    relative to the CURRENT data_certify._constants weights. Every caller
    in this project recomputes T(D)/decision via composite_score() +
    assign_decision() instead of reading those columns directly -- do the
    same in any new analysis script.
    """
    if not SCORE_MATRIX_PATH.exists():
        raise FileNotFoundError(
            f"{SCORE_MATRIX_PATH} not found -- run calibration/run_scoring.py "
            "first (or confirm you are running from the correct repo checkout)."
        )
    scores = pd.read_csv(SCORE_MATRIX_PATH)
    manifest = pd.read_csv(MANIFEST_PATH)
    # Both files carry an n_records column (both populated at generation
    # time from the same source records.csv, confirmed identical for every
    # row in this corpus) -- drop the manifest's copy before merging so the
    # result has a single unambiguous `n_records` column instead of pandas
    # auto-suffixing to n_records_x/n_records_y, which silently broke every
    # downstream script that referenced df["n_records"] directly.
    manifest_for_merge = manifest.drop(columns=["n_records"])
    df = scores.merge(manifest_for_merge, on="dataset_id", how="left", validate="one_to_one")

    missing = df[df["label"].isna()]
    if len(missing):
        raise ValueError(
            f"{len(missing)} rows in score_matrix.csv have no matching "
            f"corpus_manifest.csv entry (dataset_id mismatch) -- "
            f"e.g. {missing['dataset_id'].head(5).tolist()}. "
            "Fix the mismatch before trusting any downstream analysis."
        )

    def _group(row) -> str:
        if row["category"] == "real":
            return "known_good"
        if row["category"] == "corrupted":
            return "corrupted_real"
        if row["category"] == "fabricated":
            return "fabricated"
        return f"other:{row['category']}"

    df["group"] = df.apply(_group, axis=1)

    if include_adversarial:
        if ADVERSARIAL_SCORE_MATRIX_PATH.exists():
            adv_scores = pd.read_csv(ADVERSARIAL_SCORE_MATRIX_PATH)
            adv_manifest = pd.read_csv(ADVERSARIAL_MANIFEST_PATH)
            adv_manifest_for_merge = adv_manifest.drop(columns=["n_records"])
            adv = adv_scores.merge(adv_manifest_for_merge, on="dataset_id", how="left", validate="one_to_one")
            adv["group"] = "held_out_adversarial"
            missing_cols = set(df.columns) - set(adv.columns)
            for c in missing_cols:
                adv[c] = np.nan
            adv = adv[df.columns]
            df = pd.concat([df, adv], ignore_index=True)
        else:
            print(
                f"NOTE: {ADVERSARIAL_SCORE_MATRIX_PATH.name} not found -- "
                "the 30 held-out adversarial datasets are EXCLUDED from this "
                "analysis. Run score_adversarial_holdout.py first to include "
                "them (required for a complete Group-B analysis -- see the "
                "held-out/adversarial row in DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B).",
                file=sys.stderr,
            )

    return df


def composite_score(
    df: pd.DataFrame,
    axis_weights: Dict[str, float],
    within_weights: Dict[str, Dict[str, float]],
) -> pd.Series:
    """Recompute T(D) directly from the raw per-sub-criterion scores in
    `df` (columns A1..A5, P4..P9, C1..C4, I1..I5) under an arbitrary
    (axis_weights, within_weights) pair, replicating run_scoring.py's own
    axis-then-composite logic (missing/inapplicable sub-criteria -> NaN ->
    renormalize the axis's own within-weights over the applicable subset;
    an axis with zero applicable sub-criteria -> that axis's own score is
    NaN -> renormalize AXIS_WEIGHTS over the remaining applicable axes).
    This mirrors axis_authenticity.py/axis_plausibility.py/etc.'s own
    handling of inapplicable sub-tests exactly. Verified against a
    hand-computed toy example in `_unit_test_composite_score()` below (run
    automatically on import); NOTE this does NOT claim to reproduce
    score_matrix.csv's cached trust_score_ahp_only column when that file
    is stale relative to data_certify/_constants.py -- see `_self_check()`.
    """
    axis_scores = {}
    for axis in AXES:
        crits = [c for c in within_weights[axis] if c in df.columns]
        w = np.array([within_weights[axis][c] for c in crits], dtype=float)
        vals = df[crits].to_numpy(dtype=float)
        applicable = ~np.isnan(vals)
        w_bcast = np.broadcast_to(w, vals.shape)
        w_masked = np.where(applicable, w_bcast, 0.0)
        w_sum = w_masked.sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            axis_score = np.where(
                w_sum > 0,
                np.nansum(np.where(applicable, vals * w_bcast, 0.0), axis=1) / w_sum,
                np.nan,
            )
        axis_scores[axis] = axis_score

    axis_arr = np.column_stack([axis_scores[a] for a in AXES])
    axis_w = np.array([axis_weights[a] for a in AXES], dtype=float)
    applicable_axes = ~np.isnan(axis_arr)
    axis_w_bcast = np.broadcast_to(axis_w, axis_arr.shape)
    axis_w_masked = np.where(applicable_axes, axis_w_bcast, 0.0)
    axis_w_sum = axis_w_masked.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        t_d = np.where(
            axis_w_sum > 0,
            np.nansum(np.where(applicable_axes, axis_arr * axis_w_bcast, 0.0), axis=1) / axis_w_sum,
            np.nan,
        )
    return pd.Series(t_d, index=df.index)


def assign_decision(
    t_d: pd.Series,
    hard_override_fired: pd.Series,
    theta_admit: float = THETA_ADMIT,
    theta_reject: float = THETA_REJECT,
    respect_hard_override: bool = True,
) -> pd.Series:
    """Vectorized version of the production decision rule
    (decision.py / run_scoring.py's score_one): REJECT if hard override
    fired (when respect_hard_override=True); else ADMIT/CONDITIONAL/REJECT
    by T(D) thresholds; REJECT if T(D) is NaN (no applicable axis at all).
    `respect_hard_override=False` is used by the "weighted-sum only, no
    hard override" ablation arm.
    """
    hof = hard_override_fired.fillna(False).astype(bool)
    decision = pd.Series("REJECT", index=t_d.index, dtype=object)
    decision[t_d >= theta_admit] = "ADMIT"
    decision[(t_d >= theta_reject) & (t_d < theta_admit)] = "CONDITIONAL"
    decision[t_d < theta_reject] = "REJECT"
    decision[t_d.isna()] = "REJECT"
    if respect_hard_override:
        decision[hof] = "REJECT"
    return decision


def assign_decision_gated(
    df: pd.DataFrame,
    t_d: pd.Series,
    theta_admit: float = THETA_ADMIT,
    theta_reject: float = THETA_REJECT,
    respect_hard_override: bool = True,
    min_evidence_coverage: float = PRODUCTION_MIN_EVIDENCE_COVERAGE,
    min_sample_sufficiency: float = PRODUCTION_MIN_SAMPLE_SUFFICIENCY,
    min_n_records_for_admit: int = MIN_N_RECORDS_FOR_ADMIT,
    min_applicable_subtests_for_admit: int = MIN_APPLICABLE_SUBTESTS_FOR_ADMIT,
) -> pd.Series:
    """
    Gate-aware decision assignment (2026-07-21, added in response to a
    paper-readiness review finding that `assign_decision()` above -- used
    by every Group-B report, including the previously-disclosed 19/490
    (3.9%) false-admit headline number -- reproduces ONLY Stage 1 (hard
    override) + Stage 2 (theta_admit/theta_reject) threshold logic. Real
    users of `DataCertifyAuditor.audit()` additionally get two weight-
    fraction safety gates (min_evidence_coverage, min_sample_sufficiency)
    and, as of this same date, two count-based ADMIT-eligibility floors
    (min_n_records_for_admit, min_applicable_subtests_for_admit) -- see
    decision.py's `DataCertifyAuditor.__init__` docstring for each gate's
    full rationale, and CHANGELOG.md's 2026-07-21 "ADMIT-eligibility gate +
    gate-aware re-audit" entry for the discovery and the corrected numbers.

    This function reproduces the REAL, fully-gated production decision
    path exactly, so that any report built on it is not vulnerable to the
    same staleness `assign_decision()` alone was found to have. Every gate
    is applied in the SAME ORDER decision.py's `DataCertifyAuditor.audit()`
    applies them (evidence_coverage, then sample_sufficiency, then the
    record-count floor, then the sub-test-count floor), and, matching
    decision.py's own additive design exactly, each gate ONLY ever caps an
    ADMIT down to CONDITIONAL -- a dataset already CONDITIONAL or REJECT
    under `assign_decision()` is returned completely unchanged, and no gate
    here can ever override the Stage-1 hard override (that is handled by
    `assign_decision()` itself, called internally, before any gate below
    runs).

    `respect_hard_override=False` (2026-07-21 addition, mirrors
    `assign_decision()`'s own parameter) supports the "weighted_sum_only"
    mechanism-ablation arm used by `analysis_ablation.py`/
    `analysis_selective_classification.py`: the four gates below are part
    of Stage 2's own post-processing (independent of whether Stage 1's
    hard override is being consulted at all), so it remains coherent to
    apply them while asking "how much does Stage 2 alone, INCLUDING its
    own safety gates, achieve without Stage 1."

    Requires `df` to carry `evidence_coverage`, `sample_sufficiency`,
    `n_records`, and `n_applicable_subtests` columns -- written by
    `calibration/run_scoring.py` / `calibration/score_adversarial_
    holdout.py`'s 2026-07-21 gate-awareness fix. Raises KeyError with an
    actionable message if any are missing (e.g. an un-regenerated,
    pre-fix `score_matrix.csv`), rather than silently falling back to the
    ungated behavior -- a silent fallback here would exactly reproduce the
    staleness bug this function exists to fix.
    """
    missing_cols = [
        c for c in ("evidence_coverage", "sample_sufficiency", "n_records", "n_applicable_subtests")
        if c not in df.columns
    ]
    if missing_cols:
        raise KeyError(
            f"assign_decision_gated() requires column(s) {missing_cols} in df, which "
            f"{'is' if len(missing_cols) == 1 else 'are'} missing. This means "
            "score_matrix.csv (and/or score_matrix_adversarial_holdout.csv) predates "
            "the 2026-07-21 gate-awareness fix -- re-run calibration/run_scoring.py "
            "and calibration/score_adversarial_holdout.py to regenerate them with these "
            "columns before calling this function. (assign_decision() above remains "
            "available and requires no such columns, but only reproduces Stage 1+2 "
            "threshold logic, not the real, fully-gated production decision -- see this "
            "function's own docstring.)"
        )

    decision = assign_decision(
        t_d, df["hard_override_fired"], theta_admit=theta_admit, theta_reject=theta_reject,
        respect_hard_override=respect_hard_override,
    ).copy()

    ec = df["evidence_coverage"]
    is_admit = decision == "ADMIT"
    decision[is_admit & ec.notna() & (ec < min_evidence_coverage)] = "CONDITIONAL"

    ss = df["sample_sufficiency"]
    is_admit = decision == "ADMIT"
    decision[is_admit & ss.notna() & (ss < min_sample_sufficiency)] = "CONDITIONAL"

    n_rec = df["n_records"]
    is_admit = decision == "ADMIT"
    decision[is_admit & n_rec.notna() & (n_rec < min_n_records_for_admit)] = "CONDITIONAL"

    n_appl = df["n_applicable_subtests"]
    is_admit = decision == "ADMIT"
    decision[is_admit & n_appl.notna() & (n_appl < min_applicable_subtests_for_admit)] = "CONDITIONAL"

    return decision


def wilson_ci(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Two-sided Wilson score confidence interval for a binomial proportion
    (Wilson, E.B. 1927, 'Probable Inference, the Law of Succession, and
    Statistical Inference,' JASA 22(158):209-212). Chosen over the naive
    normal (Wald) interval because Wald is known to behave poorly (can
    exceed [0,1], has poor coverage) exactly in the small-k or
    near-boundary regime this project's false-admit/false-reject counts
    fall into (e.g. k=19, n=460) -- Wilson is the standard fix and needs
    no external dependency beyond the standard-normal z-quantile, which is
    a fixed constant for a fixed confidence level (z=1.96 for 95%),
    keeping this scipy-free in the same spirit as
    data_certify/stats.py's chi_square_sf.
    """
    if n == 0:
        return (float("nan"), float("nan"))
    p_hat = k / n
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    half_width = (z / denom) * math.sqrt((p_hat * (1 - p_hat) / n) + (z ** 2 / (4 * n ** 2)))
    lo = max(0.0, center - half_width)
    hi = min(1.0, center + half_width)
    return (lo, hi)


def fmt_rate_ci(k: int, n: int) -> str:
    if n == 0:
        return "n/a (n=0)"
    p = k / n
    lo, hi = wilson_ci(k, n)
    return f"{p:.4f} ({k}/{n}) [95% CI: {lo:.4f}-{hi:.4f}]"


def _unit_test_gate_defaults_match_production() -> None:
    """Guards PRODUCTION_MIN_EVIDENCE_COVERAGE/PRODUCTION_MIN_SAMPLE_SUFFICIENCY
    (hand-copied above, since they are DataCertifyAuditor.__init__'s own
    default ARGUMENT values, not importable data_certify._constants module
    constants) against silent drift: inspects the REAL, live
    DataCertifyAuditor.__init__ signature and raises immediately if either
    hand-copied number no longer matches. Runs automatically on import,
    same fail-loud-on-import philosophy as `_self_check()` below -- if
    this fails, `assign_decision_gated()` is silently gating against the
    WRONG thresholds and every report built on it must not be trusted
    until this file's two constants are updated to match."""
    from data_certify.decision import DataCertifyAuditor  # local import: avoid a hard
    # dependency on decision.py's internal default machinery at module-load
    # time for every other function in this file that does not need it.

    sig = inspect.signature(DataCertifyAuditor.__init__)
    real_ec = sig.parameters["min_evidence_coverage"].default
    real_ss = sig.parameters["min_sample_sufficiency"].default
    if real_ec != PRODUCTION_MIN_EVIDENCE_COVERAGE:
        raise AssertionError(
            f"_analysis_common.PRODUCTION_MIN_EVIDENCE_COVERAGE="
            f"{PRODUCTION_MIN_EVIDENCE_COVERAGE} no longer matches "
            f"DataCertifyAuditor.__init__'s real default min_evidence_coverage="
            f"{real_ec} -- update this file's hand-copied constant to match "
            f"before trusting assign_decision_gated() or any report built on it."
        )
    if real_ss != PRODUCTION_MIN_SAMPLE_SUFFICIENCY:
        raise AssertionError(
            f"_analysis_common.PRODUCTION_MIN_SAMPLE_SUFFICIENCY="
            f"{PRODUCTION_MIN_SAMPLE_SUFFICIENCY} no longer matches "
            f"DataCertifyAuditor.__init__'s real default min_sample_sufficiency="
            f"{real_ss} -- update this file's hand-copied constant to match "
            f"before trusting assign_decision_gated() or any report built on it."
        )


def _unit_test_composite_score() -> None:
    """Pure unit test of composite_score()'s renormalization logic against a
    hand-computed toy example -- independent of score_matrix.csv entirely,
    so this keeps working (and keeps meaning something) even when the real
    corpus file is stale or missing. Two rows:
      row 0: all sub-criteria present on every axis -> composite is just
             the textbook nested weighted average.
      row 1: axis 'C' has ALL its sub-criteria missing (NaN) -> axis C's
             own score must come out NaN, and AXIS_WEIGHTS must be
             renormalized over {A, P, I} only for that row (mirrors
             run_scoring.py's score_one() `applicable_axes` logic).
    """
    toy_within = {
        "A": {"A1": 0.5, "A2": 0.5},
        "P": {"P7": 1.0},
        "C": {"C1": 1.0},
        "I": {"I1": 1.0},
    }
    toy_axis_w = {"A": 0.4, "P": 0.3, "C": 0.2, "I": 0.1}
    toy_df = pd.DataFrame([
        {"A1": 0.8, "A2": 0.4, "P7": 0.6, "C1": 0.9, "I1": 0.2},
        {"A1": 0.8, "A2": 0.4, "P7": 0.6, "C1": float("nan"), "I1": 0.2},
    ])
    out = composite_score(toy_df, toy_axis_w, toy_within)

    expected_axis_a = 0.5 * 0.8 + 0.5 * 0.4  # = 0.6, same both rows
    expected_row0 = (0.4 * expected_axis_a + 0.3 * 0.6 + 0.2 * 0.9 + 0.1 * 0.2) / 1.0
    w_sum_row1 = 0.4 + 0.3 + 0.1  # C dropped, renormalize over A+P+I
    expected_row1 = (0.4 * expected_axis_a + 0.3 * 0.6 + 0.1 * 0.2) / w_sum_row1

    if abs(out.iloc[0] - expected_row0) > 1e-9:
        raise AssertionError(
            f"composite_score() unit test FAILED on the fully-applicable "
            f"toy row: got {out.iloc[0]!r}, expected {expected_row0!r}. "
            f"This is a real bug in composite_score() (not a staleness "
            f"issue -- this test never touches score_matrix.csv)."
        )
    if abs(out.iloc[1] - expected_row1) > 1e-9:
        raise AssertionError(
            f"composite_score() unit test FAILED on the axis-dropped toy "
            f"row (C entirely NaN): got {out.iloc[1]!r}, expected "
            f"{expected_row1!r}. This means the axis-renormalization "
            f"branch (dropping an axis with zero applicable sub-criteria "
            f"and renormalizing AXIS_WEIGHTS over the rest) is broken."
        )


def _self_check() -> None:
    """Two-layer sanity check run automatically on import (cheap -- no
    re-scoring involved):

    Layer 1 -- `_unit_test_composite_score()`: proves composite_score()'s
    renormalization logic is correct against a hand-computed toy example
    that never touches score_matrix.csv. This is the check that actually
    certifies the FUNCTION is right, and it always runs (hard failure --
    AssertionError -- if it fails; this is a real code bug, never a data
    issue).

    Layer 2 -- staleness/reproduction check against the real
    score_matrix.csv, split into two distinguishable outcomes:

      (a) FILE-STALENESS (non-fatal WARNING): calibration/score_matrix.csv
          was last written BEFORE data_certify/_constants.py's current
          mtime. score_matrix.csv caches two kinds of columns per dataset:
          (i) raw per-sub-criterion scores (A1-A5, P4-P9, C1-C4, I1-I5),
          which do NOT depend on AXIS_WEIGHTS/WITHIN_* and remain valid
          regardless of later weight recalibration; and (ii) derived
          axis-level (A/P/C/I) and composite (trust_score_ahp_only)
          columns, which DO depend on those weights and were baked in at
          generation time. If _constants.py has been edited since, (ii) is
          stale even though (i) is still trustworthy. Confirmed for this
          project on 2026-07-12: score_matrix.csv was generated 2026-07-11
          02:02 (immediately followed by ewm_report.json,
          threshold_report.json, bootstrap_stability_report.json, and
          hard_override_calibration_report.json between 02:02-02:57, i.e.
          the tail end of a calibration pipeline run), while
          data_certify/_constants.py was last edited 2026-07-11 03:13 --
          ~11 minutes after the LAST of those reports, consistent with the
          final blended AXIS_WEIGHTS/WITHIN_* being hand-transcribed into
          _constants.py from that pipeline's output as the very last step,
          without score_matrix.csv itself being regenerated afterward.
          This is data-freshness, not a code bug, and is confined to
          LEGACY_STALE_COLUMNS -- every Group-B script recomputes
          T(D)/decision live via composite_score()/assign_decision()
          rather than reading those columns, so it does not affect any
          Group-B report. Downgraded from AssertionError to a printed
          warning for exactly this reason (see the warning text itself for
          the full reasoning).

      (b) UNEXPLAINED DRIFT (fatal AssertionError): score_matrix.csv is
          NOT older than _constants.py and STILL does not reproduce --
          this would indicate a genuine bug (either in composite_score()
          despite it passing the Layer-1 unit test, e.g. a real-data edge
          case the toy example doesn't cover, or in run_scoring.py's own
          score_one() implementation) and needs investigation before
          trusting anything downstream.
    """
    _unit_test_composite_score()
    _unit_test_gate_defaults_match_production()

    if not SCORE_MATRIX_PATH.exists():
        return
    df = pd.read_csv(SCORE_MATRIX_PATH)
    recomputed = composite_score(df, AXIS_WEIGHTS, WITHIN)
    mask = (df["hard_override_fired"] == False) & df["trust_score_ahp_only"].notna()  # noqa: E712
    if mask.sum() == 0:
        return
    diff = (recomputed[mask] - df.loc[mask, "trust_score_ahp_only"]).abs()
    max_diff = diff.max()
    if max_diff <= 1e-6:
        return

    bad = df.loc[mask].loc[diff > 1e-6, "dataset_id"].head(5).tolist()
    n_bad = int((diff > 1e-6).sum())

    constants_path = ROOT / "data_certify" / "_constants.py"
    score_mtime = SCORE_MATRIX_PATH.stat().st_mtime
    const_mtime = constants_path.stat().st_mtime if constants_path.exists() else None
    is_stale = const_mtime is not None and const_mtime > score_mtime

    if is_stale:
        print(
            "WARNING [_analysis_common._self_check]: score_matrix.csv's "
            "cached trust_score_ahp_only column does NOT match "
            "composite_score() under current weights (max abs diff = "
            + format(max_diff, ".6g") + " on " + str(n_bad) + "/" + str(int(mask.sum()))
            + " rows, e.g. " + str(bad) + "). DIAGNOSED CAUSE: FILE STALENESS -- "
            + SCORE_MATRIX_PATH.name + " was last written "
            + str(pd.Timestamp(score_mtime, unit="s"))
            + ", but data_certify/_constants.py was last edited "
            + str(pd.Timestamp(const_mtime, unit="s")) + " (later). "
            "This affects ONLY the cached columns in LEGACY_STALE_COLUMNS -- "
            "the raw per-sub-criterion columns (A1-A5/P4-P9/C1-C4/I1-I5) and "
            "hard_override_fired remain valid, and every Group-B script "
            "recomputes T(D)/decision live via composite_score()/"
            "assign_decision() rather than trusting the stale cache, so "
            "this does NOT invalidate any Group-B report. Recommended "
            "(not required) hygiene fix, at your convenience:\n"
            "    mv calibration/score_matrix.csv calibration/score_matrix.csv.stale_"
            + pd.Timestamp(score_mtime, unit="s").strftime("%Y%m%dT%H%M%S") + "\n"
            "    python3 calibration/run_scoring.py\n",
            file=sys.stderr,
        )
        return
    else:
        raise AssertionError(
            "_analysis_common.composite_score() does NOT reproduce "
            "score_matrix.csv's cached trust_score_ahp_only column "
            "(max abs diff = " + format(max_diff, ".6g") + " on " + str(n_bad) + "/"
            + str(int(mask.sum())) + " rows, e.g. " + str(bad) + "), AND "
            "score_matrix.csv is not older than data_certify/_constants.py, "
            "so this is NOT the usual file-staleness explanation. "
            "composite_score() passed its own Layer-1 unit test "
            "(_unit_test_composite_score()), which rules out the most "
            "likely renormalization bugs, but this real-data mismatch "
            "means either: a real-data edge case the unit test does not "
            "cover, or run_scoring.py's score_one() has itself changed in "
            "a way this module's composite_score() does not yet mirror. "
            "DO NOT trust any Group-B report generated while this check is "
            "failing -- compare composite_score() line-by-line against "
            "calibration/run_scoring.py's score_one() (specifically the "
            "axis-then-composite renormalization block) before proceeding."
        )


_self_check()
