# -*- coding: utf-8 -*-
"""
calibration/run_a6_scoring.py -- Score A6 (external catalog
cross-validation) for every dataset in the calibration corpus, using a
REAL, live external reference -- unlike calibration/run_scoring.py,
which always calls score_authenticity(ds) with reference=None
(NullExternalCatalog), so A6 was never exercised anywhere in the
existing score_matrix.csv / threshold_report.md.

This closes that gap: theta_auth (currently 0.50, explicitly disclosed
as "not calibrated" in threshold_report.md) needs a real matched_fraction
distribution over known_good vs known_bad datasets to be calibrated the
same way theta_admit/theta_reject already were.

v2: added --reference-source, reusing run_audit.py's own
_build_reference() helper (same {usgs,emsc,isc,multi,weighted-multi}
options, same --min-corroborating-sources / --default-mc-ref-weight-discount
knobs) instead of hardcoding USGSComCatReference.

WHY THIS WAS ADDED: the first full run (USGS-only) surfaced a real,
important finding -- two known_good real datasets, "chile" (CSN Chile
national network) and "nz" (GeoNet New Zealand national network), scored
matched_fraction 0.0 and 0.355 respectively against USGS ComCat alone.
Both are below the current theta_auth=0.50 (chile is EXACTLY 0.0, tied
with several confirmed-fabricated datasets in the SAME corpus -- there
is no threshold that admits chile without also admitting fabricated
data). This is not a threshold-tuning problem; it looks like a genuine
gap in relying on a single global reference catalog for national-network
sourced data (USGS's own catalog is not guaranteed complete for every
country's locally-detected M4+ events). Before concluding theta_auth
simply cannot be calibrated, the natural next test is whether an
organizationally-independent SECOND source (EMSC) -- which may have
better regional coverage via its own network of contributing agencies --
resolves the false positive. Output is written to a reference-source-
specific file (score_matrix_a6_<source>.csv) so this diagnostic run
never overwrites or gets confused with the original USGS-only results.

Output: calibration/score_matrix_a6_<source>.csv, one row per dataset:
  dataset_id, label, n_records, a6_applicable, matched_fraction,
  n_stratum, mc_ref, mc_ref_is_default, hard_reject_would_fire,
  n_corroborated, n_contradicted_eligible, n_unverifiable,
  contradicted_confirmed, contradicted_p_value, hard_reject_reason, note

v3 (Group C3, 2026-07-12): added the three-state columns above (see
data_certify/axis_authenticity.py's _score_a6_external() docstring and
data_certify/_constants.py's A6_CONTRADICTED_* block). To actually
exercise the "Externally contradicted" path (which now requires
A6_CONTRADICTED_MIN_SOURCES=2 independent sources), run with
`--reference-source multi --min-corroborating-sources 1` (or
`weighted-multi`) against >=2 sources -- a single-source run
(the default) can now only ever produce "corroborated" or
"unverifiable", never "contradicted", by design. See
calibration/calibrate_a6_three_state.py for the downstream analysis of
this script's output.

Resumable: appends incrementally, skips dataset_ids already present in
that source's own output file.

Usage:
    python3 calibration/run_a6_scoring.py                           # USGS (default), full corpus
    python3 calibration/run_a6_scoring.py --only chile,nz --reference-source emsc
    python3 calibration/run_a6_scoring.py --reference-source multi --min-corroborating-sources 1
    python3 calibration/run_a6_scoring.py --reference-source weighted-multi
"""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify.schema import load_dataset_csv
from data_certify.axis_authenticity import score_authenticity
from run_audit import _build_reference

MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"


def out_path_for(reference_source: str) -> Path:
    suffix = "" if reference_source == "usgs" else f"_{reference_source}"
    return Path(__file__).resolve().parent / f"score_matrix_a6{suffix}.csv"


