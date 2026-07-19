# -*- coding: utf-8 -*-
"""
data_certify/axis_plausibility.py -- Physical & Logical Plausibility axis
P(D)  (covers Categories II & III of the failure-mode taxonomy: Modes 6-14).

Implements tests P1-P9 per DATA-CERTIFY_Theoretical_Framework.md Section 3.2.

    P1  Lat/lon geometric bounds                       -- HARD GATE
    P2  Depth bound (750 km, tectonic-regime-conditional) -- HARD GATE
    P3  Magnitude bound (9.5)                            -- HARD GATE
    P4  Tsunami joint plausibility (mag x depth x mechanism)
    P5  Wells & Coppersmith (1994) rupture-scaling consistency
    P6  Moment-magnitude self-consistency (Mw vs M0)
    P7  Chronological consistency
    P8  Plate-boundary proximity (soft, distance-decay)
    P9  Bakun & Wentworth (1997) intensity-distance consistency

P1-P3 are NOT part of the weighted sum (main framework Section 3.2): they
are per-record violation flags consumed directly by hard_override.py's
Clopper-Pearson non-trivial-fraction test, never diluted into a graded
score. This module reports both: (a) the per-record violation masks needed
by hard_override.py, and (b) the graded P(D) axis score built from P4-P9 only.
"""

from __future__ import annotations

import math
from typing import Dict, Optional

import numpy as np

from . import stats
from ._constants import (
    DEPTH_MAX_KM, DEPTH_MIN_KM, LAT_MAX, LAT_MIN, LON_MAX, LON_MIN,
    MAGNITUDE_MAX, MAGNITUDE_MIN, MOMENT_MAGNITUDE_SI_CONSTANT, WITHIN_P,
)
from .reference_data import FaultDatabaseReference, NullFaultDatabase
from .results import AxisResult, SubTestResult
from .schema import CertifyDataset

# ---------------------------------------------------------------------------
# P1-P3: structural hard-gate violation masks (used by hard_override.py)
# ---------------------------------------------------------------------------


def p1_violation_mask(dataset: CertifyDataset) -> np.ndarray:
    """P1: |lat| > 90 or |lon| > 180. NaN coordinates are NOT violations
    (that is a completeness failure, C1's concern, not a plausibility one)."""
    lat, lon = dataset.latitude, dataset.longitude
    viol = np.zeros(dataset.n, dtype=bool)
    valid_lat = np.isfinite(lat)
    valid_lon = np.isfinite(lon)
    viol[valid_lat] |= (lat[valid_lat] < LAT_MIN) | (lat[valid_lat] > LAT_MAX)
    viol[valid_lon] |= (lon[valid_lon] < LON_MIN) | (lon[valid_lon] > LON_MAX)
    return viol


def p2_violation_mask(dataset: CertifyDataset) -> np.ndarray:
    """P2: depth outside [DEPTH_MIN_KM, DEPTH_MAX_KM] = [-5, 750] km (lower
    bound revised 2026-07-06 from 0.0 -- see _constants.py's DEPTH_MIN_KM
    comment for the calibration finding and USGS primary-source citations).
    Tectonic-regime-conditional shallow-vs-
    Wadati-Benioff banding (main framework Section 3.2) requires a
    plate-boundary reference; only the universal hard bound is enforced here
    -- the regime-conditional refinement is folded into P8's soft signal
    (Deep-Dive 04, Mode 9) rather than duplicated as a second hard gate."""
    depth = dataset.depth_km
    viol = np.zeros(dataset.n, dtype=bool)
    valid = np.isfinite(depth)
    viol[valid] = (depth[valid] < DEPTH_MIN_KM) | (depth[valid] > DEPTH_MAX_KM)
    return viol


def p3_violation_mask(dataset: CertifyDataset) -> np.ndarray:
    """P3: magnitude outside [MAGNITUDE_MIN, MAGNITUDE_MAX] = [-2.5, 9.5]
    (lower bound revised 2026-07-06 from 0.0 -- see _constants.py's
    MAGNITUDE_MIN comment for the calibration finding and USGS citation)."""
    mag = dataset.magnitude
    viol = np.zeros(dataset.n, dtype=bool)
    valid = np.isfinite(mag)
    viol[valid] = (mag[valid] < MAGNITUDE_MIN) | (mag[valid] > MAGNITUDE_MAX)
    return viol


