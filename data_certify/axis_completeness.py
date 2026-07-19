# -*- coding: utf-8 -*-
"""
data_certify/axis_completeness.py -- Completeness & Coverage axis C(D)
(covers Categories IV & V of the failure-mode taxonomy: Modes 15-22).

Implements tests C1-C4 per DATA-CERTIFY_Theoretical_Framework.md Section 3.3,
with the explicit bounded [0,1] scoring transforms specified in
DATA-CERTIFY_06_Gap_Remediation_and_Robustness_Addendum.md Section 3.2
(effect-size-based, per the ASA's 2016 guidance against using raw p-values
as a magnitude score).

    C1  Field-level missingness rate (+ Little's 1988 MCAR chi-square test)
    C2  Magnitude-of-completeness (Mc) adequacy
    C3  Spatio-temporal coverage-gap detection (quadrat / chi-square)
    C4  Sample-size sufficiency per stratum
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import numpy as np

from . import stats
from ._constants import MIN_STRATUM_N, TAU_MC, WITHIN_C
from .results import AxisResult, SubTestResult
from .schema import CertifyDataset


def _score_c1_missingness(dataset: CertifyDataset) -> SubTestResult:
    """
    C1: Score_C1 = 1 - missingness_rate, per required field, averaged
    (Gap-Remediation Addendum Section 3.2). The MCAR flag now uses
    Little's (1988) actual chi-square test (`stats.little_mcar_test`),
    fit via EM on the assumption of approximate multivariate normality of
    (origin_time_days, latitude, longitude, depth_km, magnitude) --
    replacing the earlier first-half/second-half missingness-imbalance
    heuristic, which was disclosed at the time as "a proxy for Little
    1988's formal test, which requires multivariate normality assumptions
    this reference implementation does not fit." It now fits them, via
    `stats.em_mvn_missing`.

    Disclosed limitation carried over from the statistics themselves (not
    specific to this implementation): Little's test, like any MCAR
    diagnostic based only on the observed data, cannot detect missingness
    that depends solely on the unobserved value of the missing field
    itself (pure MNAR/non-ignorable censoring, e.g. "large-magnitude
    events are dropped precisely because they are large") -- this is a
    mathematical impossibility to detect from observed data alone (Rubin
    1976; Little & Rubin 2002), not a gap a better test could close. A
    passing (non-rejected) MCAR flag should be read as "no evidence of
    missingness correlated with OTHER recorded fields," not as a
    guarantee against this class of self-censoring.
    """
    per_field = dataset.required_missingness()
    mean_missingness = float(np.mean(list(per_field.values()))) if per_field else float("nan")
    score = float(1.0 - mean_missingness) if not math.isnan(mean_missingness) else float("nan")

    mcar_like = True
    mcar_detail: Dict[str, Any] = {}
    if dataset.n >= 20:
        days = dataset.origin_time_days()
        X = np.column_stack([days, dataset.latitude, dataset.longitude,
                              dataset.depth_km, dataset.magnitude])
        mcar_result = stats.little_mcar_test(X)
        mcar_like = mcar_result["mcar_at_alpha05"]
        mcar_detail = {
            "little_d2": mcar_result["d2"], "little_df": mcar_result["df"],
            "little_p_value": mcar_result["p_value"],
            "little_n_patterns": mcar_result["n_patterns"],
            "little_em_converged": mcar_result["em_converged"],
        }

    return SubTestResult(
        name="C1", score=score, applicable=True,
        detail={"per_field_missingness": per_field, "mcar_like": mcar_like, **mcar_detail},
        note=f"Mean required-field missingness: {mean_missingness:.1%}. "
             f"Missingness pattern is {'consistent with' if mcar_like else 'NOT consistent with'} "
             f"MCAR (Little 1988 chi-square test"
             + (f", p={mcar_detail['little_p_value']:.4f}" if mcar_detail.get("little_p_value") is not None
                and not math.isnan(mcar_detail["little_p_value"]) else ", insufficient distinct patterns to test")
             + ").",
    )


def _score_c2_completeness_magnitude(dataset: CertifyDataset) -> SubTestResult:
    """C2: Score_C2 = 1 - clip(sigma_Mc / tau_Mc, 0, 1) (Gap-Remediation
    Addendum Section 3.2)."""
    mags = dataset.magnitude[np.isfinite(dataset.magnitude)]
    if len(mags) < 30:
        return SubTestResult(name="C2", score=float("nan"), applicable=False,
                              note="Fewer than 30 valid magnitudes -- Mc estimation unreliable.")

    mc = stats.maximum_curvature_mc(mags)
    if math.isnan(mc):
        return SubTestResult(name="C2", score=float("nan"), applicable=False,
                              note="Maximum-Curvature Mc estimation failed.")

    sigma_mc = stats.mc_bootstrap_se(mags)
    if math.isnan(sigma_mc):
        return SubTestResult(name="C2", score=float("nan"), applicable=False,
                              note=f"Mc={mc:.2f} estimated, but bootstrap SE could not be computed.")

    score = float(np.clip(1.0 - sigma_mc / TAU_MC, 0.0, 1.0))
    return SubTestResult(
        name="C2", score=score, applicable=True,
        detail={"mc": mc, "sigma_mc": sigma_mc, "tau_mc": TAU_MC},
        note=f"Mc={mc:.2f} +/- {sigma_mc:.3f} (tolerance tau_Mc={TAU_MC}).",
    )


def _score_c3_coverage_gaps(
    dataset: CertifyDataset,
    n_time_bins: int = 10,
    n_lat_bins: int = 5,
    n_lon_bins: int = 5,
) -> SubTestResult:
    """
    C3: Spatio-temporal coverage-gap detection via quadrat-count analysis
    against a Poisson-process expected background rate (main framework
    Section 3.3). Score_C3 = 1 - (flagged_cell_count / total_cell_count)
    (Gap-Remediation Addendum Section 3.2).
    """
    valid = (np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
             & ~np.isnat(dataset.origin_time))
    if np.sum(valid) < 30:
        return SubTestResult(name="C3", score=float("nan"), applicable=False,
                              note="Fewer than 30 fully-located, timestamped records.")

    lat = dataset.latitude[valid]
    lon = dataset.longitude[valid]
    days = dataset.origin_time_days()[valid]

    lat_edges = np.linspace(lat.min(), lat.max(), n_lat_bins + 1)
    lon_edges = np.linspace(lon.min(), lon.max(), n_lon_bins + 1)
    time_edges = np.linspace(days.min(), days.max(), n_time_bins + 1)

    # Widen the last bin edge slightly so np.histogramdd's right-inclusive
    # boundary does not silently drop the maximum-valued record.
    lat_edges[-1] += 1e-9
    lon_edges[-1] += 1e-9
    time_edges[-1] += 1e-9

    counts, _ = np.histogramdd(
        np.column_stack([lat, lon, days]),
        bins=[lat_edges, lon_edges, time_edges],
    )
    total_cells = counts.size
    expected_rate = counts.sum() / total_cells

    if expected_rate <= 0:
        return SubTestResult(name="C3", score=float("nan"), applicable=False,
                              note="Zero expected background rate -- cannot evaluate coverage gaps.")

    # A cell is "flagged" if its count is a statistically significant
    # deficit relative to the Poisson expectation (chi-square-style z-test
    # on a single Poisson count: z = (observed - expected) / sqrt(expected)).
    z = (counts - expected_rate) / math.sqrt(expected_rate)
    flagged = z < -1.96  # significant deficit, alpha ~ 0.05 one-sided-ish
    n_flagged = int(np.sum(flagged))
    score = float(1.0 - n_flagged / total_cells)

    return SubTestResult(
        name="C3", score=score, applicable=True,
        detail={"n_flagged_cells": n_flagged, "total_cells": int(total_cells),
                "expected_rate_per_cell": float(expected_rate)},
        note=f"{n_flagged}/{int(total_cells)} space-time bins show a statistically "
             f"significant event-count deficit vs. the Poisson background expectation.",
    )


def _score_c4_sample_sufficiency(
    dataset: CertifyDataset,
    n_lat_strata: int = 4,
    n_lon_strata: int = 4,
) -> SubTestResult:
    """
    C4: Sample-size sufficiency per (region) stratum, using the Shi & Bolt
    (1982) b-value uncertainty bound to determine whether N is large enough
    -- mirrors the N>=30 rule of thumb (main framework Section 3.3).
    Score_C4 = (# strata meeting sufficiency) / (# strata) (Gap-Remediation
    Addendum Section 3.2).
    """
    valid = np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude) & np.isfinite(dataset.magnitude)
    if np.sum(valid) < MIN_STRATUM_N:
        return SubTestResult(name="C4", score=float("nan"), applicable=False,
                              note=f"Fewer than {MIN_STRATUM_N} fully-valid records overall.")

    lat = dataset.latitude[valid]
    lon = dataset.longitude[valid]
    mag = dataset.magnitude[valid]

    lat_edges = np.linspace(lat.min(), lat.max(), n_lat_strata + 1)
    lon_edges = np.linspace(lon.min(), lon.max(), n_lon_strata + 1)
    lat_edges[-1] += 1e-9
    lon_edges[-1] += 1e-9

    lat_bin = np.digitize(lat, lat_edges[1:-1])
    lon_bin = np.digitize(lon, lon_edges[1:-1])

    n_sufficient, n_total_strata = 0, 0
    for i in range(n_lat_strata):
        for j in range(n_lon_strata):
            mask = (lat_bin == i) & (lon_bin == j)
            n_stratum = int(np.sum(mask))
            if n_stratum == 0:
                continue
            n_total_strata += 1
            if n_stratum >= MIN_STRATUM_N:
                n_sufficient += 1

    if n_total_strata == 0:
        return SubTestResult(name="C4", score=float("nan"), applicable=False,
                              note="No non-empty spatial strata found.")

    score = float(n_sufficient / n_total_strata)
    return SubTestResult(
        name="C4", score=score, applicable=True,
        detail={"n_sufficient_strata": n_sufficient, "n_total_strata": n_total_strata,
                "min_stratum_n": MIN_STRATUM_N},
        note=f"{n_sufficient}/{n_total_strata} spatial strata meet the N>={MIN_STRATUM_N} "
             f"sample-sufficiency bound.",
    )


def score_completeness(dataset: CertifyDataset) -> AxisResult:
    """Compute C(D), the Completeness & Coverage axis."""
    c1 = _score_c1_missingness(dataset)
    c2 = _score_c2_completeness_magnitude(dataset)
    c3 = _score_c3_coverage_gaps(dataset)
    c4 = _score_c4_sample_sufficiency(dataset)

    subs = {"C1": c1, "C2": c2, "C3": c3, "C4": c4}
    applicable = {k: v for k, v in subs.items() if v.applicable and not math.isnan(v.score)}

    if applicable:
        w_sum = sum(WITHIN_C[k] for k in applicable)
        score = sum(WITHIN_C[k] * v.score for k, v in applicable.items()) / w_sum
    else:
        score = float("nan")

    notes = [f"C(D) computed from {len(applicable)}/4 applicable tests."]
    return AxisResult(axis="C", score=score, sub_results=subs, notes=notes)
