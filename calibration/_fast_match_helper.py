"""
Calibration-only helper: produces bit-identical results to
data_certify.reference_data._match_against_reference_arrays (verified via
verify_fast_match.py -- exact matched-array and mc_ref/mc_ref_se parity on
real_tonga_20210101_20220117_query), but finds the time-tolerance candidate
window via np.searchsorted on a once-sorted reference array instead of a
full O(n_ref) subtract per query. Same tolerances, same haversine_km
formula, same mc_ref estimator -- only the candidate-lookup strategy
differs, purely for tractability on very large catalogs (e.g.
real_usgs_main: 75,810 x 116,789 events) within this sandbox's per-call
time limits. NOT a change to production code.
"""
import numpy as np
from data_certify.reference_data import _estimate_mc_ref, MatchResult
from data_certify.stats import haversine_km


def fast_match(dataset, ref_time, ref_lat, ref_lon, ref_mag,
               time_tol_sec=30.0, dist_tol_km=50.0, mag_tol=0.5):
    mc_ref, mc_ref_se, mc_ref_is_default = _estimate_mc_ref(ref_mag)
    n = dataset.n
    matched = np.zeros(n, dtype=bool)
    if len(ref_time) == 0:
        return MatchResult(matched=matched, mc_ref=mc_ref, mc_ref_se=mc_ref_se,
                            mc_ref_is_default=mc_ref_is_default)
    order = np.argsort(ref_time)
    ref_time_sorted = ref_time[order]
    ref_lat_sorted = ref_lat[order]
    ref_lon_sorted = ref_lon[order]
    ref_mag_sorted = ref_mag[order]
    tol_td = np.timedelta64(int(round(time_tol_sec * 1000)), "ms")
    for i in range(n):
        query_time = dataset.origin_time[i]
        if np.isnat(query_time):
            continue
        lo = np.searchsorted(ref_time_sorted, query_time - tol_td, side="left")
        hi = np.searchsorted(ref_time_sorted, query_time + tol_td, side="right")
        if lo >= hi:
            continue
        for j in range(lo, hi):
            rt = ref_time_sorted[j]
            if np.isnat(rt):
                continue
            dt_sec = abs((rt - query_time) / np.timedelta64(1, "s"))
            if dt_sec > time_tol_sec:
                continue
            dist = haversine_km(dataset.latitude[i], dataset.longitude[i],
                                 ref_lat_sorted[j], ref_lon_sorted[j])
            if not np.isfinite(dist) or dist > dist_tol_km:
                continue
            if not np.isfinite(dataset.magnitude[i]) or not np.isfinite(ref_mag_sorted[j]):
                continue
            if abs(dataset.magnitude[i] - ref_mag_sorted[j]) <= mag_tol:
                matched[i] = True
                break
    return MatchResult(matched=matched, mc_ref=mc_ref, mc_ref_se=mc_ref_se,
                        mc_ref_is_default=mc_ref_is_default)
