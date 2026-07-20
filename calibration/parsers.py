# -*- coding: utf-8 -*-
"""
calibration/parsers.py -- Bespoke pre-processing for the 3 non-standard-
schema real earthquake catalogs included in the calibration corpus:

    Dataset/earthquake1.csv                  (NOAA/ISC-GEM significant
                                               earthquakes 1965-2016)
    Dataset/Events.csv                       (Atkinson/NGA-West3 ground-
                                               motion research catalog)
    Dataset/PastHugeEarthquakeinNankai.csv   (hand-compiled historical
                                               Nankai-trough catalog, 684
                                               AD - 1946)

None of these three fit prepare_dataset.py's existing auto-detection +
--date-col/--hour-col merge model as-is, each for a different reason
documented in its own function below. Rather than extending
prepare_dataset.py's CLI surface for three one-off quirks, each function
here does the MINIMAL possible pre-processing (row filtering, column
construction) needed to produce an intermediate CSV that
prepare_dataset.py's existing, already-tested `prepare()` CAN handle
natively, then calls it directly -- so all of its numeric/date parsing
and canonical-CSV-writing logic is reused unchanged rather than
duplicated.

Every filtering/transformation decision made here is disclosed via a
print() at conversion time (consistent with prepare_dataset.py's own
logging style) AND in this module's docstrings, per this project's
honesty-first documentation culture: nothing is silently dropped,
inferred, or fabricated without saying so.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import prepare_dataset as _pd_mod  # the CLI script's module -- reuse its prepare()

TMP_DIR = ROOT / "calibration" / "_tmp_preprocessed"


def prepare_earthquake1(src: Path, dataset_name: str) -> Path:
    """
    Dataset/earthquake1.csv -- NOAA/ISC-GEM "Significant Earthquakes
    1965-2016" catalog. Its columns already match most of
    prepare_dataset.py's auto-detection CANDIDATES case/punctuation-
    insensitively (Latitude, Longitude, Depth, Magnitude, "Magnitude
    Type", "Azimuthal Gap", ID, Source, Status). Two things it cannot
    do out of the box:

      1. origin_time: Date ("MM-DD-YYYY") and Time ("HH:MM:SS") are two
         separate columns -- this is exactly what prepare()'s existing
         --date-col/--hour-col merge was built for, so no pre-processing
         is needed for this part.
      2. Row filtering: the raw file mixes true tectonic earthquakes
         with a small number of non-earthquake rows (Type in
         {"Explosion", "Nuclear Explosion", "Rock Burst"}). Including
         these would silently contaminate the calibration corpus with
         non-seismic events, so they are dropped HERE (disclosed via
         the printed counts below) before handing off to prepare().
    """
    df = pd.read_csv(src, dtype=str)
    n_before = len(df)
    df = df[df["Type"] == "Earthquake"].copy()
    n_after = len(df)
    print(f"[earthquake1] dropped {n_before - n_after} non-earthquake rows "
          f"(Type != 'Earthquake': Explosion/Nuclear Explosion/Rock Burst); "
          f"kept {n_after}/{n_before}.")

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / "earthquake1_filtered.csv"
    df.to_csv(tmp_path, index=False)

    return _pd_mod.prepare(
        input_path=tmp_path,
        dataset_name=dataset_name,
        column_overrides={},
        interactive=False,
        date_col="Date",
        hour_col="Time",
    )


def prepare_events(src: Path, dataset_name: str) -> Path:
    """
    Dataset/Events.csv -- Atkinson/NGA-West3 ground-motion research
    catalog (5,664 real California/Pacific-NW events). origin_time is
    split across SIX columns (Year, Month, Day, Hour, Minute, Second)
    rather than the two prepare_dataset.py's --date-col/--hour-col
    mechanism supports, and `Second` is frequently missing (read as
    NaN by pandas' default "NA" -> NaN coercion, even under dtype=str).
    Both are handled HERE by constructing a single combined datetime
    string column before handing off to prepare() (as --date-col alone,
    since it is already fully combined -- no --hour-col needed).

    Missing Second is treated as ":00.000000", NOT dropped or NaT'd --
    an event with a known Y/M/D/H/M but unknown sub-minute second is
    still overwhelmingly identifiable/usable, and zero-filling the
    sub-minute remainder is a disclosed, bounded (<60s) approximation,
    unlike guessing at a missing year or lat/lon. Rows missing Hour
    and/or Minute (39/5664) have no safe zero-fill -- origin_time is
    left blank (-> NaT) for those instead, so C1 correctly counts them
    as missing rather than silently mislabelling them as midnight.
    """
    df = pd.read_csv(src, dtype=str)
    n_missing_sec = int(df["Second"].isna().sum())
    n_missing_hm = int((df["Hour"].isna() | df["Minute"].isna()).sum())
    print(f"[Events] {n_missing_sec}/{len(df)} rows have no 'Second' value; "
          f"zero-filled to :00.000000 (disclosed, bounded <60s approximation).")
    print(f"[Events] {n_missing_hm}/{len(df)} rows have no 'Hour' and/or 'Minute' "
          f"value -- Year/Month/Day are known but the sub-day time is not, so "
          f"origin_time is left BLANK (-> NaT) for these rows rather than "
          f"guessing a time-of-day; C1 will correctly count these as missing.")

    def _combine(row) -> str:
        if pd.isna(row["Year"]) or pd.isna(row["Month"]) or pd.isna(row["Day"]) \
                or pd.isna(row["Hour"]) or pd.isna(row["Minute"]):
            return ""
        sec = row["Second"]
        try:
            sec_f = 0.0 if pd.isna(sec) else float(sec)
        except (TypeError, ValueError):
            sec_f = 0.0
        return (f"{int(float(row['Year'])):04d}-{int(float(row['Month'])):02d}-"
                f"{int(float(row['Day'])):02d} {int(float(row['Hour'])):02d}:"
                f"{int(float(row['Minute'])):02d}:{sec_f:09.6f}")

    df["_origin_time_combined"] = df.apply(_combine, axis=1)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / "events_combined.csv"
    df.to_csv(tmp_path, index=False)

    return _pd_mod.prepare(
        input_path=tmp_path,
        dataset_name=dataset_name,
        column_overrides={
            "origin_time": "_origin_time_combined",
            "magnitude": "Preferred_Magnitude",
            "magnitude_type": "ComCat_Magnitude_Type",
            "event_uid_source": "USGS_ComCatID",
            "source": "Source_of_Data",
        },
        interactive=False,
    )


def prepare_nankai(src: Path, dataset_name: str) -> Path:
    """
    Dataset/PastHugeEarthquakeinNankai.csv -- a hand-compiled 13-row
    catalog of historical Nankai-trough earthquakes back to 684 AD.
    Two things need bespoke handling no CANDIDATES-based mapping could do:

      1. `coordinate` is a single string like "32.8 [deg] N 134.3 [deg] E"
         that must be split into separate numeric latitude/longitude
         columns.
      2. `time` contains dates as old as 0684/11/29 -- outside the
         [1677-09-21, 2262-04-11] range representable by numpy's
         datetime64[ns] (the dtype schema.py uses for origin_time).
         pandas' `pd.to_datetime(..., errors="coerce")` already converts
         any out-of-bounds date to NaT rather than raising (verified
         directly against this file: 8 of the 13 rows, all pre-1677,
         become NaT; the 5 rows from 1707 onward parse correctly) --
         so no special-casing is needed for correctness, but this IS
         disclosed here because it means 8/13 = 62% of this dataset will
         show up as "missing origin_time" under C1 completeness scoring:
         a disclosed datetime64[ns] REPRESENTATION LIMIT of the storage
         format, not a genuine defect in the source catalog. See
         calibration/build_corpus.py's manifest `notes` field for this
         dataset and the calibration write-up for how this is factored
         into (not silently allowed to distort) the EWM/threshold
         calibration.

    This source also reports no depth for any event at all -- rather
    than fabricating a value, an explicitly BLANK depth_km column is
    written, which prepare()'s existing NaN-for-unknown handling
    represents correctly as "genuinely unknown," not as a zero or a
    guessed regional-average depth.
    """
    df = pd.read_csv(src, dtype=str)
    coord = df["coordinate"].str.strip()
    _deg = chr(176)  # the degree symbol (U+00B0), built via chr() rather
                      # than a literal glyph to keep this source file
                      # plain-ASCII (avoids editor/sync mangling of non-ASCII)
    _coord_pattern = "([\\d.]+)\\s*" + _deg + "?\\s*([NS])\\s+([\\d.]+)\\s*" + _deg + "?\\s*([EW])"
    ext = coord.str.extract(_coord_pattern, expand=True)
    n_unparsed = int(ext[0].isna().sum())
    if n_unparsed:
        print(f"[nankai] WARNING: {n_unparsed}/{len(df)} coordinate strings did not "
              f"match the expected degree-N/S degree-E/W pattern -- left as NaN.")
    lat = ext[0].astype(float) * ext[1].map({"N": 1.0, "S": -1.0})
    lon = ext[2].astype(float) * ext[3].map({"E": 1.0, "W": -1.0})

    n_ancient = int(pd.to_datetime(df["time"], errors="coerce", utc=True, format="mixed").isna().sum())
    print(f"[nankai] {n_ancient}/{len(df)} rows have dates before 1677-09-21 "
          f"(datetime64[ns] floor) and will be stored as NaT origin_time -- "
          f"a disclosed representation limit, not a data-quality defect.")

    out = pd.DataFrame({
        "time": df["time"],
        "latitude": lat,
        "longitude": lon,
        "mag": df["mag"],
        "depth_km": ["" for _ in range(len(df))],  # genuinely unreported, not fabricated
    })

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / "nankai_split.csv"
    out.to_csv(tmp_path, index=False)

    return _pd_mod.prepare(
        input_path=tmp_path,
        dataset_name=dataset_name,
        column_overrides={},
        interactive=False,
    )


def prepare_usgs_geojson(src: Path, dataset_name: str) -> Path:
    """
    Dataset/ishikawa_202401.json and Dataset/japan_2023-.json -- two real
    USGS ComCat GeoJSON FeatureCollection exports (confirmed via their own
    `metadata.url` field: both are literal
    earthquake.usgs.gov/fdsnws/event/1/query.geojson? API calls, same
    source as every other real file in this corpus, just in GeoJSON rather
    than CSV form).

    DISCLOSED CORRECTION: these two files were present in the user's
    original file list but were missed by the initial Dataset/ inventory
    pass (task #43) -- neither built into the corpus nor recorded in
    build_corpus.py's EXCLUDED_NON_CATALOG_FILES list, an undisclosed gap
    caught only during a later full re-verification pass. Both are
    genuine, usable point-event earthquake catalogs (not administrative
    boundaries or wildfire perimeters like the files that WERE correctly
    excluded), so the correct fix is to include them, not exclude them --
    this function does the minimal GeoJSON-to-flat-CSV flattening needed
    (each Feature's `properties` dict plus its Point `geometry.coordinates`
    -> one row) so prepare_dataset.py's existing CANDIDATES auto-detection
    can pick up the resulting columns exactly as it already does for the
    plain-CSV ComCat exports (same field names: time, latitude, longitude,
    depth, mag, magType, id, updated, place, type, net, status, mmi, gap,
    nst, dmin, rms, tsunami -- GeoJSON's `properties.mag`/`geometry.
    coordinates` etc. use the identical vocabulary as the CSV export of
    the same underlying API).

    `time` and `updated` are UNIX epoch milliseconds in the raw GeoJSON
    (confirmed: `d["features"][0]["properties"]["time"]` is a 13-digit
    integer) -- converted here to ISO-8601 strings via
    `pd.to_datetime(..., unit="ms")` so prepare_dataset.py's existing
    date-parsing path (which expects a string/parseable datetime, not a
    raw epoch integer) handles them without any bespoke epoch-handling
    logic of its own.
    """
    import json as _json

    with open(src, "r", encoding="utf-8") as f:
        geo = _json.load(f)
    features = geo.get("features", [])
    print(f"[usgs_geojson:{dataset_name}] {len(features)} features "
          f"(metadata.count={geo.get('metadata', {}).get('count')}) "
          f"from {geo.get('metadata', {}).get('url', '<no url>')}")

    rows = []
    for feat in features:
        props = dict(feat.get("properties", {}))
        coords = feat.get("geometry", {}).get("coordinates", [None, None, None])
        lon, lat = coords[0], coords[1]
        depth = coords[2] if len(coords) > 2 else None
        rows.append({
            "time": props.get("time"),
            "updated": props.get("updated"),
            "latitude": lat,
            "longitude": lon,
            "depth": depth,
            "mag": props.get("mag"),
            "magType": props.get("magType"),
            "id": feat.get("id"),
            "place": props.get("place"),
            "type": props.get("type"),
            "net": props.get("net"),
            "status": props.get("status"),
            "mmi": props.get("mmi"),
            "gap": props.get("gap"),
            "nst": props.get("nst"),
            "dmin": props.get("dmin"),
            "rms": props.get("rms"),
            "tsunami": props.get("tsunami"),
        })
    df = pd.DataFrame(rows)

    n_before = len(df)
    df = df[df["type"] == "earthquake"].copy()
    n_after = len(df)
    if n_after != n_before:
        print(f"[usgs_geojson:{dataset_name}] dropped {n_before - n_after} non-earthquake "
              f"features (type != 'earthquake'); kept {n_after}/{n_before}.")

    for col in ("time", "updated"):
        df[col] = pd.to_datetime(df[col], unit="ms", utc=True, errors="coerce").astype(str)

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = TMP_DIR / f"{dataset_name}_geojson_flat.csv"
    df.to_csv(tmp_path, index=False)

    return _pd_mod.prepare(
        input_path=tmp_path,
        dataset_name=dataset_name,
        column_overrides={},
        interactive=False,
    )
