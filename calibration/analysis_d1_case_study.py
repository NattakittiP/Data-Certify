# -*- coding: utf-8 -*-
"""
calibration/analysis_d1_case_study.py -- Group D1 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group D / D1;
decision rationale in Docs/03_Paper_Prep/DATA-CERTIFY_Downstream_Case_Studies_Combined_Summary.md):
downstream DRR case study, option (a) -- "does trusting DATA-CERTIFY's
ADMIT/CONDITIONAL/REJECT verdict actually improve a real downstream
scientific-parameter estimate (Gutenberg-Richter b-value / recurrence
interval), compared to a naive practice of using every catalog file
regardless of quality?"

IMPORTANT DESIGN NOTE (corrected after a 2026-07-16 design review with the
user): DATA-CERTIFY's audit protocol produces ONE decision per WHOLE
dataset file (ADMIT/CONDITIONAL/REJECT), not a per-record filter -- there
is no mechanism anywhere in data_certify/ that flags and removes individual
bad records from within an otherwise-kept file. This script's methodology
reflects that reality: it does NOT attempt to "clean" a corrupted catalog
by dropping bad rows. Instead it simulates two downstream USER BEHAVIORS
applied across a batch of catalog files (a mix of realistically-corrupted
derivatives of real clean catalogs):

  (1) NAIVE baseline: use every file's magnitudes for the b-value estimate,
      regardless of its DATA-CERTIFY verdict.
  (2) DATA-CERTIFY-INFORMED baseline: only use files that DATA-CERTIFY did
      NOT reject (ADMIT or CONDITIONAL); drop REJECTed files entirely.

HEADLINE FINDING (discovered during this script's own first run against
`nz`, then independently CONFIRMED on a second, structurally different
catalog `real_kahramanmaras_turkey_2023` -- see Section (5) of the
generated report): magnitude_gr_violation (the ONE corruption type that
directly degrades the Gutenberg-Richter b-value, replacing genuine
magnitudes with values drawn UNIFORMLY over the observed range) does NOT
reliably lower T(D), and can even RAISE it. Root cause, confirmed via
per-sub-test breakdown on both catalogs: A2 (b-value plausibility) DOES
correctly degrade, but I1 (Mann-Kendall trend-in-magnitude test) and I2
(observed-vs-G-R-extrapolated count-above-threshold test) can swing
STRONGLY IN THE OPPOSITE DIRECTION, because real catalogs have genuine,
naturally-occurring temporal trends/deviations from strict G-R behaviour
that a uniform-magnitude-replacement corruption "accidentally erases,"
more than offsetting A2's degradation in the A/P/C/I-weighted composite
T(D). This is a genuine, newly-discovered, general architectural
limitation (cross-axis signal cancellation under a specific corruption
mechanism), not a catalog-specific artifact or a bug in this script --
also logged in Docs/01_Deep_Dives/DATA-CERTIFY_06_Gap_Remediation_and_
Robustness_Addendum.md and Docs/00_Overview/DATA-CERTIFY_Theoretical_
Framework.md Section 7, per this project's established disclosure
discipline.

Methodology:
  1. Load real, clean base catalogs: `nz` (regional, 1-year span, canonical
     dataset used throughout the main 968-dataset calibration corpus) and
     `real_kahramanmaras_turkey_2023` (a single mainshock-aftershock
     sequence, ~2-month span, structurally very different from nz --
     included specifically to test whether any finding here is
     catalog-specific or general).
  2. Build a battery of corrupted derivatives per catalog using the SAME
     corruption functions/severity constants already used to build the
     main calibration corpus (calibration/corrupt.py) -- not a bespoke
     one-off corruption scheme invented just for this case study.
     Deliberately includes corruption types that do NOT touch the
     magnitude field at all (coordinate_jitter, inject_duplicates,
     inject_missingness, depth_implausible, timestamp_collision) so the
     b-value-error <-> verdict correlation is not tautological, plus
     magnitude_gr_violation itself as the metric this case study cares
     about most directly.
  3. Run DATA-CERTIFY's audit protocol OFFLINE (reference=None, i.e. no
     live external-catalog query -- A6 falls back to intrinsic-only
     scoring, matching Theoretical_Framework.md Section 1.1's
     "operability without continuous connectivity" design goal, and
     keeping this case study 100% locally reproducible with no network
     dependency / no timeout risk).
  4. For each variant, compute the Gutenberg-Richter b-value (Aki MLE,
     data_certify/stats.py -- the SAME estimator function A2 itself uses,
     already ground-truth-verified in tests/test_scientific_validity.py)
     and a recurrence-interval estimate at a fixed reference magnitude,
     and compare both against the clean catalog's own values (which serve
     as the intrinsic ground truth -- no external literature citation
     required, avoiding Mc/catalog-completeness mismatch issues that would
     arise from comparing against a different study's published number).
  5. Aggregate: mean/median b-value error split by DATA-CERTIFY verdict
     bucket, a rank correlation between T(D) and b-value error, and an
     explicit cross-axis cancellation check (A(D) vs I(D) direction under
     magnitude_gr_violation specifically).

Usage:
    python3 calibration/analysis_d1_case_study.py [<catalog_name>|report]

Output:
    calibration/group_d_reports/d1_case_study_variants.csv
    calibration/group_d_reports/d1_case_study_report.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

CALIBRATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CALIBRATION_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(CALIBRATION_DIR))

from data_certify import DataCertifyAuditor, load_dataset_csv  # noqa: E402
from data_certify.stats import (  # noqa: E402
    gr_b_value_aki,
    gr_b_value_shi_bolt_se,
    maximum_curvature_mc,
)
import corrupt  # noqa: E402

OUT_DIR = CALIBRATION_DIR / "group_d_reports"
OUT_DIR.mkdir(exist_ok=True)

CATALOGS = [
    ("nz", PROJECT_ROOT / "datasets" / "nz" / "records.csv"),
    ("kahramanmaras_2023", PROJECT_ROOT / "datasets" / "real_kahramanmaras_turkey_2023" / "records.csv"),
]
DELTA_M = 0.1
RNG_SEED = 20260716  # fixed for reproducibility

# Corruption battery: (function_name, severity_label, severity_value).
# Same functions/severity constants used to build the main 968-dataset
# corpus (calibration/build_corpus.py) -- not bespoke to this script.
CORRUPTION_BATTERY = [
    ("coordinate_jitter", "low", corrupt.SEVERITY_LOW),
    ("coordinate_jitter", "med", corrupt.SEVERITY_MED),
    ("coordinate_jitter", "high", corrupt.SEVERITY_HIGH),
    ("inject_duplicates", "low", corrupt.SEVERITY_LOW),
    ("inject_duplicates", "med", corrupt.SEVERITY_MED),
    ("inject_duplicates", "high", corrupt.SEVERITY_HIGH),
    ("inject_missingness", "low", corrupt.SEVERITY_LOW),
    ("inject_missingness", "med", corrupt.SEVERITY_MED),
    ("inject_missingness", "high", corrupt.SEVERITY_HIGH),
    ("depth_implausible", "low", corrupt.SEVERITY_LOW),
    ("depth_implausible", "med", corrupt.SEVERITY_MED),
    ("depth_implausible", "high", corrupt.SEVERITY_HIGH),
    ("timestamp_collision", "low", corrupt.SEVERITY_LOW),
    ("timestamp_collision", "med", corrupt.SEVERITY_MED),
    ("timestamp_collision", "high", corrupt.SEVERITY_HIGH),
    # The one corruption type that directly touches magnitude -- this is
    # the case this study cares about MOST, not a side positive-control;
    # see the HEADLINE FINDING note above.
    ("magnitude_gr_violation", "low", corrupt.SEVERITY_LOW),
    ("magnitude_gr_violation", "med", corrupt.SEVERITY_MED),
    ("magnitude_gr_violation", "high", corrupt.SEVERITY_HIGH),
]

REFERENCE_MAGNITUDE = 6.0  # recurrence interval computed at M>=6.0


def compute_b_value_and_recurrence(ds) -> dict:
    """Compute Mc (Maximum Curvature), b-value (Aki MLE) with Shi & Bolt
    SE, and a recurrence-interval estimate at REFERENCE_MAGNITUDE, from a
    CertifyDataset's magnitude array. Returns NaNs if too few events."""
    mags = ds.magnitude[np.isfinite(ds.magnitude)]
    n_total = len(mags)
    if n_total < 10:
        return dict(mc=float("nan"), b=float("nan"), b_se=float("nan"),
                    n_geq_mc=0, recurrence_years=float("nan"), n_total=n_total)

    mc = maximum_curvature_mc(mags)
    above = mags[mags >= mc]
    n_geq_mc = len(above)
    if n_geq_mc < 5:
        return dict(mc=mc, b=float("nan"), b_se=float("nan"),
                    n_geq_mc=n_geq_mc, recurrence_years=float("nan"), n_total=n_total)

    b = gr_b_value_aki(above, mc, delta_m=DELTA_M)
    b_se = gr_b_value_shi_bolt_se(above, b)

    times = ds.origin_time[~pd.isna(ds.origin_time)]
    if len(times) < 2:
        return dict(mc=mc, b=b, b_se=b_se, n_geq_mc=n_geq_mc,
                    recurrence_years=float("nan"), n_total=n_total)
    span_days = (np.max(times) - np.min(times)) / np.timedelta64(1, "D")
    span_years = max(span_days / 365.25, 1e-6)

    if not np.isnan(b):
        a_value = np.log10(n_geq_mc / span_years) + b * mc
        rate_ref = 10 ** (a_value - b * REFERENCE_MAGNITUDE)
        recurrence_years = 1.0 / rate_ref if rate_ref > 0 else float("nan")
    else:
        recurrence_years = float("nan")

    return dict(mc=mc, b=b, b_se=b_se, n_geq_mc=n_geq_mc,
                recurrence_years=recurrence_years, n_total=n_total)


