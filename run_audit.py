# -*- coding: utf-8 -*-
"""
run_audit.py -- DATA-CERTIFY Generic Dataset Auditor
=====================================================

Usage:
    python run_audit.py                          # scan all datasets/
    python run_audit.py --dataset nz              # run a single dataset
    python run_audit.py --dataset nz --theta-admit 0.70 --theta-reject 0.45
    python run_audit.py --list                    # list available datasets
    python run_audit.py --dataset nz --reference-csv datasets/chile/records.csv
    python run_audit.py --dataset nz --offline    # force fully offline (no A6 network call)
    python run_audit.py --dataset nz --save-json
    python run_audit.py --dataset nz --uncertainty --n-boot 200
    python run_audit.py --dataset nz --reference-source emsc
    python run_audit.py --dataset nz --reference-source multi --min-corroborating-sources 2
    python run_audit.py --dataset nz --reference-source weighted-multi
    python run_audit.py --dataset nz --fault-db-source gem
    python run_audit.py --dataset nz --fault-db-source gem --gem-fault-db-path /path/to/faults.geojson
    python run_audit.py --help

A6 (external cross-validation) default, as of this version: unless
--reference-csv or --offline is given, the auditor now attempts A6 against
the REAL, live USGS ComCat API by default (data_certify.USGSComCatReference)
and gracefully falls back to intrinsic-only A1-A5 scoring if unreachable --
see data_certify/reference_data.py's module docstring for why this
default changed (A6 is the only signal in the whole framework that can
catch a physically-plausible-but-fabricated catalog).

--reference-source {usgs,emsc,isc,multi,weighted-multi} selects WHICH
external catalog(s) A6 checks against (default: usgs, unchanged). "multi"
combines USGS + EMSC + ISC via MultiSourceExternalCatalogReference and only
counts a record as externally corroborated once at least
--min-corroborating-sources (default 2) of the reachable sources
independently agree -- this directly defends against the scenario where a
single source (e.g. USGS ComCat) is itself spoofed or compromised.
"weighted-multi" takes a different, complementary approach: USGS, EMSC,
and ISC each query and match INDEPENDENTLY (their own matched_fraction
over a shared reference-complete stratum), and the per-source results are
then reliability-weighted together (weight ~ 1/mc_ref, discounted for
sources that could not fit a region-specific completeness estimate) into
one combined A6 verdict -- see
WeightedMultiSourceExternalCatalogReference's own docstring in
data_certify/reference_data.py for the full formula and disclosed
trade-offs versus "multi". Use --default-mc-ref-weight-discount to adjust
how much a defaulted (non-region-fitted) source's weight is discounted
(default: 0.5). See data_certify/reference_data.py's module docstring for
more on all reference-source options. Note ISCReference has not been
live-verified in this project's development environment (see its own
docstring) -- worth a manual spot check before relying on it in
production.

--fault-db-source {bundled,gem} selects the P8 plate-boundary reference.
"bundled" is the small ~30-point demo-scale sample (same as the older
--fault-db flag, kept for backward compatibility). "gem" loads the REAL
GEM Global Active Faults Database (Styron & Pagani 2020, ~13,700 faults)
from a GeoJSON file (see --gem-fault-db-path; auto-detects
Dataset/GAF-DB/ in this repo if not given) -- see
data_certify/reference_data.py's GEMActiveFaultsDatabase docstring for the
three disclosed approximations this real-data path involves (point-cloud
vs. true polyline distance, approximate grid-indexed nearest-neighbor
search, and a long-range sentinel distance).

Folder structure:
    datasets/
    └── <dataset_name>/
        └── records.csv     (canonical schema -- see prepare_dataset.py)
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from data_certify import (
    DataCertifyAuditor, CertifyDecision, THETA_ADMIT, THETA_REJECT,
    BundledSampleFaultDatabase, EMSCReference, GEMActiveFaultsDatabase, ISCReference,
    LocalCSVCatalogReference, MultiSourceExternalCatalogReference, NullExternalCatalog,
    USGSComCatReference, WeightedMultiSourceExternalCatalogReference, default_gem_geojson_path,
)
from data_certify._constants import MIN_APPLICABLE_SUBTESTS_FOR_ADMIT, MIN_N_RECORDS_FOR_ADMIT
from data_certify.schema import load_dataset_csv

DATASETS_DIR = ROOT / "datasets"

GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
YELLOW = "\033[1;33m"
RED = "\033[0;31m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
NC = "\033[0m"


def banner(text: str) -> None:
    w = 65
    print(f"\n{BLUE}{'='*w}{NC}")
    print(f"{BLUE}  {text}{NC}")
    print(f"{BLUE}{'='*w}{NC}")


def section(text: str) -> None:
    dashes = max(0, 55 - len(text))
    print(f"\n{CYAN}{BOLD}-- {text} {'-'*dashes}{NC}")


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


def list_datasets() -> List[Path]:
    if not DATASETS_DIR.exists():
        return []
    return sorted(
        d for d in DATASETS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith("_") and (d / "records.csv").exists()
    )


def print_audit_summary(result) -> None:
    w = 65
    print(f"\n{BOLD}{BLUE}{'='*w}{NC}")
    print(f"{BOLD}{BLUE}  AUDIT SUMMARY - {result.dataset_name}{NC}")
    print(f"{BOLD}{BLUE}{'='*w}{NC}")

    print(f"\n  {BOLD}Dataset{NC}")
    print(f"    Records      : {result.n_records}")
    print(f"    Thresholds   : theta_admit={result.theta_admit}  theta_reject={result.theta_reject}")
    if result.evidence_coverage is not None:
        print(f"    Evidence coverage : {result.evidence_coverage:.1%} of T(D)'s nominal "
              f"calibrated weight backed by applicable evidence (see --verbose for per-sub-test "
              f"effective_weight detail).")
    if result.sample_sufficiency is not None:
        print(f"    Sample sufficiency: {result.sample_sufficiency:.1%} of covered evidence's "
              f"nominal weight rests on a sub-test sample size meeting its disclosed "
              f"MIN_RELIABLE_N floor (see --verbose for per-sub-test n_used detail).")
    if result.n_applicable_subtests is not None:
        print(f"    Applicable sub-tests: {result.n_applicable_subtests} of a possible 20 "
              f"(unweighted count).")

    print(f"\n  {BOLD}Decision{NC}")
    if result.decision == CertifyDecision.ADMIT:
        print(f"    {GREEN}{BOLD}[ADMIT]{NC}  T(D)={result.trust_score:.4f}")
        print(f"    {GREEN}Cleared for downstream disaster-response use, "
              f"relative to the named test battery. No mandatory-review flag raised.{NC}")
    elif result.decision == CertifyDecision.CONDITIONAL:
        ts = result.trust_score if result.trust_score is not None else float("nan")
        print(f"    {YELLOW}{BOLD}[CONDITIONAL]{NC}  T(D)={ts:.4f}")
        print(f"    {YELLOW}Usable only with the documented caveats below -- "
              f"no unconditional trust guarantee.{NC}")
    else:
        print(f"    {RED}{BOLD}[REJECT]{NC}")
        if result.hard_override.fired:
            print(f"    {RED}Hard override fired -- see reasons below. "
                  f"No amount of completeness/plausibility can offset this.{NC}")
        else:
            ts = result.trust_score if result.trust_score is not None else float("nan")
            print(f"    {RED}T(D)={ts:.4f} < theta_reject={result.theta_reject}{NC}")

    print(f"\n  {BOLD}Per-axis scores{NC}")
    for axis_name, label in (("A", "Authenticity"), ("P", "Plausibility"),
                              ("C", "Completeness"), ("I", "Instrumentation")):
        axis = result.axis_results.get(axis_name)
        if axis is None:
            continue
        score_str = "N/A" if math.isnan(axis.score) else f"{axis.score:.4f}"
        w_used = result.weights_used.get(axis_name, float("nan"))
        mode_str = f"  [{axis.mode}]" if axis.mode else ""
        print(f"    {axis_name}(D) {label:<17} = {score_str:<8} (weight {w_used:.3f}){mode_str}")

    if result.hard_override.reasons:
        print(f"\n  {BOLD}{RED}Hard-override reasons{NC}")
        for r in result.hard_override.reasons:
            print(f"    - {r}")

    if result.caveats:
        print(f"\n  {BOLD}Caveats{NC}")
        for c in result.caveats:
            print(f"    - {c}")

    print(f"\n{BOLD}{BLUE}{'='*w}{NC}\n")


def _build_reference(
    reference_csv: Optional[str], offline: bool,
    reference_source: str = "usgs", min_corroborating_sources: int = 2,
    default_mc_ref_weight_discount: float = 0.5,
    timeout_sec: Optional[float] = None,
):
    """
    Choose the A6 external-reference implementation, in priority order:
      1. --reference-csv PATH   -> LocalCSVCatalogReference(PATH) (explicit, always wins)
      2. --offline              -> NullExternalCatalog() (explicit fully-offline/air-gapped mode)
      3. --reference-source     -> usgs (default) / emsc / isc / multi / weighted-multi (see below)

    timeout_sec (added 2026-07-09, motivated by a real finding: ISC's
    production default timeout of 15s was demonstrated live to be too
    short for large calibration-scale queries -- the "chile" corpus
    dataset scored matched_fraction=0.0 with mc_ref_is_default=True at
    15s, but produced a real, non-default mc_ref and a much higher score
    once queried with a 90s timeout). When given (not None), overrides
    every live source's (USGS/EMSC/ISC) own default per-request timeout;
    when None (the default), each class keeps its own production default
    (USGS/EMSC=10s, ISC=15s) -- i.e. passing nothing here is a no-op,
    fully backward compatible with every prior call site.

    --reference-source options:
      usgs  (default) -> USGSComCatReference() -- unchanged from prior versions.
      emsc             -> EMSCReference() -- EMSC SeismicPortal, an organizationally
                          independent source from USGS.
      isc              -> ISCReference() -- ISC, a third independent source (live-verified
                          2026-07-08/09 -- see its docstring in data_certify/reference_data.py).
      multi            -> MultiSourceExternalCatalogReference([USGS, EMSC, ISC],
                          min_corroborating_sources=--min-corroborating-sources) --
                          requires independent agreement from N of the 3 sources before
                          treating a record as externally corroborated, closing the
                          single-point-of-spoofing-failure gap of relying on any one
                          catalog alone (see data_certify/reference_data.py's module
                          docstring, MultiSourceExternalCatalogReference section).
      weighted-multi   -> WeightedMultiSourceExternalCatalogReference([USGS, EMSC, ISC],
                          default_mc_ref_weight_discount=--default-mc-ref-weight-discount) --
                          each of USGS/EMSC/ISC queries and matches INDEPENDENTLY, then their
                          own matched_fraction results are reliability-weighted together
                          (weight ~ 1/mc_ref, discounted if a source could not fit a
                          region-specific completeness estimate) into one combined A6 verdict.
                          Complementary to "multi": targets ordinary differences in each
                          honestly-operated agency's own regional completeness, rather than a
                          compromised/spoofed source (see data_certify/reference_data.py's
                          module docstring, WeightedMultiSourceExternalCatalogReference section).
    """
    if reference_csv:
        return LocalCSVCatalogReference(reference_csv), f"local CSV ({reference_csv})"
    if offline:
        return NullExternalCatalog(), "disabled (--offline)"

    _kw = {} if timeout_sec is None else {"timeout_sec": timeout_sec}
    _timeout_note = "" if timeout_sec is None else f", timeout={timeout_sec}s"

    if reference_source == "emsc":
        return EMSCReference(**_kw), f"live EMSC SeismicPortal{_timeout_note}"
    if reference_source == "isc":
        return ISCReference(**_kw), (
            f"live ISC (verified 2026-07-08/09 -- see ISCReference docstring){_timeout_note}")
    if reference_source == "multi":
        sources = [USGSComCatReference(**_kw), EMSCReference(**_kw), ISCReference(**_kw)]
        label = (f"multi-source corroboration (USGS+EMSC+ISC, requires "
                 f"{min_corroborating_sources}-of-3 independently reachable agreement)"
                 f"{_timeout_note}")
        return MultiSourceExternalCatalogReference(
            sources, min_corroborating_sources=min_corroborating_sources), label
    if reference_source == "weighted-multi":
        sources = [USGSComCatReference(**_kw), EMSCReference(**_kw), ISCReference(**_kw)]
        label = (f"weighted multi-source corroboration (USGS+EMSC+ISC, each queried "
                 f"independently and reliability-weighted by 1/mc_ref, default-mc_ref "
                 f"discount={default_mc_ref_weight_discount}){_timeout_note}")
        return WeightedMultiSourceExternalCatalogReference(
            sources, default_mc_ref_weight_discount=default_mc_ref_weight_discount), label

    return USGSComCatReference(**_kw), f"live USGS ComCat (default; use --offline to disable){_timeout_note}"


def _build_fault_db(
    use_fault_db: bool,
    fault_db_source: Optional[str],
    gem_fault_db_path: Optional[str],
):
    """
    Choose the P8 fault-database implementation, in priority order:
      1. --fault-db-source gem      -> GEMActiveFaultsDatabase(path), the REAL GEM
                                        Global Active Faults Database.
      2. --fault-db-source bundled, or the older --fault-db flag (kept for
                                        backward compatibility) -> BundledSampleFaultDatabase().
      3. neither given              -> None (P8 not evaluated).
    """
    if fault_db_source == "gem":
        path = gem_fault_db_path or default_gem_geojson_path()
        if not path:
            return None, (
                "GEM fault DB requested (--fault-db-source gem) but no GeoJSON file was "
                "found -- pass --gem-fault-db-path, or place a file under Dataset/GAF-DB/. "
                "P8 not evaluated."
            )
        db = GEMActiveFaultsDatabase(path)
        if not db.is_available():
            return None, f"GEM fault DB failed to load ({db.load_error}) -- P8 not evaluated."
        return db, (
            f"REAL GEM Global Active Faults DB ({db.n_points} fault-trace vertices "
            f"after subdivision, from {path}) -- see GEMActiveFaultsDatabase's docstring "
            f"for disclosed distance-approximation caveats"
        )

    if fault_db_source == "bundled" or use_fault_db:
        return BundledSampleFaultDatabase(), "bundled sample (demo-scale, ~30 points)"

    return None, "not configured -- P8 not evaluated"


def audit_dataset(
    dataset_path: Path,
    theta_admit: float,
    theta_reject: float,
    reference_csv: Optional[str],
    offline: bool,
    use_fault_db: bool,
    save_json: bool,
    verbose: bool,
    uncertainty: bool = False,
    n_boot: int = 100,
    subsample_fraction: float = 0.8,
    reference_source: str = "usgs",
    min_corroborating_sources: int = 2,
    default_mc_ref_weight_discount: float = 0.5,
    fault_db_source: Optional[str] = None,
    gem_fault_db_path: Optional[str] = None,
    timeout_sec: Optional[float] = None,
    min_evidence_coverage: float = 0.5,
    min_sample_sufficiency: float = 0.5,
    min_n_records_for_admit: int = MIN_N_RECORDS_FOR_ADMIT,
    min_applicable_subtests_for_admit: int = MIN_APPLICABLE_SUBTESTS_FOR_ADMIT,
) -> Dict[str, Any]:
    dataset_name = dataset_path.name
    banner(f"Dataset: {dataset_name}")

    print(f"\n{YELLOW}[1/3] Loading canonical dataset...{NC}")
    dataset = load_dataset_csv(dataset_path / "records.csv", name=dataset_name)
    print(f"  Records loaded: {dataset.n}")

    reference, reference_label = _build_reference(
        reference_csv, offline, reference_source, min_corroborating_sources,
        default_mc_ref_weight_discount, timeout_sec=timeout_sec)
    fault_db, fault_db_label = _build_fault_db(use_fault_db, fault_db_source, gem_fault_db_path)

    print(f"\n{YELLOW}[2/3] Running DATA-CERTIFY audit protocol...{NC}")
    print(f"  theta_admit={theta_admit}  theta_reject={theta_reject}")
    print(f"  A6 external reference : {reference_label}")
    if not reference_csv and not offline:
        # Live-API mode: probe feasibility now so the operator sees
        # up front whether A6 will actually run for this audit, rather
        # than only finding out from a caveat buried in the result.
        feasible = reference.is_feasible()
        print(f"                          -> {'reachable, A6 will run' if feasible else 'UNREACHABLE, falling back to intrinsic-only A(D)'}")
    print(f"  P8 fault database     : {fault_db_label}")

    auditor = DataCertifyAuditor(
        theta_admit=theta_admit, theta_reject=theta_reject,
        reference=reference, fault_db=fault_db,
        min_evidence_coverage=min_evidence_coverage,
        min_sample_sufficiency=min_sample_sufficiency,
        min_n_records_for_admit=min_n_records_for_admit,
        min_applicable_subtests_for_admit=min_applicable_subtests_for_admit,
    )
    result = auditor.audit(dataset)

    print()
    print(str(result))

    if verbose:
        section("Per-axis detail")
        for axis_name in ("A", "P", "C", "I"):
            axis = result.axis_results.get(axis_name)
            if axis is not None:
                print(str(axis))

    uncertainty_result = None
    if uncertainty:
        section("Resampling uncertainty on T(D)")
        print(f"  Running {n_boot} subsample-without-replacement replicates of the full audit "
              f"pipeline -- this costs roughly {n_boot}x a single audit and is opt-in for that "
              f"reason (see DataCertifyAuditor.estimate_uncertainty's docstring for why "
              f"subsampling, not the textbook with-replacement bootstrap, is used).")
        uncertainty_result = auditor.estimate_uncertainty(
            dataset, n_boot=n_boot, subsample_fraction=subsample_fraction)
        print(str(uncertainty_result))

    print(f"\n{YELLOW}[3/3] Finalising...{NC}")
    print_audit_summary(result)

    output = result.to_dict()
    if uncertainty_result is not None:
        output["uncertainty"] = uncertainty_result.to_dict()
    if save_json:
        out_path = dataset_path / "audit_result.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(_json_safe(output), f, indent=2, ensure_ascii=False)
        print(f"{GREEN}  Saved -> {out_path}{NC}")

    return output


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DATA-CERTIFY Generic Dataset Auditor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--dataset", type=str, default=None,
                        help="Dataset folder name inside datasets/ (default: run all).")
    parser.add_argument("--theta-admit", type=float, default=THETA_ADMIT,
                        help=f"ADMIT threshold (default: {THETA_ADMIT}, empirically calibrated).")
    parser.add_argument("--theta-reject", type=float, default=THETA_REJECT,
                        help=f"REJECT threshold (default: {THETA_REJECT}, empirically calibrated).")
    parser.add_argument("--min-evidence-coverage", type=float, default=0.5,
                        help="Evidence-coverage safety gate (default: 0.5): if an ADMIT decision "
                             "rests on less than this fraction of T(D)'s nominal calibrated weight "
                             "actually being backed by applicable evidence, cap the decision down "
                             "to CONDITIONAL. A pragmatic, disclosed default -- NOT itself "
                             "empirically calibrated. Set to 0.0 to disable this gate.")
    parser.add_argument("--min-sample-sufficiency", type=float, default=0.5,
                        help="Sample-sufficiency safety gate (default: 0.5; 2026-07-21 external "
                             "review): if an ADMIT decision rests on covered sub-tests whose own "
                             "underlying sample size (n_used, e.g. A3's number of independent "
                             "aftershock clusters) mostly falls short of that sub-test's disclosed "
                             "MIN_RELIABLE_N floor, cap the decision down to CONDITIONAL. Distinct "
                             "from --min-evidence-coverage (which only checks a sub-test ran, not "
                             "whether it ran on enough data). A pragmatic, disclosed default -- NOT "
                             "itself empirically calibrated. Set to 0.0 to disable this gate.")
    parser.add_argument("--min-n-records-for-admit", type=int, default=MIN_N_RECORDS_FOR_ADMIT,
                        help=f"ADMIT-eligibility record-count floor (default: "
                             f"{MIN_N_RECORDS_FOR_ADMIT}; 2026-07-21, response to a "
                             f"paper-readiness review of the 19/490 false-admit finding): "
                             f"ADMIT is never reachable below this many total records, "
                             f"regardless of T(D) or the two gates above -- capped to "
                             f"CONDITIONAL instead. A raw record count, unlike "
                             f"--min-evidence-coverage/--min-sample-sufficiency, so it cannot "
                             f"be defeated by a future weight recalibration. Set to 0 to "
                             f"disable. See MIN_N_RECORDS_FOR_ADMIT in "
                             f"data_certify/_constants.py for the full empirical basis and "
                             f"disclosed residual this does not close.")
    parser.add_argument("--min-applicable-subtests-for-admit", type=int,
                        default=MIN_APPLICABLE_SUBTESTS_FOR_ADMIT,
                        help=f"Companion count-based ADMIT-eligibility floor (default: "
                             f"{MIN_APPLICABLE_SUBTESTS_FOR_ADMIT}): ADMIT is never reachable "
                             f"below this many applicable, computable non-hard-gate sub-tests "
                             f"(out of a possible 20), independent of how much nominal weight "
                             f"they carry. Set to 0 to disable. See "
                             f"MIN_APPLICABLE_SUBTESTS_FOR_ADMIT in data_certify/_constants.py.")
    parser.add_argument("--reference-csv", type=str, default=None,
                        help="Canonical-schema CSV to use as the A6 external reference catalog "
                             "(takes priority over the live-API default and --offline).")
    parser.add_argument("--offline", action="store_true",
                        help="Force A6 fully offline (NullExternalCatalog): no network call at "
                             "all, for reproducible/air-gapped runs. Without this flag (and "
                             "without --reference-csv), A6 attempts the live USGS ComCat API by "
                             "default and gracefully falls back to intrinsic-only A(D) if "
                             "unreachable.")
    parser.add_argument("--fault-db", action="store_true",
                        help="Enable P8 using the bundled sample plate-boundary reference "
                             "(demo-scale -- see data_certify/reference_data.py). Kept for "
                             "backward compatibility; equivalent to --fault-db-source bundled. "
                             "Ignored if --fault-db-source is also given.")
    parser.add_argument("--fault-db-source", type=str, default=None,
                        choices=["bundled", "gem"],
                        help="Which P8 fault database to use. 'bundled' = small ~30-point "
                             "demo-scale sample (same as --fault-db). 'gem' = the REAL GEM "
                             "Global Active Faults Database (Styron & Pagani 2020, ~13,700 "
                             "faults) -- see --gem-fault-db-path and "
                             "data_certify/reference_data.py's GEMActiveFaultsDatabase "
                             "docstring for the disclosed distance-approximation caveats this "
                             "involves. If omitted, --fault-db is used, or P8 is not evaluated.")
    parser.add_argument("--gem-fault-db-path", type=str, default=None,
                        help="Path to a GEM GAF-DB GeoJSON file (LineString/MultiLineString "
                             "fault traces), used only with --fault-db-source gem. Defaults to "
                             "auto-detecting Dataset/GAF-DB/gem_active_faults_harmonized.geojson "
                             "(falling back to gem_active_faults.geojson) in this repo.")
    parser.add_argument("--save-json", action="store_true",
                        help="Save audit result to audit_result.json inside the dataset folder.")
    parser.add_argument("--list", action="store_true", help="List available datasets and exit.")
    parser.add_argument("--verbose", action="store_true", help="Print full per-axis sub-test detail.")
    parser.add_argument("--uncertainty", action="store_true",
                         help="Also compute a nonparametric (subsample-without-replacement) "
                              "resampling confidence interval for T(D) -- see "
                              "data_certify.DataCertifyAuditor.estimate_uncertainty's docstring "
                              "for why subsampling is used instead of the textbook with-"
                              "replacement bootstrap. Opt-in: costs roughly --n-boot times a "
                              "single audit's runtime.")
    parser.add_argument("--n-boot", type=int, default=100,
                         help="Number of resampling replicates for --uncertainty (default: 100).")
    parser.add_argument("--subsample-fraction", type=float, default=0.8,
                         help="Fraction of records drawn WITHOUT replacement per --uncertainty "
                              "replicate (default: 0.8). See estimate_uncertainty's docstring "
                              "for why without-replacement subsampling, not the textbook "
                              "with-replacement bootstrap, is used.")
    parser.add_argument("--reference-source", type=str, default="usgs",
                         choices=["usgs", "emsc", "isc", "multi", "weighted-multi"],
                         help="Which external catalog(s) A6 checks against (default: usgs, "
                              "unchanged from prior versions). 'multi' combines USGS+EMSC+ISC "
                              "and requires --min-corroborating-sources of them to agree before "
                              "treating a record as externally corroborated -- hardens A6 "
                              "against a single source being spoofed/compromised. "
                              "'weighted-multi' instead queries USGS+EMSC+ISC INDEPENDENTLY and "
                              "reliability-weights their own separate matched_fraction results "
                              "together (weight ~ 1/mc_ref) into one combined A6 verdict -- see "
                              "data_certify/reference_data.py's module docstring for both. "
                              "Ignored if --reference-csv or --offline is given.")
    parser.add_argument("--min-corroborating-sources", type=int, default=2,
                         help="With --reference-source multi, how many of the (reachable) "
                              "configured sources must independently agree before a record "
                              "counts as externally matched (default: 2 of 3).")
    parser.add_argument("--default-mc-ref-weight-discount", type=float, default=0.5,
                         help="With --reference-source weighted-multi, the weight multiplier "
                              "applied to a source whose mc_ref could not be fit from its own "
                              "region-specific data and fell back to the global default floor "
                              "(default: 0.5 -- see WeightedMultiSourceExternalCatalogReference's "
                              "docstring). Must be in (0, 1].")
    parser.add_argument("--timeout", type=float, default=None,
                         help="Per-request timeout in seconds, overriding every live source's "
                              "(USGS/EMSC/ISC) own default (USGS/EMSC=10s, ISC=15s). Added "
                              "2026-07-09 after live testing showed the ISC default was too "
                              "short for large calibration-scale queries (e.g. the 'chile' "
                              "corpus dataset needed ~90s to get a genuine, non-fallback "
                              "mc_ref) -- see calibration/debug_diagnostics/debug_chile_isc_emsc_gap.py. "
                              "Ignored with --reference-csv or --offline. Default: None "
                              "(each source's own production default, unchanged behavior).")
    args = parser.parse_args()

    if args.list:
        datasets = list_datasets()
        if not datasets:
            print(f"{YELLOW}No datasets found in {DATASETS_DIR}{NC}")
            print("Create a subfolder under datasets/ with a records.csv (see prepare_dataset.py).")
        else:
            print(f"\n{BOLD}Available datasets in {DATASETS_DIR}:{NC}")
            for d in datasets:
                ds = load_dataset_csv(d / "records.csv", name=d.name)
                print(f"  {GREEN}OK{NC} {d.name:<20} {ds.n} records")
        return

    if args.dataset:
        target = DATASETS_DIR / args.dataset
        if not (target / "records.csv").exists():
            print(f"{RED}Dataset not found: {target / 'records.csv'}{NC}")
            print("Run --list to see available datasets, or use prepare_dataset.py first.")
            sys.exit(1)
        dataset_paths = [target]
    else:
        dataset_paths = list_datasets()
        if not dataset_paths:
            print(f"{RED}No datasets found in {DATASETS_DIR}{NC}")
            sys.exit(1)

    results = []
    for dp in dataset_paths:
        try:
            r = audit_dataset(
                dataset_path=dp,
                theta_admit=args.theta_admit,
                theta_reject=args.theta_reject,
                reference_csv=args.reference_csv,
                offline=args.offline,
                use_fault_db=args.fault_db,
                save_json=args.save_json,
                verbose=args.verbose,
                uncertainty=args.uncertainty,
                n_boot=args.n_boot,
                subsample_fraction=args.subsample_fraction,
                reference_source=args.reference_source,
                min_corroborating_sources=args.min_corroborating_sources,
                default_mc_ref_weight_discount=args.default_mc_ref_weight_discount,
                fault_db_source=args.fault_db_source,
                gem_fault_db_path=args.gem_fault_db_path,
                timeout_sec=args.timeout,
                min_evidence_coverage=args.min_evidence_coverage,
                min_sample_sufficiency=args.min_sample_sufficiency,
                min_n_records_for_admit=args.min_n_records_for_admit,
                min_applicable_subtests_for_admit=args.min_applicable_subtests_for_admit,
            )
            results.append(r)
        except Exception as exc:
            print(f"\n{RED}ERROR auditing '{dp.name}': {exc}{NC}")
            import traceback
            traceback.print_exc()

    if len(results) > 1:
        print(f"\n{BOLD}{BLUE}{'='*65}{NC}")
        print(f"{BOLD}{BLUE}  MULTI-DATASET SUMMARY{NC}")
        print(f"{BOLD}{BLUE}{'='*65}{NC}")
        for r in results:
            if not r:
                continue
            dec = r.get("decision", "?")
            ts = r.get("trust_score")
            ts_str = f"{ts:.4f}" if isinstance(ts, (int, float)) else "N/A"
            color = GREEN if dec == "ADMIT" else (YELLOW if dec == "CONDITIONAL" else RED)
            print(f"  {color}{dec:<12}{NC}  {r['dataset']:<20}  T(D)={ts_str}")
        print(f"{BOLD}{BLUE}{'='*65}{NC}\n")


if __name__ == "__main__":
    main()
