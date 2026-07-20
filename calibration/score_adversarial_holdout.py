# -*- coding: utf-8 -*-
"""
calibration/score_adversarial_holdout.py -- Group B1 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group B): scores
the 30 held-out `datasets_adversarial/` datasets (level-10 adversarial
fabrications, deliberately tuned to game every remaining intrinsic check
simultaneously -- see calibration/adversarial_corpus_manifest.csv's notes
column) that have NEVER been scored before. These 30 datasets were
excluded from the 968-dataset calibration corpus specifically so that
weight/threshold calibration was never fit against them (avoiding a
circularity risk flagged during internal verification -- this script
produces the actual numbers to check whether that theoretical risk
manifests in practice).

Methodology: DELIBERATELY mirrors calibration/run_scoring.py's score_one()
as closely as possible, for a fair, apples-to-apples comparison against
the main corpus:
  - Same four axis-scoring functions (score_authenticity/score_plausibility/
    score_completeness/score_instrumentation), called directly (not through
    DataCertifyAuditor.audit()) so the composite score is still recorded
    even when the hard-override gate fires.
  - Same P8 fault-database wiring (GEMActiveFaultsDatabase, bundled local
    GeoJSON -- no live network call).
  - Same A6 non-wiring: run_scoring.py calls score_authenticity(ds) with
    NO `reference` argument, so A6 defaults to NullExternalCatalog()
    (infeasible) for every dataset in the 968-corpus. This script matches
    that choice exactly -- A6 is NOT wired here either. This is a
    deliberate parity decision, not an oversight: comparing "A6 off vs A6
    off" isolates what the adversarial holdout run is actually testing
    (does the current weight/threshold calibration generalize to unseen
    adversarial constructions), without conflating it with a separate
    question (does A6, when available, catch these adversarial datasets --
    a question calibration/run_a6_scoring.py's separate 88-90 dataset
    subset addresses for the main corpus, and which this script does not
    attempt to replicate for the adversarial holdout since none of these
    30 datasets have real external-catalog matches to query in the first
    place -- they are synthetic).
  - Same hard-override + composite-score post-processing logic
    (check_hard_override(), then AXIS_WEIGHTS-weighted composite with
    per-axis NaN-dropping renormalization).
  - Same resumable/incremental design (flushes after every dataset) as
    run_scoring.py, for consistency, though with only 30 datasets this is
    unlikely to matter in practice (run_scoring.py needed it because a few
    of the 968 corpus catalogs are ~100k+ records and take 20-45s each;
    every adversarial holdout dataset is ~1500 records and scores in a
    fraction of a second on unconstrained hardware -- but P8's GEM
    fault-database grid search adds real overhead too, so resumability is
    kept as a safety net regardless).

Output columns are IDENTICAL to calibration/score_matrix.csv's schema, so
`_analysis_common.load_corpus()` can concatenate the two directly. Because
this file is generated NOW (after data_certify/_constants.py's last edit),
its cached A/P/C/I/trust_score_ahp_only/decision_ahp_only columns are NOT
subject to the staleness issue documented in _analysis_common.py's
_self_check() -- but downstream scripts still recompute live via
composite_score()/assign_decision() rather than trusting them directly,
per this project's LEGACY_STALE_COLUMNS convention (consistency over
special-casing).

Usage:
    python3 calibration/score_adversarial_holdout.py [--limit N] [--fresh]

    --limit N   only score the first N not-yet-done datasets this run
    --fresh     ignore any existing score_matrix_adversarial_holdout.csv
                and rescore everything from scratch (default: resume)
"""
from __future__ import annotations

import argparse
import math
import sys
import traceback
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

CALIBRATION_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = CALIBRATION_DIR / "adversarial_corpus_manifest.csv"
SCORE_MATRIX_PATH = CALIBRATION_DIR / "score_matrix_adversarial_holdout.csv"
DATASETS_DIR = ROOT / "datasets_adversarial"