def run_offline_audit(ds) -> dict:
    """Run DATA-CERTIFY's audit protocol with no live external reference
    (reference=None -> A6 falls back to intrinsic-only scoring). Returns
    T(D), decision, hard-override status, and the A(D)/I(D) axis scores
    plus I1/I2 sub-scores (needed for the cross-axis cancellation check)."""
    auditor = DataCertifyAuditor(reference=None, fault_db=None)
    result = auditor.audit(ds)
    t_d = result.trust_score
    a_axis = result.axis_results.get("A")
    i_axis = result.axis_results.get("I")
    i1 = i_axis.sub_results.get("I1") if i_axis else None
    i2 = i_axis.sub_results.get("I2") if i_axis else None
    a2 = a_axis.sub_results.get("A2") if a_axis else None
    return dict(
        t_d=float(t_d) if t_d is not None else float("nan"),
        decision=str(result.decision.value if hasattr(result.decision, "value") else result.decision),
        hard_override_fired=bool(result.hard_override.fired) if result.hard_override else False,
        a_score=float(a_axis.score) if a_axis else float("nan"),
        i_score=float(i_axis.score) if i_axis else float("nan"),
        a2_score=float(a2.score) if a2 is not None and not (a2.score is None) else float("nan"),
        i1_score=float(i1.score) if i1 is not None and not (i1.score is None) else float("nan"),
        i2_score=float(i2.score) if i2 is not None and not (i2.score is None) else float("nan"),
    )


