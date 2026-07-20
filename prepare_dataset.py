# -*- coding: utf-8 -*-
"""
prepare_dataset.py -- Raw earthquake CSV -> canonical DATA-CERTIFY schema.

Real-world earthquake catalogs arrive in wildly inconsistent shapes (this is
itself exactly the kind of heterogeneity DATA-CERTIFY's I5 temporal-
distribution-drift and P6/unit-consistency tests exist to catch downstream).
This script is the one place pandas is used in the whole project -- the
core `data_certify` package is numpy-only.

Usage:
    python prepare_dataset.py --input raw.csv --dataset my_data
    python prepare_dataset.py --input raw.csv --dataset my_data \
        --origin-time-col origintime --latitude-col _latitude \
        --longitude-col longitude --depth-km-col _depth --magnitude-col _magnitude
    python prepare_dataset.py --input raw.csv --dataset my_data --no-interactive

Column auto-detection: if column-mapping flags are not given, the script
tries a list of common candidate names per canonical field (case-insensitive,
punctuation-insensitive) and reports what it inferred. Ambiguous or missing
mappings raise an error rather than silently guessing wrong (a wrong lat/lon
mapping is exactly the kind of Mode-12 field-swap error this project's own
theory documents warn about).

Handles, out of the box:
    - Quoted string fields (e.g. Chile catalog's `'2024-03-01 16:35:22'`)
    - Depth reported as a string with units, e.g. "243 km" -> depth_km=243.0
    - Magnitude reported with a trailing scale suffix, e.g. "2.9 Ml" ->
      magnitude=2.9, magnitude_type="Ml"
    - Separate date + time columns, AUTO-DETECTED and merged into a single
      origin_time with no flags needed (e.g. "date_utc"+"time_utc",
      "Date"+"Time", "event_date"+"event_time_utc") -- see
      DATE_ONLY_CANDIDATES/TIME_ONLY_CANDIDATES below for the exact name
      list tried; --date-col/--hour-col remain available to force a
      specific pair when a catalog uses names outside that list.
    - A single combined date+time column, auto-detected the same way
      (e.g. "origintime", "datetime", "event_time") -- tried BEFORE the
      separate-pair detection above, so a real combined column is never
      mistaken for one half of a pair.
    - Date and time glued with no separator, e.g. "2020-05-3023:45:48.085"
    - Malformed rows (broken quoting, wrong field count) are skipped with a
      warning rather than crashing the whole conversion.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from data_certify.schema import ALL_FIELDS, REQUIRED_FIELDS

DATASETS_DIR = ROOT / "datasets"

CANDIDATES: Dict[str, List[str]] = {
    "origin_time": ["origintime", "origin_time", "utc date", "time", "date_time",
                    "datetime", "event_time"],
    "latitude": ["latitude", "_latitude", "lat"],
    "longitude": ["longitude", "_longitude", "lon", "long"],
    "depth_km": ["depth_km", "_depth", "depth", "profoundity"],
    "magnitude": ["magnitude", "_magnitude", "mag"],
    "magnitude_type": ["magnitude_type", "mag_type", "magtype"],
    "seismic_moment_n_m": ["seismic_moment_n_m", "moment", "m0"],
    "tsunami_flag": ["tsunami_flag", "tsunami"],
    "mechanism": ["mechanism", "focal_mechanism"],
    "source": ["source", "agency", "network"],
    "event_uid_source": ["event_uid_source", "event_id", "id", "eventid"],
    "revision_status": ["revision_status", "status"],
    "mmi": ["mmi", "intensity"],
    "station_distance_km": ["station_distance_km", "distance_km", "delta"],
    "rupture_length_km": ["rupture_length_km", "rupture_length"],
    "rupture_area_km2": ["rupture_area_km2", "rupture_area"],
    "rupture_displacement_m": ["rupture_displacement_m", "displacement"],
    "azimuthal_gap_deg": ["azimuthal_gap_deg", "gap", "azimuthal_gap"],
}

# Candidate names for a DATE-ONLY column and a TIME-ONLY column, tried as a
# PAIR when no single combined origin_time column is found (see
# _auto_detect_date_time_pair below). Kept deliberately separate from
# CANDIDATES["origin_time"] above (which is for a single column that
# already contains a FULL timestamp) so the two detection passes can never
# be confused with each other -- a dataset with, say, an "event_time"
# column (a full timestamp, per CANDIDATES) is matched by the single-column
# pass first and never reaches the pair-detection logic at all.
DATE_ONLY_CANDIDATES: List[str] = [
    "date", "date_utc", "utc_date", "event_date", "eventdate",
    "origin_date", "occurrence_date", "quake_date",
]
TIME_ONLY_CANDIDATES: List[str] = [
    "time", "time_utc", "utc_time", "origin_time_of_day",
    "occurrence_time", "quake_time", "hour",
]


def _normalise_colname(c: str) -> str:
    return re.sub(r"[^a-z0-9]", "", c.strip().lower())


def _auto_detect(columns: List[str]) -> Dict[str, str]:
    norm_map = {_normalise_colname(c): c for c in columns}
    detected: Dict[str, str] = {}
    for canonical, candidates in CANDIDATES.items():
        for cand in candidates:
            key = _normalise_colname(cand)
            if key in norm_map:
                detected[canonical] = norm_map[key]
                break
    return detected


def _auto_detect_date_time_pair(columns: List[str]) -> Optional[Tuple[str, str]]:
    """
    Try to find a separate date column AND a separate time column (by name,
    case/punctuation-insensitive) to merge into origin_time, for catalogs
    that split date and time across two columns instead of one combined
    column (e.g. "date_utc"/"time_utc", "Date"/"Time"). Returns (date_col,
    time_col) if BOTH are found, else None -- deliberately requires both,
    since a lone "date"-like column with no time counterpart should still
    fall through to the interactive prompt rather than silently defaulting
    every event to midnight.
    """
    norm_map = {_normalise_colname(c): c for c in columns}
    date_col = next((norm_map[_normalise_colname(c)] for c in DATE_ONLY_CANDIDATES
                      if _normalise_colname(c) in norm_map), None)
    time_col = next((norm_map[_normalise_colname(c)] for c in TIME_ONLY_CANDIDATES
                      if _normalise_colname(c) in norm_map), None)
    if date_col and time_col:
        return date_col, time_col
    return None


_DEPTH_RE = re.compile(r"[-+]?\d*\.?\d+")
_MAG_RE = re.compile(r"([-+]?\d*\.?\d+)\s*([A-Za-z]*)")


def _clean_string_series(s: pd.Series) -> pd.Series:
    """Strip surrounding quotes/whitespace that some CSV exports leave in
    string cells (e.g. Chile catalog's `'2024-03-01 16:35:22'`)."""
    return s.astype(str).str.strip().str.strip("'\"")


def _parse_depth(raw: pd.Series) -> pd.Series:
    """Parse a depth column that may be a bare number or a string like
    '243 km' -- extracts the leading numeric portion, assumes km unless a
    'mi'/'mile' unit token is present (Mode 10 unit-consistency handling)."""
    cleaned = _clean_string_series(raw)

    def _one(v: str) -> float:
        v_lower = v.lower()
        m = _DEPTH_RE.search(v_lower)
        if not m:
            return float("nan")
        val = float(m.group())
        if "mi" in v_lower:
            val *= 1.60934
        return val

    return cleaned.map(_one)


def _parse_magnitude(raw: pd.Series):
    """Parse a magnitude column that may be a bare number or a string like
    '2.9 Ml' -- returns (magnitude: float series, magnitude_type: str series)."""
    cleaned = _clean_string_series(raw)
    mags, types = [], []
    for v in cleaned:
        m = _MAG_RE.search(v)
        if not m:
            mags.append(float("nan"))
            types.append("")
        else:
            mags.append(float(m.group(1)))
            types.append(m.group(2).strip())
    return pd.Series(mags, index=raw.index), pd.Series(types, index=raw.index)


def _parse_time(raw: pd.Series) -> pd.Series:
    cleaned = _clean_string_series(raw)
    # Some exports glue date and time with no separator, e.g.
    # "2020-05-3023:45:48.085" (NZ catalog) -- insert a 'T' before parsing
    # rather than silently failing to NaT for every row.
    fixed = cleaned.str.replace(r"^(\d{4}-\d{2}-\d{2})(\d{2}:\d{2}:\d{2}.*)$", r"\1T\2", regex=True)
    return pd.to_datetime(fixed, errors="coerce", utc=True, format="mixed")


def _prompt_for_column(field_name: str, columns: List[str]) -> Optional[str]:
    """
    Interactively ask the user which source column to use for a required
    field that auto-detection could not map. Returns the chosen column
    name, or None if the user aborts (blank input).

    Only called when `interactive=True` (the default) and a required field
    is still unmapped after auto-detection -- with `--no-interactive`,
    `prepare()` raises immediately instead of calling this.
    """
    print(f"\nCould not auto-detect a source column for required field '{field_name}'.")
    print(f"Available columns: {columns}")
    while True:
        try:
            answer = input(f"Enter the column name to use for '{field_name}' "
                            f"(or leave blank to abort): ").strip()
        except EOFError:
            # No interactive stdin available (e.g. piped/non-tty invocation)
            # -- treat exactly like an abort rather than looping forever.
            return None
        if answer == "":
            return None
        if answer in columns:
            return answer
        print(f"  '{answer}' not found in the CSV's columns. Try again.")


def _read_raw_csv(input_path: Path) -> pd.DataFrame:
    """Read a raw CSV as robustly as possible, skipping malformed rows
    (broken quoting, wrong field count) with a warning rather than
    crashing the whole conversion -- itself a real-world instance of the
    Category III human/pipeline data-entry errors this project's own
    taxonomy documents."""
    try:
        df = pd.read_csv(input_path, dtype=str, keep_default_na=True,
                          skipinitialspace=True, on_bad_lines="warn", engine="python")
    except TypeError:
        df = pd.read_csv(input_path, dtype=str, keep_default_na=True,
                          skipinitialspace=True, engine="python")
    df.columns = [c.strip() for c in df.columns]
    return df


def prepare(
    input_path: Path,
    dataset_name: str,
    column_overrides: Dict[str, str],
    interactive: bool = True,
    date_col: Optional[str] = None,
    hour_col: Optional[str] = None,
) -> Path:
    df = _read_raw_csv(input_path)

    detected_auto = _auto_detect(list(df.columns))
    detected = dict(detected_auto)
    detected.update(column_overrides)
    explicit_origin_time = "origin_time" in column_overrides

    # If origin_time wasn't pinned down explicitly (--origin-time-col) or
    # via --date-col, try auto-detecting a separate date+time PAIR -- this
    # is what lets a catalog that splits date and time into two columns
    # "just work" with no flags, the same way a single combined column
    # already does. IMPORTANT: this must run even when the single-column
    # pass above already matched something, because that pass's own
    # candidate list for origin_time includes a bare "time" (to catch
    # catalogs where a single column really does hold a full timestamp
    # named just "Time"). If a sibling "Date"-like column ALSO exists, that
    # single "time"-only match is actually just one half of a pair, and
    # trusting it alone would silently default every event's date to
    # *today's* date -- worse than not detecting anything. So: prefer the
    # full pair whenever the single-column match is either absent, or is
    # exactly the time-half of an available pair.
    auto_detected_pair = False
    if not date_col and not explicit_origin_time:
        pair = _auto_detect_date_time_pair(list(df.columns))
        if pair:
            date_half, time_half = pair
            single_auto_match = detected_auto.get("origin_time")
            if single_auto_match is None or single_auto_match == time_half:
                detected.pop("origin_time", None)
                date_col, hour_col = date_half, time_half
                auto_detected_pair = True

    missing_required = [f for f in REQUIRED_FIELDS if f != "origin_time" and f not in detected]
    has_time = "origin_time" in detected or (date_col and date_col in df.columns)

    if (missing_required or not has_time) and interactive:
        # interactive=True (the default): prompt for each unmapped required
        # field instead of failing immediately. If the user aborts (blank
        # input, or no interactive stdin available), fall through to the
        # same ValueError as --no-interactive below.
        print("Some required fields could not be auto-detected from the column names.")
        columns = list(df.columns)
        for f in list(missing_required):
            col = _prompt_for_column(f, columns)
            if col is not None:
                detected[f] = col
        missing_required = [f for f in REQUIRED_FIELDS if f != "origin_time" and f not in detected]

        if not has_time:
            col = _prompt_for_column("origin_time", columns)
            if col is not None:
                detected["origin_time"] = col
                has_time = True

    if missing_required or not has_time:
        problems = list(missing_required)
        if not has_time:
            problems.append("origin_time (or --date-col/--hour-col)")
        raise ValueError(
            f"prepare_dataset.py: could not map required field(s) {problems} from "
            f"columns {list(df.columns)}. Use --<field>-col to specify explicitly"
            + ("." if interactive else ", or omit --no-interactive to be prompted for them.")
        )

    print(f"Read {len(df)} rows from '{input_path.name}'.")
    print(f"Column mapping used:")
    for canonical, src in sorted(detected.items()):
        print(f"  {canonical:<24} <- '{src}'")
    if date_col:
        how = "auto-detected pair" if auto_detected_pair else "--date-col/--hour-col"
        print(f"  {'origin_time':<24} <- '{date_col}' + '{hour_col}' (merged, {how})")

    out = pd.DataFrame(index=df.index)

    if date_col and date_col in df.columns:
        date_part = _clean_string_series(df[date_col])
        hour_part = _clean_string_series(df[hour_col]) if hour_col and hour_col in df.columns else ""
        combined = (date_part + " " + hour_part) if hour_col else date_part
        out["origin_time"] = _parse_time(combined)
    else:
        out["origin_time"] = _parse_time(df[detected["origin_time"]])

    out["latitude"] = pd.to_numeric(_clean_string_series(df[detected["latitude"]]), errors="coerce")
    out["longitude"] = pd.to_numeric(_clean_string_series(df[detected["longitude"]]), errors="coerce")
    out["depth_km"] = _parse_depth(df[detected["depth_km"]])

    mag_series, mag_type_series = _parse_magnitude(df[detected["magnitude"]])
    out["magnitude"] = mag_series
    out["magnitude_type"] = mag_type_series

    if "magnitude_type" in detected:
        explicit_type = _clean_string_series(df[detected["magnitude_type"]])
        out["magnitude_type"] = explicit_type.where(explicit_type != "", out["magnitude_type"])

    for f in ["seismic_moment_n_m", "tsunami_flag", "mmi", "station_distance_km",
              "rupture_length_km", "rupture_area_km2", "rupture_displacement_m",
              "azimuthal_gap_deg"]:
        if f in detected:
            out[f] = pd.to_numeric(_clean_string_series(df[detected[f]]), errors="coerce")
        else:
            out[f] = np.nan

    for f in ["mechanism", "source", "event_uid_source", "revision_status"]:
        if f in detected:
            out[f] = _clean_string_series(df[detected[f]])
        else:
            out[f] = ""

    out = out[ALL_FIELDS]

    n_before = len(out)
    n_missing_required = int(
        out["latitude"].isna().sum() + out["longitude"].isna().sum()
        + out["depth_km"].isna().sum() + out["magnitude"].isna().sum()
        + out["origin_time"].isna().sum()
    )
    print(f"\nParsed {n_before} rows. Required-field missing-value cells (summed "
          f"across the 5 required columns): {n_missing_required}.")
    print("NOTE: rows with missing required fields are KEPT, not dropped -- "
          "DATA-CERTIFY's own C1 completeness test is the correct place to "
          "quantify and score this, not this loader.")

    out_dir = DATASETS_DIR / dataset_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "records.csv"

    write_df = out.copy()
    write_df["origin_time"] = write_df["origin_time"].dt.strftime("%Y-%m-%dT%H:%M:%S.%f").fillna("")
    write_df = write_df.fillna("")
    write_df.to_csv(out_path, index=False)

    print(f"\nWrote canonical dataset -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a raw earthquake CSV into the canonical DATA-CERTIFY schema.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, type=str, help="Path to raw input CSV.")
    parser.add_argument("--dataset", required=True, type=str,
                        help="Output dataset name (written to datasets/<name>/records.csv).")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Fail fast instead of prompting on ambiguous mapping.")
    parser.add_argument("--date-col", type=str, default=None,
                        help="Use this column (optionally + --hour-col) as origin_time instead of auto-detection.")
    parser.add_argument("--hour-col", type=str, default=None,
                        help="Column to merge with --date-col to build a full timestamp.")
    for field_name in CANDIDATES:
        flag = "--" + field_name.replace("_", "-") + "-col"
        parser.add_argument(flag, type=str, default=None,
                            help="Explicit source column for '" + field_name + "'.")
    args = parser.parse_args()

    overrides = {}
    for field_name in CANDIDATES:
        val = getattr(args, field_name + "_col")
        if val:
            overrides[field_name] = val

    prepare(
        input_path=Path(args.input),
        dataset_name=args.dataset,
        column_overrides=overrides,
        interactive=not args.no_interactive,
        date_col=args.date_col,
        hour_col=args.hour_col,
    )


if __name__ == "__main__":
    main()
