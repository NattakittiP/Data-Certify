# -*- coding: utf-8 -*-
"""
calibration/corrupt.py -- Synthetic corruption generator for building
labeled "known-bad" variants of real earthquake catalogs, for the
calibration corpus (Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md
Sections 4-5's "known-trustworthy and known-problematic" corpus requirement).

Design: each degradation function takes a real CertifyDataset and a
severity in (0, 1] and a seeded RandomState, and returns
(corrupted_dataset, description_string) -- the description is stored in
the corpus manifest so every "known-bad" label is traceable to exactly
what was done and how aggressively, never an unexplained black-box label.

None of these corruptions are novel inventions for this module alone --
coordinate/magnitude/duplicate/missingness/depth/timestamp corruption
each directly mirror one of the failure-mode categories this project's
own Docs/00_Overview/DATA-CERTIFY_Theoretical_Framework.md catalogs (Category I
instrumentation drift, Category II fabrication, Category III
human/pipeline data-entry error). The "sophisticated adversarial
fabrication" generator directly reuses the construction from
tests/test_adversarial.py's make_gamed_fabricated_catalog (same
Gutenberg-Richter + fault-line-clustering idea), parametrized here by
seed instead of hard-coded, credited explicitly rather than silently
re-derived.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from data_certify.schema import ALL_FIELDS, CertifyDataset

SEVERITY_LOW: float = 0.20
SEVERITY_MED: float = 0.45
SEVERITY_HIGH: float = 0.80


def _copy(ds: CertifyDataset) -> CertifyDataset:
    return CertifyDataset(name=ds.name, n=ds.n,
                           **{f: getattr(ds, f).copy() for f in ALL_FIELDS})


def coordinate_jitter(ds: CertifyDataset, severity: float,
                       rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Perturb a severity-scaled fraction of records' lat/lon with
    gaussian noise of severity-scaled magnitude (up to ~9 degrees,
    ~1000km, at severity=1). Degrades spatial-clustering / tectonic-
    plausibility signals (A4 fractal dimension, P8 plate-boundary
    proximity) without touching any other field."""
    out = _copy(ds)
    frac = min(1.0, 0.3 + 0.7 * severity)
    n_affected = max(1, int(round(frac * ds.n)))
    idx = rng.choice(ds.n, size=n_affected, replace=False)
    std_deg = 0.5 + 8.0 * severity
    out.latitude[idx] = np.clip(out.latitude[idx] + rng.normal(0, std_deg, n_affected), -90.0, 90.0)
    out.longitude[idx] = ((out.longitude[idx] + rng.normal(0, std_deg, n_affected) + 180.0) % 360.0) - 180.0
    return out, f"coordinate_jitter(severity={severity:.2f}, n_affected={n_affected}, std_deg={std_deg:.2f})"


