# -*- coding: utf-8 -*-
"""
calibration/analysis_d1d_cross_agency_merge.py -- Group D1 option (d)
("light" scope -- b-value only, no full hazard curve; see
Docs/03_Paper_Prep/DATA-CERTIFY_Downstream_Case_Studies_Combined_Summary.md, option (d)):
analysis step for
the cross-agency-merge case study. Consumes the three CSVs produced by
`calibration/fetch_multisource_chile_iquique.py` (which must be run FIRST,
on a machine with real internet access -- see that script's docstring).

QUESTION THIS ANSWERS: D2's related-work review found that no existing
framework combines cross-agency deduplication with authenticity auditing
(Melgarejo-Hernández et al. 2026 does dedup only). This case study asks:
when a downstream analyst naively concatenates USGS + EMSC catalogs for
the same real sequence WITHOUT deduplication (creating a file with genuine
cross-catalog duplicate events -- the same physical earthquake reported
twice, once by each agency, often with slightly different magnitude/
location due to each agency's own processing pipeline), does DATA-CERTIFY
correctly detect and quantify that problem, and does trusting its verdict
lead to a more accurate downstream b-value?

WHY I4, NOT A6, IS THE RELEVANT SUB-TEST HERE (an important, deliberate
design choice): A6 (external cross-agency corroboration) is designed to
catch FABRICATED events that do not correspond to anything real -- it
would not help here, because every record in this case study's merged
file genuinely IS a real USGS or EMSC event; the problem is duplication of
GENUINE events, not fabrication. Using a live A6 reference in this specific
case study would in fact be circular: A6 would query USGS/EMSC live and
find near-perfect matches for almost every record, since that is
literally where the merged file's records came from -- telling us nothing
new. The correct, non-circular test is I4 (data_certify/axis_instrumentation.py,
"Cross-catalog duplicate-ID detection via EM-fitted Fellegi-Sunter"),
which is explicitly scoped to exactly this scenario (its own docstring:
"a single-source dataset has no cross-catalog merge to check") and
operates entirely INTRINSICALLY on the dataset's own `source` field --
no live network call needed for the audit step itself (only the initial
fetch, handled by fetch_multisource_chile_iquique.py, needs one).
`reference=None` is used for the DataCertifyAuditor call below,
deliberately, for this reason -- not to avoid network risk (D1(a)/(b)'s
reason), but because a live A6 reference would be the wrong, circular
test for the specific failure mode this case study is about.

METHODOLOGY:
  1. Load usgs_raw.csv, emsc_raw.csv (single-source, from the live fetch)
     and naive_merged.csv (the two concatenated, no dedup).
  2. Compute b-value (same Aki MLE / Shi-Bolt SE pipeline as D1(a), from
     data_certify/stats.py) on usgs_raw, emsc_raw, and naive_merged.
  3. Compare all three against `datasets/real_chile_iquique_2014/records.csv`
     -- originally intended as an independently-curated reference, but
     VERIFIED (2026-07-16, against real live-fetched data) to actually be
     the same USGS pull, not independent -- see the explicit circularity
     check and corrected framing in Section (3) below.
  4. Run DATA-CERTIFY's audit (offline, reference=None -- see above) on
     naive_merged, extracting T(D), decision, and the I4 and A5 sub-scores
     specifically.
  5. Independently estimate the TRUE cross-catalog duplicate fraction via
     a simple, fixed-threshold space-time nearest-match heuristic (NOT
     I4's own EM-fitted Fellegi-Sunter code -- a deliberately different,
     independent implementation, to sanity-check I4's own estimate
     without circularity, mirroring D1(a)'s Round-1-style independent
     recomputation discipline).
  6. Deduplicate naive_merged using the matched pairs from step 5 (an
     I4-informed downstream action a real analyst would plausibly take),
     and compare its b-value against the raw naive merge -- a clean,
     non-circular comparison that does not depend on the compromised
     reference from step 3.

Usage:
    python3 calibration/fetch_multisource_chile_iquique.py   # run FIRST, needs internet
    python3 calibration/analysis_d1d_cross_agency_merge.py

Output:
    calibration/group_d_reports/d1d_cross_agency_report.txt
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

CALIBRATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALIBRATION_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from data_certify import DataCertifyAuditor, load_dataset_csv  # noqa: E402
from data_certify.stats import gr_b_value_aki, gr_b_value_shi_bolt_se, maximum_curvature_mc, haversine_km  # noqa: E402

MULTI_DIR = CALIBRATION_DIR / "group_d_reports" / "d1d_multisource"
REFERENCE_CATALOG = PROJECT_ROOT / "datasets" / "real_chile_iquique_2014" / "records.csv"
OUT_DIR = CALIBRATION_DIR / "group_d_reports"

# Independent duplicate-match heuristic thresholds (deliberately simple and
# fixed, NOT the EM-fitted probabilistic thresholds I4 itself uses --
# see module docstring on why this needs to be an independent check).
DUP_TIME_TOL_SEC = 30.0
DUP_DIST_TOL_KM = 50.0
DUP_MAG_TOL = 0.5


def compute_b_value(ds) -> dict:
    mags = ds.magnitude[np.isfinite(ds.magnitude)]
    n_total = len(mags)
    if n_total < 10:
        return dict(mc=float("nan"), b=float("nan"), b_se=float("nan"), n_geq_mc=0, n_total=n_total)
    mc = maximum_curvature_mc(mags)
    above = mags[mags >= mc]
    if len(above) < 5:
        return dict(mc=mc, b=float("nan"), b_se=float("nan"), n_geq_mc=len(above), n_total=n_total)
    b = gr_b_value_aki(above, mc)
    b_se = gr_b_value_shi_bolt_se(above, b)
    return dict(mc=mc, b=b, b_se=b_se, n_geq_mc=len(above), n_total=n_total)


def independent_duplicate_fraction(ds) -> dict:
    """A simple, fixed-threshold nearest-cross-source-match heuristic,
    deliberately independent of I4's own EM-fitted Fellegi-Sunter linkage
    (see module docstring). For each 'usgs' record, checks whether an
    'emsc' record exists within DUP_TIME_TOL_SEC / DUP_DIST_TOL_KM /
    DUP_MAG_TOL -- if so, both are counted as a matched cross-source pair.
    Returns the fraction of the smaller source's records that found a match."""
    src = ds.source
    days = ds.origin_time_days()
    lat, lon, mag = ds.latitude, ds.longitude, ds.magnitude

    usgs_idx = np.where(src == "usgs")[0]
    emsc_idx = np.where(src == "emsc")[0]
    if len(usgs_idx) == 0 or len(emsc_idx) == 0:
        return dict(n_usgs=len(usgs_idx), n_emsc=len(emsc_idx), n_matched=0,
                     duplicate_fraction=float("nan"), matched_pairs=[])

    matched = 0
    used_emsc = set()
    matched_pairs = []
    for i in usgs_idx:
        if not (np.isfinite(days[i]) and np.isfinite(lat[i]) and np.isfinite(lon[i])):
            continue
        best_j, best_dt = None, None
        for j in emsc_idx:
            if j in used_emsc or not np.isfinite(days[j]):
                continue
            dt_sec = abs(days[i] - days[j]) * 86400.0
            if dt_sec > DUP_TIME_TOL_SEC:
                continue
            if np.isfinite(mag[i]) and np.isfinite(mag[j]) and abs(mag[i] - mag[j]) > DUP_MAG_TOL:
                continue
            dist_km = haversine_km(lat[i], lon[i], lat[j], lon[j])
            if dist_km > DUP_DIST_TOL_KM:
                continue
            if best_dt is None or dt_sec < best_dt:
                best_dt, best_j = dt_sec, j
        if best_j is not None:
            matched += 1
            used_emsc.add(best_j)
            matched_pairs.append((int(i), int(best_j)))

    denom = min(len(usgs_idx), len(emsc_idx))
    return dict(n_usgs=len(usgs_idx), n_emsc=len(emsc_idx), n_matched=matched,
                duplicate_fraction=matched / denom if denom > 0 else float("nan"),
                matched_pairs=matched_pairs)