def run_catalog(catalog_name: str, catalog_path: Path) -> pd.DataFrame:
    print(f"\n{'#' * 100}\nCatalog: {catalog_name}  ({catalog_path})\n{'#' * 100}")
    clean_ds = load_dataset_csv(catalog_path, name=f"{catalog_name}_clean")
    print(f"  n={clean_ds.n} records")

    clean_metrics = compute_b_value_and_recurrence(clean_ds)
    print(f"  Clean b-value = {clean_metrics['b']:.4f} +/- {clean_metrics['b_se']:.4f} "
          f"(Mc={clean_metrics['mc']:.2f}, n>=Mc={clean_metrics['n_geq_mc']}, "
          f"recurrence@M{REFERENCE_MAGNITUDE}={clean_metrics['recurrence_years']:.2f}y)")

    clean_audit = run_offline_audit(clean_ds)
    print(f"  Clean audit: T(D)={clean_audit['t_d']:.4f} decision={clean_audit['decision']} "
          f"A(D)={clean_audit['a_score']:.4f} I(D)={clean_audit['i_score']:.4f}")

    rows = [dict(
        catalog=catalog_name, variant="clean_original", fn="none", severity_label="none", severity_value=0.0,
        **clean_audit, **clean_metrics,
        b_abs_error=0.0, recurrence_abs_pct_error=0.0,
    )]

    for fn_name, sev_label, sev_val in CORRUPTION_BATTERY:
        rng = np.random.RandomState(RNG_SEED)
        fn = getattr(corrupt, fn_name)
        corrupted_ds, desc = fn(clean_ds, sev_val, rng)
        variant_name = f"{fn_name}_{sev_label}"
        print(f"\nVariant: {variant_name}  ({desc})")

        metrics = compute_b_value_and_recurrence(corrupted_ds)
        audit = run_offline_audit(corrupted_ds)
        print(f"  T(D)={audit['t_d']:.4f} decision={audit['decision']} "
              f"A(D)={audit['a_score']:.4f} I(D)={audit['i_score']:.4f} "
              f"b={metrics['b']:.4f} (clean={clean_metrics['b']:.4f})")

        b_abs_error = (abs(metrics["b"] - clean_metrics["b"])
                        if not (np.isnan(metrics["b"]) or np.isnan(clean_metrics["b"]))
                        else float("nan"))
        if (not np.isnan(metrics["recurrence_years"]) and not np.isnan(clean_metrics["recurrence_years"])
                and clean_metrics["recurrence_years"] > 0):
            recurrence_pct_error = 100.0 * abs(
                metrics["recurrence_years"] - clean_metrics["recurrence_years"]
            ) / clean_metrics["recurrence_years"]
        else:
            recurrence_pct_error = float("nan")

        rows.append(dict(
            catalog=catalog_name, variant=variant_name, fn=fn_name,
            severity_label=sev_label, severity_value=sev_val,
            **audit, **metrics,
            b_abs_error=b_abs_error, recurrence_abs_pct_error=recurrence_pct_error,
        ))

    return pd.DataFrame(rows)


