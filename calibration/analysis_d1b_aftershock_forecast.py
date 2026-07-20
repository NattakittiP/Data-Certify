# -*- coding: utf-8 -*-
"""
calibration/analysis_d1b_aftershock_forecast.py -- Group D1 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md, Group D / D1;
decision rationale in Docs/03_Paper_Prep/DATA-CERTIFY_Downstream_Case_Studies_Combined_Summary.md):
downstream DRR case study, option (b) -- "does trusting DATA-CERTIFY's
ADMIT/CONDITIONAL/REJECT verdict actually improve a real downstream
aftershock-forecast-accuracy estimate (Omori-Utsu K/c/p fit -> forecasted
event count in a held-out window), compared to a naive practice of using
every catalog file regardless of quality -- and separately, does
correcting for Short-Term Aftershock Incompleteness (STAI) matter on its
own, independent of any corruption at all?"

DESIGN NOTE ON STAI (the domain risk explicitly flagged for this option in
the D1 decision brief): DATA-CERTIFY's own A3 sub-test
(data_certify/axis_authenticity.py, _score_a3_omori_utsu /
_identify_mainshock_aftershock_clusters) does NOT correct for STAI -- it
fits stats.fit_omori_utsu() directly on every candidate-aftershock time
starting at t>0, with no early-time exclusion and no magnitude-dependent
completeness filter. This case study does NOT reuse A3's windowing
uncritically; it implements its own explicit, literature-grounded STAI
correction, and treats "how much does that correction actually matter"
as one of its own reported findings (Section 7 below), not an assumed fact.

STAI correction method (grounded, not an arbitrary cutoff): Helmstetter,
Kagan & Jackson (2006, "Comparison of Short-Term and Time-Independent
Earthquake Forecast Models for Southern California," BSSA 96(1):90-106,
doi:10.1785/0120050067) found the earthquake-detection magnitude threshold
immediately after a mainshock of magnitude M follows, empirically,
    m_det(t, M) = M - 4.5 - 0.75*log10(t)      (t = days since mainshock)
(worked-example cross-check: for a M=7.7 mainshock this formula gives
m~4.0 at t=2 hours and m~3.0 at t=2 days -- matching the two published
reference points for that relation to within 0.03 magnitude units. Also
independently used, in the identical functional form, by Hainzl (2016,
"Apparent Triggering Function of Aftershocks Resulting from Rate-Dependent
Incompleteness of Earthquake Catalogs," JGR Solid Earth,
doi:10.1002/2016JB013319) to simulate STAI in synthetic ETAS catalogs).

This script inverts that relation ONCE per catalog (using the CLEAN
baseline's own mainshock magnitude and its own empirically-estimated
Mc_ref = maximum_curvature_mc() -- the SAME Mc estimator A2/C2 already use,
not a new one invented here) to get a single STAI-clearance time t_c at
which the catalog's Mc_ref becomes reliable:
    t_c = 10 ** ((M_mainshock - 4.5 - Mc_ref) / 0.75)
and then compares, on every variant (clean and corrupted alike), a "naive"
fit (all events with magnitude >= Mc_ref, from t=0) against an
"STAI-corrected" fit (the SAME magnitude floor, but only events with
t > t_c) -- holding the target magnitude population fixed and changing
only whether the STAI-incomplete early window is excluded, isolating the
STAI effect from every other methodological choice in the script.
Mc_ref and t_c are computed ONCE from the CLEAN catalog and reused for
every corrupted variant of that catalog (same rationale as fixing the
mainshock's row-index from the clean catalog below: keeps the "target
population" definition identical across variants being compared, instead
of letting corruption silently redefine what's being measured).

Mainshock anchoring: the mainshock is identified ONCE per catalog as the
single largest-magnitude event in the CLEAN dataset, by its ORIGINAL ROW
INDEX (not by re-detecting "largest magnitude" on each corrupted variant,
which would be circular under magnitude_gr_violation -- a corrupted
magnitude could make a different row look like the "mainshock", or make
the true mainshock's own magnitude look smaller than 5.5 and vanish from
naive detection entirely). All of this project's corruption functions in
calibration/corrupt.py preserve original row order and count for every
corruption except inject_duplicates (which only APPENDS extra rows,
never reorders or removes existing ones) -- confirmed by direct source
inspection before relying on this -- so reusing the clean catalog's
mainshock row-index against a corrupted variant's own origin_time/
magnitude arrays at that same index always refers to the same physical
event. If that event's own origin_time becomes unusable (NaT, e.g. hit by
inject_missingness or reassigned by timestamp_collision), the variant is
flagged mainshock_anchor_lost=True and excluded from the fit/forecast
comparison (but still gets its own DATA-CERTIFY audit) rather than
silently producing a meaningless number.

Two catalogs are used, chosen deliberately to be structurally different
mainshock-aftershock sequences (mirroring the two-catalog design of
analysis_d1_case_study.py / D1 option (a)):
  - real_kahramanmaras_turkey_2023 (Mw7.8 mainshock, n=488, 56-day span)
  - real_gorkha_nepal_2015 (Mw7.8 mainshock, n=259, 58-day span) -- this
    sequence includes a well-documented Mw7.3 secondary aftershock on
    2015-05-12 (~17 days after the mainshock) that itself triggered its
    own burst of aftershocks. A single-sequence Omori-Utsu fit calibrated
    on the primary mainshock's early decay CANNOT capture this secondary
    triggering (that is what ETAS-family models exist for) -- this is a
    genuine, disclosed, well-documented domain limitation of the Omori-Utsu
    single-sequence model itself, not a bug in this script or in
    DATA-CERTIFY, and is expected to show up as a large forecast
    under-prediction in this catalog's (7,21]-day forecast window
    regardless of any data-quality corruption.

Methodology:
  1. Load the two real clean base catalogs, identify each one's mainshock
     (largest magnitude, by row index) and compute Mc_ref/t_c once.
  2. Build the SAME 18-variant corruption battery used throughout this
     project's calibration corpus and analysis_d1_case_study.py (D1
     option (a)) -- calibration/corrupt.py's six functions x three
     severities -- so this case study is not run against a bespoke
     corruption scheme.
  3. For each variant (18 corrupted + 1 clean, per catalog): fit
     Omori-Utsu K/c/p twice (naive vs STAI-corrected) on a FIT window
     (0 or t_c, 7] days since the mainshock, then integrate each fit over
     a FORECAST window (7, 21] days to get a predicted event count, and
     compare against the ACTUAL count of M>=Mc_ref events observed in
     that forecast window IN THE CLEAN CATALOG (the fixed ground truth
     for every variant of that catalog, exactly matching D1(a)'s "ground
     truth is the clean catalog's own value" philosophy).
  4. Run DATA-CERTIFY's audit protocol OFFLINE (reference=None) on every
     variant, exactly as in D1(a), extracting T(D), decision, A(D), and
     the A3 (Omori-Utsu conformity) sub-score specifically.
  5. Aggregate: forecast error by DATA-CERTIFY verdict, naive vs
     DATA-CERTIFY-informed usage (with the same composition-artifact
     caveat check D1(a) needed), a T(D)/A3-vs-forecast-error correlation,
     an explicit STAI-correction ablation (naive vs STAI-corrected fit,
     on the CLEAN catalogs specifically, isolating STAI's own effect from
     any corruption), and a magnitude_gr_violation-specific check (does
     the same kind of cross-axis cancellation D1(a) found for A2/I1/I2
     also show up here for A3, or does forecast accuracy degrade cleanly?).

Usage:
    python3 calibration/analysis_d1b_aftershock_forecast.py [<catalog_name>|report]

Output:
    calibration/group_d_reports/d1b_aftershock_variants.csv
    calibration/group_d_reports/d1b_aftershock_report.txt
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
sys.path.insert(0, str(CALIBRATION_DIR))

from data_certify import DataCertifyAuditor, load_dataset_csv  # noqa: E402
from data_certify.stats import fit_omori_utsu, maximum_curvature_mc  # noqa: E402
import corrupt  # noqa: E402

OUT_DIR = CALIBRATION_DIR / "group_d_reports"
OUT_DIR.mkdir(exist_ok=True)

CATALOGS = [
    ("kahramanmaras_2023", PROJECT_ROOT / "datasets" / "real_kahramanmaras_turkey_2023" / "records.csv"),
    ("gorkha_nepal_2015", PROJECT_ROOT / "datasets" / "real_gorkha_nepal_2015" / "records.csv"),
]

RNG_SEED = 20260716  # same fixed seed used throughout this project's calibration/D1 work

FIT_WINDOW_END_DAYS = 7.0
FORECAST_WINDOW_END_DAYS = 21.0

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
    ("magnitude_gr_violation", "low", corrupt.SEVERITY_LOW),
    ("magnitude_gr_violation", "med", corrupt.SEVERITY_MED),
    ("magnitude_gr_violation", "high", corrupt.SEVERITY_HIGH),
]


def identify_mainshock(ds) -> tuple[int, float]:
    """Largest-magnitude event's ORIGINAL ROW INDEX and magnitude. Must be
    called on the CLEAN dataset only -- see module docstring."""
    mags = ds.magnitude
    idx = int(np.nanargmax(mags))
    return idx, float(mags[idx])


def compute_mc_ref_and_tc(ds, mainshock_idx: int, mainshock_mag: float) -> tuple[float, float]:
    """Mc_ref via the project's own maximum_curvature_mc() on this catalog's
    post-mainshock magnitudes, and the STAI-clearance time t_c via the
    inverted Helmstetter/Kagan/Jackson (2006) relation. Called ONCE on the
    clean dataset; reused for every corrupted variant (see module
    docstring)."""
    days = ds.origin_time_days()
    t0 = days[mainshock_idx]
    mask = np.ones(ds.n, dtype=bool)
    mask[mainshock_idx] = False
    rel = days[mask] - t0
    mags = ds.magnitude[mask]
    valid = np.isfinite(rel) & (rel > 0) & np.isfinite(mags)
    mc_ref = maximum_curvature_mc(mags[valid])
    if not math.isfinite(mc_ref):
        mc_ref = float(np.nanmin(mags[valid])) if np.any(valid) else float("nan")
    t_c = 10 ** ((mainshock_mag - 4.5 - mc_ref) / 0.75) if math.isfinite(mc_ref) else float("nan")
    return mc_ref, t_c


def get_rel_days_and_mag(ds, mainshock_idx: int):
    """Return (t0, rel_days_array, mag_array) for every OTHER row in `ds`,
    relative to the mainshock's own origin_time in THIS dataset. Returns
    (nan, None, None) if the mainshock's own row has become unusable
    (origin_time -> NaT after corruption)."""
    days = ds.origin_time_days()
    if mainshock_idx >= len(days):
        return float("nan"), None, None
    t0 = days[mainshock_idx]
    if not math.isfinite(t0):
        return float("nan"), None, None
    mask = np.ones(len(days), dtype=bool)
    mask[mainshock_idx] = False
    rel = days[mask] - t0
    mag = ds.magnitude[mask]
    return t0, rel, mag


def omori_integral(K: float, c: float, p: float, t1: float, t2: float) -> float:
    """Analytic integral of the fitted Omori-Utsu rate n(t)=K/(t+c)^p over
    [t1, t2] -> predicted event count in that window."""
    if not (math.isfinite(K) and math.isfinite(c) and math.isfinite(p)):
        return float("nan")
    if c <= 0 or t1 < 0 or t2 <= t1:
        return float("nan")
    if abs(p - 1.0) < 1e-6:
        return float(K * (math.log(t2 + c) - math.log(t1 + c)))
    return float(K / (1.0 - p) * ((t2 + c) ** (1.0 - p) - (t1 + c) ** (1.0 - p)))


def fit_and_forecast(rel_days: np.ndarray, mag: np.ndarray, mc_ref: float, t_c: float,
                      actual_forecast_n: int) -> dict:
    """Compute the naive and STAI-corrected Omori-Utsu fits on [0 or t_c,
    FIT_WINDOW_END_DAYS] (magnitude >= mc_ref throughout), forecast each
    forward into (FIT_WINDOW_END_DAYS, FORECAST_WINDOW_END_DAYS], and
    compare against `actual_forecast_n` (the fixed, clean-catalog ground
    truth for this catalog)."""
    above_mc = np.isfinite(mag) & (mag >= mc_ref) & np.isfinite(rel_days)

    naive_fit_mask = above_mc & (rel_days > 0) & (rel_days <= FIT_WINDOW_END_DAYS)
    stai_fit_mask = above_mc & (rel_days > t_c) & (rel_days <= FIT_WINDOW_END_DAYS)

    naive_fit = fit_omori_utsu(rel_days[naive_fit_mask])
    stai_fit = fit_omori_utsu(rel_days[stai_fit_mask])

    naive_pred = (float("nan") if naive_fit["degenerate"] else
                  omori_integral(naive_fit["K"], naive_fit["c"], naive_fit["p"],
                                  FIT_WINDOW_END_DAYS, FORECAST_WINDOW_END_DAYS))
    stai_pred = (float("nan") if stai_fit["degenerate"] else
                 omori_integral(stai_fit["K"], stai_fit["c"], stai_fit["p"],
                                 FIT_WINDOW_END_DAYS, FORECAST_WINDOW_END_DAYS))

    naive_abs_err = abs(naive_pred - actual_forecast_n) if math.isfinite(naive_pred) else float("nan")
    stai_abs_err = abs(stai_pred - actual_forecast_n) if math.isfinite(stai_pred) else float("nan")
    denom = max(1, actual_forecast_n)
    naive_rel_err = naive_abs_err / denom if math.isfinite(naive_abs_err) else float("nan")
    stai_rel_err = stai_abs_err / denom if math.isfinite(stai_abs_err) else float("nan")

    return dict(
        n_naive_fit=int(naive_fit_mask.sum()), n_stai_fit=int(stai_fit_mask.sum()),
        naive_p=naive_fit["p"], naive_c=naive_fit["c"], naive_K=naive_fit["K"],
        naive_degenerate=naive_fit["degenerate"],
        stai_p=stai_fit["p"], stai_c=stai_fit["c"], stai_K=stai_fit["K"],
        stai_degenerate=stai_fit["degenerate"],
        naive_pred_n=naive_pred, stai_pred_n=stai_pred,
        actual_forecast_n=actual_forecast_n,
        naive_abs_err=naive_abs_err, stai_abs_err=stai_abs_err,
        naive_rel_err=naive_rel_err, stai_rel_err=stai_rel_err,
    )


def run_offline_audit(ds) -> dict:
    """Same offline-audit helper as analysis_d1_case_study.py, extended to
    also pull the A3 (Omori-Utsu conformity) sub-score."""
    auditor = DataCertifyAuditor(reference=None, fault_db=None)
    result = auditor.audit(ds)
    t_d = result.trust_score
    a_axis = result.axis_results.get("A")
    a3 = a_axis.sub_results.get("A3") if a_axis else None
    return dict(
        t_d=float(t_d) if t_d is not None else float("nan"),
        decision=str(result.decision.value if hasattr(result.decision, "value") else result.decision),
        hard_override_fired=bool(result.hard_override.fired) if result.hard_override else False,
        a_score=float(a_axis.score) if a_axis else float("nan"),
        a3_score=float(a3.score) if a3 is not None and a3.score is not None else float("nan"),
    )


def run_catalog(catalog_name: str, catalog_path: Path) -> pd.DataFrame:
    print(f"\n{'#' * 100}\nCatalog: {catalog_name}  ({catalog_path})\n{'#' * 100}")
    clean_ds = load_dataset_csv(catalog_path, name=f"{catalog_name}_clean")
    print(f"  n={clean_ds.n} records")

    ms_idx, ms_mag = identify_mainshock(clean_ds)
    mc_ref, t_c = compute_mc_ref_and_tc(clean_ds, ms_idx, ms_mag)
    print(f"  Mainshock: row_idx={ms_idx}, M={ms_mag:.2f} | Mc_ref={mc_ref:.2f} | "
          f"t_c={t_c:.4f}d ({t_c * 24:.2f}h)")

    # Ground-truth actual forecast-window count, from the CLEAN catalog ONLY
    # -- fixed and reused for every corrupted variant of this catalog.
    t0_clean, rel_clean, mag_clean = get_rel_days_and_mag(clean_ds, ms_idx)
    actual_mask = (np.isfinite(mag_clean) & (mag_clean >= mc_ref) & np.isfinite(rel_clean)
                   & (rel_clean > FIT_WINDOW_END_DAYS) & (rel_clean <= FORECAST_WINDOW_END_DAYS))
    actual_forecast_n = int(actual_mask.sum())
    print(f"  Actual (clean) forecast-window (({FIT_WINDOW_END_DAYS},{FORECAST_WINDOW_END_DAYS}]d, "
          f"M>=Mc_ref) count = {actual_forecast_n}")

    clean_fc = fit_and_forecast(rel_clean, mag_clean, mc_ref, t_c, actual_forecast_n)
    clean_audit = run_offline_audit(clean_ds)
    print(f"  Clean: naive p={clean_fc['naive_p']:.3f} STAI-corrected p={clean_fc['stai_p']:.3f} | "
          f"naive_pred={clean_fc['naive_pred_n']:.2f} stai_pred={clean_fc['stai_pred_n']:.2f} "
          f"actual={actual_forecast_n} | T(D)={clean_audit['t_d']:.4f} decision={clean_audit['decision']}")

    rows = [dict(
        catalog=catalog_name, variant="clean_original", fn="none", severity_label="none", severity_value=0.0,
        mainshock_idx=ms_idx, mainshock_mag=ms_mag, mc_ref=mc_ref, t_c=t_c,
        mainshock_anchor_lost=False,
        **clean_fc, **clean_audit,
    )]

    for fn_name, sev_label, sev_val in CORRUPTION_BATTERY:
        rng = np.random.RandomState(RNG_SEED)
        fn = getattr(corrupt, fn_name)
        corrupted_ds, desc = fn(clean_ds, sev_val, rng)
        variant_name = f"{fn_name}_{sev_label}"
        print(f"\nVariant: {variant_name}  ({desc})")

        t0, rel, mag = get_rel_days_and_mag(corrupted_ds, ms_idx)
        anchor_lost = not math.isfinite(t0)
        audit = run_offline_audit(corrupted_ds)

        if anchor_lost:
            print(f"  MAINSHOCK ANCHOR LOST (origin_time at row {ms_idx} is NaT after corruption) "
                  f"-- fit/forecast skipped for this variant. T(D)={audit['t_d']:.4f} "
                  f"decision={audit['decision']}")
            fc = dict(
                n_naive_fit=0, n_stai_fit=0,
                naive_p=float("nan"), naive_c=float("nan"), naive_K=float("nan"), naive_degenerate=True,
                stai_p=float("nan"), stai_c=float("nan"), stai_K=float("nan"), stai_degenerate=True,
                naive_pred_n=float("nan"), stai_pred_n=float("nan"), actual_forecast_n=actual_forecast_n,
                naive_abs_err=float("nan"), stai_abs_err=float("nan"),
                naive_rel_err=float("nan"), stai_rel_err=float("nan"),
            )
        else:
            fc = fit_and_forecast(rel, mag, mc_ref, t_c, actual_forecast_n)
            print(f"  naive p={fc['naive_p']:.3f} STAI-corrected p={fc['stai_p']:.3f} | "
                  f"naive_pred={fc['naive_pred_n']:.2f} stai_pred={fc['stai_pred_n']:.2f} "
                  f"actual={actual_forecast_n} | T(D)={audit['t_d']:.4f} decision={audit['decision']} "
                  f"A3={audit['a3_score']:.4f}")

        rows.append(dict(
            catalog=catalog_name, variant=variant_name, fn=fn_name,
            severity_label=sev_label, severity_value=sev_val,
            mainshock_idx=ms_idx, mainshock_mag=ms_mag, mc_ref=mc_ref, t_c=t_c,
            mainshock_anchor_lost=anchor_lost,
            **fc, **audit,
        ))

    return pd.DataFrame(rows)


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    partial_dir = OUT_DIR / "_partial_d1b"
    partial_dir.mkdir(exist_ok=True)

    if only == "report":
        all_dfs = []
        for name, _ in CATALOGS:
            p = partial_dir / f"{name}.csv"
            if not p.exists():
                print(f"WARNING: missing partial result for '{name}' ({p}) -- run "
                      f"`python3 analysis_d1b_aftershock_forecast.py {name}` first.")
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
                  f"`python3 analysis_d1b_aftershock_forecast.py report` to build the combined report.")
            return
        df = pd.concat(all_dfs, ignore_index=True)

    csv_path = OUT_DIR / "d1b_aftershock_variants.csv"
    df.to_csv(csv_path, index=False)
    print(f"\nSaved -> {csv_path}")

    corrupted = df[df["variant"] != "clean_original"].copy()
    usable = corrupted[~corrupted["mainshock_anchor_lost"]].copy()
    valid = usable.dropna(subset=["stai_abs_err"])

    report_lines = []
    report_lines.append("=" * 100)
    report_lines.append("Group D1: Downstream DRR case study, option (b)")
    report_lines.append("Aftershock-forecast accuracy (Omori-Utsu): naive vs DATA-CERTIFY-informed usage,")
    report_lines.append("plus a Short-Term Aftershock Incompleteness (STAI) correction ablation")
    report_lines.append("(Group D downstream case study)")
    report_lines.append("=" * 100)
    report_lines.append("")
    report_lines.append(
        "STAI correction: Helmstetter, Kagan & Jackson (2006, BSSA 96(1):90-106) magnitude-time "
        "detection-threshold relation m_det(t,M)=M-4.5-0.75*log10(t), inverted once per catalog "
        "(from the clean baseline) to a clearance time t_c above which the catalog's own "
        "maximum_curvature_mc()-estimated Mc_ref is trusted. 'naive' fits use every M>=Mc_ref event "
        "from t=0; 'STAI-corrected' fits use the same M>=Mc_ref population but only t>t_c."
    )
    report_lines.append("")

    report_lines.append("-" * 100)
    report_lines.append("(0) Base catalogs and clean-baseline fits")
    report_lines.append("-" * 100)
    for name, _ in CATALOGS:
        c = df[(df["catalog"] == name) & (df["variant"] == "clean_original")].iloc[0]
        report_lines.append(
            f"  '{name}': mainshock M={c['mainshock_mag']:.2f}, Mc_ref={c['mc_ref']:.2f}, "
            f"t_c={c['t_c']:.4f}d ({c['t_c']*24:.2f}h)"
        )
        report_lines.append(
            f"      naive fit (n={int(c['n_naive_fit'])}): p={c['naive_p']:.3f} c={c['naive_c']:.4f} "
            f"K={c['naive_K']:.2f} degenerate={c['naive_degenerate']} -> forecast={c['naive_pred_n']:.2f}"
        )
        report_lines.append(
            f"      STAI-corrected fit (n={int(c['n_stai_fit'])}): p={c['stai_p']:.3f} c={c['stai_c']:.4f} "
            f"K={c['stai_K']:.2f} degenerate={c['stai_degenerate']} -> forecast={c['stai_pred_n']:.2f}"
        )
        report_lines.append(
            f"      ACTUAL count in (7,21] days = {int(c['actual_forecast_n'])}  |  "
            f"naive |error|={c['naive_abs_err']:.2f} ({c['naive_rel_err']*100:.1f}%)  "
            f"STAI-corrected |error|={c['stai_abs_err']:.2f} ({c['stai_rel_err']*100:.1f}%)  |  "
            f"T(D)={c['t_d']:.4f} ({c['decision']})  A3={c['a3_score']:.4f}"
        )

    n_anchor_lost = int(corrupted["mainshock_anchor_lost"].sum())
    report_lines.append("")
    report_lines.append(f"Corrupted variants: {len(corrupted)} total across {len(CATALOGS)} catalogs "
                         f"({len(CORRUPTION_BATTERY)} corruption-fn x severity combinations per catalog).")
    report_lines.append(f"  Mainshock-anchor-lost (origin_time at the mainshock's own row became NaT "
                         f"after corruption): {n_anchor_lost} variant(s) -- excluded from fit/forecast "
                         f"analysis below, but still audited.")
    report_lines.append(f"  Usable (anchor intact) variants: {len(usable)}; of those, "
                         f"{len(valid)} produced a non-degenerate STAI-corrected fit.")

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(1) STAI-corrected forecast |error| BY DATA-CERTIFY VERDICT (pooled, corrupted variants)")
    report_lines.append("-" * 100)
    report_lines.append(
        "  CAVEAT (read together with Section (2)): REJECT here is exclusively depth_implausible, which "
        "does not touch time/magnitude at all -- its forecast error is NOT zero, it equals that catalog's "
        "OWN clean-baseline error (gorkha_nepal_2015's baseline error is large due to the secondary-"
        "aftershock effect noted in the caveats below), so a REJECT-vs-CONDITIONAL comparison here is a "
        "composition artifact of catalog mix, not a clean signal about DATA-CERTIFY protecting forecast "
        "accuracy specifically -- same caution as D1(a)'s Section (2)."
    )
    for decision in ["ADMIT", "CONDITIONAL", "REJECT"]:
        subset = valid[valid["decision"] == decision]
        if len(subset) == 0:
            report_lines.append(f"  {decision}: n=0 variants")
            continue
        report_lines.append(
            f"  {decision}: n={len(subset)}  mean |error|={subset['stai_abs_err'].mean():.3f}  "
            f"median |error|={subset['stai_abs_err'].median():.3f}  "
            f"mean rel.error={subset['stai_rel_err'].mean()*100:.1f}%"
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(2) NAIVE-USER vs DATA-CERTIFY-INFORMED downstream usage (STAI-corrected fit)")
    report_lines.append("-" * 100)
    rej_fns = sorted(valid[valid["decision"] == "REJECT"]["fn"].unique().tolist())
    report_lines.append(
        f"  CAVEAT: as in D1(a), check whether REJECT correlates with a magnitude/time-independent "
        f"failure mode before reading this as a clean signal. REJECTed variants here come from: "
        f"{rej_fns if rej_fns else '(none)'}."
    )
    naive_mean_error = valid["stai_abs_err"].mean()
    informed = valid[valid["decision"] != "REJECT"]
    informed_mean_error = informed["stai_abs_err"].mean() if len(informed) > 0 else float("nan")
    report_lines.append(
        f"  ALL variants (regardless of verdict): mean |forecast error| across {len(valid)} = "
        f"{naive_mean_error:.3f}"
    )
    report_lines.append(
        f"  DATA-CERTIFY-INFORMED (drop REJECTed, keep {len(informed)} ADMIT/CONDITIONAL): "
        f"mean |forecast error| = {informed_mean_error:.3f}"
    )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(3) CORRELATION: T(D) and A3 vs STAI-corrected forecast |error| (pooled)")
    report_lines.append("-" * 100)
    if len(valid) >= 3:
        corr_td = valid[["t_d", "stai_abs_err"]].corr(method="spearman").iloc[0, 1]
        corr_a3 = valid[["a3_score", "stai_abs_err"]].corr(method="spearman").iloc[0, 1]
        report_lines.append(
            f"  Spearman rank correlation(T(D), |forecast error|) across {len(valid)} variants = {corr_td:.4f}"
        )
        report_lines.append(
            f"  Spearman rank correlation(A3, |forecast error|) across {len(valid)} variants = {corr_a3:.4f}"
        )
    else:
        report_lines.append("  Not enough valid variants for correlation.")

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(4) Per-variant detail")
    report_lines.append("-" * 100)
    report_lines.append(
        corrupted[["catalog", "variant", "t_d", "decision", "a3_score", "mainshock_anchor_lost",
                   "stai_p", "stai_pred_n", "actual_forecast_n", "stai_abs_err"]]
        .to_string(index=False)
    )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(5) magnitude_gr_violation check: cross-axis cancellation (like D1(a)'s A2/I1/I2), "
                         "or clean degradation, for A3/forecast accuracy?")
    report_lines.append("-" * 100)
    mgv = corrupted[corrupted["fn"] == "magnitude_gr_violation"]
    for _, row in mgv.iterrows():
        clean_row = df[(df["catalog"] == row["catalog"]) & (df["variant"] == "clean_original")].iloc[0]
        report_lines.append(
            f"    [{row['catalog']}] {row['variant']}: "
            f"T(D) {clean_row['t_d']:.4f} -> {row['t_d']:.4f}  "
            f"A3 {clean_row['a3_score']:.4f} -> {row['a3_score']:.4f}  "
            f"STAI-forecast-error {clean_row['stai_abs_err']:.2f} -> {row['stai_abs_err']:.2f}  "
            f"(anchor_lost={row['mainshock_anchor_lost']})"
        )

    report_lines.append("")
    report_lines.append("-" * 100)
    report_lines.append("(6) STAI-correction ablation (clean catalogs only -- isolates STAI's own effect)")
    report_lines.append("-" * 100)
    for name, _ in CATALOGS:
        c = df[(df["catalog"] == name) & (df["variant"] == "clean_original")].iloc[0]
        report_lines.append(
            f"  '{name}': naive p={c['naive_p']:.3f} vs STAI-corrected p={c['stai_p']:.3f} "
            f"(delta={c['stai_p']-c['naive_p']:+.3f})  |  "
            f"naive forecast |error|={c['naive_abs_err']:.2f} ({c['naive_rel_err']*100:.1f}%) vs "
            f"STAI-corrected |error|={c['stai_abs_err']:.2f} ({c['stai_rel_err']*100:.1f}%)"
        )

    report_lines.append("")
    report_lines.append("Caveats (disclosed explicitly, consistent with this project's honesty discipline):")
    report_lines.append(
        "  - 'Ground truth' is each clean catalog's OWN recorded event count in the forecast window, "
        "not an independently published catalog or aftershock-forecast benchmark -- this validates "
        "INTERNAL CONSISTENCY (recovery from corruption), not agreement with an external standard."
    )
    report_lines.append(
        "  - real_gorkha_nepal_2015's forecast window (7,21] days contains a well-documented Mw7.3 "
        "secondary aftershock (~17 days after the mainshock) that triggered its own aftershock burst. "
        "A single-sequence Omori-Utsu fit on the primary mainshock's early decay structurally cannot "
        "predict this (ETAS-family multi-generation models exist precisely for this reason) -- expect "
        "a large under-prediction on this catalog independent of any corruption; this is a genuine "
        "domain limitation of the Omori-Utsu single-sequence model, not a script or DATA-CERTIFY bug."
    )
    report_lines.append(
        "  - Mc_ref and t_c are fixed from the CLEAN catalog and reused across all corrupted variants "
        "of that catalog (same rationale as fixing the mainshock row-index) -- this measures 'how well "
        "does a fit on possibly-corrupted DATA still predict the true future,' not 'how would the "
        "corrupted data's own (possibly also corrupted) Mc/STAI estimate come out.'"
    )
    report_lines.append(
        "  - reference=None (offline/intrinsic-only A6) throughout, matching D1(a)."
    )
    report_lines.append(
        "  - Two base catalogs (kahramanmaras_2023, gorkha_nepal_2015), both large (M7.8) shallow "
        "continental mainshocks with well-instrumented global monitoring -- findings here should not "
        "be assumed to generalize to smaller-magnitude or poorly-instrumented sequences without "
        "further testing."
    )

    report_text = "\n".join(report_lines)
    report_path = OUT_DIR / "d1b_aftershock_report.txt"
    report_path.write_text(report_text, encoding="utf-8")
    print(f"Saved -> {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
