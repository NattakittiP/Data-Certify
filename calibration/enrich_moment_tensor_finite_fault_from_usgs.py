# -*- coding: utf-8 -*-
"""
calibration/enrich_moment_tensor_finite_fault_from_usgs.py -- Backfill
seismic_moment_n_m (P6), and where available rupture_length_km /
rupture_area_km2 / rupture_displacement_m / mechanism (P5), for
USGS-sourced datasets in datasets/, using USGS's own per-event
"moment-tensor" and "finite-fault" PRODUCTS.

v2 CHANGES (after a real run showed this was much slower than expected):
  1. GLOBAL, CROSS-DATASET, CROSS-RUN CACHE (calibration/_mt_ff_cache.json)
     keyed by event_uid_source. The corpus's "corrupted" datasets are
     derived from "real" ones by jittering/duplicating/etc. and mostly
     KEEP THE SAME event_uid_source values as their parent -- v1 refetched
     every one of those ids from scratch per dataset, redundantly. The
     cache makes every event_uid_source cost at most one HTTP request
     ever, across the whole corpus and across every future run. Includes
     a "MISS" sentinel so events confirmed to have neither product are
     also cached (not re-fetched every run).
  2. --categories real (DEFAULT): only the manifest's category=="real"
     rows are processed by default. "corrupted"/"fabricated" derivatives
     mostly reuse ids already in the cache from their real parent, so
     skipping them by default avoids redundant work; pass
     --categories real,corrupted,fabricated to force-include them once
     the cache is warm (cheap at that point -- pure cache hits).
  3. --max-per-dataset (default 300), candidates sorted by magnitude
     DESCENDING before truncating. Calibration only needs enough
     observations to clear EWM's n_obs>=20 threshold, not literally
     every M>=min-mag event in a 20,000-event catalog -- and larger
     events are more likely to actually HAVE a moment-tensor/finite-fault
     product anyway, so sorting by magnitude first also improves yield
     per request, not just bounds total time.
  4. Incremental checkpointing: the cache is flushed to disk every 25
     fetches (not just at the very end), and records.csv is now
     rewritten every 100 processed candidates within a large dataset
     (still behind the same backup-once contract), so interrupting a
     long-running dataset (e.g. real_earthquake1, ~23k rows) loses at
     most a small, bounded amount of progress instead of the entire
     dataset's work.

v3 FIX (found during a "does this have downsides" self-review, before
any real run hit it -- not from a reported failure): fetch_products_raw
used to collapse two very different situations into the same {} return
value: (a) the fetch SUCCEEDED and the event genuinely has neither
product, and (b) the fetch FAILED (timeout / network error / bad JSON).
The cache then stored BOTH as the same permanent "MISS" sentinel. That
meant one momentary USGS hiccup would silently and PERMANENTLY poison
that event id in the cache as "no moment tensor", forever suppressing
real data for it on every future run, with no visible symptom other
than a slightly lower yield count. Fixed by having fetch_products_raw
return None (not {}) on failure, and having Fetcher.get() only cache
confirmed-empty ({}) results -- a None is left uncached so a later run
retries it. See Fetcher.n_transient_failures in the final summary line.

Confirmed field mapping (verified against a real event, us6000m0xl, the
2024 Noto Peninsula M7.5 already in this corpus -- see git history /
conversation log for the raw fetch if you need to re-derive this):
  moment-tensor.properties["scalar-moment"]  -> seismic_moment_n_m
      Already in SI units (N.m), NOT dyne-cm -- verified against
      Hanks-Kanamori for that one event (predicted ~2.24e20 N.m vs
      USGS-reported 2.27E+20). Disclosed: verified against exactly ONE
      event; if a different event's value looks off by ~1e7x, STOP.
  moment-tensor.properties["nodal-plane-1-rake"] -> mechanism, via the
      standard rake-angle convention, bucketed into the 3 mechanisms
      axis_plausibility.py's P5_WC_COEFFICIENTS already supports:
        -45<=rake<=45 or |rake|>=135 -> "strike-slip"
        45<rake<135                  -> "reverse"
        -135<rake<-45                -> "normal"
      Disclosed simplification (oblique mechanisms bucketed to nearest
      pure type). Only applied when dataset.mechanism is blank/unknown.
  finite-fault.properties["model-length"]           -> rupture_length_km
  finite-fault.properties["model-length"] * ["model-width"]
                                                       -> rupture_area_km2
  finite-fault.properties["maximum-slip"]           -> rupture_displacement_m

EXPECTED YIELD IS ASYMMETRIC: moment-tensor products exist for most
M>=5.0 events globally (P6 should gain plenty of observations).
finite-fault products only exist for major, well-instrumented
earthquakes (roughly M>=6.5, and only a fraction of those) -- expect
rupture_length_km (P5) to gain at most a handful. That is a property of
how sparse finite-fault modeling is worldwide, not a bug here.

DISCLOSED RESIDUAL LIMITATIONS (asked directly, answering honestly):
  - --categories real (default) means corrupted/fabricated datasets'
    OWN records.csv files are NOT enriched by a default run -- their
    event ids may be warm in the cache, but each dataset's file is only
    written when enrich_one() runs against IT specifically. If you want
    those enriched too (e.g. to sanity-check P5/P6 on a corrupted
    dataset), run again with --categories real,corrupted,fabricated;
    it will be cheap once the cache is warm.
  - --max-per-dataset caps very large real datasets (e.g. real_earthquake1)
    to their top-N-by-magnitude events rather than every M>=min-mag
    event. This introduces a real, disclosed asymmetry: datasets small
    enough to finish under the cap get full M>=5 coverage; datasets that
    hit the cap get a magnitude-biased subsample. P6's underlying check
    (Mw vs M0 consistency) is a physical relationship that should not
    itself depend on magnitude, so this is unlikely to bias the
    calibration's conclusions, but it is a real deviation from "as much
    real data as possible" and is disclosed here rather than left silent.
  - The cache has no expiry. USGS occasionally revises a moment-tensor
    solution after initial review; a value cached today will not
    auto-refresh if USGS later revises it. For a one-time calibration
    snapshot (which is what corpus_manifest.csv already represents) this
    is arguably the right behavior, not a bug -- but it means the cache
    is not "live" and should be deleted (or an event's key removed) if a
    genuine re-check against current USGS data is ever needed.

Safety: --dry-run by default. --apply backs up records.csv to
records.csv.bak_pre_mt_enrich before the FIRST write (never overwritten
on later runs) and never touches a row whose target field is already
populated -- so this script is safely resumable: re-running after a
Ctrl+C just picks up wherever the on-disk records.csv/cache left off.

Network note: requires real outbound HTTPS to earthquake.usgs.gov.
Confirmed NOT reachable from the Claude sandbox's bash tool (allowlist
proxy blocks it). Must be run on your own machine (confirmed working).

Usage:
    python3 calibration/enrich_moment_tensor_finite_fault_from_usgs.py --apply
    python3 calibration/enrich_moment_tensor_finite_fault_from_usgs.py --apply --categories real,corrupted,fabricated
    python3 calibration/enrich_moment_tensor_finite_fault_from_usgs.py --only real_earthquake1 --apply --max-per-dataset 500
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"
DATASETS_DIR = ROOT / "datasets"
CACHE_PATH = Path(__file__).resolve().parent / "_mt_ff_cache.json"

USGS_DETAIL_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USGS_COUNT_URL = "https://earthquake.usgs.gov/fdsnws/event/1/count"
_USER_AGENT = "data-certify-p5-p6-enrichment/0.2"
TIMEOUT_SEC = 15.0
DEFAULT_MIN_MAG = 5.0
DEFAULT_RATE_LIMIT_SEC = 0.25  # ~4 req/sec
DEFAULT_MAX_PER_DATASET = 300
CACHE_FLUSH_EVERY = 25
CSV_FLUSH_EVERY = 100
_MISS = "__MISS__"


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


def classify_mechanism(rake_deg: float) -> str:
    r = ((rake_deg + 180.0) % 360.0) - 180.0
    if -45.0 <= r <= 45.0 or r >= 135.0 or r <= -135.0:
        return "strike-slip"
    elif 45.0 < r < 135.0:
        return "reverse"
    else:
        return "normal"


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")


def fetch_products_raw(event_id: str) -> dict | None:
    """Uncached fetch.
    Returns {} if the fetch SUCCEEDED and the event genuinely has neither
    product (a confirmed, cacheable-forever negative).
    Returns None if the fetch itself FAILED (network error, timeout, bad
    JSON) -- a transient failure that must NOT be permanently cached as
    "no product", or a momentary USGS outage would silently and forever
    starve that one event of real data. Callers must treat None as
    "try again another time", not as a confirmed miss."""
    params = {"eventid": event_id, "format": "geojson"}
    url = f"{USGS_DETAIL_URL}?{urllib.parse.urlencode(params)}"
    raw = _get(url)
    if raw is None:
        return None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    products = (payload.get("properties") or {}).get("products") or {}
    out: dict = {}

    mt_list = products.get("moment-tensor")
    if mt_list:
        p = mt_list[0].get("properties", {})
        try:
            scalar_moment = float(p["scalar-moment"])
        except (KeyError, ValueError, TypeError):
            scalar_moment = None
        rake = None
        try:
            rake = float(p.get("nodal-plane-1-rake"))
        except (TypeError, ValueError):
            pass
        if scalar_moment is not None:
            out["moment_tensor"] = {
                "seismic_moment_n_m": scalar_moment,
                "mechanism": classify_mechanism(rake) if rake is not None else None,
            }

    ff_list = products.get("finite-fault")
    if ff_list:
        p = ff_list[0].get("properties", {})
        try:
            length = float(p["model-length"])
            width = float(p["model-width"])
            out["finite_fault"] = {
                "rupture_length_km": length,
                "rupture_area_km2": length * width,
            }
            if "maximum-slip" in p:
                out["finite_fault"]["rupture_displacement_m"] = float(p["maximum-slip"])
        except (KeyError, ValueError, TypeError):
            pass

    return out


class Fetcher:
    """Wraps fetch_products_raw with a persistent, periodically-flushed
    cache keyed by event_uid_source."""

    def __init__(self, rate_limit_sec: float):
        self.cache = load_cache()
        self.rate_limit_sec = rate_limit_sec
        self._since_flush = 0
        self.n_hits = 0
        self.n_misses_cached = 0
        self.n_fetched = 0
        self.n_transient_failures = 0

    def get(self, event_id: str) -> dict:
        if event_id in self.cache:
            self.n_hits += 1
            cached = self.cache[event_id]
            return {} if cached == _MISS else cached

        products = fetch_products_raw(event_id)
        time.sleep(self.rate_limit_sec)
        self.n_fetched += 1

        if products is None:
            # Transient network/parse failure -- do NOT cache. Caching this
            # as a permanent miss would mean one momentary USGS hiccup
            # silently and forever starves this event of real data on every
            # future run. Leave it uncached so a later run retries it.
            self.n_transient_failures += 1
            return {}

        self.cache[event_id] = products if products else _MISS
        self._since_flush += 1
        if self._since_flush >= CACHE_FLUSH_EVERY:
            save_cache(self.cache)
            self._since_flush = 0
        return products

    def flush(self) -> None:
        save_cache(self.cache)
        self._since_flush = 0


def enrich_one(dataset_id: str, apply: bool, min_mag: float,
               max_per_dataset: int, fetcher: Fetcher) -> dict:
    ds_dir = DATASETS_DIR / dataset_id
    csv_path = ds_dir / "records.csv"
    if not csv_path.exists():
        return {"dataset_id": dataset_id, "status": "SKIP (no records.csv)"}

    df = pd.read_csv(csv_path)
    if "event_uid_source" not in df.columns or df["event_uid_source"].isna().all():
        return {"dataset_id": dataset_id, "status": "SKIP (no event_uid_source populated)"}

    for col, default in [("seismic_moment_n_m", float("nan")), ("mechanism", ""),
                          ("rupture_length_km", float("nan")),
                          ("rupture_area_km2", float("nan")),
                          ("rupture_displacement_m", float("nan"))]:
        if col not in df.columns:
            df[col] = default
    df["mechanism"] = df["mechanism"].astype(object)

    mag = pd.to_numeric(df["magnitude"], errors="coerce")
    cand_mask = (mag >= min_mag) & df["event_uid_source"].notna() & df["seismic_moment_n_m"].isna()
    candidates = df.index[cand_mask].tolist()
    # prioritize the largest events first -- more likely to have products,
    # and bounds total time if max_per_dataset truncates the list.
    candidates.sort(key=lambda i: -mag[i])
    if max_per_dataset:
        candidates = candidates[:max_per_dataset]

    if not candidates:
        return {"dataset_id": dataset_id, "status": f"SKIP (no M>={min_mag} candidates needing enrichment)"}

    n_mt = n_ff = n_mech = 0
    backed_up = False
    for k, i in enumerate(candidates):
        eid = df.at[i, "event_uid_source"]
        products = fetcher.get(eid)

        mt = products.get("moment_tensor")
        if mt:
            df.at[i, "seismic_moment_n_m"] = mt["seismic_moment_n_m"]
            n_mt += 1
            current_mech = df.at[i, "mechanism"]
            mech_is_blank = pd.isna(current_mech) or str(current_mech).strip() == ""
            if mt.get("mechanism") and mech_is_blank:
                df.at[i, "mechanism"] = mt["mechanism"]
                n_mech += 1

        ff = products.get("finite_fault")
        if ff and pd.isna(df.at[i, "rupture_length_km"]):
            df.at[i, "rupture_length_km"] = ff["rupture_length_km"]
            df.at[i, "rupture_area_km2"] = ff["rupture_area_km2"]
            if "rupture_displacement_m" in ff:
                df.at[i, "rupture_displacement_m"] = ff["rupture_displacement_m"]
            n_ff += 1

        if apply and (k + 1) % CSV_FLUSH_EVERY == 0 and (n_mt or n_ff):
            backup_path = ds_dir / "records.csv.bak_pre_mt_enrich"
            if not backed_up and not backup_path.exists():
                shutil.copy2(csv_path, backup_path)
                backed_up = True
            df.to_csv(csv_path, index=False)

    status = (f"checked {len(candidates)} M>={min_mag} candidates "
              f"(cache: {fetcher.n_hits} hits so far this run); "
              f"moment_tensor={n_mt} finite_fault={n_ff} mechanism_filled={n_mech}")

    if apply and (n_mt or n_ff):
        backup_path = ds_dir / "records.csv.bak_pre_mt_enrich"
        if not backup_path.exists():
            shutil.copy2(csv_path, backup_path)
        df.to_csv(csv_path, index=False)
        status += " -- WRITTEN (backup at records.csv.bak_pre_mt_enrich)"
    elif not apply:
        status += " -- DRY RUN, nothing written"

    return {"dataset_id": dataset_id, "status": status,
            "n_moment_tensor": n_mt, "n_finite_fault": n_ff, "n_mechanism": n_mech}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--only", type=str, default=None)
    parser.add_argument("--min-mag", type=float, default=DEFAULT_MIN_MAG)
    parser.add_argument("--rate-limit-sec", type=float, default=DEFAULT_RATE_LIMIT_SEC)
    parser.add_argument("--max-per-dataset", type=int, default=DEFAULT_MAX_PER_DATASET,
                         help="0 = no cap")
    parser.add_argument("--categories", type=str, default="real",
                         help="comma-separated: real,corrupted,fabricated (default: real only)")
    args = parser.parse_args()

    print(f"USGS reachable: {is_feasible()}")
    if not is_feasible():
        print("ABORT: no connectivity to earthquake.usgs.gov from this environment.")
        sys.exit(1)

    manifest = pd.read_csv(MANIFEST_PATH)
    wanted_categories = set(args.categories.split(","))
    manifest = manifest[manifest["category"].isin(wanted_categories)]
    ids = manifest["dataset_id"].tolist()
    if args.only:
        wanted = set(args.only.split(","))
        ids = [i for i in ids if i in wanted]

    print(f"{len(ids)} candidate datasets (categories={sorted(wanted_categories)}). "
          f"apply={args.apply} min_mag={args.min_mag} max_per_dataset={args.max_per_dataset or 'unlimited'} "
          f"rate_limit={args.rate_limit_sec}s/req")

    fetcher = Fetcher(args.rate_limit_sec)
    print(f"Cache loaded: {len(fetcher.cache)} event ids already known from previous runs.")

    t_start = time.time()
    total_mt = total_ff = total_mech = 0
    try:
        for dataset_id in ids:
            r = enrich_one(dataset_id, args.apply, args.min_mag, args.max_per_dataset, fetcher)
            print(f"  {dataset_id}: {r['status']}")
            total_mt += r.get("n_moment_tensor", 0) or 0
            total_ff += r.get("n_finite_fault", 0) or 0
            total_mech += r.get("n_mechanism", 0) or 0
    finally:
        fetcher.flush()

    elapsed = time.time() - t_start
    print(f"\nTotals: moment_tensor(P6)={total_mt}, finite_fault(P5)={total_ff}, mechanism={total_mech}")
    print(f"Cache stats this run: {fetcher.n_hits} hits, {fetcher.n_fetched} live fetches "
          f"({fetcher.n_transient_failures} transient network failures, NOT cached -- "
          f"will retry on next run). Elapsed: {elapsed/60:.1f} min.")
    if not args.apply:
        print("(dry-run -- re-run with --apply to write changes)")


if __name__ == "__main__":
    main()
