# -*- coding: utf-8 -*-
"""
tests/test_decision_score_matrix_consistency.py -- Regression guard against
the exact bug class behind the 2026-07-21 gate-awareness finding: the
calibration analysis pipeline (calibration/_analysis_common.py's
assign_decision_gated(), used by every Group-B post-hoc report, fed by
calibration/run_scoring.py's score_one(), which writes score_matrix.csv)
reconstructing a DIFFERENT decision than DataCertifyAuditor.audit() --
production -- actually reaches, for the same dataset and the same
weights/thresholds/gates.

Before 2026-07-21, `_analysis_common.assign_decision()` silently applied
ONLY Stage-1 hard-override + Stage-2 theta thresholds, omitting the two
weight-fraction safety gates and (once added) the two count-based
ADMIT-eligibility floors that DataCertifyAuditor.audit() actually applies
by default -- so every disclosed false-admit/ADMIT-rate number in the
paper's own analysis reports was computed against a DIFFERENT decision rule
than the one shipped in production. That was fixed by adding
assign_decision_gated(). As of 2026-07-23, both DataCertifyAuditor.audit()
and assign_decision_gated() (and run_scoring.py's decision_ahp_only column)
are additionally routed through the SAME shared pure functions in
data_certify/decision.py (assign_stage2_decision(),
apply_admit_eligibility_gates()) -- see CHANGELOG.md's 2026-07-23 entry.

This test is the automated guard that class of bug needed and never had:
for a handful of real bundled datasets spanning different decision outcomes,
it runs BOTH paths independently --

  (1) PRODUCTION: DataCertifyAuditor(...).audit(dataset).decision
  (2) CALIBRATION RECONSTRUCTION: calibration/run_scoring.py's score_one()
      (the ACTUAL function that writes score_matrix.csv rows -- called
      directly here, not re-implemented) feeds a one-row DataFrame into
      calibration/_analysis_common.py's composite_score() +
      assign_decision_gated() -- exactly what every Group-B report does.

-- and asserts they agree. If a future change to gate logic, gate order, or
the Stage-2 threshold rule is made in only ONE of these two code paths,
this test fails in CI immediately, rather than surfacing months later as a
paper-readiness review finding the way the original bug did.

Both paths are made P8/A6-consistent by construction (see
test_production_and_calibration_reconstruction_agree's own comments) and
run fully offline for A6 (no network dependency, deterministic in CI).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CALIBRATION_DIR = ROOT / "calibration"
if str(CALIBRATION_DIR) not in sys.path:
    sys.path.insert(0, str(CALIBRATION_DIR))

from data_certify.decision import DataCertifyAuditor  # noqa: E402
from data_certify.schema import load_dataset_csv  # noqa: E402

import _analysis_common as ac  # noqa: E402  (calibration/_analysis_common.py)

# calibration/run_scoring.py is a standalone script, not a package module
# (no __init__.py in calibration/) -- loaded via a direct module-file
# import, the same pattern calibration/run_a6_scoring.py itself already
# uses to import run_audit.py's _build_reference() from the repo root.
_spec = importlib.util.spec_from_file_location(
    "calibration_run_scoring", str(CALIBRATION_DIR / "run_scoring.py"))
_run_scoring = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_run_scoring)

DATASETS_DIR = ROOT / "datasets"

# Datasets spanning different decision paths, kept small in count so this
# stays fast in CI. "nz"/"chile" are already relied on by the existing CI
# smoke test (.github/workflows/tests.yml), so guaranteed present; the
# fabricated ones round out coverage of small-N/gate-triggering and
# likely-REJECT/hard-override paths, not just a large known-good catalog.
CANDIDATE_DATASET_IDS = [
    "nz", "chile", "fabricated_level1_1", "fabricated_naive_1",
]


def _available_dataset_ids() -> list:
    return [d for d in CANDIDATE_DATASET_IDS if (DATASETS_DIR / d / "records.csv").exists()]


@pytest.mark.parametrize("dataset_id", _available_dataset_ids())
def test_production_and_calibration_reconstruction_agree(dataset_id):
    """DataCertifyAuditor.audit() (production) and the calibration
    score_matrix.csv reconstruction path (run_scoring.score_one() ->
    _analysis_common.composite_score()+assign_decision_gated(), exactly as
    every Group-B report computes it) must reach the SAME decision for the
    same dataset, with default weights/thresholds/gates."""
    dataset_path = DATASETS_DIR / dataset_id / "records.csv"
    dataset = load_dataset_csv(dataset_path, name=dataset_id)

    # -- (2) CALIBRATION RECONSTRUCTION FIRST -----------------------------
    # score_one() is the ACTUAL function that writes score_matrix.csv rows
    # in the real calibration pipeline -- called directly (not
    # re-implemented here) so this test exercises the real code path. Its
    # A6 reference is always None (score_one() never passes one -- see its
    # own module docstring), so this is inherently an offline-A6
    # comparison; its P8 fault_db is whatever module-level FAULT_DB
    # run_scoring.py loaded at import time (the real GEM database if
    # Dataset/GAF-DB/ is present, else None).
    row = _run_scoring.score_one(dataset_id)
    df = pd.DataFrame([row])
    t_d = ac.composite_score(df, ac.AXIS_WEIGHTS, ac.WITHIN)
    recon_decision = ac.assign_decision_gated(df, t_d).iloc[0]

    # -- (1) PRODUCTION -----------------------------------------------
    # Uses the SAME fault_db object run_scoring.py's score_one() just used
    # (rather than DataCertifyAuditor()'s own fault_db=None default) so P8
    # is evaluated identically on both sides -- otherwise a P plausibility-
    # axis difference from P8 being on for one side and off for the other
    # would be a false positive for this test, unrelated to the gate-
    # awareness bug class this test actually guards against. reference is
    # left at its own default (None), matching score_one()'s own
    # score_authenticity(ds) call (no reference passed).
    auditor = DataCertifyAuditor(fault_db=_run_scoring.FAULT_DB)
    prod_result = auditor.audit(dataset)
    prod_decision = prod_result.decision.value

    assert prod_decision == recon_decision, (
        f"Decision MISMATCH for dataset_id={dataset_id!r}: production "
        f"DataCertifyAuditor.audit() -> {prod_decision!r}, but the "
        f"calibration score_matrix.csv reconstruction path "
        f"(run_scoring.score_one() + _analysis_common.assign_decision_gated()) "
        f"-> {recon_decision!r}. This is exactly the class of bug the "
        f"2026-07-21 gate-awareness finding uncovered -- see CHANGELOG.md's "
        f"2026-07-21 and 2026-07-23 entries. Investigate whether "
        f"data_certify/decision.py's Stage-2 threshold rule or its four "
        f"ADMIT-eligibility gates have changed without "
        f"calibration/run_scoring.py or calibration/_analysis_common.py "
        f"being updated to match (prod T(D)={prod_result.trust_score!r}, "
        f"hard_override_fired={prod_result.hard_override.fired!r})."
    )


def test_at_least_two_datasets_were_actually_checked():
    """Guards against the parametrized test above silently no-op'ing (e.g.
    a stripped-down checkout missing datasets/) -- parametrize() with an
    empty list would otherwise make it vanish without a trace instead of
    failing loudly."""
    available = _available_dataset_ids()
    assert len(available) >= 2, (
        f"Expected at least 2 of {CANDIDATE_DATASET_IDS} to be present under "
        f"{DATASETS_DIR} for this regression test to provide real coverage; "
        f"found {available!r}. This checkout may be missing the datasets/ "
        f"corpus."
    )
