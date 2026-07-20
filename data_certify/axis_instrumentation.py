# -*- coding: utf-8 -*-
"""
data_certify/axis_instrumentation.py -- Instrumentation & Provenance-Pipeline
Integrity axis I(D)  (covers Categories VI & VII of the failure-mode
taxonomy: Modes 23-28).

Implements tests I1-I5 per DATA-CERTIFY_Theoretical_Framework.md Section 3.4,
with the explicit bounded [0,1] scoring transforms specified in
DATA-CERTIFY_06_Gap_Remediation_and_Robustness_Addendum.md Section 3.3.

    I1  Temporal drift (Mann-Kendall trend flag + Sen's slope effect size)
    I2  Large-event clipping / saturation
    I3  Revision-flag (preliminary/final) consistency
    I4  Cross-catalog duplicate-ID detection (EM-fitted Fellegi-Sunter)
    I5  Temporal distribution drift (early-vs-late two-sample Kolmogorov-Smirnov)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np

from . import stats
from ._constants import TAU_DRIFT, WITHIN_I
from .results import AxisResult, SubTestResult
from .schema import CertifyDataset


def _score_i1_temporal_drift(dataset: CertifyDataset) -> SubTestResult:
    """
    I1: Temporal drift test on magnitude residuals against a stable
    reference (main framework Section 3.4). This reference implementation
    has no external stable-reference subset to compare against, so it
    directly tests the magnitude series itself for a monotonic trend over
    time via Mann-Kendall, with Sen's slope as the bounded effect size
    (Gap-Remediation Addendum Section 3.3).

    NOTE on scope: testing the raw series (rather than a residual from a
    local rolling baseline) is a deliberate choice -- detrending against a
    *local* rolling statistic would remove exactly the slow, low-frequency
    drift signal I1 exists to detect. The disclosed limitation is that a
    genuine, non-instrumental regional shift in typical magnitude (e.g. a
    real change in seismicity rate or completeness over a multi-decade
    catalog) would also register as "drift" here -- a real stable external
    reference subset (as the main framework specifies) would disambiguate
    this; absent one, I1 should be read as "the magnitude series shows an
    unexplained trend," not conclusively as instrumentation drift.
    """
    valid = np.isfinite(dataset.magnitude) & ~np.isnat(dataset.origin_time)
    if np.sum(valid) < 30:
        return SubTestResult(name="I1", score=float("nan"), applicable=False,
                              note="Fewer than 30 valid, timestamped magnitudes.")

    days = dataset.origin_time_days()
    order = np.argsort(days)
    mag_sorted = dataset.magnitude[order]
    days_sorted = days[order]
    valid_sorted = np.isfinite(mag_sorted) & np.isfinite(days_sorted)
    mag_sorted = mag_sorted[valid_sorted]
    days_sorted = days_sorted[valid_sorted]

    mk = stats.mann_kendall_test(mag_sorted)
    slope_per_day = stats.sen_slope(days_sorted, mag_sorted)
    slope_per_decade = slope_per_day * 365.25 * 10.0 if math.isfinite(slope_per_day) else float("nan")

    if math.isnan(slope_per_decade):
        return SubTestResult(name="I1", score=float("nan"), applicable=False,
                              note="Sen's slope could not be computed.")

    score = float(np.clip(1.0 - abs(slope_per_decade) / TAU_DRIFT, 0.0, 1.0)) \
        if mk["trend_detected"] else 1.0

    return SubTestResult(
        name="I1", score=score, applicable=True,
        detail={"mann_kendall_z": mk["z"], "trend_detected": mk["trend_detected"],
                "sen_slope_per_decade": slope_per_decade, "tau_drift": TAU_DRIFT},
        note=(f"Mann-Kendall trend {'DETECTED' if mk['trend_detected'] else 'not detected'} "
              f"(z={mk['z']:.2f}); Sen's slope={slope_per_decade:.4f} mag/decade "
              f"(tolerance {TAU_DRIFT})."),
    )


def _score_i2_clipping(dataset: CertifyDataset) -> SubTestResult:
    """
    I2: Large-event clipping check -- compare the empirical magnitude tail
    against the Gutenberg-Richter extrapolation from the fitted b-value.
    """
    mags = dataset.magnitude[np.isfinite(dataset.magnitude)]
    if len(mags) < 50:
        return SubTestResult(name="I2", score=float("nan"), applicable=False,
                              note="Fewer than 50 valid magnitudes.")

    mc = stats.maximum_curvature_mc(mags)
    if math.isnan(mc):
        return SubTestResult(name="I2", score=float("nan"), applicable=False,
                              note="Could not estimate Mc for GR extrapolation.")

    complete = mags[mags >= mc]
    if len(complete) < 20:
        return SubTestResult(name="I2", score=float("nan"), applicable=False,
                              note="Fewer than 20 events at/above Mc.")

    b_hat = stats.gr_b_value_aki(complete, mc)
    if math.isnan(b_hat) or b_hat <= 0:
        return SubTestResult(name="I2", score=float("nan"), applicable=False,
                              note="b-value estimation failed.")

    # Predicted vs. observed count in the top decile of the observed range.
    m_max_observed = float(np.max(complete))
    m_tail_floor = mc + 0.75 * (m_max_observed - mc)
    if m_tail_floor >= m_max_observed:
        return SubTestResult(name="I2", score=1.0, applicable=True,
                              note="Magnitude range too narrow to assess a tail deficit.")

    n_ge_mc = len(complete)
    predicted_n_tail = n_ge_mc * 10 ** (-b_hat * (m_tail_floor - mc))
    observed_n_tail = int(np.sum(complete >= m_tail_floor))

    if predicted_n_tail <= 0:
        return SubTestResult(name="I2", score=float("nan"), applicable=False,
                              note="Degenerate GR extrapolation (predicted_n_tail <= 0).")

    deficit_fraction = float(np.clip(1.0 - observed_n_tail / predicted_n_tail, 0.0, 1.0))
    score = float(1.0 - deficit_fraction)
    return SubTestResult(
        name="I2", score=score, applicable=True,
        detail={"b_value": b_hat, "predicted_n_tail": predicted_n_tail,
                "observed_n_tail": observed_n_tail, "m_tail_floor": m_tail_floor},
        note=f"Observed {observed_n_tail} events >= M{m_tail_floor:.2f}; "
             f"GR extrapolation (b={b_hat:.2f}) predicts {predicted_n_tail:.1f}.",
    )


def _score_i3_revision_flag(dataset: CertifyDataset) -> SubTestResult:
    """I3: fraction of records carrying an explicit, distinguishable
    revision-status field (schema-presence check, no statistical test needed)."""
    has_status = dataset.revision_status != ""
    score = float(np.mean(has_status)) if dataset.n else float("nan")
    return SubTestResult(
        name="I3", score=score, applicable=True,
        detail={"n_with_revision_status": int(np.sum(has_status)), "n": dataset.n},
        note=f"{int(np.sum(has_status))}/{dataset.n} records carry an explicit "
             f"revision_status (preliminary/final) field.",
    )


def _score_i4_cross_catalog_dedup(
    dataset: CertifyDataset,
    time_tol_sec: float = 120.0,
    dist_tol_km: float = 100.0,
    mag_tol: float = 0.6,
) -> SubTestResult:
    """
    I4: Cross-catalog duplicate-ID detection via a full EM-fitted
    Fellegi-Sunter (1969) linkage model (Winkler 1988's EM algorithm --
    see `stats.fellegi_sunter_em`), replacing the earlier fixed-Gaussian-
    kernel heuristic that this reference implementation previously
    disclosed as a simplification ("a fixed, documented logistic-style
    combination of normalised field distances, rather than an EM fit").
    It now IS an EM fit, estimated unsupervised directly from this
    dataset's own candidate comparison pairs (no labeled match/non-match
    training set is needed for EM). Only meaningful when the dataset
    carries a `source` field distinguishing multiple contributing
    agencies/catalogs -- otherwise this test is not applicable (a
    single-source dataset has no cross-catalog merge to check).

    Two-pass design: first collect every candidate cross-source pair
    within the (time, distance) blocking window (same blocking logic as
    before), THEN fit the EM model once, in a single batch, over all
    candidate pairs found across the whole dataset -- rather than fitting
    per-record, which would both be far more expensive and give EM too
    little data per fit to be stable.
    """
    distinct_sources = set(s for s in dataset.source if s)
    if len(distinct_sources) < 2:
        return SubTestResult(
            name="I4", score=float("nan"), applicable=False,
            note="Fewer than 2 distinct values in the 'source' field -- no cross-catalog "
                 "merge to check (I4 is scoped to multi-agency-merged datasets).")

    days = dataset.origin_time_days()
    n = dataset.n
    order = np.argsort(days)
    d_sorted = days[order]
    lat_sorted = dataset.latitude[order]
    lon_sorted = dataset.longitude[order]
    mag_sorted = dataset.magnitude[order]
    src_sorted = dataset.source[order]

    time_tol_days = time_tol_sec / 86400.0

    pair_owner: List[int] = []
    pair_dt: List[float] = []
    pair_dist: List[float] = []
    pair_dmag: List[float] = []

    j_start = 0
    for i in range(n):
        if not np.isfinite(d_sorted[i]):
            continue
        while j_start < i and (d_sorted[i] - d_sorted[j_start]) > time_tol_days:
            j_start += 1
        for j in range(j_start, n):
            if j == i or not np.isfinite(d_sorted[j]):
                continue
            if (d_sorted[j] - d_sorted[i]) > time_tol_days:
                break
            if src_sorted[j] == src_sorted[i]:
                continue  # I4 targets CROSS-catalog matches specifically
            dt = abs(d_sorted[j] - d_sorted[i]) * 86400.0
            dist = stats.haversine_km(lat_sorted[i], lon_sorted[i], lat_sorted[j], lon_sorted[j])
            if not np.isfinite(dist) or dist > dist_tol_km:
                continue
            dmag = abs(mag_sorted[i] - mag_sorted[j]) if (
                np.isfinite(mag_sorted[i]) and np.isfinite(mag_sorted[j])) else float("nan")
            pair_owner.append(i)
            pair_dt.append(dt)
            pair_dist.append(dist)
            pair_dmag.append(dmag)

    if not pair_owner:
        return SubTestResult(
            name="I4", score=1.0, applicable=True,
            detail={"duplicate_fraction": 0.0, "n_sources": len(distinct_sources),
                    "n_candidate_pairs": 0},
            note=f"No cross-catalog candidate pairs found within tolerance across "
                 f"{len(distinct_sources)} distinct sources.",
        )

    em_result = stats.fellegi_sunter_em_match_probs(
        np.array(pair_dt), np.array(pair_dist), np.array(pair_dmag),
        time_scale_sec=time_tol_sec, dist_scale_km=dist_tol_km, mag_scale=mag_tol,
    )
    posterior = em_result["posterior"]

    per_record_probs: Dict[int, List[float]] = {}
    for owner, p in zip(pair_owner, posterior):
        per_record_probs.setdefault(owner, []).append(float(p))

    p_dup = np.zeros(n, dtype=float)
    for i, probs in per_record_probs.items():
        p_dup[i] = stats.probability_at_least_one_match(probs)

    duplicate_fraction = float(np.mean(p_dup))
    score = float(1.0 - duplicate_fraction)
    return SubTestResult(
        name="I4", score=score, applicable=True,
        detail={"duplicate_fraction": duplicate_fraction, "n_sources": len(distinct_sources),
                "n_candidate_pairs": len(pair_owner),
                "em_converged": em_result["converged"], "em_pi_estimated": em_result["pi"]},
        note=f"Estimated cross-catalog duplicate fraction: {duplicate_fraction:.1%} "
             f"across {len(distinct_sources)} distinct sources "
             f"(EM-fitted Fellegi-Sunter over {len(pair_owner)} candidate pairs, "
             f"pi_hat={em_result['pi']:.4f}, "
             f"{'converged' if em_result['converged'] else 'did NOT converge'}).",
    )


def _score_i5_temporal_distribution_drift(
    dataset: CertifyDataset,
    field: str = "magnitude",
    n_windows: int = 2,
) -> SubTestResult:
    """
    I5: Temporal distribution drift -- an early-vs-late two-sample
    Kolmogorov-Smirnov test on a single numeric field's distribution
    (main framework Section 3.4). Score_I5 = 1 - D, the KS statistic
    itself, already bounded in [0,1] (Gap-Remediation Addendum Section
    3.3).

    NAMING NOTE (2026-07-20): this test was previously named/labeled
    "schema drift" in code, comments, and output. That name is
    misleading -- "schema drift" ordinarily refers to STRUCTURAL changes
    to a dataset (columns added/removed/renamed, dtype changes, unit
    changes, new categorical values appearing). What this function
    actually detects is DISTRIBUTIONAL drift: whether a single already-
    present numeric field's values (by default, `magnitude`) are drawn
    from a different distribution in the later half of the catalog's
    time range than the earlier half (e.g. a step-change in reported
    magnitudes suggesting an instrumentation or processing change). It
    does not inspect the dataset's schema/structure at all. Renamed here
    for accuracy; the underlying KS-test computation is unchanged.
    """
    values = getattr(dataset, field)
    valid = np.isfinite(values) & ~np.isnat(dataset.origin_time)
    if np.sum(valid) < 40:
        return SubTestResult(name="I5", score=float("nan"), applicable=False,
                              note=f"Fewer than 40 valid, timestamped '{field}' values.")

    days = dataset.origin_time_days()
    order = np.argsort(days[valid])
    v_sorted = values[valid][order]

    n = len(v_sorted)
    half = n // 2
    early, late = v_sorted[:half], v_sorted[half:]
    d_stat = stats.ks_statistic_2sample(early, late)
    if math.isnan(d_stat):
        return SubTestResult(name="I5", score=float("nan"), applicable=False,
                              note="KS statistic could not be computed.")

    score = float(1.0 - d_stat)
    return SubTestResult(
        name="I5", score=score, applicable=True,
        detail={"ks_statistic": d_stat, "field_checked": field, "n": n},
        note=f"Two-sample KS D={d_stat:.3f} between early/late halves of the "
             f"time-sorted '{field}' distribution.",
    )


def score_instrumentation(dataset: CertifyDataset) -> AxisResult:
    """Compute I(D), the Instrumentation & Provenance-Pipeline Integrity axis."""
    i1 = _score_i1_temporal_drift(dataset)
    i2 = _score_i2_clipping(dataset)
    i3 = _score_i3_revision_flag(dataset)
    i4 = _score_i4_cross_catalog_dedup(dataset)
    i5 = _score_i5_temporal_distribution_drift(dataset)

    subs = {"I1": i1, "I2": i2, "I3": i3, "I4": i4, "I5": i5}
    applicable = {k: v for k, v in subs.items() if v.applicable and not math.isnan(v.score)}

    if applicable:
        w_sum = sum(WITHIN_I[k] for k in applicable)
        score = sum(WITHIN_I[k] * v.score for k, v in applicable.items()) / w_sum
    else:
        score = float("nan")

    notes = [f"I(D) computed from {len(applicable)}/5 applicable tests."]
    return AxisResult(axis="I", score=score, sub_results=subs, notes=notes)