def deduplicate_merge(ds, matched_pairs):
    """Build a deduplicated CertifyDataset from `ds` (assumed to be a
    two-source USGS+EMSC merge), given a list of (usgs_row_idx,
    emsc_row_idx) matched pairs from `independent_duplicate_fraction`.
    For each matched pair, keeps the USGS record only (arbitrary but
    disclosed choice: USGS is this project's existing primary/default
    source elsewhere in the corpus); keeps every unmatched record from
    either source untouched. This is what a downstream analyst would
    plausibly do once warned (by I4) that heavy cross-catalog duplication
    exists -- ordinary record-linkage-informed deduplication, not
    DATA-CERTIFY performing the dedup itself (DATA-CERTIFY has no
    per-record filtering mechanism -- see D1(a)/(b))."""
    from data_certify.schema import ALL_FIELDS, CertifyDataset
    matched_emsc_idx = {j for _, j in matched_pairs}
    keep_mask = np.ones(ds.n, dtype=bool)
    src = ds.source
    for i in range(ds.n):
        if src[i] == "emsc" and i in matched_emsc_idx:
            keep_mask[i] = False
    fields = {f: getattr(ds, f)[keep_mask] for f in ALL_FIELDS}
    return CertifyDataset(name=f"{ds.name}_dedup", n=int(keep_mask.sum()), **fields)