# ---------------------------------------------------------------------------
# P4-P9: graded plausibility tests
# ---------------------------------------------------------------------------

# P4: primary-source-verified against Whitmore et al. (2008), "NOAA/West
# Coast and Alaska Tsunami Warning Center Pacific Ocean response criteria,"
# Science of Tsunami Hazards 27(2):1-19 (USGS Pub 70010016). Two independent
# findings from that paper support these two numbers directly:
#   - Depth: the paper's Table 2 (worldwide tsunamis >=0.5m amplitude since
#     1900) shows 90% of tsunamigenic earthquakes occur at <50 km, 9% at
#     50-100 km, and <1% at >100 km, and the paper states this "support[s]
#     the international tsunami standard of not issuing tsunami warnings for
#     earthquakes over 100km in depth except in cases where the size, depth,
#     and location of the quake indicate possible rupture to shallow
#     depths" -- i.e. 100 km is the literal, named primary-source figure,
#     not an approximation of one.
#   - Magnitude: the paper's Table 3 bins WCATWC criteria levels by
#     magnitude and shows tsunami-generation rate jumps from 0% in the
#     6.0-6.4 bin to 0.75% in the 6.5-7.0 bin (the first bin with any
#     nonzero historical generation), which is the natural primary-source
#     basis for a 6.5 floor.
# Disclosed simplification: the real WCATWC criteria are a graduated,
# multi-tier magnitude/distance decision system (Figures 6-7 of the paper,
# not reproducible as literal numbers from the text -- they are flowcharts)
# that also considers distance from coast and, for events between M7.1 and
# M7.5, offshore/onshore location. This implementation's single joint
# mag>=6.5 AND depth<=100km check is a defensible, primary-source-grounded
# simplification of that system, not a literal reproduction of it.
# RE-VERIFIED (2026-07-07, Earth Science Informatics submission prep): independently re-fetched
# the primary source (pubs.usgs.gov/publication/70010016, PDF at
# library.lanl.gov/tsunami/ts272.pdf) and re-confirmed both numbers against
# it directly -- no change to either constant.
P4_MAG_FLOOR = 6.5
P4_DEPTH_CEILING_KM = 100.0

# P5: Wells & Coppersmith (1994), BSSA 84:974-1002, Table 2A, regression
# "log10(SRL) = a + b*M" (SRL = surface rupture length in km). Verified
# directly against the original paper (coefficient, standard error in
# parentheses, sigma = regression standard deviation, N = event count):
# RE-VERIFIED (2026-07-07, Earth Science Informatics submission prep): independently re-fetched
# the primary-source PDF and checked all four rows digit-for-digit against
# the paper's own Table 2A text -- exact match, no change.
#   All  (any mechanism): a=-3.22(0.27), b=0.69(0.04), sigma=0.22, N=77
#   SS   (strike-slip):   a=-3.55(0.37), b=0.74(0.05), sigma=0.23, N=43
#   R    (reverse):       a=-2.86(0.55), b=0.63(0.08), sigma=0.20, N=19
#   N    (normal):        a=-2.01(0.65), b=0.50(0.10), sigma=0.21, N=15
# Selected per-record by the dataset's `mechanism` field (schema.py:
# "strike-slip"|"reverse"|"normal"|""), falling back to the "All" row when
# mechanism is unknown/blank. NOTE: an earlier draft of this module used
# the SS-specific coefficients (-3.55, 0.74) mislabeled as "generic
# all-mechanisms" -- that was a real bug (SS != All), not just missing
# detail; fixed here by using the correct "All" row as the generic
# fallback and adding real per-mechanism selection as originally intended.
P5_WC_COEFFICIENTS = {
    "all":         (-3.22, 0.69, 0.22),
    "strike-slip": (-3.55, 0.74, 0.23),
    "reverse":     (-2.86, 0.63, 0.20),
    "normal":      (-2.01, 0.50, 0.21),
}
P5_SIGMA_MULTIPLIER = 3.0  # ~3-sigma plausibility band (main framework Section 3.2)

