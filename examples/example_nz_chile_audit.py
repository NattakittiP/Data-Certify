# -*- coding: utf-8 -*-
"""
Example: NZ + Chile Real-Catalog Audit
========================================

Runs the full DATA-CERTIFY two-stage audit protocol against the two real
earthquake catalogs bundled with this repository:

    datasets/nz/records.csv       20,648 events  (GeoNet, New Zealand)
    datasets/chile/records.csv  132,964 events  (CSN, Chile)

(originally prepared from messy raw source CSVs by prepare_dataset.py --
see that script for the real-world parsing this involved: glued datetime
strings, unit-suffixed depth/magnitude fields, malformed CSV rows.)

Demonstrates, on real (not synthetic) data:
    1. A baseline audit of each catalog with default settings.
    2. The effect of enabling P8 (plate-boundary proximity) via the bundled
       sample fault database -- both catalogs sit on genuine subduction
       zones, so P8 should score them favourably once enabled.
    3. An A6 self-consistency sanity check: matching NZ against a *copy of
       itself* as the external reference. This is NOT a fabrication test
       (of course a catalog matches itself) -- it verifies the A6 matching
       and Mc_ref-stratification machinery is wired correctly end to end,
       the same way a unit test would, but on the full real dataset.
    4. Threshold sensitivity: how the ADMIT/CONDITIONAL/REJECT decision
       moves as theta_admit/theta_reject are varied around the empirically
       calibrated defaults.

NOTE: this script runs several full audits over the 133k-record "chile"
catalog (baseline, P8-enabled, threshold sweep), so expect it to take
roughly 1-2 minutes rather than seconds -- this is expected, not a hang.

Usage:
    python examples/example_nz_chile_audit.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from data_certify import (
    DataCertifyAuditor,
    CertifyDecision,
    THETA_ADMIT,
    THETA_REJECT,
    BundledSampleFaultDatabase,
    LocalCSVCatalogReference,
)
from data_certify.schema import load_dataset_csv

DATASETS_DIR = ROOT / "datasets"


def banner(text: str) -> None:
    w = 65
    print(f"\n{'='*w}")
    print(f"  {text}")
    print(f"{'='*w}")


def section(text: str) -> None:
    dashes = max(0, 55 - len(text))
    print(f"\n-- {text} {'-'*dashes}")


def main() -> None:
    banner("DATA-CERTIFY: NZ + Chile Real-Catalog Audit")

    nz_path = DATASETS_DIR / "nz" / "records.csv"
    chile_path = DATASETS_DIR / "chile" / "records.csv"
    if not nz_path.exists() or not chile_path.exists():
        print(f"Missing dataset(s): expected {nz_path} and {chile_path}.\n"
              f"These ship with the repository -- if they're missing, "
              f"re-clone the repository or restore them from git.")
        sys.exit(1)

    nz = load_dataset_csv(nz_path, name="nz")
    chile = load_dataset_csv(chile_path, name="chile")
    print(f"\nLoaded nz    : {nz.n:>7} records")
    print(f"Loaded chile : {chile.n:>7} records")

    # -- 1. Baseline audit, default settings -----------------------------
    section("1. Baseline audit (no A6, no P8)")
    auditor = DataCertifyAuditor()
    nz_result = auditor.audit(nz)
    chile_result = auditor.audit(chile)
    print(str(nz_result))
    print(str(chile_result))

    # -- 2. Effect of enabling P8 (bundled sample fault database) --------
    section("2. Effect of enabling P8 (plate-boundary proximity)")
    fault_db = BundledSampleFaultDatabase()
    auditor_p8 = DataCertifyAuditor(fault_db=fault_db)
    nz_p8 = auditor_p8.audit(nz)
    chile_p8 = auditor_p8.audit(chile)

    def p_score(r):
        p = r.axis_results.get("P")
        return p.score if p is not None else float("nan")

    def p8_score(r):
        p = r.axis_results.get("P")
        if p is None:
            return None
        sub = p.sub_results.get("P8")
        return sub.score if sub is not None and sub.applicable else None

    print(f"  {'Dataset':<10} {'P(D) w/o P8':>14} {'P(D) w/ P8':>14} {'P8 score':>12}")
    for name, before, after in (("nz", nz_result, nz_p8), ("chile", chile_result, chile_p8)):
        p8 = p8_score(after)
        p8_str = f"{p8:.4f}" if p8 is not None else "N/A"
        print(f"  {name:<10} {p_score(before):>14.4f} {p_score(after):>14.4f} {p8_str:>12}")
    print("\n  (Both catalogs sit on real subduction/transform boundaries, so "
          "enabling P8 should\n   not penalise them -- it is a soft, "
          "additive plausibility signal, not a gate.)")

    # -- 3. A6 self-consistency sanity check -----------------------------
    section("3. A6 self-consistency sanity check (NZ matched against itself)")
    print("  NOTE: this deliberately uses the SAME catalog as its own A6 reference.\n"
          "  It is a wiring/sanity check for the matching + Mc_ref-stratification\n"
          "  logic, not a real fabrication test -- a genuine deployment would point\n"
          "  LocalCSVCatalogReference at an independent authoritative catalog\n"
          "  (USGS ComCat / ISC / EMSC / JMA).")
    self_reference = LocalCSVCatalogReference(nz_path)
    auditor_a6 = DataCertifyAuditor(reference=self_reference)
    nz_a6_result = auditor_a6.audit(nz)
    a6_sub = nz_a6_result.axis_results["A"].sub_results.get("A6")
    if a6_sub is not None and a6_sub.applicable:
        print(f"\n  A6 matched_fraction : {a6_sub.detail.get('matched_fraction'):.4f}")
        print(f"  A6 n_stratum        : {a6_sub.detail.get('n_stratum')}")
        print(f"  Hard override fired : {nz_a6_result.hard_override.fired}")
    else:
        print("\n  A6 not applicable (no records fell in the reference-complete stratum).")

    # -- 4. Threshold sensitivity -----------------------------------------
    section("4. Threshold sensitivity (theta_admit / theta_reject)")
    print(f"  Default: theta_admit={THETA_ADMIT}  theta_reject={THETA_REJECT} "
          f"(empirically calibrated and re-validated against a larger internal "
          f"calibration corpus)\n")
    print(f"  {'theta_admit':>12} {'theta_reject':>13}   {'nz decision':<12} {'chile decision':<12}")
    for theta_admit, theta_reject in [(0.75, 0.50), (0.55, 0.30)]:
        a = DataCertifyAuditor(theta_admit=theta_admit, theta_reject=theta_reject)
        r_nz = a.audit(nz)
        r_chile = a.audit(chile)
        print(f"  {theta_admit:>12.2f} {theta_reject:>13.2f}   "
              f"{r_nz.decision.value:<12} {r_chile.decision.value:<12}")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
