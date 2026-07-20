# -*- coding: utf-8 -*-
"""
data_certify/axis_authenticity.py -- Authenticity axis A(D)  (covers
Category I of the failure-mode taxonomy: Modes 1-5).

Implements tests A1-A6 per DATA-CERTIFY_Theoretical_Framework.md Section
3.1, corrected per DATA-CERTIFY_06_Gap_Remediation_and_Robustness_Addendum.md
Section 1 (magnitude-of-completeness-conditional A6).

    A1  Benford's Law on seismic moment, depth, inter-event waiting times
    A2  Gutenberg-Richter b-value conformity
    A3  Omori-Utsu aftershock-decay conformity
    A4  Spatial fractal-clustering conformity (correlation dimension)
    A5  Duplicate / near-duplicate detection
    A6  External provenance cross-validation (strongest signal, when feasible)

Formula (main framework Section 3.1, corrected per Gap-Remediation Section 1):

    A(D) = A6                                    for the M >= Mc_ref + sigma_Mc stratum,
                                                  when an external reference is feasible
         = (w_A1.A1 + ... + w_A5.A5) / sum(w)    otherwise, or for the M < Mc_ref stratum
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import numpy as np

from . import stats
from ._constants import (
    WITHIN_A, THETA_AUTH,
    A6_CONTRADICTED_MIN_SOURCES, A6_CONTRADICTED_MIN_N_STRATUM, A6_CONTRADICTED_ALPHA,
)
from .reference_data import ExternalCatalogReference, NullExternalCatalog
from .results import AxisResult, SubTestResult
from .schema import CertifyDataset


def _score_a1_benford(dataset: CertifyDataset) -> SubTestResult:
    """
    A1: Benford's Law conformity on multi-order-of-magnitude derived
    quantities -- seismic moment M0, depth (km), and inter-event waiting
    times. Deliberately NOT applied to raw magnitude (Deep-Dive 03, Section
    1.3: too narrow a dynamic range for the scale-invariance precondition).
    """
    candidates: Dict[str, np.ndarray] = {}

    moment = dataset.seismic_moment_n_m
    if np.sum(np.isfinite(moment) & (moment > 0)) >= 30:
        candidates["seismic_moment_n_m"] = moment[np.isfinite(moment) & (moment > 0)]

    depth = dataset.depth_km
    if np.sum(np.isfinite(depth) & (depth > 0)) >= 30:
        candidates["depth_km"] = depth[np.isfinite(depth) & (depth > 0)]

    days = dataset.origin_time_days()
    order = np.argsort(days)
    days_sorted = days[order][np.isfinite(days[order])]
    inter_event = np.diff(days_sorted)
    inter_event = inter_event[inter_event > 0]
    if len(inter_event) >= 30:
        candidates["inter_event_waiting_times"] = inter_event

    if not candidates:
        return SubTestResult(
            name="A1", score=float("nan"), applicable=False,
            note="No multi-order-of-magnitude field (seismic moment / depth / "
                 "inter-event time) with >=30 valid values available for Benford testing.",
        )

    per_field_scores = {}
    per_field_chi2 = {}
    for field_name, values in candidates.items():
        chi2, dof, n = stats.benford_chi_square(values)
        per_field_scores[field_name] = stats.benford_score(chi2, n)
        per_field_chi2[field_name] = chi2

    score = float(np.mean(list(per_field_scores.values())))
    # n_used (2026-07-21, external review, sample-sufficiency gate --
    # MIN_RELIABLE_N in _constants.py): the smallest per-field valid-value
    # count actually used, i.e. the weakest link among whichever field(s)
    # this score rests on -- see decision.py's `_compute_sample_sufficiency`.
    n_used = min(len(v) for v in candidates.values())
    return SubTestResult(
        name="A1", score=score, applicable=True,
        detail={"per_field_score": per_field_scores, "per_field_chi2": per_field_chi2,
                "n_used": n_used},
        note=f"Benford conformity across {list(candidates.keys())}.",
    )


def _score_a2_gutenberg_richter(dataset: CertifyDataset,
                                 mc: Optional[float] = None) -> SubTestResult:
    """A2: Gutenberg-Richter b-value conformity (main framework Section 3.1)."""
    mags = dataset.magnitude[np.isfinite(dataset.magnitude)]
    if len(mags) < 30:
        return SubTestResult(name="A2", score=float("nan"), applicable=False,
                              note="Fewer than 30 valid magnitudes -- b-value unreliable.")

    mc_est = mc if mc is not None else stats.maximum_curvature_mc(mags)
    if not math.isfinite(mc_est):
        return SubTestResult(name="A2", score=float("nan"), applicable=False,
                              note="Could not estimate magnitude of completeness.")

    complete = mags[mags >= mc_est]
    if len(complete) < 10:
        return SubTestResult(name="A2", score=float("nan"), applicable=False,
                              note=f"Fewer than 10 events at/above estimated Mc={mc_est:.2f}.")

    b_hat = stats.gr_b_value_aki(complete, mc_est)
    se = stats.gr_b_value_shi_bolt_se(complete, b_hat)
    if math.isnan(b_hat):
        return SubTestResult(name="A2", score=float("nan"), applicable=False,
                              note="b-value estimation failed (non-positive denominator).")

    # Score = 1 - clip((|b-1.0| - 0.5)/1.0, 0, 1)  -- main framework Section 3.1.
    score = float(np.clip(1.0 - (abs(b_hat - 1.0) - 0.5) / 1.0, 0.0, 1.0))
    return SubTestResult(
        name="A2", score=score, applicable=True,
        detail={"b_value": b_hat, "shi_bolt_se": se, "mc_used": mc_est, "n": len(complete),
                # n_used (2026-07-21, external review, sample-sufficiency gate):
                # alias of "n" above, named consistently with A1/A3/A4/A5 for
                # decision.py's `_compute_sample_sufficiency` to consume generically.
                "n_used": len(complete)},
        note=f"b={b_hat:.3f} (+/-{se:.3f}), Mc={mc_est:.2f}, plausible band [0.5, 1.5].",
    )


def _gardner_knopoff_radius_km(magnitude: float) -> float:
    """
    Gardner & Knopoff (1974) magnitude-dependent aftershock-zone radius,
    L(M) = 10^(0.1238*M + 0.983) km -- the standard empirical fit widely
    used in seismic declustering (see e.g. van Stiphout, Wiemer & Marzocchi
    2012, "Theme V" review, Eq. 2, for the same coefficients as used here).
    Larger mainshocks are expected to produce aftershocks over a
    correspondingly larger area (e.g. ~40 km at M5.5, ~80 km at M7.0,
    ~145 km at M8.0) -- used by `_identify_mainshock_aftershock_clusters`
    below to add the spatial constraint that function's docstring
    previously disclosed as missing (see BUGFIX note there).
    """
    return float(10.0 ** (0.1238 * magnitude + 0.983))


def _identify_mainshock_aftershock_clusters(dataset: CertifyDataset,
                                             mainshock_mag_threshold: float = 5.5,
                                             window_days: float = 30.0) -> List[np.ndarray]:
    """
    Gardner-Knopoff-style declustering: for each event above
    `mainshock_mag_threshold`, treat subsequent smaller events within
    `window_days` AND within a magnitude-dependent spatial radius
    (`_gardner_knopoff_radius_km`, Gardner & Knopoff 1974) as candidate
    aftershocks.

    BUGFIX (2026-07-21, found by external review): this function previously
    used ONLY the time window and magnitude condition, with no spatial
    constraint at all -- meaning two independent earthquakes on opposite
    sides of the planet, occurring within the same `window_days` window,
    could be merged into a single "aftershock sequence" for a regional or
    global catalog. This directly affects A3, which carries ~29% of A(D)'s
    nominal weight in the common intrinsic-only case -- a global catalog
    could show an apparent Omori-Utsu-consistent decay purely from
    unrelated, independent seismicity coincidentally decaying in rate over
    time (background seismicity is not stationary), not genuine aftershock
    physics. Fixed by adding the missing spatial term, using each
    candidate mainshock's own Gardner-Knopoff radius (so a large mainshock
    is allowed a correspondingly larger aftershock zone, not a fixed
    distance for every magnitude).

    NOTE: this changes A3's actual scored output for any dataset spanning
    a large geographic area (previously time-window-only candidates that
    are NOT within the spatial radius of their putative mainshock are no
    longer included) -- a genuine, disclosed behavior change from the
    prior simplification, not merely an additive diagnostic.

    PERFORMANCE NOTE (calibration-corpus bug-hunt, discovered scoring
    Dataset/earthquake1.csv -- NOAA/ISC-GEM's "significant earthquakes"
    catalog): the previous implementation re-scanned the FULL sorted
    `d_sorted`/`mags` arrays with `np.where(...)` once per candidate
    mainshock, i.e. O(n_mainshocks * n) overall. On an ordinary seismic-
    network catalog (mostly M<5.5 events) n_mainshocks << n and this is
    cheap; but on a catalog that is ITSELF already pre-filtered to
    significant/large events -- a legitimate, non-adversarial real input,
    not an edge case -- essentially every row qualifies as a "mainshock"
    (confirmed: 23,232/23,232 rows on earthquake1.csv), making this
    effectively O(n^2) and measured to take >40s on that one 23k-row
    file (score_authenticity() on the whole calibration corpus needed to
    complete calls like this in a couple of seconds to be tractable).
    Since `d_sorted` is already sorted ascending, `np.searchsorted`
    binary-searches the two window boundaries in O(log n) instead of
    re-scanning in O(n) per mainshock, turning the whole loop into
    O(n_mainshocks * log n + total window size) -- verified to produce
    BIT-IDENTICAL cluster output to the previous implementation on a
    4,000-row random subsample of earthquake1.csv (1,071/1,071 clusters
    matching exactly, including cluster contents) while cutting the
    full-file runtime from >40s (timed out) to 0.44s.
    """
    days = dataset.origin_time_days()
    order = np.argsort(days)
    mags = dataset.magnitude[order]
    d_sorted = days[order]
    lat_sorted = dataset.latitude[order]
    lon_sorted = dataset.longitude[order]

    clusters = []
    mainshock_idx = np.where(np.isfinite(mags) & (mags >= mainshock_mag_threshold))[0]
    for idx in mainshock_idx:
        t0 = d_sorted[idx]
        if not np.isfinite(t0):
            continue
        if not (np.isfinite(lat_sorted[idx]) and np.isfinite(lon_sorted[idx])):
            continue  # no coordinates for the candidate mainshock -- cannot apply the spatial term at all
        # Binary-search the (t0, t0+window_days] slice instead of an
        # O(n) full-array boolean scan (see perf note above). d_sorted
        # is ascending, so side="right" on t0 gives the first index with
        # d_sorted > t0, and side="right" on t0+window_days gives the
        # first index with d_sorted > t0+window_days -- together these
        # bracket exactly the same half-open interval the original
        # `(d_sorted > t0) & (d_sorted <= t0 + window_days)` mask did.
        lo = np.searchsorted(d_sorted, t0, side="right")
        hi = np.searchsorted(d_sorted, t0 + window_days, side="right")
        if hi <= lo:
            continue
        window_days_arr = d_sorted[lo:hi]
        window_mags = mags[lo:hi]
        window_lat = lat_sorted[lo:hi]
        window_lon = lon_sorted[lo:hi]

        # SPATIAL TERM (2026-07-21 bugfix -- see docstring above): only
        # candidates within this mainshock's own Gardner-Knopoff radius
        # count as aftershocks. NaN candidate coordinates are excluded
        # (haversine propagates NaN -> the distance check below correctly
        # drops them), not silently treated as "at distance 0".
        radius_km = _gardner_knopoff_radius_km(mags[idx])
        dist_km = stats.haversine_km_matrix(
            np.array([lat_sorted[idx]]), np.array([lon_sorted[idx]]),
            window_lat, window_lon,
        )[0]
        spatial_mask = np.isfinite(dist_km) & (dist_km <= radius_km)

        after_mask = (window_mags < mags[idx]) & spatial_mask
        if int(np.sum(after_mask)) >= 5:
            clusters.append(window_days_arr[after_mask] - t0)
    return clusters


MAX_A3_CLUSTERS: int = 2000


def _score_a3_omori_utsu(dataset: CertifyDataset) -> SubTestResult:
    """A3: Omori-Utsu aftershock-decay conformity (main framework Section 3.1).

    PERFORMANCE NOTE (same bug-hunt as _identify_mainshock_aftershock_
    clusters' docstring above): fixing that function's O(n^2) search
    still leaves one more cost proportional to the RESULT size, not n --
    each candidate cluster gets its own `stats.fit_omori_utsu` call
    (~2ms, an iterative fit), and a catalog composed mostly of M>=5.5
    events with a 30-day window produces heavily OVERLAPPING candidate
    clusters (measured: 17,570 clusters on earthquake1.csv's 23,232
    events -- most clusters share the bulk of their member events with
    several neighbouring clusters, since nearby mainshocks' 30-day
    windows overlap). Fitting all 17,570 took ~35s by itself. Since A3's
    score is just `0.5*frac_non_degenerate + 0.5*mean(p_scores)` over
    the fitted clusters -- an average that stabilises with a few hundred
    to a couple thousand samples and does not meaningfully change by
    fitting tens of thousands of heavily-redundant windows -- this caps
    the number of clusters actually fit at MAX_A3_CLUSTERS, subsampling
    (without replacement, fixed seed) exactly like `correlation_dimension`'s
    own disclosed `max_points` cap in stats.py, for the same reason:
    bounding an O(result_size) cost that scales with catalog composition
    rather than raw record count, without a corresponding gain in the
    score's precision beyond that sample size.
    """
    clusters = _identify_mainshock_aftershock_clusters(dataset)
    if not clusters:
        return SubTestResult(name="A3", score=float("nan"), applicable=False,
                              note="No mainshock-aftershock sequence with >=5 candidate "
                                   "aftershocks identified (needs M>=5.5 mainshock).")

    n_clusters_found = len(clusters)
    if n_clusters_found > MAX_A3_CLUSTERS:
        rng = np.random.RandomState(42)
        keep = rng.choice(n_clusters_found, size=MAX_A3_CLUSTERS, replace=False)
        clusters = [clusters[k] for k in keep]

    fits = [stats.fit_omori_utsu(c) for c in clusters]
    valid_fits = [f for f in fits if not f["degenerate"] and math.isfinite(f["p"])]

    frac_non_degenerate = len(valid_fits) / len(fits)
    # Score rewards fits with realistic decay exponent p in [0.9, 1.5]
    # (Utsu, Ogata & Matsu'ura 1995) and penalises degenerate (non-decaying) fits.
    if valid_fits:
        p_scores = [1.0 - min(1.0, abs(f["p"] - 1.2) / 1.2) for f in valid_fits]
        p_score = float(np.mean(p_scores))
    else:
        p_score = 0.0

    score = float(0.5 * frac_non_degenerate + 0.5 * p_score)
    cap_note = (f" ({n_clusters_found} candidate clusters found; subsampled to "
                f"MAX_A3_CLUSTERS={MAX_A3_CLUSTERS} for tractability -- see this "
                f"function's docstring.)" if n_clusters_found > MAX_A3_CLUSTERS else "")
    return SubTestResult(
        name="A3", score=score, applicable=True,
        detail={"n_clusters": len(clusters), "n_clusters_found": n_clusters_found,
                "n_valid_fits": len(valid_fits),
                "mean_p": float(np.mean([f["p"] for f in valid_fits])) if valid_fits else None,
                # n_used (2026-07-21, external review, sample-sufficiency gate --
                # MIN_RELIABLE_N["A3"] in _constants.py): the number of INDEPENDENT
                # candidate mainshock-aftershock clusters identified, NOT the event
                # count within any single cluster -- a score built from one cluster
                # cannot be trusted the way an average over dozens can.
                "n_used": n_clusters_found},
        note=f"{len(valid_fits)}/{len(clusters)} candidate aftershock sequences show "
             f"genuine Omori-Utsu-consistent decay.{cap_note}",
    )


def _score_a4_fractal_dimension(dataset: CertifyDataset,
                                 reference_dc: Optional[float] = None) -> SubTestResult:
    """
    A4: Spatial fractal-clustering conformity via correlation dimension Dc
    (Grassberger-Procaccia 1983; Kagan & Knopoff 1976, 1980).

    Compared against a reference Dc when available (Deep-Dive 03, Section
    2.3: no fixed universal band is used); absent a reference, flags only
    the unambiguous failure direction -- Dc trending toward the embedding
    dimension (2.0), the signature of spatially near-uniform (fabricated)
    coordinates rather than fault-controlled real seismicity.

    BUGFIX (2026-07-21, found by external review): previously passed raw
    (latitude, longitude) IN DEGREES directly into `correlation_dimension`,
    which computes plain Euclidean pairwise distance -- wrong for
    geographic coordinates (longitude's km-per-degree shrinks toward the
    poles, and the +/-180 antimeridian is a discontinuity in raw degrees
    despite being geographically contiguous). Fixed by projecting to a
    local, small-to-regional-scale equirectangular approximation in km
    first (`stats.project_lonlat_to_local_km`) -- see that function's
    docstring for the full rationale. This changes A4's actual scored Dc
    for any dataset spanning a wide area, near the poles, or straddling
    the dateline (e.g. Fiji/Tonga/Aleutians) -- a genuine, disclosed
    behavior change, not merely an additive diagnostic. Any externally
    supplied `reference_dc` must be computed the same way (under this
    same km-projection) to remain a valid comparison point.
    """
    valid = np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
    if np.sum(valid) < 50:
        return SubTestResult(name="A4", score=float("nan"), applicable=False,
                              note="Fewer than 50 valid (lat, lon) pairs for correlation-dimension estimation.")

    points = stats.project_lonlat_to_local_km(dataset.latitude[valid], dataset.longitude[valid])
    dc = stats.correlation_dimension(points)
    if math.isnan(dc):
        return SubTestResult(name="A4", score=float("nan"), applicable=False,
                              note="Correlation-dimension fit did not converge.")

    if reference_dc is not None and math.isfinite(reference_dc):
        deviation = abs(dc - reference_dc)
        score = float(np.clip(1.0 - deviation / 0.5, 0.0, 1.0))
        note = f"Dc={dc:.3f} vs reference Dc={reference_dc:.3f}."
    else:
        # No reference available: only flag the unambiguous direction
        # (Dc -> 2.0, i.e. spatially unclustered/uniform-random points).
        score = float(np.clip((2.0 - dc) / 1.0, 0.0, 1.0))
        note = (f"Dc={dc:.3f} (embedding dim=2.0); no same-region reference catalog "
                f"available, so only the Dc->2.0 (uniform/unclustered) failure "
                f"direction is scored (Deep-Dive 03 Section 2.3).")

    return SubTestResult(name="A4", score=score, applicable=True,
                          detail={"correlation_dimension": dc, "reference_dc": reference_dc,
                                   # n_used (2026-07-21, external review, sample-sufficiency
                                   # gate -- MIN_RELIABLE_N["A4"] in _constants.py): count of
                                   # valid (lat, lon) pairs actually fed into the
                                   # correlation-dimension estimate.
                                   "n_used": int(np.sum(valid))},
                          note=note)


MAX_A5_NEIGHBORHOOD_CANDIDATES: int = 500


def _score_a5_duplicates(dataset: CertifyDataset,
                          time_eps_sec: float = 5.0,
                          dist_eps_km: float = 2.0,
                          mag_eps: float = 0.05,
                          max_neighborhood_candidates: int = MAX_A5_NEIGHBORHOOD_CANDIDATES) -> SubTestResult:
    """
    A5: Duplicate / near-duplicate detection via exact hash + epsilon-ball
    clustering in normalised (time, lat, lon, magnitude) space (Deep-Dive
    03, Section 3).

    PERFORMANCE / CORRECTNESS NOTE (calibration-corpus bug-hunt): the
    previous implementation's inner `for j in range(j_start, i)` loop
    compared EVERY pair of records within the sliding time window,
    i.e. O(k^2) for a time-cluster of k records sharing (approximately)
    one timestamp -- the comment above it claiming "O(N) amortised for
    typical catalogs" is only true when no single time-cluster is large,
    which fails exactly for the "many records share one timestamp"
    batch-import defect this sub-test exists to catch (verified: hung
    past 40s on a 7,009-record catalog with ~70% of records sharing one
    injected timestamp). The fix adds a coarse spatial grid (bucket
    pitch sized to dist_eps_km) so each record `i` is only compared
    against records in its own and the 8 neighbouring cells, rather than
    every other record active in the time window -- correct because any
    genuine near-duplicate (within dist_eps_km) is guaranteed to fall in
    that 3x3 neighbourhood, verified bit-identical to the previous
    all-pairs result on a 3,000-record random subsample of a duplicate-
    heavy corpus dataset (212/212 flagged records matching exactly), and
    cuts the pathological 7,009-record case from a >40s hang to 0.24s.
    Longitude cells are widened by 1/cos(max|latitude| in the dataset) so
    the fixed-degree grid pitch still spans dist_eps_km at high latitude
    (a degree of longitude shrinks toward the poles); this is exact for
    this dataset's own most extreme latitude, not a universal constant,
    and -- like `correlation_dimension`'s percentile-based scaling
    region -- is a disclosed geometric approximation good enough for a
    duplicate-detection PRE-FILTER (the actual accept/reject distance
    check below still uses the exact haversine formula).

    BUGFIX (2026-07-21, found by external review -- longitude wraparound):
    the spatial grid's cell index previously used
    `floor(lon / lon_cell_deg)` on raw signed longitude with NO
    wraparound handling, so two points a few hundred metres apart across
    the +/-180 degree antimeridian (e.g. Fiji, Tonga, the Aleutians, or
    any New Zealand/Pacific-region catalog straddling the dateline) landed
    in grid cells at opposite ends of the index range and were NEVER
    compared by the 3x3-neighbourhood scan -- even though the actual
    accept/reject check already correctly used the exact haversine
    formula. Fixed by computing the longitude cell index modulo the total
    number of cells spanning the full 360-degree circle, and wrapping the
    +/-1 neighbour offset the same way, so the highest- and lowest-index
    longitude cells are correctly treated as adjacent.

    PERFORMANCE NOTE (dense-bucket worst case, same review pass): even
    with the spatial grid above, a pathological cluster of many (thousands+)
    records ALL mutually within time_eps/dist_eps/mag_eps of each other
    still costs O(k^2) in the worst case -- the 3x3-neighbourhood candidate
    list itself has k members, and each of the k records must be checked
    against it to exactly determine every duplicate pair. This is not
    fixable for free: exactly identifying every pair within an epsilon-ball
    in a genuinely dense cluster inherently requires an amount of work
    related to how many actual matching pairs exist. As with A3's
    `MAX_A3_CLUSTERS` and `correlation_dimension`'s `max_points`, this is
    therefore BOUNDED rather than solved: if a single record's
    3x3-neighbourhood candidate list exceeds `max_neighborhood_candidates`,
    only a deterministic random subsample (fixed seed) of that size is
    exhaustively checked against it, capping the worst-case cost at
    O(n * max_neighborhood_candidates) instead of O(n^2). A dataset that
    trips this cap already has overwhelming evidence of a batch-import/
    duplication defect (hundreds+ of records sharing the same ~2km/5s/
    0.05-magnitude cell) -- this is a disclosed approximation of the exact
    duplicate_fraction ONLY in that already-anomalous regime, not a change
    to ordinary-catalog behaviour (no bundled or realistic test dataset
    approaches this cap).
    """
    n = dataset.n
    if n < 2:
        return SubTestResult(name="A5", score=1.0, applicable=True,
                              note="Fewer than 2 records -- no duplicates possible.")

    days = dataset.origin_time_days()
    order = np.argsort(days)
    d_sorted = days[order]
    lat_sorted = dataset.latitude[order]
    lon_sorted = dataset.longitude[order]
    mag_sorted = dataset.magnitude[order]

    is_duplicate = np.zeros(n, dtype=bool)
    time_eps_days = time_eps_sec / 86400.0

    # Coarse spatial grid used to avoid the O(k^2) all-pairs blowup within
    # a large same-timestamp cluster (see docstring). Grid pitch is sized
    # so that any two points within dist_eps_km fall in the same or an
    # adjacent cell; longitude pitch is widened using this dataset's own
    # most extreme |latitude| (clipped at 89.9 deg to avoid a div-by-zero
    # at the poles) since a degree of longitude covers fewer km there.
    finite_lat = lat_sorted[np.isfinite(lat_sorted)]
    max_abs_lat = float(np.max(np.abs(finite_lat))) if len(finite_lat) else 0.0
    cos_min = max(math.cos(math.radians(min(max_abs_lat, 89.9))), 1e-6)
    lat_cell_deg = max(dist_eps_km / 111.0, 1e-9)
    lon_cell_deg = max(dist_eps_km / (111.0 * cos_min), 1e-9)
    # Total number of longitude cells spanning the full 360-degree circle,
    # used to wrap the cell index at the +/-180 antimeridian seam (see
    # BUGFIX note above) rather than letting it run off the end.
    n_lon_cells = max(1, int(math.ceil(360.0 / lon_cell_deg)))

    def _lon_cell_index(lon: float) -> int:
        # Normalise to [0, 360) first so a raw longitude near -180 and one
        # near +180 map to cell indices that are numerically adjacent (or
        # wrap around via the modulo below) instead of landing at opposite
        # ends of the index range.
        return int((lon % 360.0) // lon_cell_deg) % n_lon_cells

    def _cell(lat: float, lon: float):
        if not (np.isfinite(lat) and np.isfinite(lon)):
            return None
        return (int(np.floor(lat / lat_cell_deg)), _lon_cell_index(lon))

    grid: Dict[Any, List[int]] = {}

    def _add_to_grid(k: int) -> None:
        c = _cell(lat_sorted[k], lon_sorted[k])
        if c is not None:
            grid.setdefault(c, []).append(k)

    def _remove_from_grid(k: int) -> None:
        c = _cell(lat_sorted[k], lon_sorted[k])
        if c is not None and c in grid:
            try:
                grid[c].remove(k)
                if not grid[c]:
                    del grid[c]
            except ValueError:
                pass

    subsample_rng = np.random.RandomState(42)

    # Candidate-cap diagnostics (2026-07-21, external review): the dense-
    # bucket safety valve below silently subsampled the 3x3-neighbourhood
    # candidate list whenever it exceeded max_neighborhood_candidates,
    # with no record of how often this fired or how severe the
    # subsampling was -- meaning a caller had no way to tell an exact
    # duplicate_fraction apart from one computed under heavy sampling in
    # an anomalously dense cluster. Tracked here and surfaced in `detail`
    # below so this approximation is disclosed, not silent.
    n_capped_queries = 0
    max_candidates_observed = 0

    # Sliding window over the time-sorted array, cross-referenced against
    # the spatial grid: only records within BOTH time_eps_days AND a
    # neighbouring grid cell are ever compared (see docstring for why
    # this is equivalent to, but far cheaper than, the previous
    # unconditional all-pairs-in-time-window comparison).
    j_start = 0
    for i in range(n):
        if not np.isfinite(d_sorted[i]):
            continue
        while j_start < i and (d_sorted[i] - d_sorted[j_start]) > time_eps_days:
            _remove_from_grid(j_start)
            j_start += 1
        c_i = _cell(lat_sorted[i], lon_sorted[i])
        if c_i is not None:
            cy, cx = c_i
            candidates: List[int] = []
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    # Wrap the longitude neighbour offset modulo n_lon_cells
                    # (see BUGFIX note above) so the cell just past +180
                    # correctly wraps to the cell just past -180.
                    wrapped_cx = (cx + dx) % n_lon_cells
                    candidates.extend(grid.get((cy + dy, wrapped_cx), []))
            # Dense-bucket safety valve (see PERFORMANCE NOTE above): bound
            # the worst-case O(k^2) blowup for a pathologically dense
            # cluster, exactly like MAX_A3_CLUSTERS/max_points elsewhere.
            raw_candidate_count = len(candidates)
            if raw_candidate_count > max_candidates_observed:
                max_candidates_observed = raw_candidate_count
            if raw_candidate_count > max_neighborhood_candidates:
                n_capped_queries += 1
                keep = subsample_rng.choice(
                    raw_candidate_count, size=max_neighborhood_candidates, replace=False)
                candidates = [candidates[k] for k in keep]
            for j in candidates:
                dist = stats.haversine_km(lat_sorted[i], lon_sorted[i], lat_sorted[j], lon_sorted[j])
                if not np.isfinite(dist) or dist > dist_eps_km:
                    continue
                if not np.isfinite(mag_sorted[i]) or not np.isfinite(mag_sorted[j]):
                    continue
                if abs(mag_sorted[i] - mag_sorted[j]) <= mag_eps:
                    is_duplicate[i] = True
                    is_duplicate[j] = True
        _add_to_grid(i)

    dup_fraction = float(np.sum(is_duplicate) / n)
    score = float(1.0 - dup_fraction)
    candidate_cap_triggered = n_capped_queries > 0
    # sampling_fraction: the most aggressive subsampling ratio actually
    # applied (max_neighborhood_candidates / the largest raw candidate
    # list observed before subsampling) -- i.e. the worst-case fraction
    # of a dense bucket that was actually exhaustively checked. 1.0 when
    # the cap never fired (no approximation was applied at all).
    sampling_fraction = (
        float(max_neighborhood_candidates) / max_candidates_observed
        if candidate_cap_triggered and max_candidates_observed > 0
        else 1.0
    )
    cap_disclosure_note = (
        f" [approximate: dense-bucket cap triggered on {n_capped_queries} "
        f"of {n} record queries; largest 3x3-neighbourhood candidate list "
        f"observed was {max_candidates_observed} (cap={max_neighborhood_candidates}, "
        f"worst-case sampling_fraction={sampling_fraction:.3f}) -- "
        f"duplicate_fraction above is a sampled approximation in this regime, "
        f"see _score_a5_duplicates docstring.]"
        if candidate_cap_triggered else ""
    )
    return SubTestResult(
        name="A5", score=score, applicable=True,
        detail={"duplicate_fraction": dup_fraction,
                "n_flagged": int(np.sum(is_duplicate)),
                # n_used (2026-07-21, external review, sample-sufficiency gate --
                # MIN_RELIABLE_N["A5"] in _constants.py): total record count.
                "n_used": n,
                # A5 candidate-cap diagnostics (2026-07-21, external review,
                # Task 33): disclose whenever the dense-bucket safety valve
                # above caused duplicate_fraction to be an approximation
                # rather than an exact count, and how severe that
                # approximation was -- see the tracking added around the
                # main loop above.
                "candidate_cap_triggered": candidate_cap_triggered,
                "n_capped_queries": n_capped_queries,
                "max_candidates_observed": max_candidates_observed,
                "sampling_fraction": sampling_fraction},
        note=f"{np.sum(is_duplicate)}/{n} records flagged as (near-)duplicates."
             f"{cap_disclosure_note}")


def _score_a6_external(dataset: CertifyDataset,
                        reference: ExternalCatalogReference) -> Dict[str, "SubTestResult | np.ndarray"]:
    """
    A6: External provenance cross-validation, magnitude-of-completeness
    stratified (Gap-Remediation Addendum Section 1.2), THREE-STATE per
    record within that stratum (Group C3, 2026-07-12 -- see
    `_constants.py`'s A6_CONTRADICTED_* block for the full rationale):

        "Externally corroborated": >=1 independent source matched it.
        "Externally contradicted": queried against >=A6_CONTRADICTED_MIN_SOURCES
            independent sources, none matched (per-record), AND the
            dataset-level match rate over the FULL population that was
            meaningfully queried (corroborated + contradicted-eligible
            records together, not just the zero-match subset in isolation
            -- see the bugfix note inline below) is confirmed
            (Clopper-Pearson lower-tail test) to sit below THETA_AUTH with
            statistical confidence, not just as a point estimate. ONLY this
            state can fire the A6 hard-override REJECT.
        "Externally unverifiable": everything else that isn't a match --
            falls back to intrinsic A1-A5 scoring, no A6 penalty either way.

    Returns a dict with:
        "sub_result": SubTestResult for the reference-complete stratum
        "reference_complete_mask": bool array, True where A6's score
            actually applies (i.e. "Externally corroborated" records, plus
            "Externally contradicted" records IF the dataset-level test
            confirmed -- "Externally unverifiable" records are NEVER in
            this mask, they fall back to intrinsic scoring)
        "hard_reject": bool, True iff the dataset-level "Externally
            contradicted" test fired (this is now the SINGLE authoritative
            computation of A6's hard-override contribution -- hard_override.py
            no longer independently re-derives it from a bare float, see
            that module's updated docstring)
        "hard_reject_reason": str
    """
    n = dataset.n
    empty_mask = np.zeros(n, dtype=bool)
    if not reference.is_feasible():
        return {"sub_result": SubTestResult(
            name="A6", score=float("nan"), applicable=False,
            note="External reference catalog infeasible (no connectivity / no reference "
                 "configured) -- A(D) falls back to intrinsic-only A1-A5 for all records "
                 "(main framework Section 1.1 graceful-degradation design)."),
            "reference_complete_mask": empty_mask, "hard_reject": False, "hard_reject_reason": ""}

    match_result = reference.match(dataset)
    mag = dataset.magnitude
    stratum_mask = np.isfinite(mag) & (
        mag >= (match_result.mc_ref + match_result.mc_ref_se)
    )
    n_stratum = int(np.sum(stratum_mask))
    # REPRODUCIBILITY METADATA (review point 3.7): attached to every A6
    # SubTestResult that actually reached a live/local reference query
    # (i.e. every branch below this point), so a reader can tell exactly
    # which source was queried, when, with what tolerances, and how many
    # reference events were available -- see MatchResult's docstring in
    # reference_data.py for the full rationale.
    reference_metadata = {
        "source_name": match_result.source_name,
        "query_timestamp_utc": match_result.query_timestamp_utc,
        "query_params": match_result.query_params,
    }
    if n_stratum == 0:
        return {"sub_result": SubTestResult(
            name="A6", score=float("nan"), applicable=False,
            detail=dict(reference_metadata),
            note=f"No records at/above reference-complete stratum "
                 f"(Mc_ref={match_result.mc_ref:.2f} + SE {match_result.mc_ref_se:.2f}). "
                 f"A(D) falls back to intrinsic-only A1-A5 for the whole dataset."),
            "reference_complete_mask": empty_mask, "hard_reject": False, "hard_reject_reason": ""}

    # Per-record (queried, matched) source counts. None (single-source-style
    # reference) degrades to exactly 1 source queried for every stratum
    # record, which by construction can never reach A6_CONTRADICTED_MIN_SOURCES.
    if match_result.n_sources_queried is not None and match_result.n_sources_matched is not None:
        q = match_result.n_sources_queried
        m = match_result.n_sources_matched
    else:
        q = stratum_mask.astype(int)
        m = (stratum_mask & match_result.matched.astype(bool)).astype(int)

    corroborated_mask = stratum_mask & (m >= 1)
    contradicted_eligible_mask = stratum_mask & (m == 0) & (q >= A6_CONTRADICTED_MIN_SOURCES)
    unverifiable_mask = stratum_mask & (m == 0) & (q < A6_CONTRADICTED_MIN_SOURCES)

    n_corroborated = int(np.sum(corroborated_mask))
    n_contradicted_eligible = int(np.sum(contradicted_eligible_mask))
    n_unverifiable = int(np.sum(unverifiable_mask))

    # BUGFIX (Group C3, 2026-07-13, caught on the very first live
    # multi-source corpus run): the dataset-level confirmation test MUST be
    # evaluated over the full population that was meaningfully queried
    # (>=A6_CONTRADICTED_MIN_SOURCES sources) -- n_corroborated +
    # n_contradicted_eligible -- not just the contradicted_eligible subset
    # in isolation. The subset alone is DEFINED to have zero matches
    # (m==0), so testing k=0 against it is tautological: it "confirms"
    # contradiction for ANY dataset with enough non-matching records,
    # regardless of the dataset's true overall match rate. This was caught
    # empirically: "nz" (matched_fraction=0.568, a MAJORITY of records
    # matched) still hard-rejected under the original k=0-only test, which
    # is exactly the false-positive Group C3 exists to prevent.
    n_queried = n_corroborated + n_contradicted_eligible

    contradicted_confirmed = False
    contradicted_p_value: Optional[float] = None
    if n_queried >= A6_CONTRADICTED_MIN_N_STRATUM:
        # Tests H0: "true match rate over the >=A6_CONTRADICTED_MIN_SOURCES
        # -queried population >= THETA_AUTH", using the ACTUAL observed
        # corroboration count k=n_corroborated (not fixed at 0) out of
        # n=n_queried trials. A dataset with a genuinely high match rate
        # cannot be confirmed here, even if some individual records didn't
        # match any source.
        contradicted_p_value = stats.clopper_pearson_lower_tail(
            n_corroborated, n_queried, THETA_AUTH)
        contradicted_confirmed = contradicted_p_value < A6_CONTRADICTED_ALPHA

    hard_reject = contradicted_confirmed
    hard_reject_reason = ""
    if hard_reject:
        hard_reject_reason = (
            f"A6: dataset-level match rate {n_corroborated}/{n_queried} over records "
            f"queried against >={A6_CONTRADICTED_MIN_SOURCES} independent reference "
            f"sources, comfortably above each source's own completeness stratum, "
            f"confirmed (Clopper-Pearson lower-tail p={contradicted_p_value:.2e} < "
            f"alpha={A6_CONTRADICTED_ALPHA}) to sit credibly below theta_auth="
            f"{THETA_AUTH} -- 'Externally contradicted', confirmed-fabrication floor "
            f"triggered."
        )

    # Effective stratum for the A(D) BLEND (Stage-2 composite contribution):
    # only "corroborated" records count, always. "Contradicted" records are
    # folded in too ONLY when the dataset-level test actually confirmed
    # (moot for the final decision either way, since hard_reject already
    # short-circuits Stage 2 entirely in that case -- included here purely
    # so the reported A(D) composite score is an honest reflection of what
    # was found, not for its own hard_reject consequence). "Unverifiable"
    # records are NEVER counted in A6's own score -- they fall back to
    # intrinsic A1-A5 (see score_authenticity()'s intrinsic_mask below).
    effective_mask = corroborated_mask | (contradicted_eligible_mask if contradicted_confirmed else empty_mask)
    n_effective = int(np.sum(effective_mask))

    if n_effective == 0:
        # Every stratum record landed in "unverifiable" (typical single-
        # source-reference outcome when nothing matched) -- A6 contributes
        # nothing this call; everything falls to intrinsic A1-A5.
        return {"sub_result": SubTestResult(
            name="A6", score=float("nan"), applicable=False,
            detail={"n_stratum": n_stratum, "n_corroborated": n_corroborated,
                    "n_contradicted_eligible": n_contradicted_eligible,
                    "n_unverifiable": n_unverifiable, "n_queried": n_queried,
                    "contradicted_confirmed": contradicted_confirmed,
                    "contradicted_p_value": contradicted_p_value,
                    "mc_ref": match_result.mc_ref, "mc_ref_se": match_result.mc_ref_se,
                    "mc_ref_is_default": match_result.mc_ref_is_default,
                    "theta_auth": THETA_AUTH,
                    **reference_metadata},
            note=f"{n_stratum} reference-complete-stratum records, but none reached "
                 f"'Externally corroborated' or a confirmed 'Externally contradicted' "
                 f"verdict ({n_unverifiable} 'Externally unverifiable', "
                 f"{n_contradicted_eligible} contradicted-eligible but not statistically "
                 f"confirmed) -- A(D) falls back to intrinsic-only A1-A5 for these records."),
            "reference_complete_mask": empty_mask,
            "hard_reject": hard_reject, "hard_reject_reason": hard_reject_reason}

    # n_effective = n_corroborated when not contradicted_confirmed (effective_mask
    # is corroborated-only in that case); when contradicted_confirmed,
    # effective_mask also includes the contradicted_eligible records, which
    # are 100% non-match by construction, so this fraction correctly dilutes
    # toward 0 in that case -- reported for honesty, moot for the final
    # decision since hard_reject already short-circuits Stage 2.
    matched_fraction = float(n_corroborated / n_effective)

    return {"sub_result": SubTestResult(
        name="A6", score=matched_fraction, applicable=True,
        detail={"matched_fraction": matched_fraction, "n_stratum": n_stratum,
                "n_effective": n_effective, "n_corroborated": n_corroborated,
                "n_contradicted_eligible": n_contradicted_eligible,
                "n_unverifiable": n_unverifiable, "n_queried": n_queried,
                "contradicted_confirmed": contradicted_confirmed,
                "contradicted_p_value": contradicted_p_value,
                "mc_ref": match_result.mc_ref, "mc_ref_se": match_result.mc_ref_se,
                "mc_ref_is_default": match_result.mc_ref_is_default,
                "theta_auth": THETA_AUTH,
                **reference_metadata},
        note=f"{n_corroborated}/{n_effective} 'Externally corroborated' of the records "
             f"A6 actually forms a verdict on ({n_stratum} reference-complete-stratum "
             f"total; {n_unverifiable} 'Externally unverifiable' excluded and scored via "
             f"intrinsic A1-A5 instead; {n_contradicted_eligible} contradicted-eligible"
             + (", CONFIRMED" if contradicted_confirmed else ", not statistically confirmed")
             + ")."),
        "reference_complete_mask": effective_mask,
        "hard_reject": hard_reject, "hard_reject_reason": hard_reject_reason}


def score_authenticity(
    dataset: CertifyDataset,
    reference: Optional[ExternalCatalogReference] = None,
    reference_dc: Optional[float] = None,
) -> AxisResult:
    """
    Compute A(D), the Authenticity axis, per main framework Section 3.1 and
    the Gap-Remediation Addendum's per-stratum A6 correction.

    Args:
        dataset:      The catalog under audit.
        reference:    ExternalCatalogReference for A6. Defaults to
                      NullExternalCatalog() (A6 infeasible -> intrinsic-only).
        reference_dc: Optional reference correlation dimension for A4.

    Returns:
        AxisResult with per-sub-test detail and the composite A(D) score.
        `hard_reject` is set if A6 fires the theta_auth floor on the
        reference-complete stratum (main framework Section 5).
    """
    reference = reference or NullExternalCatalog()

    a6_out = _score_a6_external(dataset, reference)
    a6_result: SubTestResult = a6_out["sub_result"]
    stratum_mask: np.ndarray = a6_out["reference_complete_mask"]

    intrinsic_mask = ~stratum_mask  # everything not covered by a feasible A6 stratum
    # BUGFIX (scientific-validity review pass): previously fell back to the
    # FULL `dataset` (not an empty subset) whenever intrinsic_mask was
    # entirely False (i.e. every record qualifies for the A6 stratum). That
    # made A1-A5 silently compute and report "applicable" scores over the
    # whole dataset -- including records that were supposed to be excluded
    # because A6 already covers them -- rather than correctly reporting
    # "not applicable" for an empty intrinsic stratum. It did not corrupt
    # the final composite A(D) score (n_intrinsic, computed independently
    # below via intrinsic_mask.sum(), is still 0 and correctly gates the
    # blending logic to use A6 alone), but it made the per-sub-test detail
    # in the returned AxisResult misleading. dataset.subset() already
    # handles an all-False mask correctly (returns an n=0 dataset, which
    # every A1-A5 scorer already treats as "not applicable"), so the
    # special case was unnecessary as well as wrong.
    intrinsic_dataset = dataset.subset(intrinsic_mask)

    a1 = _score_a1_benford(intrinsic_dataset)
    a2 = _score_a2_gutenberg_richter(intrinsic_dataset)
    a3 = _score_a3_omori_utsu(intrinsic_dataset)
    a4 = _score_a4_fractal_dimension(intrinsic_dataset, reference_dc=reference_dc)
    a5 = _score_a5_duplicates(intrinsic_dataset)

    intrinsic_subs = {"A1": a1, "A2": a2, "A3": a3, "A4": a4, "A5": a5}
    applicable_intrinsic = {k: v for k, v in intrinsic_subs.items()
                             if v.applicable and not math.isnan(v.score)}

    if applicable_intrinsic:
        w_sum = sum(WITHIN_A[k] for k in applicable_intrinsic)
        intrinsic_score = sum(WITHIN_A[k] * v.score for k, v in applicable_intrinsic.items()) / w_sum
    else:
        intrinsic_score = float("nan")

    n_stratum = int(np.sum(stratum_mask))
    n_intrinsic = int(np.sum(intrinsic_mask))

    all_subs = dict(intrinsic_subs)
    all_subs["A6"] = a6_result

    notes = []
    # SINGLE SOURCE OF TRUTH (Group C3, 2026-07-12, replaces the former SYNC
    # NOTE pattern): _score_a6_external() is now the ONLY place that decides
    # whether A6's three-state "Externally contradicted" verdict fires --
    # this AxisResult.hard_reject flag and hard_override.check_hard_override()'s
    # actual Stage-1 veto both consume THIS SAME value (decision.py passes
    # a_result.hard_reject/hard_reject_reason straight into
    # check_hard_override() -- see that module's docstring). There is no
    # longer a second, independently-recomputed condition to keep in sync.
    hard_reject = bool(a6_out["hard_reject"])
    hard_reject_reason = str(a6_out["hard_reject_reason"])

    if a6_result.applicable:
        matched_fraction = a6_result.detail.get("matched_fraction", float("nan"))
        # Blend: A6 fully substitutes for its stratum; intrinsic score covers
        # the rest. Weight by record count in each stratum.
        if n_intrinsic > 0 and not math.isnan(intrinsic_score):
            total = n_stratum + n_intrinsic
            composite = (n_stratum * matched_fraction + n_intrinsic * intrinsic_score) / total
            mode = "mixed (A6 + intrinsic per-stratum)"
        else:
            composite = matched_fraction
            mode = "external (A6, full coverage)"
        notes.append(f"A6 applied to {n_stratum} reference-complete records; "
                     f"intrinsic A1-A5 applied to {n_intrinsic} sub-Mc_ref records.")
    else:
        composite = intrinsic_score
        mode = "intrinsic (A1-A5)"
        notes.append(a6_result.note)

    return AxisResult(
        axis="A", score=composite, sub_results=all_subs, mode=mode, notes=notes,
        hard_reject=hard_reject, hard_reject_reason=hard_reject_reason,
    )