def magnitude_gr_violation(ds: CertifyDataset, severity: float,
                            rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Replace a severity-scaled fraction of magnitudes with values drawn
    UNIFORMLY over the observed [min,max] range instead of the genuine
    Gutenberg-Richter exponential tail -- degrades A2 (b-value
    conformity) and C2 (Mc adequacy)."""
    out = _copy(ds)
    finite = np.isfinite(out.magnitude)
    if not np.any(finite):
        return out, "magnitude_gr_violation(skipped: no finite magnitudes)"
    lo, hi = float(np.nanmin(out.magnitude)), float(np.nanmax(out.magnitude))
    if hi <= lo:
        hi = lo + 1.0
    frac = min(1.0, 0.3 + 0.7 * severity)
    n_affected = max(1, int(round(frac * ds.n)))
    idx = rng.choice(ds.n, size=n_affected, replace=False)
    out.magnitude[idx] = rng.uniform(lo, hi, n_affected)
    return out, f"magnitude_gr_violation(severity={severity:.2f}, n_affected={n_affected})"


def inject_duplicates(ds: CertifyDataset, severity: float,
                       rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Append a severity-scaled fraction of EXACT duplicate records (as a
    real batch-reimport bug would produce), inflating n and degrading A5
    / P7 duplicate-detection scores."""
    frac = min(1.0, 0.15 + 0.6 * severity)
    n_dup = max(1, int(round(frac * ds.n)))
    idx = rng.choice(ds.n, size=n_dup, replace=True)
    fields = {}
    for f in ALL_FIELDS:
        arr = getattr(ds, f)
        fields[f] = np.concatenate([arr, arr[idx]])
    out = CertifyDataset(name=ds.name, n=ds.n + n_dup, **fields)
    return out, f"inject_duplicates(severity={severity:.2f}, n_dup={n_dup})"


def inject_missingness(ds: CertifyDataset, severity: float,
                        rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Blank out (-> NaN/NaT) a severity-scaled fraction of cells in the
    REQUIRED fields, degrading C1 (field-level missingness). origin_time
    is blanked at half the rate of the numeric fields since NaT there
    also silently degrades every axis that depends on chronology (P7,
    I1), which would conflate C1 with several other criteria at high
    severity."""
    out = _copy(ds)
    frac = min(0.9, 0.1 + 0.7 * severity)
    for f in ("latitude", "longitude", "depth_km", "magnitude"):
        n_affected = max(0, int(round(frac * ds.n)))
        if n_affected == 0:
            continue
        idx = rng.choice(ds.n, size=n_affected, replace=False)
        getattr(out, f)[idx] = np.nan
    n_time_affected = max(0, int(round(frac * 0.5 * ds.n)))
    if n_time_affected:
        idx = rng.choice(ds.n, size=n_time_affected, replace=False)
        out.origin_time[idx] = np.datetime64("NaT")
    return out, f"inject_missingness(severity={severity:.2f}, frac={frac:.2f})"


def depth_implausible(ds: CertifyDataset, severity: float,
                       rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Overwrite a severity-scaled fraction of depths with physically
    impossible values (negative, or far beyond DEPTH_MAX_KM=750km),
    simulating a unit/sign data-entry error -- directly the field P1-P3
    hard-gate on depth checks."""
    out = _copy(ds)
    frac = min(0.5, 0.05 + 0.35 * severity)
    n_affected = max(1, int(round(frac * ds.n)))
    idx = rng.choice(ds.n, size=n_affected, replace=False)
    bad_vals = rng.choice([-1.0, -50.0, 900.0, 5000.0], size=n_affected)
    out.depth_km[idx] = bad_vals + rng.normal(0, 5.0, n_affected)
    return out, f"depth_implausible(severity={severity:.2f}, n_affected={n_affected})"


def timestamp_collision(ds: CertifyDataset, severity: float,
                         rng: np.random.RandomState) -> Tuple[CertifyDataset, str]:
    """Overwrite a severity-scaled fraction of origin_time values with a
    single shared timestamp, simulating a batch-import bug where a
    default/system-clock value leaks into the time field -- degrades P7
    (chronological consistency) / I4 (cross-catalog dedup)."""
    out = _copy(ds)
    valid = ~np.isnat(out.origin_time)
    if not np.any(valid):
        return out, "timestamp_collision(skipped: no valid origin_time)"
    frac = min(1.0, 0.2 + 0.6 * severity)
    n_affected = max(1, int(round(frac * ds.n)))
    idx = rng.choice(ds.n, size=n_affected, replace=False)
    shared_t = out.origin_time[valid][0]
    out.origin_time[idx] = shared_t
    return out, f"timestamp_collision(severity={severity:.2f}, n_affected={n_affected})"


CORRUPTIONS = {
    "coordinate_jitter": coordinate_jitter,
    "magnitude_gr_violation": magnitude_gr_violation,
    "inject_duplicates": inject_duplicates,
    "inject_missingness": inject_missingness,
    "depth_implausible": depth_implausible,
    "timestamp_collision": timestamp_collision,
}


def _make_synthetic(n: int, magnitude: np.ndarray, latitude: np.ndarray,
                     longitude: np.ndarray, depth_km: np.ndarray,
                     origin_time: np.ndarray, name: str) -> CertifyDataset:
    empty_str = np.array([""] * n, dtype="<U64")
    nan_arr = np.full(n, np.nan)
    return CertifyDataset(
        name=name, n=n, origin_time=origin_time, latitude=latitude, longitude=longitude,
        depth_km=depth_km, magnitude=magnitude, magnitude_type=empty_str.copy(),
        seismic_moment_n_m=nan_arr.copy(), tsunami_flag=nan_arr.copy(), mechanism=empty_str.copy(),
        source=empty_str.copy(), event_uid_source=empty_str.copy(), revision_status=empty_str.copy(),
        mmi=nan_arr.copy(), station_distance_km=nan_arr.copy(), rupture_length_km=nan_arr.copy(),
        rupture_area_km2=nan_arr.copy(), rupture_displacement_m=nan_arr.copy(), azimuthal_gap_deg=nan_arr.copy(),
    )


def fabricate_naive(n: int, rng: np.random.RandomState, name: str = "fabricated_naive") -> CertifyDataset:
    """A crude, unsophisticated total fabrication: magnitudes drawn
    uniformly (violates GR-law) and lat/lon scattered uniformly over a
    plausible box (violates fault-clustering) -- the kind of naive
    fabrication A2/A4's intrinsic checks alone should already catch,
    included as the "easy" end of the known-bad spectrum."""
    magnitude = rng.uniform(2.5, 7.5, n)
    latitude = rng.uniform(-60.0, 60.0, n)
    longitude = rng.uniform(-180.0, 180.0, n)
    depth_km = rng.uniform(1.0, 100.0, n)
    base_time = np.datetime64("2015-01-01T00:00:00", "ns")
    offsets = rng.permutation(n)
    origin_time = (base_time + offsets * np.timedelta64(1, "h")).astype("datetime64[ns]")
    return _make_synthetic(n, magnitude, latitude, longitude, depth_km, origin_time, name)


LEVEL_DESCRIPTIONS = {
    1: "uniform magnitude + uniform 2D scatter + uniform depth + evenly-spaced timestamps "
       "(identical construction to fabricate_naive -- the 'obviously fake' floor of the ladder)",
    2: "+ genuine Gutenberg-Richter magnitude distribution (b~1.0) replacing uniform magnitude",
    3: "+ physically plausible shallow-biased depth distribution replacing uniform depth",
    4: "+ fault-line-clustered spatial pattern replacing uniform 2D scatter",
    5: "+ Omori-Utsu-like temporal clustering around synthetic mainshocks replacing uniform inter-event spacing",
    6: "+ realistic magnitude_type/source/revision_status metadata fields populated (previously blank)",
    7: "+ P5/P9-relevant fields populated (rupture_length_km/rupture_area_km2/rupture_displacement_m, "
       "station_distance_km, azimuthal_gap_deg) but Wells-Coppersmith-INCONSISTENT -- tests whether P5 "
       "fires and correctly flags the inconsistency once the field actually exists",
    8: "+ same specialized fields as level 7, but now Wells-Coppersmith-CONSISTENT rupture geometry -- "
       "tests whether a well-tuned fake passes P5 once given a populated, physically-plausible field",
    9: "+ physically-derived seismic_moment_n_m (via the real Mw=(2/3)log10(M0)-6.07 relation, so its "
       "leading-digit distribution is naturally Benford-compliant rather than absent/uniform)",
    10: "ADVERSARIAL / HELD OUT -- everything above combined and deliberately tuned to game every "
        "remaining intrinsic check simultaneously (extends fabricate_sophisticated with the levels "
        "6-9 metadata realism). NOT part of the calibration corpus: used only as a held-out probe in "
        "tests/test_adversarial.py, to avoid calibrating weights/thresholds against the exact "
        "adversarial construction being evaluated (circular calibration).",
}


def _omori_like_times(n: int, rng: np.random.RandomState, n_mainshocks: int = 3,
                       days_span: float = 365.0) -> np.ndarray:
    """Cluster n events unevenly in time around a handful of synthetic
    'mainshocks' with an Omori-Utsu-like (Omori 1894; Utsu, Ogata &
    Matsu'ura 1995) decay in inter-event density, instead of the evenly-
    spaced timestamps a naive fabrication (level <= 4) leaves behind.
    Not fit to any real sequence -- a generic decay shape used only so
    the fabricated catalog's temporal clustering signature stops being a
    trivial giveaway."""
    mainshock_days = np.sort(rng.uniform(0.0, days_span, n_mainshocks))
    weights = rng.dirichlet(np.ones(n_mainshocks))
    counts = np.maximum(1, np.round(weights * n).astype(int))
    counts[-1] += n - int(counts.sum())
    c, p = 0.3, 1.05
    days_chunks = []
    for ms_day, cnt in zip(mainshock_days, counts):
        cnt = int(cnt)
        if cnt <= 0:
            continue
        u = rng.uniform(0.0, 1.0, cnt)
        t_since = c * ((1.0 - u) ** (1.0 / (1.0 - p)) - 1.0)
        days_chunks.append(ms_day + np.clip(t_since, 0.0, days_span))
    days = np.concatenate(days_chunks) if days_chunks else rng.uniform(0.0, days_span, n)
    if days.shape[0] < n:
        days = np.concatenate([days, rng.uniform(0.0, days_span, n - days.shape[0])])
    elif days.shape[0] > n:
        days = days[:n]
    # NOTE (bug found 2026-07-11 during run_scoring.py on the 9th-pass
    # corpus): truncating to whole-SECOND resolution here let many
    # near-simultaneous aftershocks (a real, intended feature of Omori
    # decay -- lots of events cluster within seconds/minutes of a
    # mainshock) collapse onto the IDENTICAL integer-second timestamp.
    # When A3's clustering then grouped several of those tied-timestamp
    # events into one cluster, `fit_omori_utsu`'s log-spaced bin edges
    # (`np.geomspace(t[0], t_max, ...)`) degenerated to a constant array
    # (t[0] == t_max), which numpy's histogram correctly rejects as
    # non-monotonic. Fixed by keeping nanosecond resolution throughout
    # instead of truncating to whole seconds -- collisions at that
    # resolution are astronomically unlikely for n<=~10000.
    base_time = np.datetime64("2015-01-01T00:00:00", "ns")
    nanoseconds = np.clip(days, 0.0, None) * 86400.0 * 1e9
    origin_time = (base_time + nanoseconds.astype("int64") * np.timedelta64(1, "ns")).astype("datetime64[ns]")
    return np.sort(origin_time)


def fabricate_graduated(level: int, n: int, rng: np.random.RandomState,
                         name: str = "fabricated_graduated") -> CertifyDataset:
    """Shared engine behind fabricate_level1..fabricate_level10 -- a
    10-rung realism ladder where each level ADDS exactly one additional
    realistic statistical property relative to the previous level (see
    LEVEL_DESCRIPTIONS above for the full per-level rationale), rather
    than being 10 arbitrary noise settings. This lets the calibration
    corpus (and the paper) report a monotonic-ish 'how many realistic
    properties does a fabricated catalog need before detection starts to
    break down' curve, instead of only two flat naive/sophisticated
    points. Levels 1-9 are intended for the calibration corpus; level 10
    is deliberately withheld from calibration (see LEVEL_DESCRIPTIONS[10])."""
    if not (1 <= level <= 10):
        raise ValueError(f"fabricate_graduated: level must be 1-10, got {level}")

    # ---- magnitude: uniform (L1) vs genuine Gutenberg-Richter (L2+) ----
    if level <= 1:
        magnitude = rng.uniform(2.5, 7.5, n)
    else:
        mc, b_value = 3.0, 1.0
        beta = b_value * np.log(10.0)
        magnitude = mc + rng.exponential(1.0 / beta, size=n)

    # ---- depth: uniform (L1-2) vs shallow-biased exponential (L3+) ----
    if level <= 2:
        depth_km = rng.uniform(1.0, 100.0, n)
    else:
        depth_km = np.clip(rng.exponential(15.0, n), 1.0, 60.0)

    # ---- spatial: uniform scatter (L1-3) vs fault-line clustering (L4+) ----
    if level <= 3:
        latitude = rng.uniform(-60.0, 60.0, n)
        longitude = rng.uniform(-180.0, 180.0, n)
    else:
        seg_id = rng.randint(0, 5, n)
        angles = seg_id * 0.7
        along = rng.uniform(0, 40, n)
        jitter = rng.normal(0, 1.0, n)
        latitude = -20.0 + along * np.cos(angles) + jitter * np.sin(angles)
        longitude = -70.0 + along * np.sin(angles) - jitter * np.cos(angles)

    # ---- temporal: evenly-spaced (L1-4) vs Omori-like clustering (L5+) ----
    if level <= 4:
        base_time = np.datetime64("2015-01-01T00:00:00", "ns")
        offsets = rng.permutation(n)
        origin_time = (base_time + offsets * np.timedelta64(1, "h")).astype("datetime64[ns]")
    else:
        origin_time = _omori_like_times(n, rng)

    empty_str = np.array([""] * n, dtype="<U64")
    nan_arr = np.full(n, np.nan)
    magnitude_type = empty_str.copy()
    source = empty_str.copy()
    event_uid_source = empty_str.copy()
    revision_status = empty_str.copy()
    mechanism = empty_str.copy()
    seismic_moment_n_m = nan_arr.copy()
    tsunami_flag = nan_arr.copy()
    mmi = nan_arr.copy()
    station_distance_km = nan_arr.copy()
    rupture_length_km = nan_arr.copy()
    rupture_area_km2 = nan_arr.copy()
    rupture_displacement_m = nan_arr.copy()
    azimuthal_gap_deg = nan_arr.copy()

    # ---- metadata schema realism: blank (L1-5) vs populated (L6+) ----
    if level >= 6:
        magnitude_type = np.where(magnitude < 4.0, "ML", np.where(magnitude < 6.0, "mb", "Mw")).astype("<U64")
        fake_network_codes = np.array(["zq", "xw", "qv", "wk", "yt"], dtype="<U64")
        source = fake_network_codes[rng.randint(0, len(fake_network_codes), n)]
        event_uid_source = np.array([f"{name[:8]}{i:08d}" for i in range(n)], dtype="<U64")
        revision_status = np.full(n, "reviewed", dtype="<U64")
        tsunami_flag = np.zeros(n)

    # ---- P5/P9-relevant fields: absent (L1-6) vs populated (L7-9), inconsistent (L7) vs
    # Wells-Coppersmith-consistent (L8-9) -- deliberately populated on only a subset of
    # levels (not all 9), per the disclosed trade-off that doing this changes the nature
    # of the P5/P9/I4 field-scarcity finding from "no real data available" to "synthetic
    # data supplied to test whether EWM's n_obs/CV actually respond." ----
    if level in (7, 8, 9):
        station_distance_km = np.abs(rng.normal(50.0, 40.0, n))
        azimuthal_gap_deg = rng.uniform(10.0, 180.0, n)
        if level == 7:
            # Deliberately inconsistent with Wells-Coppersmith: rupture length
            # drawn independent of magnitude, so P5 should flag it.
            rupture_length_km = rng.uniform(1.0, 500.0, n)
        else:
            # Wells & Coppersmith (1994) Table 2A "all" coefficients, plus
            # modest noise -- should read as WC-consistent to P5.
            a_wc, b_wc = -3.22, 0.69
            log_l = a_wc + b_wc * magnitude + rng.normal(0, 0.15, n)
            rupture_length_km = 10.0 ** log_l
        rupture_area_km2 = rupture_length_km * (rupture_length_km * 0.5)
        rupture_displacement_m = np.clip(10.0 ** (-4.80 + 0.69 * magnitude), 0.01, 20.0)

    # ---- Benford-compliant derived quantity: absent (L1-8) vs physically-derived (L9+) ----
    if level >= 9:
        seismic_moment_n_m = 10.0 ** (1.5 * (magnitude + 6.07))

    if level == 10:
        # Adversarial / held-out tier: layer on the same fault-clustering +
        # GR-law construction as fabricate_sophisticated (credited there),
        # combined with every metadata/field realism property above.
        seg_id = rng.randint(0, 5, n)
        angles = seg_id * 0.7
        along = rng.uniform(0, 40, n)
        jitter = rng.normal(0, 1.0, n)
        latitude = -20.0 + along * np.cos(angles) + jitter * np.sin(angles)
        longitude = -70.0 + along * np.sin(angles) - jitter * np.cos(angles)
        depth_km = np.clip(rng.exponential(15.0, n), 1.0, 60.0)

    return CertifyDataset(
        name=name, n=n, origin_time=origin_time, latitude=latitude, longitude=longitude,
        depth_km=depth_km, magnitude=magnitude, magnitude_type=magnitude_type,
        seismic_moment_n_m=seismic_moment_n_m, tsunami_flag=tsunami_flag, mechanism=mechanism,
        source=source, event_uid_source=event_uid_source, revision_status=revision_status,
        mmi=mmi, station_distance_km=station_distance_km, rupture_length_km=rupture_length_km,
        rupture_area_km2=rupture_area_km2, rupture_displacement_m=rupture_displacement_m,
        azimuthal_gap_deg=azimuthal_gap_deg,
    )


def fabricate_level1(n: int, rng: np.random.RandomState, name: str = "fabricated_level1") -> CertifyDataset:
    return fabricate_graduated(1, n, rng, name)


def fabricate_level2(n: int, rng: np.random.RandomState, name: str = "fabricated_level2") -> CertifyDataset:
    return fabricate_graduated(2, n, rng, name)


def fabricate_level3(n: int, rng: np.random.RandomState, name: str = "fabricated_level3") -> CertifyDataset:
    return fabricate_graduated(3, n, rng, name)


def fabricate_level4(n: int, rng: np.random.RandomState, name: str = "fabricated_level4") -> CertifyDataset:
    return fabricate_graduated(4, n, rng, name)


def fabricate_level5(n: int, rng: np.random.RandomState, name: str = "fabricated_level5") -> CertifyDataset:
    return fabricate_graduated(5, n, rng, name)


def fabricate_level6(n: int, rng: np.random.RandomState, name: str = "fabricated_level6") -> CertifyDataset:
    return fabricate_graduated(6, n, rng, name)


def fabricate_level7(n: int, rng: np.random.RandomState, name: str = "fabricated_level7") -> CertifyDataset:
    return fabricate_graduated(7, n, rng, name)


def fabricate_level8(n: int, rng: np.random.RandomState, name: str = "fabricated_level8") -> CertifyDataset:
    return fabricate_graduated(8, n, rng, name)


def fabricate_level9(n: int, rng: np.random.RandomState, name: str = "fabricated_level9") -> CertifyDataset:
    return fabricate_graduated(9, n, rng, name)


def fabricate_level10_adversarial(n: int, rng: np.random.RandomState,
                                   name: str = "fabricated_level10_adversarial") -> CertifyDataset:
    """Level 10 -- deliberately NOT wired into build_corpus.py's main
    calibration-corpus assembly. Import and call this directly from a
    separate adversarial-test-corpus script (see
    tests/test_adversarial.py) instead."""
    return fabricate_graduated(10, n, rng, name)


def fabricate_sophisticated(n: int, rng: np.random.RandomState, name: str = "fabricated_sophisticated") -> CertifyDataset:
    """A synthetic catalog engineered to defeat every INTRINSIC check
    (genuine GR b~1.0, fault-clustered coordinates, distinct timestamps,
    plausible shallow-crustal depths) -- structurally identical to
    tests/test_adversarial.py's make_gamed_fabricated_catalog (credited,
    not re-derived independently), reused here as the calibration
    corpus's hardest "known-bad" case: one that only A6 external
    cross-validation can catch, exactly the residual gap that test file
    documents and demonstrates."""
    mc, b_value = 3.0, 1.0
    beta = b_value * np.log(10.0)
    magnitude = mc + rng.exponential(1.0 / beta, size=n)
    seg_id = rng.randint(0, 5, n)
    angles = seg_id * 0.7
    along = rng.uniform(0, 40, n)
    jitter = rng.normal(0, 1.0, n)
    latitude = -20.0 + along * np.cos(angles) + jitter * np.sin(angles)
    longitude = -70.0 + along * np.sin(angles) - jitter * np.cos(angles)
    depth_km = np.clip(rng.exponential(15.0, n), 1.0, 60.0)
    base_time = np.datetime64("2021-01-01T00:00:00", "ns")
    hour_offsets = rng.permutation(n)
    origin_time = (base_time + hour_offsets * np.timedelta64(1, "h")).astype("datetime64[ns]")
    return _make_synthetic(n, magnitude, latitude, longitude, depth_km, origin_time, name)