# Per-dataset wall-clock cap on the A6 external-reference lookup (2026-07-13,
# live-run finding, see conversation log same date): under
# --reference-source multi, each of USGS/EMSC/ISC gets its OWN separate
# _PAGINATION_MAX_TOTAL_REQUESTS=500-request budget (data_certify/
# reference_data.py) -- these are NOT shared across sources. A dataset that
# triggers a known EMSC/ISC pagination pathology (a source returning a
# bogus "still over the 20000-event cap" response for a physically
# implausible narrow/old query window, instead of a genuine result) can
# burn its FULL budget on EACH of the 3 sources, compounded by HTTP retry
# backoff on failures -- observed LIVE to take 5+ hours for a single
# dataset (real_nankai_historical, just 13 records but a 684-1946 AD span)
# before being manually interrupted, and separately observed on
# real_usgs_current (a perfectly ordinary, narrow, MODERN 2022 dataset)
# against ISC specifically -- i.e. this is not limited to the handful of
# multi-century datasets identified earlier; any dataset can trigger it if
# a source is currently degraded/rate-limited. Rather than hand-maintaining
# a per-dataset skip-list (fragile, and does not generalize to a source
# having a bad day for an otherwise-ordinary dataset), this wraps
# score_one() in a wall-clock timeout: well-behaved datasets observed live
# so far range from ~4s to ~440s (the largest, "chile", 132,964 records) --
# SCORE_ONE_TIMEOUT_SEC=600 comfortably covers every legitimate case seen
# while cutting the pathological multi-hour case down to at most 10
# minutes before moving on. This is a calibration-script-only change -- no
# production code (data_certify/reference_data.py, axis_authenticity.py)
# is touched.
SCORE_ONE_TIMEOUT_SEC = 600


def _timed_out_row(dataset_id: str, label: str, timeout_sec: float) -> dict:
    return {
        "dataset_id": dataset_id, "label": label, "n_records": None,
        "a6_applicable": False, "matched_fraction": float("nan"),
        "n_stratum": 0, "mc_ref": float("nan"), "mc_ref_is_default": None,
        "hard_reject_would_fire": False,
        "n_corroborated": None, "n_contradicted_eligible": None,
        "n_unverifiable": None, "contradicted_confirmed": None,
        "contradicted_p_value": None, "hard_reject_reason": None,
        "elapsed_sec": round(timeout_sec, 2),
        "note": (f"SKIPPED (timeout): A6 external-reference lookup did not complete "
                 f"within {timeout_sec:.0f}s -- almost certainly the known EMSC/ISC "
                 f"'bogus over-cap response for old/rate-limited queries' pagination "
                 f"pathology (see conversation 2026-07-13), not a genuine A6 result. "
                 f"Needs separate investigation; not evaluated here."),
    }


def score_one_with_timeout(dataset_id: str, label: str, reference,
                            timeout_sec: float = SCORE_ONE_TIMEOUT_SEC) -> dict:
    """Wraps score_one() in a wall-clock timeout -- see SCORE_ONE_TIMEOUT_SEC's
    module-level comment for the full motivation.

    TWO bugs found while testing this fix (2026-07-13), both confirmed live
    with a synthetic 30s-sleep task and timeout_sec=2:

    (1) Using `ThreadPoolExecutor` as a context manager (`with ... as ex:`)
        does NOT actually give up after `timeout_sec` -- `Executor.__exit__`
        calls `shutdown(wait=True)`, which BLOCKS until every submitted
        task finishes, regardless of whether `fut.result(timeout=...)`
        already raised `TimeoutError` and control is in the `except` block
        trying to return. First attempted fix: stopped using the executor
        as a context manager and called `shutdown(wait=False)` explicitly
        instead. This made THIS FUNCTION return promptly (confirmed:
        returned in 2.00s as expected) -- but exposed bug (2):

    (2) `ThreadPoolExecutor`'s worker threads are NOT daemon threads by
        default. Even though this function itself returned promptly and
        the calling loop in main() correctly moved on to the next dataset
        immediately, the abandoned 30s-sleep thread was still alive and
        NON-daemon, so the Python INTERPRETER refused to fully exit at the
        end of the script until that thread (and every other orphaned one
        accumulated across the whole run) finished -- confirmed live: the
        wrapped call returned in 2.00s and the calling script's own
        subsequent print statements executed immediately, yet the process
        itself still hung past a 15s external `timeout` wrapper.
        Fixed by switching from `ThreadPoolExecutor` to a raw
        `threading.Thread(daemon=True)` + a 1-slot `queue.Queue` to carry
        the result back: daemon threads do NOT block interpreter exit --
        Python abruptly discards them when the main thread finishes,
        which is exactly the "abandon it" behavior this wrapper is
        supposed to have, both mid-run (so the loop keeps moving) AND at
        the very end (so the script's final "written -> ... total rows"
        summary is followed by a normal, prompt exit instead of an
        indefinite-feeling hang while orphaned threads are reaped).
    """
    result_q: "queue.Queue" = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_q.put(("ok", score_one(dataset_id, label, reference)))
        except Exception as exc:  # surface the real error, not silence it
            result_q.put(("error", exc))

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join(timeout=timeout_sec)
    if t.is_alive():
        # Still running past the deadline -- abandon it (daemon thread,
        # will not block process exit) and report a timeout row.
        return _timed_out_row(dataset_id, label, timeout_sec)
    status, payload = result_q.get_nowait()
    if status == "error":
        raise payload
    return payload


