# -*- coding: utf-8 -*-
"""
calibration/enrich_tsunami_mmi_from_usgs.py -- Backfill the tsunami_flag
and mmi optional columns for USGS-sourced datasets in datasets/, using
data that is ALREADY present in the same USGS ComCat query endpoint
these datasets were originally pulled from -- it was simply dropped
because the ORIGINAL downloads used USGS's plain-CSV export format
(time,latitude,longitude,depth,mag,magType,nst,gap,dmin,rms,net,id,
updated,place,type,horizontalError,depthError,magError,magNst,status,
locationSource,magSource -- confirmed by inspecting
Dataset/afghanistan_20231008_query.csv's header), which never included
tsunami/mmi columns at all. The GeoJSON query endpoint (same API,
different `format=` param) DOES return both `tsunami` (0/1) and `mmi`
(float, often null for smaller events) per event.

Why this is safe (not "inventing" data): every affected dataset already
carries `event_uid_source` populated with the exact USGS event id (e.g.
"us6000qxlc") from the original download (see schema.py's
event_uid_source field). This script re-queries USGS for the dataset's
own bounding box + time range + minimum magnitude (same footprint-only
query pattern as reference_data.py's USGSComCatReference.match(), see
that class's docstring for the "never the whole planet" design
rationale) and joins back onto the existing rows by EXACT id match --
never by fuzzy time/space proximity. Rows whose id isn't found in the
query response are left untouched (their tsunami_flag/mmi stay NaN, same
as before).

This closes part of the P4/P9 sparse-observation gap identified during
the 2026-07-05 quality audit (P4 n_obs=2, P9 n_obs=0 across the 73-
dataset corpus per calibration/ewm_report.md) -- but only tsunami_flag
and mmi. rupture_length_km (P5) and seismic_moment_n_m (P6) are NOT
available from this endpoint at all (they require GCMT moment-tensor /
finite-fault-model products, a genuinely different data source) and are
NOT touched by this script.

Network note: this makes live HTTP requests to earthquake.usgs.gov.
Must be run from an environment with real internet access to that host
(confirmed NOT reachable from the Claude sandbox's bash tool as of
2026-07-05 -- only certain allowlisted domains, e.g. pypi.org, are
reachable from there; USGS is not on that allowlist). The user's own
machine already has confirmed working access (see their live
run_audit.py run earlier in this session, which successfully hit A6
against USGS ComCat).

Safety: defaults to --dry-run (prints what WOULD change, writes
nothing). Pass --apply to actually write. When --apply is used, the
original records.csv is first copied to records.csv.bak_pre_enrich
(never overwritten if that backup already exists, so re-running --apply
is idempotent and never destroys the true original).

Usage:
    python3 calibration/enrich_tsunami_mmi_from_usgs.py             # dry-run, all eligible datasets
    python3 calibration/enrich_tsunami_mmi_from_usgs.py --apply      # actually write
    python3 calibration/enrich_tsunami_mmi_from_usgs.py --only real_afghanistan_2025_09_01 --apply
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"
DATASETS_DIR = ROOT / "datasets"

USGS_QUERY_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USGS_COUNT_URL = "https://earthquake.usgs.gov/fdsnws/event/1/count"
_USER_AGENT = "data-certify-p4-p9-enrichment/0.1"
TIMEOUT_SEC = 15.0


def _get(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def is_feasible() -> bool:
    raw = _get(f"{USGS_COUNT_URL}?starttime=2020-01-01&endtime=2020-01-02&minmagnitude=5")
    if raw is None:
        return False
    try:
        int(raw.decode("utf-8").strip())
        return True
    except (ValueError, UnicodeDecodeError):
        return False


def fetch_id_to_tsunami_mmi(start_iso: str, end_iso: str,
                             lat_min: float, lat_max: float,
                             lon_min: float, lon_max: float,
                             min_mag: float) -> dict:
    """One bounded query covering the dataset's own footprint. Returns
    {usgs_event_id: (tsunami_int_or_None, mmi_float_or_None)}."""
    params = {
        "format": "geojson", "starttime": start_iso, "endtime": end_iso,
        "minlatitude": f"{lat_min:.6f}", "maxlatitude": f"{lat_max:.6f}",
        "minlongitude": f"{lon_min:.6f}", "maxlongitude": f"{lon_max:.6f}",
        "minmagnitude": f"{min_mag:.3f}", "limit": "20000", "orderby": "time",
    }
    url = f"{USGS_QUERY_URL}?{urllib.parse.urlencode(params)}"
    raw = _get(url)
    if raw is None:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    out = {}
    for feat in payload.get("features", []) or []:
        eid = feat.get("id")
        props = feat.get("properties") or {}
        if eid:
            out[eid] = (props.get("tsunami"), props.get("mmi"))
    return out


def enrich_one(dataset_id: str, apply: bool) -> dict:
    ds_dir = DATASETS_DIR / dataset_id
    csv_path = ds_dir / "records.csv"
    if not csv_path.exists():
        return {"dataset_id": dataset_id, "status": "SKIP (no records.csv)"}

    df = pd.read_csv(csv_path)
    if "event_uid_source" not in df.columns or df["event_uid_source"].isna().all():
        return {"dataset_id": dataset_id, "status": "SKIP (no event_uid_source populated)"}

    origin = pd.to_datetime(df["origin_time"], errors="coerce", utc=True)
    if origin.isna().all():
        return {"dataset_id": dataset_id, "status": "SKIP (no valid origin_time)"}

    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")
    mag = pd.to_numeric(df["magnitude"], errors="coerce")
    if lat.isna().all() or lon.isna().all() or mag.isna().all():
        return {"dataset_id": dataset_id, "status": "SKIP (no valid lat/lon/mag)"}

    start_iso = (origin.min() - pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    end_iso = (origin.max() + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    min_mag = max(0.0, float(mag.min()) - 0.05)

    id_map = fetch_id_to_tsunami_mmi(
        start_iso, end_iso,
        float(lat.min()) - 0.01, float(lat.max()) + 0.01,
        float(lon.min()) - 0.01, float(lon.max()) + 0.01,
        min_mag,
    )
    if not id_map:
        return {"dataset_id": dataset_id, "status": "NO_MATCH (empty USGS response)"}

    n_tsunami_filled = 0
    n_mmi_filled = 0
    if "tsunami_flag" not in df.columns:
        df["tsunami_flag"] = float("nan")
    if "mmi" not in df.columns:
        df["mmi"] = float("nan")

    for i, eid in df["event_uid_source"].items():
        if pd.isna(eid) or eid not in id_map:
            continue
        tsunami, mmi = id_map[eid]
        if tsunami is not None and pd.isna(df.at[i, "tsunami_flag"]):
            df.at[i, "tsunami_flag"] = float(tsunami)
            n_tsunami_filled += 1
        if mmi is not None and pd.isna(df.at[i, "mmi"]):
            df.at[i, "mmi"] = float(mmi)
            n_mmi_filled += 1

    status = f"MATCHED {len(id_map)} usgs events; filled tsunami={n_tsunami_filled} mmi={n_mmi_filled}"

    if apply and (n_tsunami_filled or n_mmi_filled):
        backup_path = ds_dir / "records.csv.bak_pre_enrich"
        if not backup_path.exists():
            shutil.copy2(csv_path, backup_path)
        df.to_csv(csv_path, index=False)
        status += " -- WRITTEN (backup at records.csv.bak_pre_enrich)"
    elif not apply:
        status += " -- DRY RUN, nothing written"

    return {"dataset_id": dataset_id, "status": status,
            "n_tsunami_filled": n_tsunami_filled, "n_mmi_filled": n_mmi_filled}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually write changes (default: dry-run)")
    parser.add_argument("--only", type=str, default=None, help="comma-separated dataset_ids")
    args = parser.parse_args()

    print(f"USGS reachable: {is_feasible()}")
    if not is_feasible():
        print("ABORT: no connectivity to earthquake.usgs.gov from this environment.")
        sys.exit(1)

    manifest = pd.read_csv(MANIFEST_PATH)
    ids = manifest["dataset_id"].tolist()
    if args.only:
        wanted = set(args.only.split(","))
        ids = [i for i in ids if i in wanted]

    print(f"{len(ids)} candidate datasets. apply={args.apply}")
    total_tsunami = total_mmi = 0
    for dataset_id in ids:
        r = enrich_one(dataset_id, args.apply)
        print(f"  {dataset_id}: {r['status']}")
        total_tsunami += r.get("n_tsunami_filled", 0) or 0
        total_mmi += r.get("n_mmi_filled", 0) or 0

    print(f"\nTotals: tsunami_flag filled={total_tsunami}, mmi filled={total_mmi}")
    if not args.apply:
        print("(dry-run -- re-run with --apply to write changes)")


if __name__ == "__main__":
    main()
