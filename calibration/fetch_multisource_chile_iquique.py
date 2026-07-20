# -*- coding: utf-8 -*-
"""
calibration/fetch_multisource_chile_iquique.py -- Group D1 option (d)
(see Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group D / D1;
decision rationale in Docs/03_Paper_Prep/DATA-CERTIFY_Downstream_Case_Studies_Combined_Summary.md,
option (d), "light" scope -- b-value only, no full hazard curve):
live data-fetch step for the cross-agency-merge case study.

*** THIS SCRIPT MUST BE RUN ON A MACHINE WITH REAL INTERNET ACCESS. ***
It was NOT possible to run this from the sandboxed environment this
analysis was otherwise developed in -- a direct connectivity test against
earthquake.usgs.gov, seismicportal.eu, isc.ac.uk, and even google.com all
returned "Tunnel connection failed: 403 Forbidden" through that sandbox's
egress proxy (a general outbound-network restriction, not specific to
seismological APIs). This matches the project's own established
convention (D1 Decision Brief, Section 2, evaluation criterion 5): work
requiring live external API access or the full corpus is run by the user
on their own machine, with results sent back for verification -- exactly
as this file is designed for.

WHAT THIS SCRIPT DOES: queries the REAL, live USGS ComCat and EMSC
SeismicPortal FDSN event web services (the same two of the three sources
`data_certify/reference_data.py` already implements for A6) for the same
region/time-window/magnitude-floor as this project's existing
`datasets/real_chile_iquique_2014/records.csv` (a proven, already-used
scope: n=621 single-source events, 2014-03-01 to 2014-05-31, lat
[-20.9718, -18.096], lon [-71.4602, -69.1422], magnitude>=3.5 -- the 2014
Iquique, Chile Mw8.2 sequence), saving three files:
  - `usgs_raw.csv`   -- USGS ComCat events only, source="usgs"
  - `emsc_raw.csv`   -- EMSC SeismicPortal events only, source="emsc"
  - `naive_merged.csv` -- the two concatenated with NO deduplication
    (exactly what a downstream analyst gets from a naive
    `pd.concat([usgs_df, emsc_df])`-style merge, and exactly the scenario
    D2's literature review found no existing framework combines
    deduplication with authenticity auditing for -- see
    Docs/03_Paper_Prep/DATA-CERTIFY_Related_Work_Literature_Review.md).

WHY ONLY TWO OF THE THREE SOURCES (no ISC): USGS and EMSC both expose a
GeoJSON API with a near-identical, simple response shape. ISC's FDSN
event service returns QuakeML/XML instead (data_certify/reference_data.py's
own ISCReference class has an entire dedicated, non-trivial XML parser,
`_parse_quakeml_events`, hardened over multiple real bug-hunts documented
in that file). Writing a NEW QuakeML parser here, in a script that cannot
be tested against a live endpoint from this environment before being
handed to the user, would be new, unvalidated code exercising exactly the
kind of format-parsing edge cases that file's own history shows are easy
to get subtly wrong. Two independent sources (USGS, EMSC) already fully
demonstrate the cross-agency merge phenomenon this case study needs
(duplicate events, magnitude-convention differences) -- D2's own related-
work finding is about multi-source integration in general, not a specific
3-source requirement. ISC's exclusion is a disclosed, deliberate scope
reduction to avoid shipping untested parsing logic, not an oversight.

WHY NOT THE PROJECT'S OWN USGSComCatReference/EMSCReference CLASSES
DIRECTLY: those classes' private `_fetch_events`/`_query` methods
deliberately discard the depth field (A6 matching only ever needed
time/lat/lon/mag). This case study needs depth_km (a REQUIRED field in
`data_certify/schema.py`'s CertifyDataset), so this script reimplements
the same query-building logic (same base URLs, same param names, same
retry/timeout helper reused directly from that module) with one small,
low-risk addition: extracting the depth value each API already returns
(USGS: the 3rd element of the GeoJSON geometry's `coordinates` array;
EMSC: the `depth` property) but the existing private methods simply never
read.

NO PAGINATION: unlike USGSComCatReference/EMSCReference's production
match() methods (which must handle arbitrarily large datasets and
therefore implement recursive time-window halving), this script queries a
SINGLE, small, already-proven-scale window in one request per source
(expected ~400-900 events per source, based on the existing single-source
real_chile_iquique_2014 scale of n=621) -- comfortably under both APIs'
documented ~20,000-event single-request cap. This intentionally avoids
reimplementing the recursive-pagination logic (which has its own
multi-bug history in reference_data.py) in code that cannot be tested
live before being handed to the user. If either source's returned count
comes back suspiciously close to the request `limit`, this script prints
an explicit warning rather than silently truncating -- see `_warn_if_near_cap`.

Usage (run on a machine with internet access, from the project root):
    python3 calibration/fetch_multisource_chile_iquique.py

Output (written to calibration/group_d_reports/d1d_multisource/):
    usgs_raw.csv, emsc_raw.csv, naive_merged.csv
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

import numpy as np

CALIBRATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALIBRATION_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Reuse the project's own already-hardened HTTP retry/timeout helper and
# ISO-time parser directly, rather than reimplementing them -- these are
# module-level functions in reference_data.py, not class-private.
from data_certify.reference_data import (  # noqa: E402
    _get_with_retry, _iso_to_datetime64_ns,
    USGS_COMCAT_BASE_URL, EMSC_BASE_URL,
)

OUT_DIR = CALIBRATION_DIR / "group_d_reports" / "d1d_multisource"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Same region/window/magnitude-floor as the existing, already-used
# datasets/real_chile_iquique_2014/records.csv (2014 Iquique, Chile Mw8.2
# sequence) -- a proven, moderate scale (n=621 single-source), chosen
# specifically to keep this a single-request, non-paginated, low-risk pull.
START_ISO = "2014-03-01T00:00:00"
END_ISO = "2014-06-01T00:00:00"
LAT_MIN, LAT_MAX = -20.9718, -18.096
LON_MIN, LON_MAX = -71.4602, -69.1422
MIN_MAG = 3.5
REQUEST_LIMIT = 5000  # well above the ~600-900 events/source expected at this scale
TIMEOUT_SEC = 20.0

CSV_HEADER = [
    "origin_time", "latitude", "longitude", "depth_km", "magnitude",
    "magnitude_type", "seismic_moment_n_m", "tsunami_flag", "mechanism",
    "source", "event_uid_source", "revision_status", "mmi",
    "station_distance_km", "rupture_length_km", "rupture_area_km2",
    "rupture_displacement_m", "azimuthal_gap_deg",
]


def _warn_if_near_cap(source_name: str, n_returned: int, limit: int) -> None:
    if n_returned >= int(0.9 * limit):
        print(f"  WARNING: {source_name} returned {n_returned} events, close to the "
              f"request limit ({limit}) -- results may be TRUNCATED. If so, re-run with "
              f"a smaller time window or a higher MIN_MAG and treat this pull as invalid "
              f"until it returns comfortably under the limit.")


def fetch_usgs() -> list[dict]:
    params = {
        "starttime": START_ISO, "endtime": END_ISO,
        "minlatitude": f"{LAT_MIN:.6f}", "maxlatitude": f"{LAT_MAX:.6f}",
        "minlongitude": f"{LON_MIN:.6f}", "maxlongitude": f"{LON_MAX:.6f}",
        "minmagnitude": f"{MIN_MAG:.3f}",
        "format": "geojson", "limit": str(REQUEST_LIMIT), "orderby": "time",
    }
    url = f"{USGS_COMCAT_BASE_URL}/query?{urllib.parse.urlencode(params)}"
    print(f"Querying USGS ComCat: {url}")
    raw = _get_with_retry(url, TIMEOUT_SEC)
    if raw is None:
        print("  USGS query FAILED (network error / timeout / non-200 after retry).")
        return []
    payload = json.loads(raw.decode("utf-8"))
    rows = []
    for feat in payload.get("features", []) or []:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates")
        mag, t_ms = props.get("mag"), props.get("time")
        if not coords or len(coords) < 2 or mag is None or t_ms is None:
            continue
        lon, lat = coords[0], coords[1]
        depth_km = coords[2] if len(coords) > 2 and coords[2] is not None else float("nan")
        t = np.datetime64(int(t_ms), "ms")
        rows.append(dict(
            origin_time=str(t), latitude=lat, longitude=lon, depth_km=depth_km, magnitude=mag,
            magnitude_type=props.get("magType", ""), source="usgs",
            event_uid_source=str(feat.get("id", "")), revision_status=props.get("status", ""),
        ))
    print(f"  USGS returned {len(rows)} events.")
    _warn_if_near_cap("USGS", len(rows), REQUEST_LIMIT)
    return rows


def fetch_emsc() -> list[dict]:
    params = {
        "starttime": START_ISO, "endtime": END_ISO,
        "minlatitude": f"{LAT_MIN:.6f}", "maxlatitude": f"{LAT_MAX:.6f}",
        "minlongitude": f"{LON_MIN:.6f}", "maxlongitude": f"{LON_MAX:.6f}",
        "minmagnitude": f"{MIN_MAG:.3f}",
        "format": "json", "limit": str(REQUEST_LIMIT), "orderby": "time",
    }
    url = f"{EMSC_BASE_URL}/query?{urllib.parse.urlencode(params)}"
    print(f"Querying EMSC SeismicPortal: {url}")
    raw = _get_with_retry(url, TIMEOUT_SEC)
    if raw is None:
        print("  EMSC query FAILED (network error / timeout / non-200 after retry).")
        return []
    payload = json.loads(raw.decode("utf-8"))
    rows = []
    for feat in payload.get("features", []) or []:
        props = feat.get("properties") or {}
        t = _iso_to_datetime64_ns(props.get("time", ""))
        lat, lon, mag = props.get("lat"), props.get("lon"), props.get("mag")
        depth_km = props.get("depth", float("nan"))
        if t is None or lat is None or lon is None or mag is None:
            continue
        rows.append(dict(
            origin_time=str(t), latitude=lat, longitude=lon,
            depth_km=depth_km if depth_km is not None else float("nan"), magnitude=mag,
            magnitude_type=props.get("magtype", ""), source="emsc",
            event_uid_source=str(props.get("unid", props.get("source_id", ""))),
            revision_status=props.get("evtype", ""),
        ))
    print(f"  EMSC returned {len(rows)} events.")
    _warn_if_near_cap("EMSC", len(rows), REQUEST_LIMIT)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            full = {k: r.get(k, "") for k in CSV_HEADER}
            w.writerow(full)


def main() -> None:
    usgs_rows = fetch_usgs()
    emsc_rows = fetch_emsc()

    if not usgs_rows or not emsc_rows:
        print("\nERROR: one or both sources returned zero events -- something is wrong "
              "(network failure, or the query window/region needs adjustment). NOT writing "
              "output files. Check the printed URLs above by pasting them into a browser to "
              "debug directly.")
        sys.exit(1)

    _write_csv(OUT_DIR / "usgs_raw.csv", usgs_rows)
    _write_csv(OUT_DIR / "emsc_raw.csv", emsc_rows)
    _write_csv(OUT_DIR / "naive_merged.csv", usgs_rows + emsc_rows)

    print(f"\nSaved:")
    print(f"  {OUT_DIR / 'usgs_raw.csv'}  (n={len(usgs_rows)})")
    print(f"  {OUT_DIR / 'emsc_raw.csv'}  (n={len(emsc_rows)})")
    print(f"  {OUT_DIR / 'naive_merged.csv'}  (n={len(usgs_rows) + len(emsc_rows)}, no dedup)")
    print(f"\nNext step: python3 calibration/analysis_d1d_cross_agency_merge.py")


if __name__ == "__main__":
    main()
