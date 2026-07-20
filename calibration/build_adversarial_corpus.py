# -*- coding: utf-8 -*-
"""
calibration/build_adversarial_corpus.py -- Builds the HELD-OUT level-10
adversarial fabrication corpus (30 datasets, calibration/corrupt.py's
fabricate_level10_adversarial, the most-realistic rung of the 10-level
graduated fabrication ladder).

WHY THIS IS A SEPARATE SCRIPT, NOT PART OF build_corpus.py (2026-07-10/11):
per an explicit user decision, the most-realistic fabrication tier is kept
OUT of the calibration corpus (the one build_corpus.py assembles, and the
one run_scoring.py / compute_ewm.py / calibrate_thresholds.py /
bootstrap_ewm_stability.py compute weights and thresholds from). Feeding a
tier that is deliberately engineered to defeat every intrinsic/physical
check into the SAME pipeline that calibrates the thresholds meant to catch
it would be circular: the thresholds would end up tuned against the exact
adversarial construction being evaluated, rather than reflecting general
reliability. Levels 1-9 (calibration/corrupt.py's fabricate_level1..
fabricate_level9) do NOT have this problem and are wired into
build_corpus.py's build_fabricated_datasets() normally -- only level 10 is
held out.

This script writes into `datasets_adversarial/<name>/records.csv` (a
SEPARATE top-level directory from `datasets/`, never read by
build_corpus.py, run_scoring.py, or any calibration script) and its own
manifest `calibration/adversarial_corpus_manifest.csv` (separate from
`calibration/corpus_manifest.csv`). Nothing here is fed into EWM/threshold
calibration. Use it for:
  - Ad hoc manual inspection/scoring via run_audit.py directly against a
    single file in datasets_adversarial/.
  - The automated held-out probes in tests/test_adversarial.py's
    TestGraduatedFabricationLadder (which generate their own small
    in-memory examples and do not depend on this script having been run).

Usage:
    python3 calibration/build_adversarial_corpus.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration import corrupt
from data_certify.schema import save_dataset_csv

ADVERSARIAL_OUT = ROOT / "datasets_adversarial"
MANIFEST_PATH = Path(__file__).resolve().parent / "adversarial_corpus_manifest.csv"

N_DATASETS = 30
N_ROWS = 1500


def main() -> None:
    rows: List[Dict] = []
    for k in range(N_DATASETS):
        name = f"fabricated_level10_adversarial_{k + 1}"
        seed = 5000 + k
        ds = corrupt.fabricate_level10_adversarial(N_ROWS, np.random.RandomState(seed), name=name)
        out_path = ADVERSARIAL_OUT / name / "records.csv"
        save_dataset_csv(ds, out_path)
        rows.append({
            "dataset_id": name, "source_file": "synthetic (calibration/corrupt.py, level 10)",
            "category": "fabricated_adversarial", "label": "known_bad",
            "corruption_type": "full_fabrication_adversarial", "severity": "n/a",
            "n_records": ds.n,
            "notes": f"Level 10/10 (held out of calibration): {corrupt.LEVEL_DESCRIPTIONS[10]} seed={seed}.",
        })

    df = pd.DataFrame(rows)
    df.to_csv(MANIFEST_PATH, index=False)
    print("=" * 70)
    print(f"Adversarial (held-out) corpus assembled: {len(df)} datasets, "
          f"{N_ROWS} rows each.")
    print(f"Written -> {ADVERSARIAL_OUT}")
    print(f"Manifest -> {MANIFEST_PATH}")
    print("NOT wired into build_corpus.py / run_scoring.py / EWM calibration "
          "-- use run_audit.py directly against individual files here, or "
          "tests/test_adversarial.py::TestGraduatedFabricationLadder for "
          "automated checks.")
    print("=" * 70)


if __name__ == "__main__":
    main()