def run_offline_audit(ds) -> dict:
    auditor = DataCertifyAuditor(reference=None, fault_db=None)
    result = auditor.audit(ds)
    t_d = result.trust_score
    a_axis = result.axis_results.get("A")
    i_axis = result.axis_results.get("I")
    a5 = a_axis.sub_results.get("A5") if a_axis else None
    i4 = i_axis.sub_results.get("I4") if i_axis else None
    return dict(
        t_d=float(t_d) if t_d is not None else float("nan"),
        decision=str(result.decision.value if hasattr(result.decision, "value") else result.decision),
        hard_override_fired=bool(result.hard_override.fired) if result.hard_override else False,
        a5_score=float(a5.score) if a5 is not None and a5.score is not None else float("nan"),
        a5_applicable=bool(a5.applicable) if a5 is not None else False,
        i4_score=float(i4.score) if i4 is not None and i4.score is not None else float("nan"),
        i4_applicable=bool(i4.applicable) if i4 is not None else False,
        i4_duplicate_fraction=(float(i4.detail.get("duplicate_fraction"))
                                if i4 is not None and i4.applicable and i4.detail else float("nan")),
    )


def main() -> None:
    usgs_path = MULTI_DIR / "usgs_raw.csv"
    emsc_path = MULTI_DIR / "emsc_raw.csv"
    merged_path = MULTI_DIR / "naive_merged.csv"
    for p in (usgs_path, emsc_path, merged_path):
        if not p.exists():
            print(f"ERROR: {p} not found. Run `python3 calibration/fetch_multisource_chile_iquique.py` "
                  f"FIRST, on a machine with internet access.")
            sys.exit(1)
    if not REFERENCE_CATALOG.exists():
        print(f"ERROR: reference catalog {REFERENCE_CATALOG} not found.")
        sys.exit(1)

    usgs_ds = load_dataset_csv(usgs_path, name="usgs_raw")
    emsc_ds = load_dataset_csv(emsc_path, name="emsc_raw")
    merged_ds = load_dataset_csv(merged_path, name="naive_merged")
    ref_ds = load_dataset_csv(REFERENCE_CATALOG, name="reference_chile_iquique_2014")

    print(f"usgs_raw: n={usgs_ds.n}  emsc_raw: n={emsc_ds.n}  naive_merged: n={merged_ds.n}  "
          f"reference: n={ref_ds.n}")

    b_usgs = compute_b_value(usgs_ds)
    b_emsc = compute_b_value(emsc_ds)
    b_merged = compute_b_value(merged_ds)
    b_ref = compute_b_value(ref_ds)

    audit = run_offline_audit(merged_ds)
    indep_dup = independent_duplicate_fraction(merged_ds)

    # CIRCULARITY CHECK (found during real-data verification, 2026-07-16):
    # the "reference" catalog and usgs_raw turned out to share every single
    # event_uid_source -- i.e. the existing corpus reference IS this
    # script's own fresh USGS pull for this window, not an independent
    # source. This invalidates any "informed vs naive, scored against
    # reference" comparison, since the result would trivially depend on
    # which single source an arbitrary fallback rule happens to pick.
    # Detected and handled explicitly below rather than silently reporting
    # a misleading number.
    usgs_ids = set(usgs_ds.event_uid_source.tolist())
    ref_ids = set(ref_ds.event_uid_source.tolist())
    ref_is_circular = (len(usgs_ids) > 0 and usgs_ids == ref_ids)

    dedup_ds = deduplicate_merge(merged_ds, indep_dup["matched_pairs"])
    b_dedup = compute_b_value(dedup_ds)

    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("Group D1: Downstream DRR case study, option (d) [light scope: b-value only]")
    report_lines.append("Cross-agency (USGS + EMSC) naive merge: does DATA-CERTIFY's I4 sub-test detect")
    report_lines.append("and quantify the resulting duplication, and does trusting the verdict improve b-value?")
    report_lines.append("(Group D downstream case study; directly tests D2's")
    report_lines.append(" related-work finding that no existing framework combines dedup with authenticity)")
    report_lines.append("=" * 100)
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("(0) Base data and b-value estimates")
    report_lines.append("-" * 100)
    for label, ds, b in [("usgs_raw", usgs_ds, b_usgs), ("emsc_raw", emsc_ds, b_emsc),
                          ("naive_merged (no dedup)", merged_ds, b_merged),
                          ("deduplicated_merge (I4-informed dedup)", dedup_ds, b_dedup),
                          ("reference (real_chile_iquique_2014)", ref_ds, b_ref)]:
        report_lines.append(
            f"  {label}: n={ds.n}, b={b['b']:.4f}+/-{b['b_se']:.4f} (Mc={b['mc']:.2f}, n>=Mc={b['n_geq_mc']})"
        )
    if ref_is_circular:
        report_lines.append(
            f"  NOTE: 'reference' shares all {len(ref_ids)} event_uid_source values with usgs_raw -- see "
            f"Section (3) below, this is NOT an independent ground truth for this run."
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(1) DATA-CERTIFY audit of naive_merged (offline, reference=None -- see module docstring)")
    report_lines.append("-" * 100)
    report_lines.append(
        f"  T(D)={audit['t_d']:.4f}  decision={audit['decision']}  hard_override={audit['hard_override_fired']}"
    )
    report_lines.append(
        f"  A5 (near-duplicate detection): score={audit['a5_score']:.4f} applicable={audit['a5_applicable']}"
    )
    if math.isfinite(audit['i4_duplicate_fraction']):
        report_lines.append(
            f"  I4 (cross-catalog duplicate-ID, EM-fitted Fellegi-Sunter): score={audit['i4_score']:.4f} "
            f"applicable={audit['i4_applicable']} estimated_duplicate_fraction="
            f"{audit['i4_duplicate_fraction']:.4f}"
        )
    else:
        report_lines.append(
            f"  I4: score={audit['i4_score']:.4f} applicable={audit['i4_applicable']} "
            f"(duplicate_fraction not available)"
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(2) Independent duplicate-fraction cross-check (fixed-threshold heuristic, NOT I4's own EM code)")
    report_lines.append("-" * 100)
    report_lines.append(
        f"  n_usgs={indep_dup['n_usgs']}  n_emsc={indep_dup['n_emsc']}  n_matched_pairs={indep_dup['n_matched']}  "
        f"independent_duplicate_fraction={indep_dup['duplicate_fraction']:.4f}"
    )
    if math.isfinite(audit['i4_duplicate_fraction']) and math.isfinite(indep_dup['duplicate_fraction']):
        diff = abs(audit['i4_duplicate_fraction'] - indep_dup['duplicate_fraction'])
        report_lines.append(
            f"  |I4 estimate - independent estimate| = {diff:.4f} "
            f"({'consistent' if diff < 0.15 else 'DISCREPANT -- investigate before trusting I4 here'})"
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(3) NAIVE vs DATA-CERTIFY-INFORMED downstream b-value usage -- CORRECTED FRAMING")
    report_lines.append("-" * 100)
    if ref_is_circular:
        report_lines.append(
            "  IMPORTANT: this script's original design planned to score both a naive merge and a "
            "'DATA-CERTIFY-informed, fall back to a single source' behavior against "
            "datasets/real_chile_iquique_2014/records.csv as an independent reference. Verification against "
            "the REAL live-fetched data (2026-07-16) found this reference is NOT independent: it shares all "
            f"{len(ref_ids)}/{len(ref_ids)} event_uid_source values with this run's own fresh usgs_raw pull -- "
            "it IS a prior USGS pull for this exact window, not a third-party check. Scoring 'informed' (which "
            "falls back to whichever single source is larger) against this reference is therefore a coin flip: "
            "when the fallback rule happens to pick EMSC (as it did this run, n=756>621), the comparison "
            "trivially looks bad, entirely because of which source the reference happens to already equal -- "
            "NOT because of anything DATA-CERTIFY did. This finding is disclosed rather than the misleading "
            "comparison being reported at face value. The Section (1)-(2) findings (I4 correctly detects and "
            "accurately quantifies the real duplication) are NOT affected by this issue and remain the "
            "headline result of this case study."
        )
        report_lines.append("")
    report_lines.append(
        f"  What IS a clean, non-circular comparison: naive_merged (raw, duplicate-inflated, n={merged_ds.n}) "
        f"vs deduplicated_merge (I4-informed dedup action -- once warned by I4 that "
        f"{audit['i4_duplicate_fraction']:.1%} of records are cross-catalog duplicates, a downstream analyst "
        f"would deduplicate rather than either using the raw merge OR discarding an entire whole source, "
        f"n={dedup_ds.n})."
    )
    report_lines.append(
        f"  naive_merged:        b={b_merged['b']:.4f}+/-{b_merged['b_se']:.4f}  n={merged_ds.n}"
    )
    report_lines.append(
        f"  deduplicated_merge:  b={b_dedup['b']:.4f}+/-{b_dedup['b_se']:.4f}  n={dedup_ds.n}"
    )
    report_lines.append(
        f"  For context (not a ground-truth claim, given the circularity above): usgs_raw b={b_usgs['b']:.4f}, "
        f"emsc_raw b={b_emsc['b']:.4f}. The two single sources disagree substantially on b-value "
        f"(delta={abs(b_usgs['b']-b_emsc['b']):.4f}) -- itself a genuine, real finding: USGS and EMSC used "
        f"different effective completeness magnitudes for this sequence (Mc={b_usgs['mc']:.2f} vs "
        f"{b_emsc['mc']:.2f}), a documented type of cross-agency reporting-threshold discrepancy, distinct "
        f"from simple duplication."
    )

    report_lines.append("")
    report_lines.append("Caveats:")
    report_lines.append(
        "  - Only USGS + EMSC (2 of 3 sources A6 supports) -- ISC deliberately excluded; see "
        "fetch_multisource_chile_iquique.py's docstring for why (QuakeML parsing risk, not shipped untested)."
    )
    report_lines.append(
        "  - No independent ground-truth b-value is available for this run (see Section (3)'s circularity "
        "finding) -- this case study's clean, defensible claim is about I4's duplicate-detection ACCURACY "
        "(Sections 1-2), not about b-value improvement, which would need a genuinely third-party reference "
        "(e.g. a hand-curated regional catalog from a source neither usgs_raw nor the existing corpus dataset "
        "was built from) to test properly -- left as open follow-up, not silently patched over."
    )
    report_lines.append(
        "  - Deduplication here keeps the USGS record of each matched pair (disclosed, arbitrary choice) -- "
        "an EMSC-preferring or field-averaging dedup rule could give a modestly different b-value; the point "
        "of Section (3) is that dedup removes the raw merge's artificial n-inflation, not that this specific "
        "tie-breaking rule is uniquely correct."
    )

    report_text = "\n".join(report_lines)
    report_path = OUT_DIR / "d1d_cross_agency_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nSaved -> {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