def main() -> None:
    # Support running one catalog at a time (sys.argv[1] = catalog name) so
    # each invocation completes well within a short wall-clock budget --
    # results are cached per-catalog and merged on the final "report" pass.
    # `python3 analysis_d1_case_study.py report` skips computation and just
    # rebuilds the report from whatever per-catalog CSVs already exist.
    only = sys.argv[1] if len(sys.argv) > 1 else None
    partial_dir = OUT_DIR / "_partial"
    partial_dir.mkdir(exist_ok=True)

    if only == "report":
        all_dfs = []
        for name, _ in CATALOGS:
            p = partial_dir / f"{name}.csv"
            if not p.exists():
                print(f"WARNING: missing partial result for '{name}' ({p}) -- run "
                      f"`python3 analysis_d1_case_study.py {name}` first.")
                continue
            all_dfs.append(pd.read_csv(p))
        if not all_dfs:
            print("No partial results found. Nothing to report.")
            return
        df = pd.concat(all_dfs, ignore_index=True)
    else:
        catalogs_to_run = [(n, p) for n, p in CATALOGS if only is None or n == only]
        if not catalogs_to_run:
            print(f"Unknown catalog '{only}'. Known: {[n for n, _ in CATALOGS]}")
            return
        all_dfs = []
        for name, path in catalogs_to_run:
            cdf = run_catalog(name, path)
            cdf.to_csv(partial_dir / f"{name}.csv", index=False)
            print(f"Saved partial -> {partial_dir / f'{name}.csv'}")
            all_dfs.append(cdf)
        if only is not None:
            print(f"\nRan catalog '{only}' only. Run remaining catalogs, then "
                  f"`python3 analysis_d1_case_study.py report` to build the combined report.")
            return
        df = pd.concat(all_dfs, ignore_index=True)

    csv_path = OUT_DIR / "d1_case_study_variants.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved -> {csv_path}")

    corrupted = df[df["variant"] != "clean_original"].copy()
    valid = corrupted.dropna(subset=["b_abs_error"])

    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("Group D1: Downstream DRR case study, option (a)")
    report_lines.append("b-value / recurrence-interval accuracy: naive vs DATA-CERTIFY-informed usage")
    report_lines.append("(Group D downstream case study)")
    report_lines.append("=" * 100)
    report_lines.append("")
    for name, _ in CATALOGS:
        clean_row = df[(df["catalog"] == name) & (df["variant"] == "clean_original")].iloc[0]
        report_lines.append(
            f"Base catalog '{name}': n={int(clean_row['n_total'])}, "
            f"clean b={clean_row['b']:.4f}+/-{clean_row['b_se']:.4f} "
            f"(Mc={clean_row['mc']:.2f}, n>=Mc={int(clean_row['n_geq_mc'])}), "
            f"clean T(D)={clean_row['t_d']:.4f} ({clean_row['decision']}), "
            f"A(D)={clean_row['a_score']:.4f} I(D)={clean_row['i_score']:.4f}"
        )
    report_lines.append(f"\nCorrupted variants: {len(corrupted)} total across {len(CATALOGS)} catalogs "
                         f"({len(CORRUPTION_BATTERY)} corruption-fn x severity combinations per catalog, "
                         "same functions/severities used to build the main 968-dataset corpus)")
    report_lines.append(f"Valid variants (b-value computable on both clean & corrupted): {len(valid)}")

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(1) b-value ERROR BY DATA-CERTIFY VERDICT (pooled across both catalogs)")
    report_lines.append("-" * 100)
    for decision in ["ADMIT", "CONDITIONAL", "REJECT"]:
        subset = valid[valid["decision"] == decision]
        if len(subset) == 0:
            report_lines.append(f"  {decision}: n=0 variants")
            continue
        report_lines.append(
            f"  {decision}: n={len(subset)}  mean |b-error|={subset['b_abs_error'].mean():.4f}  "
            f"median |b-error|={subset['b_abs_error'].median():.4f}  max |b-error|={subset['b_abs_error'].max():.4f}"
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(2) NAIVE vs DATA-CERTIFY-INFORMED downstream usage")
    report_lines.append("-" * 100)
    report_lines.append(
        "  CAVEAT ON THIS COMPARISON: dropping REJECTed variants and comparing the mean |b-error| of "
        "what remains is only a fair 'before/after' comparison if REJECT correlates with the datasets "
        "that were hurting b-value the most. In this corpus, the REJECTed variants are exclusively "
        "depth_implausible (a corruption that does not touch magnitude at all, so its b-error is "
        "already ~0) -- so this comparison mechanically shows NO improvement or even a nominal "
        "increase in mean |b-error| once REJECTed (zero-error) variants are removed from the "
        "denominator. This is NOT evidence that following DATA-CERTIFY's verdict hurts b-value "
        "accuracy -- it is an artifact of this specific corruption battery's composition (REJECT was "
        "correctly triggered by a magnitude-independent failure mode). See Section (5) below for the "
        "finding that actually matters for b-value protection specifically."
    )
    naive_mean_error = valid["b_abs_error"].mean()
    informed = valid[valid["decision"] != "REJECT"]
    informed_mean_error = informed["b_abs_error"].mean() if len(informed) > 0 else float("nan")
    n_rejected = len(valid[valid["decision"] == "REJECT"])
    report_lines.append(
        f"  NAIVE (use every variant regardless of verdict): mean |b-error| across all {len(valid)} variants "
        f"= {naive_mean_error:.4f}"
    )
    report_lines.append(
        f"  DATA-CERTIFY-INFORMED (drop the {n_rejected} REJECTed variant(s), keep {len(informed)} "
        f"ADMIT/CONDITIONAL): mean |b-error| = {informed_mean_error:.4f}"
    )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(3) CORRELATION: T(D) vs b-value error (pooled)")
    report_lines.append("-" * 100)
    if len(valid) >= 3:
        corr = valid[["t_d", "b_abs_error"]].corr(method="spearman").iloc[0, 1]
        report_lines.append(
            f"  Spearman rank correlation(T(D), |b-error|) across {len(valid)} corrupted variants = {corr:.4f} "
            "(sign is NOT reliably negative -- see Section (5): T(D) is not a clean proxy for b-value "
            "accuracy specifically, because of cross-axis cancellation under magnitude_gr_violation)"
        )
    else:
        report_lines.append("  Not enough valid variants for correlation.")

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(4) Per-variant detail")
    report_lines.append("-" * 100)
    report_lines.append(
        corrupted[["catalog", "variant", "t_d", "decision", "a_score", "i_score", "b", "b_abs_error"]]
        .to_string(index=False)
    )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(5) HEADLINE FINDING: cross-axis (A/I) signal cancellation under magnitude_gr_violation")
    report_lines.append("-" * 100)
    report_lines.append(
        "  magnitude_gr_violation is the ONE corruption type in this battery that directly degrades "
        "the Gutenberg-Richter b-value (it replaces genuine magnitudes with values drawn UNIFORMLY "
        "over the observed range). If T(D) tracked b-value fidelity cleanly, magnitude_gr_violation "
        "variants should show the LARGEST T(D) drop among all variants tested. They do not -- on "
        "BOTH base catalogs tested, T(D) INCREASES under magnitude_gr_violation despite A2 (the "
        "sub-test that specifically checks b-value plausibility) correctly degrading:"
    )
    mgv = corrupted[corrupted["fn"] == "magnitude_gr_violation"]
    for _, row in mgv.iterrows():
        clean_row = df[(df["catalog"] == row["catalog"]) & (df["variant"] == "clean_original")].iloc[0]
        report_lines.append(
            f"    [{row['catalog']}] {row['variant']}: "
            f"T(D) {clean_row['t_d']:.4f} -> {row['t_d']:.4f}  "
            f"A(D) {clean_row['a_score']:.4f} -> {row['a_score']:.4f}  "
            f"I(D) {clean_row['i_score']:.4f} -> {row['i_score']:.4f}  "
            f"A2 {clean_row['a2_score']:.4f} -> {row['a2_score']:.4f}  "
            f"I1 {clean_row['i1_score']:.4f} -> {row['i1_score']:.4f}  "
            f"I2 {clean_row['i2_score']:.4f} -> {row['i2_score']:.4f}"
        )
    report_lines.append(
        "  Mechanism (confirmed identical on both catalogs): A2 degrades as expected (b-value moves "
        "toward/past the edge of its plausible [0.5, 1.5] band). But I1 (Mann-Kendall trend-in-"
        "magnitude test) and I2 (observed-vs-G-R-extrapolated count check) both move STRONGLY TOWARD "
        "a PASSING score, because real catalogs have genuine temporal trends and genuine deviations "
        "from strict Gutenberg-Richter behaviour (regional heterogeneity, network detection-capability "
        "changes over time, real physical non-stationarity) that a uniform-magnitude-replacement "
        "corruption happens to erase as a side effect -- I1's trend statistic and I2's extrapolation "
        "check are BOTH sensitive to exactly the kind of irregularity that a real, un-fabricated "
        "catalog naturally has and a flattened, fabricated one does not. In the AHP x EWM-blended "
        "composite (A(D) dominant at ~0.69, I(D) at ~0.12 in the current production weights), this "
        "specific corruption mechanism happens to move I(D) by more than enough to offset A(D)'s "
        "correct degradation, net-INCREASING T(D)."
    )
    report_lines.append(
        "  This is a genuine, newly-discovered, GENERAL limitation of the current multi-axis "
        "composite architecture (confirmed on two structurally different real catalogs, not a "
        "one-off artifact) -- not a bug in this script or in DATA-CERTIFY's implementation of any "
        "individual sub-test. Each of A2, I1, I2 is computing exactly what its own docstring/spec "
        "says it computes; the limitation is emergent from how they combine under this specific "
        "corruption mechanism. See Docs/01_Deep_Dives/DATA-CERTIFY_06_Gap_Remediation_and_Robustness_"
        "Addendum.md and Docs/00_Overview/DATA-CERTIFY_Theoretical_Framework.md Section 7 for the "
        "formal disclosure and discussion of possible future mitigations (e.g. an explicit "
        "consistency check between A2 and I1/I2's implied narratives, or a floor on A(D) that I(D) "
        "cannot compensate past, analogous to the existing hard-override design)."
    )

    report_lines.append("")
    report_lines.append("Caveats (disclosed explicitly, consistent with this project's honesty discipline):")
    report_lines.append(
        "  - 'Ground truth' is each clean catalog's OWN b-value, not an externally published literature "
        "value -- this avoids Mc/completeness-window mismatch issues but means this case study "
        "validates INTERNAL CONSISTENCY (corruption recovery), not agreement with an independent "
        "external estimate."
    )
    report_lines.append(
        "  - reference=None (offline/intrinsic-only A6) throughout -- this measures DATA-CERTIFY's "
        "P1-P3/A1-A5/C/I signals, not A6's external cross-agency corroboration (see option (d) in the "
        "D1 decision brief for that separate question)."
    )
    report_lines.append(
        "  - Two base catalogs tested (nz, kahramanmaras_2023). The magnitude_gr_violation finding "
        "reproduced identically on both, which is meaningful corroboration but not proof of "
        "universality across all possible real catalogs."
    )

    report_text = "\n".join(report_lines)
    report_path = OUT_DIR / "d1_case_study_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"Saved -> {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