def score_one(dataset_id: str, label: str, reference) -> dict:
    ds_path = ROOT / "datasets" / dataset_id / "records.csv"
    ds = load_dataset_csv(ds_path, name=dataset_id)

    t0 = time.time()
    a_result = score_authenticity(ds, reference=reference)
    elapsed = time.time() - t0

    a6 = a_result.sub_results.get("A6")
    detail = (a6.detail or {}) if (a6 is not None and a6.applicable) else {}

    return {
        "dataset_id": dataset_id,
        "label": label,
        "n_records": ds.n,
        "a6_applicable": bool(a6.applicable) if a6 is not None else False,
        "matched_fraction": detail.get("matched_fraction", float("nan")),
        "n_stratum": detail.get("n_stratum", 0),
        "mc_ref": detail.get("mc_ref", float("nan")),
        "mc_ref_is_default": detail.get("mc_ref_is_default", None),
        "hard_reject_would_fire": bool(a_result.hard_reject),
        # Group C3 (2026-07-12) three-state fields -- see
        # data_certify/axis_authenticity.py's _score_a6_external() docstring.
        # n_stratum above is now the ORIGINAL magnitude-based stratum size;
        # n_corroborated + n_contradicted_eligible + n_unverifiable sums to
        # it. contradicted_confirmed is the dataset-level statistical
        # verdict that (combined with n_contradicted_eligible>0) drives
        # hard_reject_would_fire.
        "n_corroborated": detail.get("n_corroborated", None),
        "n_contradicted_eligible": detail.get("n_contradicted_eligible", None),
        "n_unverifiable": detail.get("n_unverifiable", None),
        "contradicted_confirmed": detail.get("contradicted_confirmed", None),
        "contradicted_p_value": detail.get("contradicted_p_value", None),
        "hard_reject_reason": a_result.hard_reject_reason,
        "elapsed_sec": round(elapsed, 2),
        "note": (a6.note if a6 is not None else "no A6 sub-result"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--only", type=str, default=None,
                         help="comma-separated list of dataset_ids to run (for pilot testing)")
    parser.add_argument("--reference-source", type=str, default="usgs",
                         choices=["usgs", "emsc", "isc", "multi", "weighted-multi"])
    parser.add_argument("--min-corroborating-sources", type=int, default=2,
                         help="only used with --reference-source multi")
    parser.add_argument("--default-mc-ref-weight-discount", type=float, default=0.5,
                         help="only used with --reference-source weighted-multi")
    parser.add_argument("--timeout", type=float, default=None,
                         help="per-request timeout in seconds, overriding every live "
                              "source's own default (USGS/EMSC=10s, ISC=15s). Recommended "
                              "for corpus-scale runs -- ISC's default was shown live to be "
                              "too short for large datasets (chile needed ~90s to get a "
                              "genuine, non-fallback mc_ref; see "
                              "calibration/debug_diagnostics/debug_chile_isc_emsc_gap.py). Default: None "
                              "(each source's own production default).")
    parser.add_argument("--dataset-timeout", type=float, default=SCORE_ONE_TIMEOUT_SEC,
                         help="wall-clock cap in seconds on a SINGLE dataset's whole A6 "
                              "external-reference lookup (see SCORE_ONE_TIMEOUT_SEC's "
                              "module-level comment) -- NOT the same as --timeout above, "
                              "which is a per-HTTP-request timeout. A dataset exceeding "
                              "this is recorded as 'SKIPPED (timeout)' and the run moves "
                              "on. Default: 600s. Raise this (e.g. 1200) to retry "
                              "previously-timed-out datasets with more patience -- combine "
                              "with removing their rows from the existing output CSV first "
                              "so the resumable skip-logic re-attempts them.")
    args = parser.parse_args()

    out_path = out_path_for(args.reference_source)
    manifest = pd.read_csv(MANIFEST_PATH)

    existing = None
    done_ids = set()
    if out_path.exists():
        existing = pd.read_csv(out_path)
        done_ids = set(existing["dataset_id"])
        print(f"Resuming ({out_path.name}): {len(done_ids)} datasets already scored.")

    if args.only:
        wanted = set(args.only.split(","))
        rows_todo = [r for _, r in manifest.iterrows()
                     if r["dataset_id"] in wanted and r["dataset_id"] not in done_ids]
    else:
        rows_todo = [r for _, r in manifest.iterrows() if r["dataset_id"] not in done_ids]

    if args.limit:
        rows_todo = rows_todo[:args.limit]

    print(f"{len(rows_todo)} datasets to score this run -> {out_path.name}")

    reference, label = _build_reference(
        reference_csv=None, offline=False,
        reference_source=args.reference_source,
        min_corroborating_sources=args.min_corroborating_sources,
        default_mc_ref_weight_discount=args.default_mc_ref_weight_discount,
        timeout_sec=args.timeout,
    )
    print(f"Reference: {label}")
    feasible = reference.is_feasible()
    print(f"is_feasible() = {feasible}")
    if not feasible:
        print("ABORT: reference infeasible (no connectivity). Nothing scored.")
        return

    new_rows = []
    for i, row in enumerate(rows_todo):
        dataset_id, ds_label = row["dataset_id"], row["label"]
        try:
            r = score_one_with_timeout(dataset_id, ds_label, reference,
                                        timeout_sec=args.dataset_timeout)
            new_rows.append(r)
            status = "TIMEOUT" if str(r.get("note", "")).startswith("SKIPPED (timeout)") else "OK"
            print(f"[{i+1}/{len(rows_todo)}] {status} {dataset_id} "
                  f"(label={ds_label}) matched_fraction={r['matched_fraction']} "
                  f"n_stratum={r['n_stratum']} applicable={r['a6_applicable']} "
                  f"hard_reject={r['hard_reject_would_fire']} ({r['elapsed_sec']}s)")
        except Exception as e:
            print(f"[{i+1}/{len(rows_todo)}] FAILED {dataset_id}: {type(e).__name__}: {e}")
            traceback.print_exc()
            new_rows.append({
                "dataset_id": dataset_id, "label": ds_label, "n_records": None,
                "a6_applicable": False, "matched_fraction": float("nan"),
                "n_stratum": 0, "mc_ref": float("nan"), "mc_ref_is_default": None,
                "hard_reject_would_fire": None,
                "n_corroborated": None, "n_contradicted_eligible": None,
                "n_unverifiable": None, "contradicted_confirmed": None,
                "contradicted_p_value": None, "hard_reject_reason": None,
                "elapsed_sec": None,
                "note": f"ERROR: {type(e).__name__}: {e}",
            })


        if existing is not None:
            combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        else:
            combined = pd.DataFrame(new_rows)
        combined.to_csv(out_path, index=False)

    total = len(pd.read_csv(out_path)) if out_path.exists() else 0
    print(f"{out_path.name} written -> {out_path} ({total} total rows)")


if __name__ == "__main__":
    main()
