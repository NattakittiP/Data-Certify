# -*- coding: utf-8 -*-
"""
tests/_adversarial_fabrication.py -- self-contained synthetic-fabrication
helpers for tests/test_adversarial.py::TestGraduatedFabricationLadder.

WHY THIS FILE EXISTS (2026-07-21, CI fix): these tests used to do
`from calibration import corrupt as _corrupt` and call
`_corrupt.fabricate_level1` / `_corrupt.fabricate_level10_adversarial`.
`calibration/` is deliberately gitignored -- it is this project's private
corpus-building and calibration tooling, which depends on the private,
unpublished 968-dataset corpus and is intentionally NOT shipped on GitHub
(see .gitignore's own comment on this). The PUBLIC test suite importing a
private, unshipped module meant these 4 tests passed for the maintainer
(whose local checkout has `calibration/`) but failed with
`ModuleNotFoundError` on a clean clone / GitHub Actions checkout -- this
was a real, previously undiagnosed CI failure (external review, 2026-07-21).

This file duplicates ONLY the two pure, deterministic synthetic-data
generator functions these specific tests need
(`fabricate_level1`, `fabricate_level10_adversarial`, and the shared
`fabricate_graduated`/`_omori_like_times` engine they call) -- verbatim
from `calibration/corrupt.py` as of this fix, credited here rather than
silently re-derived. These functions contain no private corpus data or
calibration-derived constants; they are pure procedural generators, so
duplicating them into the public test tree does not leak anything
`calibration/` was created to keep private. `calibration/corrupt.py`
remains the authoritative copy for the maintainer's own corpus-building
use (levels 1-9 feed `build_corpus.py`); if the two ever drift, that
module's copy is the one the private calibration corpus was built against.
"""
from __future__ import annotations

import numpy as np

from data_certify.schema import CertifyDataset


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
    base_time = np.datetime64("2015-01-01T00:00:00", "ns")
    nanoseconds = np.clip(days, 0.0, None) * 86400.0 * 1e9
    origin_time = (base_time + nanoseconds.astype("int64") * np.timedelta64(1, "ns")).astype("datetime64[ns]")
    return np.sort(origin_time)


def fabricate_graduated(level: int, n: int, rng: np.random.RandomState,
                         name: str = "fabricated_graduated") -> CertifyDataset:
    """Shared engine behind fabricate_level1..fabricate_level10 -- a
    10-rung realism ladder where each level ADDS exactly one additional
    realistic statistical property relative to the previous level. Only
    level 1 and level 10 are actually exercised by this test file (levels
    2-9 feed the private calibration corpus via calibration/corrupt.py and
    are not duplicated here)."""
    if not (1 <= level <= 10):
        raise ValueError(f"fabricate_graduated: level must be 1-10, got {level}")

    if level <= 1:
        magnitude = rng.uniform(2.5, 7.5, n)
    else:
        mc, b_value = 3.0, 1.0
        beta = b_value * np.log(10.0)
        magnitude = mc + rng.exponential(1.0 / beta, size=n)

    if level <= 2:
        depth_km = rng.uniform(1.0, 100.0, n)
    else:
        depth_km = np.clip(rng.exponential(15.0, n), 1.0, 60.0)

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

    if level >= 6:
        magnitude_type = np.where(magnitude < 4.0, "ML", np.where(magnitude < 6.0, "mb", "Mw")).astype("<U64")
        fake_network_codes = np.array(["zq", "xw", "qv", "wk", "yt"], dtype="<U64")
        source = fake_network_codes[rng.randint(0, len(fake_network_codes), n)]
        event_uid_source = np.array([f"{name[:8]}{i:08d}" for i in range(n)], dtype="<U64")
        revision_status = np.full(n, "reviewed", dtype="<U64")
        tsunami_flag = np.zeros(n)

    if level in (7, 8, 9):
        station_distance_km = np.abs(rng.normal(50.0, 40.0, n))
        azimuthal_gap_deg = rng.uniform(10.0, 180.0, n)
        if level == 7:
            rupture_length_km = rng.uniform(1.0, 500.0, n)
        else:
            a_wc, b_wc = -3.22, 0.69
            log_l = a_wc + b_wc * magnitude + rng.normal(0, 0.15, n)
            rupture_length_km = 10.0 ** log_l
        rupture_area_km2 = rupture_length_km * (rupture_length_km * 0.5)
        rupture_displacement_m = np.clip(10.0 ** (-4.80 + 0.69 * magnitude), 0.01, 20.0)

    if level >= 9:
        seismic_moment_n_m = 10.0 ** (1.5 * (magnitude + 6.07))

    if level == 10:
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


def fabricate_level10_adversarial(n: int, rng: np.random.RandomState,
                                   name: str = "fabricated_level10_adversarial") -> CertifyDataset:
    """Level 10 -- deliberately NOT wired into calibration/build_corpus.py's
    main calibration-corpus assembly (see calibration/corrupt.py's own
    docstring); scored only here, held out of calibration entirely."""
    return fabricate_graduated(10, n, rng, name)
