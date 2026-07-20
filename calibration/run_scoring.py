# -*- coding: utf-8 -*-
"""
calibration/run_scoring.py -- Score every dataset in the calibration
corpus (calibration/corpus_manifest.csv) on all four axes AND their
individual sub-criteria, using the UNCHANGED current AHP-only scoring
functions (score_authenticity/score_plausibility/score_completeness/
score_instrumentation) called directly rather than through
DataCertifyAuditor.audit() -- a deliberate choice, not an oversight:
.audit() discards the composite score once the hard-override gate
fires (trust_score becomes None -- see decision.py's CertifyResult
docstring), but EWM (task #48) needs the RAW per-criterion score for
every dataset regardless of hard-override status, since a
hard-override-triggering dataset is exactly the kind of extreme,
informative "known-bad" data point EWM's entropy calculation benefits
from including. hard_override status and the CURRENT (AHP-only) T(D)
are still recorded per dataset, purely as diagnostic context alongside
the raw scores.

Output: calibration/score_matrix.csv, one row per dataset, with columns
for every axis-level score and every individual A1-A6/P4-P9/C1-C4/I1-I5
sub-criterion score. Results are appended incrementally (flushed after
every dataset) so a run interrupted partway through -- large catalogs
(chile, usgs_main, and their corrupted derivatives) take several
seconds each, so a full corpus run is expected to be chunked across
several invocations -- can be resumed without re-scoring datasets
already completed.

Usage:
    python3 calibration/run_scoring.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import math

from data_certify.schema import load_dataset_csv
from data_certify.axis_authenticity import score_authenticity
from data_certify.axis_plausibility import score_plausibility
from data_certify.axis_completeness import score_completeness
from data_certify.axis_instrumentation import score_instrumentation
from data_certify.decision import CertifyDecision
from data_certify.hard_override import check_hard_override
from data_certify._constants import (
    WITHIN_A, WITHIN_P, WITHIN_C, WITHIN_I, AXIS_WEIGHTS, THETA_ADMIT, THETA_REJECT,
)
from data_certify.reference_data import GEMActiveFaultsDatabase, default_gem_geojson_path

MANIFEST_PATH = Path(__file__).resolve().parent / "corpus_manifest.csv"
SCORE_MATRIX_PATH = Path(__file__).resolve().parent / "score_matrix.csv"

# P8 (plate-boundary proximity) FIX (2026-07-06): this script previously
# called score_plausibility(ds) with no fault_db, so P8 defaulted to
# NullFaultDatabase (is_available()=False) for all 73 corpus datasets --
# exactly the same "never wired up" gap A6 had before the 2026-07-05
# investigation, and the reason P8/P9 show 0/73 observations in
# ewm_report.json and RETAIN their exact AHP prior. Unlike A6, P8 needs NO
# live network call -- the real GEM Global Active Faults Database ships
# bundled locally under Dataset/GAF-DB/ (see reference_data.py's module
# docstring) -- so there is no reason not to wire it in. Loaded ONCE at
# import time (not per-dataset inside score_one) since the harmonized
# GeoJSON is ~10 MB / ~13,700 faults and re-parsing it 73 times would be
# needlessly slow; distance queries themselves are grid-indexed and cheap
# per dataset (see GEMActiveFaultsDatabase's own docstring).
_GEM_PATH = default_gem_geojson_path()
FAULT_DB = GEMActiveFaultsDatabase(_GEM_PATH) if _GEM_PATH else None
if FAULT_DB is not None and not FAULT_DB.is_available():
    print(f"WARNING: GEM fault DB at {_GEM_PATH} failed to load "
          f"({FAULT_DB.load_error}) -- P8 will remain unavailable (0 obs).")
    FAULT_DB = None
elif FAULT_DB is None:
    print("WARNING: no bundled GEM fault DB found under Dataset/GAF-DB/ -- "
          "P8 will remain unavailable (0 obs).")
else:
    print(f"P8 fault reference: {_GEM_PATH} ({FAULT_DB.n_points} indexed trace points)")

SUB_CRITERIA = {
    "A": list(WITHIN_A.keys()),
    "P": list(WITHIN_P.keys()),
    "C": list(WITHIN_C.keys()),
    "I": list(WITHIN_I.keys()),
}


def score_one(dataset_id: str) -> dict:
    ds_path = ROOT / "datasets" / dataset_id / "records.csv"
    ds = load_dataset_csv(ds_path, name=dataset_id)

    a_result = score_authenticity(ds)
    p_result = score_plausibility(ds, fault_db=FAULT_DB)
    c_result = score_completeness(ds)
    i_result = score_instrumentation(ds)

    row = {
        "dataset_id": dataset_id, "n_records": ds.n,
        "A": a_result.score, "P": p_result.score, "C": c_result.score, "I": i_result.score,
    }
    for axis_letter, axis_result in (("A", a_result), ("P", p_result), ("C", c_result), ("I", i_result)):
        for crit in SUB_CRITERIA[axis_letter]:
            sub = axis_result.sub_results.get(crit)
            row[crit] = sub.score if (sub is not None and sub.applicable) else float("nan")

    # PERFORMANCE FIX (2026-07-06): this previously called
    # DataCertifyAuditor(fault_db=FAULT_DB).audit(ds) here, which re-runs
    # score_authenticity/score_plausibility/score_completeness/
    # score_instrumentation from scratch (see decision.py's audit(), lines
    # ~249-254) -- i.e. every dataset was scored TWICE. That was cheap
    # enough before P8 was wired in, but once P8's real GEM fault-DB grid
    # search (task #81) was added, the corpus's largest catalogs (chile
    # ~133k rows; the *_inject_duplicates_high variants ~96k-124k rows)
    # take 20-45s for a single A+P+C+I pass, and doubling that blew past
    # the sandbox's 45-second-per-shell-call budget with zero partial
    # progress recorded (score_matrix.csv is only flushed once score_one()
    # returns). Fixed by replicating audit()'s POST-scoring logic (the
    # Stage-1 hard-override gate + Stage-2 AHP composite, decision.py lines
    # 249-330) directly from the a_result/p_result/c_result/i_result
    # already computed above, instead of re-scoring. check_hard_override()
    # itself still cheaply recomputes P1-P3 masks internally (vectorised
    # numpy, not the P8 grid search) -- only the four expensive
    # score_<axis>() calls are avoided.
    try:
        axis_results = {"A": a_result, "P": p_result, "C": c_result, "I": i_result}

        a6_sub = a_result.sub_results.get("A6")
        a6_matched_fraction = None
        a6_n_stratum = None
        if a6_sub is not None and a6_sub.applicable:
            a6_matched_fraction = a6_sub.detail.get("matched_fraction")
            a6_n_stratum = a6_sub.detail.get("n_stratum")

        hard_override = check_hard_override(
            ds, a6_matched_fraction=a6_matched_fraction, a6_n_stratum=a6_n_stratum,
        )

        if hard_override.fired:
            row["hard_override_fired"] = True
            row["trust_score_ahp_only"] = float("nan")
            row["decision_ahp_only"] = CertifyDecision.REJECT.value
        else:
            applicable_axes = {k: v for k, v in axis_results.items() if not math.isnan(v.score)}
            if not applicable_axes:
                trust_score = float("nan")
            else:
                w_sum = sum(AXIS_WEIGHTS[k] for k in applicable_axes)
                trust_score = sum(AXIS_WEIGHTS[k] * v.score for k, v in applicable_axes.items()) / w_sum

            if math.isnan(trust_score):
                decision = CertifyDecision.REJECT
            elif trust_score >= THETA_ADMIT:
                decision = CertifyDecision.ADMIT
            elif trust_score >= THETA_REJECT:
                decision = CertifyDecision.CONDITIONAL
            else:
                decision = CertifyDecision.REJECT

            row["hard_override_fired"] = False
            row["trust_score_ahp_only"] = trust_score
            row["decision_ahp_only"] = decision.value
    except Exception as e:
        row["hard_override_fired"] = None
        row["trust_score_ahp_only"] = float("nan")
        row["decision_ahp_only"] = f"ERROR: {e}"

    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    manifest = pd.read_csv(MANIFEST_PATH)

    existing = None
    done_ids = set()
    if SCORE_MATRIX_PATH.exists():
        existing = pd.read_csv(SCORE_MATRIX_PATH)
        done_ids = set(existing["dataset_id"])
        print(f"Resuming: {len(done_ids)} datasets already scored.")

    todo = [r for r in manifest["dataset_id"] if r not in done_ids]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(todo)} datasets to score this run.")

    new_rows = []
    for i, dataset_id in enumerate(todo):
        try:
            row = score_one(dataset_id)
            new_rows.append(row)
            print(f"[{i+1}/{len(todo)}] OK {dataset_id} n={row['n_records']} "
                  f"A={row['A']:.3f} P={row['P']:.3f} C={row['C']:.3f} I={row['I']:.3f}")
        except Exception as e:
            print(f"[{i+1}/{len(todo)}] FAILED {dataset_id}: {type(e).__name__}: {e}")
            traceback.print_exc()

        if existing is not None:
            combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        else:
            combined = pd.DataFrame(new_rows)
        combined.to_csv(SCORE_MATRIX_PATH, index=False)

    total = len(pd.read_csv(SCORE_MATRIX_PATH)) if SCORE_MATRIX_PATH.exists() else 0
    print(f"Score matrix written -> {SCORE_MATRIX_PATH} ({total} total rows)")


if __name__ == "__main__":
    main()
