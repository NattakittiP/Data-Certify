# -*- coding: utf-8 -*-
"""
calibration/benchmark_runtime.py -- Group C4.

Runtime/scalability benchmark of the DATA-CERTIFY audit pipeline
(DataCertifyAuditor.audit(), the same entry point run_audit.py uses) at
1K / 10K / 100K / 1M synthetic records, along two independent axes:

  (1) online vs offline (batch):
        "offline/batch"  -- the GEM fault database (P8) is loaded ONCE and
                             reused across every trial, exactly like
                             calibration/run_scoring.py's actual pattern
                             when scoring many datasets in one process.
        "online/live"    -- the GEM fault database is constructed FRESH for
                             every single audit call, modelling a naive
                             one-request-per-process live service that does
                             not keep a warm reference loaded between
                             requests. This isolates the fixed ~10MB
                             GeoJSON-parse cost as its own, disclosed,
                             per-request overhead rather than letting it
                             silently amortize away.

  (2) A6-enabled vs intrinsic-only:
        "intrinsic_only" -- reference=None (NullExternalCatalog fallback).
                             No network I/O at all.
        "a6_enabled"     -- reference=USGSComCatReference(), a REAL live
                             query against USGS ComCat for every trial. This
                             is genuine network I/O and is the only mode
                             that can meaningfully slow down at scale for
                             reasons other than local CPU (API latency,
                             pagination, rate limiting -- see
                             reference_data.py's module docstring for the
                             fully-disclosed pagination/retry machinery this
                             exercises).

SAFETY / RUNTIME GUARD: A6's per-record matching loop
(reference_data.py's `_match_against_reference_arrays`) is a plain Python
`for i in range(n)` loop, not vectorised -- this benchmark exists specifically
to characterise how that scales, INCLUDING poor scaling, not to hide it. To
avoid the script hanging for an unbounded time on a slow machine/connection,
each (mode, axis, size) cell is skipped, with a note, if the previous
(smaller) size in the same cell already exceeded PER_CELL_TIMEOUT_SEC --
extrapolating that the next 10x size would be prohibitive. This is a
disclosed, deliberate early-stop, not a silent gap: the report always states
exactly which cells were skipped and why.

This script does NOT touch data_certify/_constants.py, score_matrix.csv, or
corpus_manifest.csv, and does not change any calibration number -- it only
measures wall-clock time of the existing, unmodified scoring pipeline against
synthetic data generated at runtime (never written to disk, never added to
the corpus).

Usage:
    python3 calibration/benchmark_runtime.py [--sizes 1000,10000,100000,1000000]
                                              [--skip-a6] [--per-cell-timeout 300]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify.decision import DataCertifyAuditor
from data_certify.schema import ALL_FIELDS, CertifyDataset
from data_certify.reference_data import (
    GEMActiveFaultsDatabase, USGSComCatReference, default_gem_geojson_path,
)

REPORT_DIR = Path(__file__).resolve().parent / "group_c_reports"
REPORT_TXT_PATH = REPORT_DIR / "benchmark_runtime_report.txt"
REPORT_JSON_PATH = REPORT_DIR / "benchmark_runtime_report.json"

DEFAULT_SIZES = [1_000, 10_000, 100_000, 1_000_000]
PER_CELL_TIMEOUT_SEC = 300.0  # if a smaller size already exceeds this, skip larger sizes in that cell


def make_synthetic_dataset(n: int, seed: int, region: str = "california") -> CertifyDataset:
    """
    Build a schema-valid, physically-plausible-ish synthetic CertifyDataset
    of exactly `n` records, generated in-memory (never written to disk, never
    added to the corpus/manifest). Deliberately NOT run through
    calibration/corrupt.py or calibration/build_corpus.py -- this benchmark
    only needs *some* dataset of the right size and shape to time the
    scoring pipeline against, not a labeled known-good/known-bad example.

    Region is fixed to a real seismically-active bounding box (southern
    California) so that A6's live USGS query returns a realistic, non-empty
    candidate set to match against, rather than an arbitrary/empty region
    that would make A6-enabled timings look artificially fast (an empty
    reference-catalog fetch is not representative of a real audit).
    """
    rng = np.random.RandomState(seed)
    regions = {
        "california": (32.0, 36.0, -120.0, -115.0),
    }
    lat_min, lat_max, lon_min, lon_max = regions[region]

    # BUGFIX (found via the user's real 1M-record run, 2026-07-12): the
    # original generator used `rng.exponential(scale=2.0, size=n).cumsum()`,
    # whose cumulative sum grows LINEARLY with n (mean ~= n * scale days) --
    # at n=1,000,000 that is ~5,479 YEARS of synthetic catalog span, which
    # both (a) is not representative of any real catalog (more records
    # should mean denser sampling of a similar time window, not a
    # proportionally longer one) and (b) overflows/degenerates at the edges
    # of datetime64[ns]'s representable range (~1677-2262), which is exactly
    # what produced the "window 1677-09-21..2262-04-11" RuntimeWarning seen
    # in the real a6_enabled benchmark run -- A6's live USGS query ended up
    # bounded by those absurd sentinel-like dates instead of a realistic
    # window, degrading the a6_enabled timing numbers at 100K/1M (the
    # intrinsic_only numbers were NOT affected: A1/A3 only use RELATIVE
    # "days since earliest event" via origin_time_days(), never the
    # absolute date, so they were never exposed to this bug).
    # Fixed: sample n origin times UNIFORMLY within a FIXED 10-year window
    # regardless of n, sorted ascending -- span stays realistic (and safely
    # inside datetime64[ns]'s range) at every catalog size.
    start = np.datetime64("2015-01-01T00:00:00")
    window_days = 365.25 * 10
    offsets_days = np.sort(rng.uniform(0.0, window_days, size=n))
    origin_time = (start + (offsets_days * 86400).astype("timedelta64[s]")).astype("datetime64[ns]")

    latitude = rng.uniform(lat_min, lat_max, size=n)
    longitude = rng.uniform(lon_min, lon_max, size=n)
    depth_km = np.clip(rng.exponential(scale=8.0, size=n), 0.1, 700.0)
    # Gutenberg-Richter-like magnitude distribution (b~1.0) so A2 does not
    # trivially fail/NaN-out and the benchmark exercises realistic code paths.
    magnitude = 2.0 + rng.exponential(scale=1.0 / (1.0 * np.log(10)), size=n)
    magnitude = np.clip(magnitude, 0.1, 8.5)

    n_ = n
    empty_num = lambda: np.full(n_, np.nan, dtype=float)
    empty_str = lambda width: np.full(n_, "", dtype=f"<U{width}")

    return CertifyDataset(
        name=f"synthetic_benchmark_n{n}",
        n=n,
        origin_time=origin_time,
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
        magnitude=magnitude,
        magnitude_type=np.full(n, "Mw", dtype="<U16"),
        seismic_moment_n_m=empty_num(),
        tsunami_flag=empty_num(),
        mechanism=empty_str(32),
        source=np.full(n, "synthetic", dtype="<U64"),
        event_uid_source=empty_str(64),
        revision_status=empty_str(16),
        mmi=empty_num(),
        station_distance_km=empty_num(),
        rupture_length_km=empty_num(),
        rupture_area_km2=empty_num(),
        rupture_displacement_m=empty_num(),
        azimuthal_gap_deg=empty_num(),
    )


def time_one_audit(dataset: CertifyDataset, reference, fault_db) -> float:
    auditor = DataCertifyAuditor(reference=reference, fault_db=fault_db)
    t0 = time.perf_counter()
    auditor.audit(dataset)
    return time.perf_counter() - t0


def run_cell(
    mode: str,          # "offline_batch" | "online_live"
    a6_axis: str,        # "intrinsic_only" | "a6_enabled"
    sizes: List[int],
    per_cell_timeout: float,
) -> List[Dict]:
    results = []
    exceeded = False

    warm_fault_db = None
    if mode == "offline_batch":
        gem_path = default_gem_geojson_path()
        warm_fault_db = GEMActiveFaultsDatabase(gem_path) if gem_path else None
        if warm_fault_db is not None and not warm_fault_db.is_available():
            warm_fault_db = None

    warm_reference = None
    if mode == "offline_batch" and a6_axis == "a6_enabled":
        warm_reference = USGSComCatReference()

    for n in sizes:
        if exceeded:
            results.append({"n": n, "skipped": True,
                             "reason": f"previous (smaller) size in this cell already "
                                       f"exceeded PER_CELL_TIMEOUT_SEC={per_cell_timeout:.0f}s; "
                                       f"extrapolating the next size up would be prohibitive."})
            continue

        ds = make_synthetic_dataset(n, seed=20260712)

        if mode == "offline_batch":
            fault_db = warm_fault_db
            reference = warm_reference
            elapsed = time_one_audit(ds, reference=reference, fault_db=fault_db)
        else:  # online_live: fresh fault_db (and reference, if a6_enabled) per call
            gem_path = default_gem_geojson_path()
            fault_db = None
            fault_db_load_start = time.perf_counter()
            fault_db = GEMActiveFaultsDatabase(gem_path) if gem_path else None
            if fault_db is not None and not fault_db.is_available():
                fault_db = None
            fault_db_load_sec = time.perf_counter() - fault_db_load_start
            reference = USGSComCatReference() if a6_axis == "a6_enabled" else None
            t0 = time.perf_counter()
            DataCertifyAuditor(reference=reference, fault_db=fault_db).audit(ds)
            elapsed = time.perf_counter() - t0
            results_extra = {"fault_db_fresh_load_sec": fault_db_load_sec}

        row = {"n": n, "skipped": False, "elapsed_sec": elapsed,
               "records_per_sec": (n / elapsed) if elapsed > 0 else float("inf")}
        if mode == "online_live":
            row.update(results_extra)
        results.append(row)
        print(f"  [{mode}/{a6_axis}] n={n:>9,} -> {elapsed:8.3f}s "
              f"({row['records_per_sec']:,.0f} records/sec)")

        if elapsed > per_cell_timeout:
            exceeded = True
            print(f"    -> exceeded PER_CELL_TIMEOUT_SEC={per_cell_timeout:.0f}s, "
                  f"skipping larger sizes in this cell.")

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=str, default=",".join(str(s) for s in DEFAULT_SIZES))
    parser.add_argument("--skip-a6", action="store_true",
                         help="Skip the a6_enabled axis entirely (no live network calls at all).")
    parser.add_argument("--per-cell-timeout", type=float, default=PER_CELL_TIMEOUT_SEC)
    args = parser.parse_args()

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    REPORT_DIR.mkdir(exist_ok=True)

    a6_axes = ["intrinsic_only"] if args.skip_a6 else ["intrinsic_only", "a6_enabled"]

    print("=" * 100)
    print("Group C4: runtime/scalability benchmark")
    print("=" * 100)
    print(f"Sizes: {sizes}")
    print(f"Axes: online/offline x {a6_axes}")
    print(f"Per-cell timeout: {args.per_cell_timeout:.0f}s (larger sizes in a cell are skipped, "
          f"not hung on, once exceeded)")
    if "a6_enabled" in a6_axes:
        print("NOTE: a6_enabled cells make REAL live queries against USGS ComCat -- this needs "
              "network access and will be slower/more variable than intrinsic_only, by design.")
    print()

    all_results: Dict[str, Dict[str, List[Dict]]] = {}
    for mode in ["offline_batch", "online_live"]:
        all_results[mode] = {}
        for axis in a6_axes:
            print(f"--- mode={mode}, axis={axis} ---")
            all_results[mode][axis] = run_cell(mode, axis, sizes, args.per_cell_timeout)

    REPORT_JSON_PATH.write_text(json.dumps(all_results, indent=2))

    lines = ["=" * 100, "Group C4: runtime/scalability benchmark", "=" * 100, ""]
    lines.append(f"Sizes requested: {sizes}")
    lines.append("")
    for mode in all_results:
        for axis in all_results[mode]:
            lines.append(f"--- {mode} / {axis} ---")
            for row in all_results[mode][axis]:
                if row.get("skipped"):
                    lines.append(f"  n={row['n']:>9,}: SKIPPED ({row['reason']})")
                else:
                    extra = ""
                    if "fault_db_fresh_load_sec" in row:
                        extra = f" (of which fault-DB fresh-load: {row['fault_db_fresh_load_sec']:.3f}s)"
                    lines.append(f"  n={row['n']:>9,}: {row['elapsed_sec']:8.3f}s "
                                 f"({row['records_per_sec']:,.0f} records/sec){extra}")
            lines.append("")
    lines.append(
        "Reading guide: compare offline_batch vs online_live at the same n to see the fixed "
        "per-request GEM-fault-DB-load overhead (~10MB GeoJSON parse) that a naive live service "
        "would pay on every request but a batch/calibration run pays only once. Compare "
        "intrinsic_only vs a6_enabled at the same n to see A6's live-network + per-record "
        "matching-loop overhead (reference_data.py's `_match_against_reference_arrays` is an "
        "unvectorised Python loop -- this benchmark is the disclosed, honest way to see whether "
        "that matters at your deployment's expected record counts, rather than asserting it "
        "does or doesn't)."
    )
    REPORT_TXT_PATH.write_text("\n".join(lines))

    print()
    print(f"Report written to {REPORT_TXT_PATH} and {REPORT_JSON_PATH}")


if __name__ == "__main__":
    main()
