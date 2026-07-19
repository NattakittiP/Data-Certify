# -*- coding: utf-8 -*-
"""
data_certify/schema.py -- Canonical earthquake-catalog record schema and
dataset I/O for the DATA-CERTIFY audit pipeline.

DATA-CERTIFY's core package has no hard dependency on pandas: the core
package is numpy-only, and pandas is an optional dependency confined to
`prepare_dataset.py`, where raw, messy real-world CSVs of unpredictable
shape are normalised into this canonical schema. Once a
dataset has been normalised into the canonical CSV format below, the core
package loads it with nothing but the standard-library `csv` module and numpy.

Canonical CSV columns (required, always present):
    origin_time     ISO-8601 UTC timestamp string, e.g. "2020-05-30T23:45:48.085Z"
    latitude        degrees, [-90, 90]
    longitude       degrees, [-180, 180]
    depth_km        kilometres
    magnitude       dimensionless (scale given by magnitude_type)

Canonical CSV columns (optional -- blank if unknown; NEVER silently
fabricated by the loader):
    magnitude_type      "Mw" | "ML" | "Ms" | "mb" | "" (unknown)
    seismic_moment_n_m  seismic moment M0 in N.m (SI units)
    tsunami_flag        "1" | "0" | ""
    mechanism           "strike-slip" | "reverse" | "normal" | "" (unknown)
    source              reporting agency / catalog name
    event_uid_source    agency-specific event ID (for I4 cross-catalog dedup)
    revision_status     "preliminary" | "final" | ""
    mmi                 Modified Mercalli Intensity at a station (for P9)
    station_distance_km epicentral distance of the mmi reading (for P9)
    rupture_length_km   surface/subsurface rupture length (for P5)
    rupture_area_km2    rupture area (for P5)
    rupture_displacement_m  average slip displacement (for P5)
    azimuthal_gap_deg   largest azimuthal gap in station coverage (metadata pass-through, I-axis)
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

REQUIRED_FIELDS: List[str] = ["origin_time", "latitude", "longitude", "depth_km", "magnitude"]

OPTIONAL_NUMERIC_FIELDS: List[str] = [
    "seismic_moment_n_m", "tsunami_flag", "mmi", "station_distance_km",
    "rupture_length_km", "rupture_area_km2", "rupture_displacement_m",
    "azimuthal_gap_deg",
]
OPTIONAL_STRING_FIELDS: List[str] = [
    "magnitude_type", "mechanism", "source", "event_uid_source", "revision_status",
]

ALL_FIELDS: List[str] = REQUIRED_FIELDS + OPTIONAL_NUMERIC_FIELDS + OPTIONAL_STRING_FIELDS


@dataclass
class CertifyDataset:
    """
    A normalised earthquake catalog, held as parallel numpy arrays (one
    entry per event), in the canonical schema documented in this module's
    docstring.

    All arrays share the same length `n`. Numeric optional fields use NaN
    for "unknown"; string optional fields use "" for "unknown" -- the
    loader never guesses or imputes a value that was not present in the
    source file.
    """
    name: str
    n: int

    origin_time: np.ndarray            # datetime64[ns], NaT if unparseable
    latitude: np.ndarray                # float64
    longitude: np.ndarray               # float64
    depth_km: np.ndarray                 # float64
    magnitude: np.ndarray                # float64

    magnitude_type: np.ndarray           # <U16, "" if unknown
    seismic_moment_n_m: np.ndarray       # float64, NaN if unknown
    tsunami_flag: np.ndarray             # float64 (0/1), NaN if unknown
    mechanism: np.ndarray                # <U32, "" if unknown
    source: np.ndarray                   # <U64, "" if unknown
    event_uid_source: np.ndarray         # <U64, "" if unknown
    revision_status: np.ndarray          # <U16, "" if unknown
    mmi: np.ndarray                      # float64, NaN if unknown
    station_distance_km: np.ndarray      # float64, NaN if unknown
    rupture_length_km: np.ndarray        # float64, NaN if unknown
    rupture_area_km2: np.ndarray         # float64, NaN if unknown
    rupture_displacement_m: np.ndarray   # float64, NaN if unknown
    azimuthal_gap_deg: np.ndarray        # float64, NaN if unknown

    # -- convenience -----------------------------------------------------

    def required_missingness(self) -> Dict[str, float]:
        """Field-level missingness rate for each REQUIRED field (test C1)."""
        out = {}
        for f in REQUIRED_FIELDS:
            arr = getattr(self, f)
            if f == "origin_time":
                n_missing = int(np.sum(np.isnat(arr)))
            else:
                n_missing = int(np.sum(~np.isfinite(arr.astype(float))))
            out[f] = n_missing / self.n if self.n > 0 else float("nan")
        return out

    def origin_time_days(self) -> np.ndarray:
        """Origin times converted to float days since the earliest valid event."""
        valid = ~np.isnat(self.origin_time)
        if not np.any(valid):
            return np.full(self.n, np.nan)
        t0 = self.origin_time[valid].min()
        days = (self.origin_time - t0) / np.timedelta64(1, "D")
        return days.astype(float)

    def sort_by_time(self) -> "CertifyDataset":
        """Return a copy sorted by origin_time (NaT sorts last)."""
        days = self.origin_time_days()
        # NaN (from NaT) sorts last with argsort's default NaN-last behaviour.
        order = np.argsort(days)
        return CertifyDataset(**{
            "name": self.name, "n": self.n,
            **{f: getattr(self, f)[order] for f in ALL_FIELDS}
        })

    def subset(self, mask: np.ndarray) -> "CertifyDataset":
        """Return a copy containing only records where mask is True."""
        mask = np.asarray(mask, dtype=bool)
        return CertifyDataset(
            name=self.name, n=int(mask.sum()),
            **{f: getattr(self, f)[mask] for f in ALL_FIELDS},
        )

    def resample(self, idx: np.ndarray) -> "CertifyDataset":
        """
        Return a copy containing exactly the records at `idx`, which MAY
        repeat or omit indices -- unlike `subset` (a boolean mask, so each
        record is selected 0 or 1 times), this supports arbitrary fancy
        indexing (this method itself is agnostic to how `idx` was drawn).

        Used by `DataCertifyAuditor.estimate_uncertainty` in decision.py
        for its subsampling-WITHOUT-replacement bootstrap (`idx` there is
        drawn via `np.random.RandomState.choice(..., replace=False)`) --
        NOT a with-replacement bootstrap. See that method's own docstring
        for why with-replacement resampling was deliberately rejected for
        this pipeline (it manufactures exact-duplicate records that this
        framework's own A5/P7 duplicate-detection tests then correctly,
        but spuriously, flag as fabrication evidence).
        """
        idx = np.asarray(idx, dtype=int)
        return CertifyDataset(
            name=self.name, n=len(idx),
            **{f: getattr(self, f)[idx] for f in ALL_FIELDS},
        )


def _parse_float(raw: str) -> float:
    raw = (raw or "").strip()
    if raw == "":
        return float("nan")
    try:
        return float(raw)
    except ValueError:
        return float("nan")


def _parse_datetime64(raw: str) -> np.datetime64:
    raw = (raw or "").strip()
    if raw == "":
        return np.datetime64("NaT")
    try:
        return np.datetime64(raw)
    except ValueError:
        return np.datetime64("NaT")


def load_dataset_csv(path: "str | Path", name: Optional[str] = None) -> CertifyDataset:
    """
    Load a canonical-schema CSV (as produced by prepare_dataset.py) into a
    CertifyDataset.

    Raises:
        FileNotFoundError: if path does not exist.
        ValueError: if any REQUIRED_FIELDS column is missing from the header.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset CSV not found: {path}")

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        missing_required = [c for c in REQUIRED_FIELDS if c not in header]
        if missing_required:
            raise ValueError(
                f"load_dataset_csv: '{path}' is missing required column(s) "
                f"{missing_required}. Found columns: {header}. "
                f"Re-run prepare_dataset.py to (re)generate a canonical CSV."
            )
        rows = list(reader)

    n = len(rows)
    if n == 0:
        raise ValueError(f"load_dataset_csv: '{path}' contains zero data rows.")

    def col_float(name_: str) -> np.ndarray:
        return np.array([_parse_float(r.get(name_, "")) for r in rows], dtype=float)

    def col_str(name_: str) -> np.ndarray:
        return np.array([(r.get(name_, "") or "").strip() for r in rows], dtype="<U64")

    origin_time = np.array([_parse_datetime64(r.get("origin_time", "")) for r in rows],
                            dtype="datetime64[ns]")

    return CertifyDataset(
        name=name or path.stem,
        n=n,
        origin_time=origin_time,
        latitude=col_float("latitude"),
        longitude=col_float("longitude"),
        depth_km=col_float("depth_km"),
        magnitude=col_float("magnitude"),
        magnitude_type=col_str("magnitude_type"),
        seismic_moment_n_m=col_float("seismic_moment_n_m"),
        tsunami_flag=col_float("tsunami_flag"),
        mechanism=col_str("mechanism"),
        source=col_str("source"),
        event_uid_source=col_str("event_uid_source"),
        revision_status=col_str("revision_status"),
        mmi=col_float("mmi"),
        station_distance_km=col_float("station_distance_km"),
        rupture_length_km=col_float("rupture_length_km"),
        rupture_area_km2=col_float("rupture_area_km2"),
        rupture_displacement_m=col_float("rupture_displacement_m"),
        azimuthal_gap_deg=col_float("azimuthal_gap_deg"),
    )


def save_dataset_csv(dataset: CertifyDataset, path: "str | Path") -> None:
    """Write a CertifyDataset to a canonical-schema CSV file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    def fmt(v) -> str:
        if isinstance(v, (float, np.floating)):
            return "" if not math.isfinite(v) else repr(float(v))
        if isinstance(v, np.datetime64):
            if np.isnat(v):
                return ""
            return str(v)
        return str(v) if v is not None else ""

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(ALL_FIELDS)
        for i in range(dataset.n):
            row = [fmt(getattr(dataset, f)[i]) for f in ALL_FIELDS]
            writer.writerow(row)