# Same P8 wiring as run_scoring.py -- see that script's own comment for why
# this is loaded once at import time rather than per-dataset.
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
    """Identical logic to run_scoring.py's score_one(), pointed at
    datasets_adversarial/ instead of datasets/, and with NO reference
    catalog wired for A6 (matching run_scoring.py's own choice for the
    main corpus -- see module docstring)."""
    ds_path = DATASETS_DIR / dataset_id / "records.csv"
    ds = load_dataset_csv(ds_path, name=dataset_id)

    a_result = score_authenticity(ds)  # reference=None -> NullExternalCatalog -> A6 off
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
    parser.add_argument("--fresh", action="store_true",
                         help="Ignore any existing output file and rescore everything.")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"FATAL: {MANIFEST_PATH} not found.", file=sys.stderr)
        sys.exit(1)
    if not DATASETS_DIR.exists():
        print(f"FATAL: {DATASETS_DIR} not found.", file=sys.stderr)
        sys.exit(1)

    manifest = pd.read_csv(MANIFEST_PATH)
    print(f"{len(manifest)} datasets in adversarial_corpus_manifest.csv.")

    existing = None
    done_ids = set()
    if SCORE_MATRIX_PATH.exists() and not args.fresh:
        existing = pd.read_csv(SCORE_MATRIX_PATH)
        done_ids = set(existing["dataset_id"])
        print(f"Resuming: {len(done_ids)} datasets already scored "
              f"(use --fresh to rescore everything).")

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
                  f"A={row['A']:.3f} P={row['P']:.3f} C={row['C']:.3f} I={row['I']:.3f} "
                  f"hard_override={row['hard_override_fired']} "
                  f"T(D)={row['trust_score_ahp_only']} decision={row['decision_ahp_only']}")
        except Exception as e:
            print(f"[{i+1}/{len(todo)}] FAILED {dataset_id}: {type(e).__name__}: {e}")
            traceback.print_exc()

        if existing is not None:
            combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        elif new_rows:
            combined = pd.DataFrame(new_rows)
        else:
            combined = None
        if combined is not None:
            combined.to_csv(SCORE_MATRIX_PATH, index=False)

    if not SCORE_MATRIX_PATH.exists():
        print("No datasets were scored -- nothing written.", file=sys.stderr)
        sys.exit(1)

    final = pd.read_csv(SCORE_MATRIX_PATH)
    print(f"\nScore matrix written -> {SCORE_MATRIX_PATH} ({len(final)} total rows)")

    # Summary report -- decision counts under the LIVE current constants
    # (recomputed via the same logic as score_one() above, since this file
    # is written by the current run and is therefore already fresh, but we
    # recompute explicitly here rather than trusting the cached column, in
    # keeping with this project's LEGACY_STALE_COLUMNS convention so this
    # script's own summary can never silently go stale if it is re-run
    # after a future _constants.py edit without a rescore).
    sys.path.insert(0, str(CALIBRATION_DIR))
    import _analysis_common as ac  # noqa: E402

    t_d = ac.composite_score(final, ac.AXIS_WEIGHTS, ac.WITHIN)
    decision = ac.assign_decision(t_d, final["hard_override_fired"])

    print("\n=== Group B1 summary: 30 held-out adversarial datasets ===")
    print(f"Decision counts (live current weights, respecting hard-override):")
    for d in ("ADMIT", "CONDITIONAL", "REJECT"):
        k = int((decision == d).sum())
        n = len(decision)
        print(f"  {d:<12s} {ac.fmt_rate_ci(k, n)}")

    n_hard_override = int(final["hard_override_fired"].fillna(False).astype(bool).sum())
    print(f"\nHard-override fired: {ac.fmt_rate_ci(n_hard_override, len(final))}")

    n_admit_or_conditional = int((decision != "REJECT").sum())
    print(
        f"\nADMIT or CONDITIONAL (i.e. NOT rejected) on adversarial-holdout "
        f"data: {ac.fmt_rate_ci(n_admit_or_conditional, len(final))}"
    )
    print(
        "\nInterpretation note: every one of these 30 datasets is a KNOWN "
        "fabrication (level 10/10, adversarially tuned to game every "
        "remaining intrinsic check simultaneously -- see "
        "adversarial_corpus_manifest.csv's notes column). A high "
        "ADMIT-or-CONDITIONAL rate here would mean the current calibration "
        "does not generalize to adversarial constructions outside the "
        "corpus it was fit on -- exactly the circularity risk this script "
        "exists to check.\n"
        "\n"
        "IMPORTANT PRE-EXISTING CONTEXT (verified against "
        "tests/test_adversarial.py -- read before interpreting the numbers "
        "above as either a surprise or a clean pass/fail): "
        "TestGraduatedFabricationLadder.test_level10_adversarial_evades_"
        "intrinsic_only_scoring already asserts, as a PASSING test in this "
        "project's current suite, that hard_override.fired is False for a "
        "level-10 adversarial catalog when A6 is off (the default, and the "
        "same configuration run_scoring.py and this script both use) -- "
        "with the test's own docstring stating in-project: 'A6 external "
        "cross-validation remains the load-bearing defense against the "
        "hardest tier, not a redundant one.' In other words, this project "
        "ALREADY predicts and documents, before this script was ever run, "
        "that the hard-override gate alone will NOT catch these 30 "
        "datasets -- so a low hard-override rate above is the EXPECTED "
        "outcome, not new information. What B1 actually adds that was NOT "
        "previously known: (1) an exact, full-30-dataset measurement of "
        "where the COMPOSITE score T(D) lands for each of them (the "
        "existing test only checks hard_override.fired on ONE synthetic "
        "example per level, not T(D), and not across the full graduated "
        "ladder's actual held-out files); (2) whether the compensatory "
        "weighting still manages to push some of them into REJECT purely "
        "via low intrinsic sub-scores even without the hard gate firing, "
        "or whether they cluster in ADMIT/CONDITIONAL as the test's own "
        "framing would predict. A high ADMIT-or-CONDITIONAL rate here "
        "should therefore be read as CONFIRMING a limitation this project "
        "already discloses (A6 is the load-bearing defense against this "
        "specific adversarial tier; intrinsic-only scoring is not), "
        "quantified for the first time at full-holdout-set scale -- not as "
        "a newly discovered flaw. It still directly answers the external "
        "review's Section 5.1 request for held-out numbers, and the paper "
        "should report both the raw rate AND this pre-existing, "
        "already-tested context together, rather than the rate alone."
    )


if __name__ == "__main__":
    main()
