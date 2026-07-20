# -*- coding: utf-8 -*-
"""
tests/conftest.py -- Shared test fixtures/helpers for the DATA-CERTIFY test suite.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from data_certify.schema import ALL_FIELDS, CertifyDataset


def make_dataset(n: int = 50, **overrides: Any) -> CertifyDataset:
    """
    Build a CertifyDataset with sensible, fully-valid defaults for every
    field, overridable per-test via keyword arguments (e.g.
    make_dataset(n=10, latitude=np.array([...]))).

    Defaults describe a bland-but-physically-plausible synthetic catalog:
    magnitude 4.0, depth 10km, lat/lon 0, one event per day starting
    2020-01-01, no optional fields populated.
    """
    # BUGFIX (2026-07-21, CI failure on Python 3.12 only): the default
    # origin_time expression below (one day per record starting
    # 2020-01-01) was previously computed UNCONDITIONALLY as part of this
    # dict literal, even when the caller passed their own `origin_time` in
    # `overrides` that would immediately replace it via `defaults.update
    # (overrides)` below -- Python evaluates every value in a dict literal
    # eagerly, regardless of what `.update()` does to it afterwards. For
    # n>=~88,000 that default expression itself overflows datetime64[ns]'s
    # representable range (base_time + n days lands past the ~292-year-
    # from-epoch ceiling, i.e. past ~year 2262) -- so a test that overrides
    # origin_time specifically BECAUSE it needs a large n (e.g.
    # test_hard_override.py's n=100,000 large-dataset test) still crashed
    # on this unused default before its own override ever took effect. A
    # newer numpy raises OverflowError here instead of the older silent
    # wraparound-to-a-garbage-date behaviour (confirmed via direct
    # reproduction), which is how this was first caught. Fixed by only
    # computing the default when the caller hasn't already supplied their
    # own origin_time.
    if "origin_time" in overrides:
        origin_time_default = None
    else:
        base_time = np.datetime64("2020-01-01T00:00:00", "ns")
        day = np.timedelta64(1, "D")
        origin_time_default = (base_time + np.arange(n) * day).astype("datetime64[ns]")

    defaults = {
        "name": "test_dataset",
        "origin_time": origin_time_default,
        "latitude": np.linspace(-10, 10, n),
        "longitude": np.linspace(-10, 10, n),
        "depth_km": np.full(n, 10.0),
        "magnitude": np.full(n, 4.0),
        "magnitude_type": np.array([""] * n, dtype="<U64"),
        "seismic_moment_n_m": np.full(n, np.nan),
        "tsunami_flag": np.full(n, np.nan),
        "mechanism": np.array([""] * n, dtype="<U64"),
        "source": np.array([""] * n, dtype="<U64"),
        "event_uid_source": np.array([""] * n, dtype="<U64"),
        "revision_status": np.array([""] * n, dtype="<U64"),
        "mmi": np.full(n, np.nan),
        "station_distance_km": np.full(n, np.nan),
        "rupture_length_km": np.full(n, np.nan),
        "rupture_area_km2": np.full(n, np.nan),
        "rupture_displacement_m": np.full(n, np.nan),
        "azimuthal_gap_deg": np.full(n, np.nan),
    }
    defaults.update(overrides)
    return CertifyDataset(n=n, **defaults)


def make_gr_dataset(n: int = 500, b_value: float = 1.0, seed: int = 0,
                     mc: float = 3.0, **overrides: Any) -> CertifyDataset:
    """Build a dataset with magnitudes drawn from a genuine Gutenberg-Richter
    (exponential) distribution above `mc`, for exercising A2/C2/C4/I2."""
    rng = np.random.RandomState(seed)
    beta = b_value * np.log(10.0)
    mags = mc + rng.exponential(1.0 / beta, size=n)
    return make_dataset(n=n, magnitude=mags, **overrides)


@pytest.fixture
def dataset_factory():
    return make_dataset


@pytest.fixture
def gr_dataset_factory():
    return make_gr_dataset