# P9: Bakun & Wentworth (1997) intensity-magnitude relation coefficients,
# calibrated on 22 California earthquakes. Region-transferability is an
# explicitly open item (Gap-Remediation Addendum Section 4) -- no numeric
# tolerance band is asserted; this implementation reports the |MI-M|
# residual directly and scores it via a documented, disclosed provisional
# tolerance rather than an unverified "official" band.
P9_MMI_CONST, P9_DIST_COEF, P9_DIVISOR = 3.29, 0.0206, 1.68
P9_PROVISIONAL_TOLERANCE = 0.75  # magnitude units; disclosed provisional, not from Bakun & Wentworth


def _score_p4_tsunami(dataset: CertifyDataset) -> SubTestResult:
    have_flag = np.isfinite(dataset.tsunami_flag)
    if not np.any(have_flag):
        return SubTestResult(name="P4", score=float("nan"), applicable=False,
                              note="No tsunami_flag field populated.")

    idx = np.where(have_flag & (dataset.tsunami_flag > 0.5))[0]
    if len(idx) == 0:
        return SubTestResult(name="P4", score=1.0, applicable=True,
                              note="No tsunami-flagged events to check.")

    violations = 0
    for i in idx:
        mag, depth = dataset.magnitude[i], dataset.depth_km[i]
        if not (np.isfinite(mag) and np.isfinite(depth)):
            continue
        plausible = (mag >= P4_MAG_FLOOR) and (depth <= P4_DEPTH_CEILING_KM)
        if not plausible:
            violations += 1

    score = float(1.0 - violations / len(idx))
    return SubTestResult(
        name="P4", score=score, applicable=True,
        detail={"n_tsunami_flagged": len(idx), "n_implausible": violations,
                "mag_floor": P4_MAG_FLOOR, "depth_ceiling_km": P4_DEPTH_CEILING_KM},
        note=(f"{violations}/{len(idx)} tsunami_flag=true events fail the joint "
              f"mag>={P4_MAG_FLOOR}/depth<={P4_DEPTH_CEILING_KM}km check "
              f"(Whitmore et al. 2008, Tables 2-3 -- see module-level comment; "
              f"a disclosed simplification of WCATWC's full graduated criteria)."),
    )


def _score_p5_wells_coppersmith(dataset: CertifyDataset) -> SubTestResult:
    have_len = np.isfinite(dataset.rupture_length_km) & np.isfinite(dataset.magnitude)
    if not np.any(have_len):
        return SubTestResult(name="P5", score=float("nan"), applicable=False,
                              note="No rupture_length_km field populated.")

    idx = np.where(have_len)[0]
    mechanism = dataset.mechanism[idx]
    a = np.empty(len(idx), dtype=float)
    b = np.empty(len(idx), dtype=float)
    sigma = np.empty(len(idx), dtype=float)
    n_per_mechanism: Dict[str, int] = {}
    for j, mech in enumerate(mechanism):
        key = mech if mech in P5_WC_COEFFICIENTS else "all"
        n_per_mechanism[key] = n_per_mechanism.get(key, 0) + 1
        a[j], b[j], sigma[j] = P5_WC_COEFFICIENTS[key]

    predicted_log_l = a + b * dataset.magnitude[idx]
    observed_log_l = np.log10(np.clip(dataset.rupture_length_km[idx], 1e-6, None))
    residual = np.abs(observed_log_l - predicted_log_l)
    band = P5_SIGMA_MULTIPLIER * sigma
    violations = int(np.sum(residual > band))
    score = float(1.0 - violations / len(idx))
    return SubTestResult(
        name="P5", score=score, applicable=True,
        detail={"n_checked": len(idx), "n_implausible": violations,
                "n_per_mechanism": n_per_mechanism},
        note=(f"{violations}/{len(idx)} rupture-length records fall outside "
              f"{P5_SIGMA_MULTIPLIER}-sigma of the Wells & Coppersmith (1994) "
              f"Table 2A regression for their reported (or, when unknown, "
              f"generic 'all mechanisms') fault mechanism: {n_per_mechanism}."),
    )


def _score_p6_moment_magnitude(dataset: CertifyDataset, tolerance: float = 0.3) -> SubTestResult:
    have_both = np.isfinite(dataset.seismic_moment_n_m) & np.isfinite(dataset.magnitude) \
        & (dataset.seismic_moment_n_m > 0)
    if not np.any(have_both):
        return SubTestResult(name="P6", score=float("nan"), applicable=False,
                              note="No seismic_moment_n_m field populated.")

    idx = np.where(have_both)[0]
    predicted_mw = (2.0 / 3.0) * np.log10(dataset.seismic_moment_n_m[idx]) + MOMENT_MAGNITUDE_SI_CONSTANT
    residual = np.abs(predicted_mw - dataset.magnitude[idx])
    violations = int(np.sum(residual > tolerance))
    score = float(1.0 - violations / len(idx))
    return SubTestResult(
        name="P6", score=score, applicable=True,
        detail={"n_checked": len(idx), "n_inconsistent": violations, "tolerance": tolerance},
        note=f"{violations}/{len(idx)} records fail Mw=(2/3)log10(M0){MOMENT_MAGNITUDE_SI_CONSTANT:+.2f} "
             f"within tolerance {tolerance}.",
    )


def _score_p7_chronological(dataset: CertifyDataset) -> SubTestResult:
    valid = ~np.isnat(dataset.origin_time)
    if np.sum(valid) < 2:
        return SubTestResult(name="P7", score=float("nan"), applicable=False,
                              note="Fewer than 2 valid timestamps.")

    times = dataset.origin_time[valid]
    unique, counts = np.unique(times, return_counts=True)
    n_exact_dupes = int(np.sum(counts[counts > 1] - 1))
    n = len(times)
    score = float(1.0 - n_exact_dupes / n)
    return SubTestResult(
        name="P7", score=score, applicable=True,
        detail={"n_exact_duplicate_timestamps": n_exact_dupes, "n": n},
        note=f"{n_exact_dupes}/{n} records share an exact duplicate timestamp with "
             f"another record (basic causal-ordering / duplicate-ID sanity check).",
    )


def _score_p8_plate_boundary(dataset: CertifyDataset,
                              fault_db: FaultDatabaseReference,
                              decay_km: float = 300.0) -> SubTestResult:
    if not fault_db.is_available():
        return SubTestResult(name="P8", score=float("nan"), applicable=False,
                              note="No fault/plate-boundary reference database configured.")

    valid = np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
    if not np.any(valid):
        return SubTestResult(name="P8", score=float("nan"), applicable=False,
                              note="No valid (lat, lon) pairs.")

    idx = np.where(valid)[0]
    dists = fault_db.distances_to_nearest_boundary_km(dataset.latitude[idx], dataset.longitude[idx])
    dists = dists[np.isfinite(dists)]
    if len(dists) == 0:
        return SubTestResult(name="P8", score=float("nan"), applicable=False,
                              note="Distance computation failed for all records.")

    # Soft distance-decay weight -- never a hard reject (intraplate events
    # like New Madrid are rare but real; main framework Section 3.2, P8).
    per_record_score = np.exp(-dists / decay_km)
    score = float(np.mean(per_record_score))
    return SubTestResult(
        name="P8", score=score, applicable=True,
        detail={"mean_distance_km": float(np.mean(dists)), "decay_km": decay_km,
                "n_checked": len(dists)},
        note=f"Mean distance to nearest reference boundary: {np.mean(dists):.0f} km "
             f"(soft distance-decay score, decay scale {decay_km} km).",
    )


def _score_p9_intensity(dataset: CertifyDataset) -> SubTestResult:
    have_both = np.isfinite(dataset.mmi) & np.isfinite(dataset.station_distance_km) \
        & np.isfinite(dataset.magnitude)
    if not np.any(have_both):
        return SubTestResult(name="P9", score=float("nan"), applicable=False,
                              note="No mmi/station_distance_km fields populated.")

    idx = np.where(have_both)[0]
    mi = (dataset.mmi[idx] + P9_MMI_CONST + P9_DIST_COEF * dataset.station_distance_km[idx]) / P9_DIVISOR
    residual = np.abs(mi - dataset.magnitude[idx])
    violations = int(np.sum(residual > P9_PROVISIONAL_TOLERANCE))
    score = float(1.0 - violations / len(idx))
    return SubTestResult(
        name="P9", score=score, applicable=True,
        detail={"n_checked": len(idx), "n_implausible": violations,
                "tolerance": P9_PROVISIONAL_TOLERANCE},
        note=(f"{violations}/{len(idx)} intensity reports fail the Bakun & Wentworth "
              f"(1997) MI-vs-M check. NOTE: coefficients calibrated on California data; "
              f"cross-region transfer and the numeric tolerance are explicitly open "
              f"items (Gap-Remediation Addendum Section 4)."),
    )


def score_plausibility(
    dataset: CertifyDataset,
    fault_db: Optional[FaultDatabaseReference] = None,
) -> AxisResult:
    """
    Compute P(D), the Physical & Logical Plausibility axis.

    P1-P3 violation masks are computed and reported (for hard_override.py
    to consume) but are explicitly excluded from the weighted P(D) average
    -- they are structural hard gates, not graded criteria (main framework
    Section 3.2 / Criteria & Weights Master Reference Section 0).
    """
    fault_db = fault_db or NullFaultDatabase()

    p1_mask = p1_violation_mask(dataset)
    p2_mask = p2_violation_mask(dataset)
    p3_mask = p3_violation_mask(dataset)

    p1 = SubTestResult(name="P1", score=float(1.0 - p1_mask.mean()) if dataset.n else float("nan"),
                        applicable=True, detail={"n_violations": int(p1_mask.sum())},
                        note=f"{int(p1_mask.sum())}/{dataset.n} records violate lat/lon bounds "
                             f"(HARD GATE -- see hard_override.py, not part of P(D) weighted sum).")
    p2 = SubTestResult(name="P2", score=float(1.0 - p2_mask.mean()) if dataset.n else float("nan"),
                        applicable=True, detail={"n_violations": int(p2_mask.sum())},
                        note=f"{int(p2_mask.sum())}/{dataset.n} records violate depth bound "
                             f"[{DEPTH_MIN_KM}, {DEPTH_MAX_KM}] km (HARD GATE).")
    p3 = SubTestResult(name="P3", score=float(1.0 - p3_mask.mean()) if dataset.n else float("nan"),
                        applicable=True, detail={"n_violations": int(p3_mask.sum())},
                        note=f"{int(p3_mask.sum())}/{dataset.n} records violate magnitude bound "
                             f"[{MAGNITUDE_MIN}, {MAGNITUDE_MAX}] (HARD GATE).")

    p4 = _score_p4_tsunami(dataset)
    p5 = _score_p5_wells_coppersmith(dataset)
    p6 = _score_p6_moment_magnitude(dataset)
    p7 = _score_p7_chronological(dataset)
    p8 = _score_p8_plate_boundary(dataset, fault_db)
    p9 = _score_p9_intensity(dataset)

    graded = {"P4": p4, "P5": p5, "P6": p6, "P7": p7, "P8": p8, "P9": p9}
    applicable_graded = {k: v for k, v in graded.items() if v.applicable and not math.isnan(v.score)}

    if applicable_graded:
        w_sum = sum(WITHIN_P[k] for k in applicable_graded)
        score = sum(WITHIN_P[k] * v.score for k, v in applicable_graded.items()) / w_sum
    else:
        score = float("nan")

    all_subs = {"P1": p1, "P2": p2, "P3": p3, **graded}
    notes = [f"P(D) computed from {len(applicable_graded)}/6 applicable graded tests (P4-P9). "
             f"P1-P3 are hard gates -- see hard_override.py for the Clopper-Pearson "
             f"non-trivial-fraction decision, not folded into this score."]

    return AxisResult(axis="P", score=score, sub_results=all_subs, notes=notes)
