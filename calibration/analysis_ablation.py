# -*- coding: utf-8 -*-
"""
calibration/analysis_ablation.py -- Group B3 (see
Docs/03_Paper_Prep/DATA-CERTIFY_Verification_and_Improvements_Summary.md,
Group B): ablation study answering "does each design choice in DATA-CERTIFY's
decision architecture actually earn its place, or would something simpler
do just as well?"

Three separate ablation questions, each answered on the FULL 968-dataset
corpus (+ the 30-dataset adversarial holdout when available), all decisions
recomputed LIVE via _analysis_common.composite_score()/assign_decision()
under whatever weight vector each arm specifies -- never read from
score_matrix.csv's cached columns (see _analysis_common.py's
LEGACY_STALE_COLUMNS note):

  (1) WEIGHT-VECTOR ablation: WEIGHT_VARIANTS['blended_current'] (the
      production AHP x EWM blend) vs 'ahp_only' (single-analyst prior, no
      data), 'ewm_only' (pure entropy weighting, no expert prior),
      'equal_weight' (uniform baseline), and four single-axis arms
      (a_only/p_only/c_only/i_only, axis weight = 1.0 on one axis, 0
      elsewhere) -- does the blend actually outperform its two parent
      methods and the naive baselines, or is the extra complexity not
      earning its keep?

  (2) MECHANISM ablation: 'hard_override_only' (REJECT if the Stage-1 gate
      fires, else ADMIT -- no composite score consulted at all) vs
      'weighted_sum_only' (composite score under blended_current weights,
      decision thresholds applied, but hard-override NEVER consulted, i.e.
      respect_hard_override=False) vs the full two-stage architecture
      (both stages) -- how much does EACH stage contribute independently,
      and does the two-stage design actually catch cases that either stage
      alone would miss?

  (3) A6 mini-ablation: uses the SEPARATE, PARTIAL score_matrix_a6*.csv
      files (NOT score_matrix.csv) -- these were produced by
      calibration/run_a6_scoring.py, a one-off exercise that makes live
      calls to external seismic catalogs (USGS/EMSC/ISC) and is NOT part
      of the routine run_scoring.py pipeline. Coverage is restricted to
      the ~81-89 datasets large/high-magnitude enough to have a
      non-trivial "reference-complete stratum" (Mc_ref) -- 8-9% of the
      full 968-dataset corpus. THIS SECTION'S FINDINGS MUST NOT BE
      EXTRAPOLATED TO THE FULL CORPUS -- printed and disclosed prominently
      below, not just in this docstring.

Usage:
    python3 calibration/analysis_ablation.py

Output:
    calibration/group_b_reports/ablation_report.txt
    calibration/group_b_reports/ablation_weight_variants.csv
    calibration/group_b_reports/ablation_mechanism.csv
    calibration/group_b_reports/ablation_a6_mini.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

CALIBRATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CALIBRATION_DIR))
import _analysis_common as ac  # noqa: E402

OUT_DIR = CALIBRATION_DIR / "group_b_reports"
OUT_DIR.mkdir(exist_ok=True)

A6_SINGLE_PATH = CALIBRATION_DIR / "score_matrix_a6.csv"              # USGS-alone
A6_MULTI_PATH = CALIBRATION_DIR / "score_matrix_a6_weighted-multi.csv"  # weighted multi-source
A6_EMSC_PATH = CALIBRATION_DIR / "score_matrix_a6_emsc.csv"           # EMSC-alone spot check
A6_ISC_PATH = CALIBRATION_DIR / "score_matrix_a6_isc.csv"             # ISC-alone spot check


def eval_arm(df: pd.DataFrame, axis_weights, within_weights, respect_hard_override: bool = True) -> dict:
    """Compute the full set of headline metrics for one weight/mechanism
    arm, given a corpus DataFrame that already has hard_override_fired and
    group columns."""
    t_d = ac.composite_score(df, axis_weights, within_weights)
    decision = ac.assign_decision(t_d, df["hard_override_fired"], respect_hard_override=respect_hard_override)

    known_good = df["group"] == "known_good"
    known_bad = df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"])

    n_good, n_bad = int(known_good.sum()), int(known_bad.sum())
    k_false_reject = int((decision[known_good] == "REJECT").sum())
    k_false_admit = int((decision[known_bad] == "ADMIT").sum())
    k_not_rejected_bad = int((decision[known_bad] != "REJECT").sum())
    k_admit_good = int((decision[known_good] == "ADMIT").sum())

    return {
        "n_known_good": n_good,
        "n_known_bad": n_bad,
        "false_reject_rate": k_false_reject / n_good if n_good else float("nan"),
        "false_reject_k": k_false_reject,
        "false_admit_rate": k_false_admit / n_bad if n_bad else float("nan"),
        "false_admit_k": k_false_admit,
        "not_rejected_bad_rate": k_not_rejected_bad / n_bad if n_bad else float("nan"),
        "correctly_admitted_good_rate": k_admit_good / n_good if n_good else float("nan"),
        "n_admit": int((decision == "ADMIT").sum()),
        "n_conditional": int((decision == "CONDITIONAL").sum()),
        "n_reject": int((decision == "REJECT").sum()),
    }


def main() -> None:
    df = ac.load_corpus(include_adversarial=True)
    include_adv = ac.ADVERSARIAL_SCORE_MATRIX_PATH.exists()

    report = []
    report.append("=" * 100)
    report.append("Group B3: Ablation study")
    report.append("(Group B post-hoc verification analysis)")
    report.append("=" * 100)
    report.append("")
    report.append(f"Corpus: n={len(df)} ({df['group'].value_counts().to_dict()})")
    if not include_adv:
        report.append(
            "*** NOTE: held_out_adversarial group excluded -- run "
            "score_adversarial_holdout.py (Group B1) first for the complete picture. ***"
        )
    report.append("")

    # ============================================================
    # (1) Weight-vector ablation
    # ============================================================
    report.append("-" * 100)
    report.append("(1) WEIGHT-VECTOR ABLATION")
    report.append("Full two-stage architecture (hard-override respected) under each weight vector.")
    report.append("-" * 100)
    wv_rows = []
    for name, spec in ac.WEIGHT_VARIANTS.items():
        m = eval_arm(df, spec["axis"], spec["within"], respect_hard_override=True)
        m["variant"] = name
        m["label"] = spec["label"]
        wv_rows.append(m)
    wv_df = pd.DataFrame(wv_rows)
    cols = ["variant", "label", "false_reject_rate", "false_reject_k", "false_admit_rate",
            "false_admit_k", "not_rejected_bad_rate", "n_admit", "n_conditional", "n_reject"]
    wv_df = wv_df[cols]
    wv_df.to_csv(OUT_DIR / "ablation_weight_variants.csv", index=False)
    report.append(wv_df.to_string(index=False))
    report.append("")
    report.append(
        "Reading guide: false_reject_rate is the rate at which known-good real "
        "catalogs are wrongly REJECTed (safety-relevant to operators: rejecting "
        "good data has an operational cost). false_admit_rate is the rate at "
        "which known-bad (corrupted+fabricated+adversarial) data is wrongly "
        "ADMITted outright (the scientifically dangerous error). A weight "
        "vector that is simply better than blended_current on BOTH axes "
        "simultaneously would be a real finding worth acting on; a vector "
        "that trades one for the other is a value judgement, not a free win."
    )
    report.append("")

    # ============================================================
    # (2) Mechanism ablation
    # ============================================================
    report.append("-" * 100)
    report.append("(2) MECHANISM ABLATION (blended_current weights throughout)")
    report.append("-" * 100)

    mech_rows = []

    # Full two-stage (both mechanisms active)
    m = eval_arm(df, ac.AXIS_WEIGHTS, ac.WITHIN, respect_hard_override=True)
    m["arm"] = "full_two_stage"
    m["description"] = "Hard-override gate (Stage 1) + composite score (Stage 2), as in production"
    mech_rows.append(m)

    # Weighted-sum only, no hard override
    m = eval_arm(df, ac.AXIS_WEIGHTS, ac.WITHIN, respect_hard_override=False)
    m["arm"] = "weighted_sum_only"
    m["description"] = "Composite score only -- hard-override gate never consulted"
    mech_rows.append(m)

    # Hard-override only, no composite score (binary REJECT-if-fired else ADMIT)
    hof = df["hard_override_fired"].fillna(False).astype(bool)
    decision_ho_only = pd.Series(np.where(hof, "REJECT", "ADMIT"), index=df.index)
    known_good = df["group"] == "known_good"
    known_bad = df["group"].isin(["corrupted_real", "fabricated", "held_out_adversarial"])
    n_good, n_bad = int(known_good.sum()), int(known_bad.sum())
    k_false_reject = int((decision_ho_only[known_good] == "REJECT").sum())
    k_false_admit = int((decision_ho_only[known_bad] == "ADMIT").sum())
    mech_rows.append({
        "arm": "hard_override_only",
        "description": "Binary: REJECT if Stage-1 gate fires, else ADMIT -- composite score never consulted (no CONDITIONAL zone exists in this arm by construction)",
        "n_known_good": n_good, "n_known_bad": n_bad,
        "false_reject_rate": k_false_reject / n_good if n_good else float("nan"),
        "false_reject_k": k_false_reject,
        "false_admit_rate": k_false_admit / n_bad if n_bad else float("nan"),
        "false_admit_k": k_false_admit,
        "not_rejected_bad_rate": float((decision_ho_only[known_bad] != "REJECT").mean()) if n_bad else float("nan"),
        "correctly_admitted_good_rate": float((decision_ho_only[known_good] == "ADMIT").mean()) if n_good else float("nan"),
        "n_admit": int((decision_ho_only == "ADMIT").sum()),
        "n_conditional": 0,
        "n_reject": int((decision_ho_only == "REJECT").sum()),
    })

    mech_df = pd.DataFrame(mech_rows)
    mech_cols = ["arm", "description", "false_reject_rate", "false_reject_k", "false_admit_rate",
                 "false_admit_k", "not_rejected_bad_rate", "n_admit", "n_conditional", "n_reject"]
    mech_df = mech_df[mech_cols]
    mech_df.to_csv(OUT_DIR / "ablation_mechanism.csv", index=False)
    report.append(mech_df.to_string(index=False))
    report.append("")
    report.append(
        "Reading guide: 'hard_override_only' has NO CONDITIONAL zone by "
        "construction (binary ADMIT/REJECT), so its false_admit_rate directly "
        "measures what fraction of known-bad data would be autonomously "
        "ADMITted if the composite score did not exist at all -- this is the "
        "cleanest measurement of how much protective value Stage 2 adds beyond "
        "Stage 1 alone. 'weighted_sum_only' measures the converse: how much "
        "protective value Stage 1 adds beyond Stage 2 alone (compare its "
        "false_admit_rate to full_two_stage's -- any difference is entirely "
        "attributable to cases the hard-override gate catches that the "
        "composite score's ADMIT/CONDITIONAL/REJECT thresholds do not)."
    )
    report.append("")

    # ============================================================
    # (3) A6 mini-ablation (SEPARATE, PARTIAL data -- prominent disclosure)
    # ============================================================
    report.append("-" * 100)
    report.append("(3) A6 MINI-ABLATION -- ⚠ PARTIAL CORPUS, DO NOT EXTRAPOLATE ⚠")
    report.append("-" * 100)
    report.append(
        "⚠ SUPERSEDED SEMANTICS DISCLOSURE (added post-Group-C3 verification pass, "
        "2026-07-16): score_matrix_a6.csv/score_matrix_a6_weighted-multi.csv/"
        "score_matrix_a6_emsc.csv/score_matrix_a6_isc.csv below were all generated "
        "2026-07-09/10, BEFORE Group C3's A6 three-state redesign (2026-07-12/13, "
        "see data_certify/_constants.py's A6_CONTRADICTED_* block). Their cached "
        "hard_reject_would_fire column reflects the OLD BINARY rule "
        "(matched_fraction < theta_auth -> hard-REJECT on ANY single source's "
        "non-match), which current production code no longer implements. Under "
        "CURRENT code, a single reference source (e.g. USGS alone, the "
        "'single-source (USGS)' row below) can STRUCTURALLY NEVER fire A6's "
        "hard-override at all (A6_CONTRADICTED_MIN_SOURCES=2) -- so the "
        "'single-source (USGS) ... catch rate if A6 wired' figure below describes "
        "a hard-reject behavior that literally cannot occur under the codebase as "
        "it exists today, not a live prediction of what wiring up single-source A6 "
        "would currently do (it would land those catalogs in CONDITIONAL, not "
        "REJECT). The 'weighted-multi' row is less clear-cut -- "
        "WeightedMultiSourceExternalCatalogReference now also populates "
        "n_sources_queried/n_sources_matched (added during Group C3) and so DOES "
        "participate in today's three-state logic, but this specific CSV predates "
        "that code change entirely, so its cached verdicts were computed under the "
        "old rule too and have not been reconfirmed against the current "
        "implementation. This whole sub-analysis is retained for historical "
        "record (it motivated Group C3's redesign in the first place -- see "
        "Criteria_and_Weights_Master_Reference.md Section 4.4) but should NOT be "
        "cited in the paper as a description of current A6 behavior without this "
        "caveat attached."
    )
    report.append("")

    if not A6_SINGLE_PATH.exists() or not A6_MULTI_PATH.exists():
        report.append(
            "score_matrix_a6.csv / score_matrix_a6_weighted-multi.csv not found -- "
            "A6 mini-ablation skipped. Run calibration/run_a6_scoring.py first."
        )
    else:
        manifest = pd.read_csv(ac.MANIFEST_PATH)[["dataset_id", "category"]]
        main_ho = pd.read_csv(ac.SCORE_MATRIX_PATH)[["dataset_id", "hard_override_fired"]]

        single = pd.read_csv(A6_SINGLE_PATH)
        multi = pd.read_csv(A6_MULTI_PATH)

        n_total_single, n_total_multi = len(single), len(multi)
        single_app = single[single["a6_applicable"] == True].copy()  # noqa: E712
        multi_app = multi[multi["a6_applicable"] == True].copy()  # noqa: E712

        report.append(
            f"Coverage: score_matrix_a6.csv (single-source, USGS) has "
            f"{n_total_single} rows total, {len(single_app)} with a6_applicable=True "
            f"(a non-trivial reference-complete stratum exists). "
            f"score_matrix_a6_weighted-multi.csv (weighted multi-source blend) has "
            f"{n_total_multi} rows total, {len(multi_app)} with a6_applicable=True. "
            f"This is {len(single_app)}-{len(multi_app)} datasets out of the full "
            f"968-dataset corpus ({100*len(multi_app)/968:.1f}%) -- restricted to "
            f"catalogs with enough high-magnitude events to form a reference-complete "
            f"stratum in the first place. These files were produced by a SEPARATE "
            f"one-off script (run_a6_scoring.py) that makes LIVE external-network "
            f"calls (elapsed_sec column shows 100-400+ sec for the largest catalogs) "
            f"and is NOT re-run as part of routine calibration/run_scoring.py. "
            f"Findings below characterize A6's behavior ONLY on this specific "
            f"reference-complete subset, not the corpus as a whole."
        )
        report.append("")

        for label, sub in (("single-source (USGS)", single_app), ("weighted-multi", multi_app)):
            sub = sub.merge(manifest, on="dataset_id", how="left")
            sub = sub.merge(main_ho, on="dataset_id", how="left")
            n = len(sub)
            k_fire = int(sub["hard_reject_would_fire"].sum())
            good = sub[sub["category"] == "real"]
            bad = sub[sub["category"].isin(["corrupted", "fabricated"])]
            k_fire_good = int(good["hard_reject_would_fire"].sum())
            k_fire_bad = int(bad["hard_reject_would_fire"].sum())
            # marginal: of the bad datasets A6-would-catch, how many does
            # CURRENT production (A6 off, P1-P3 only) already catch anyway?
            bad_caught_by_a6 = bad[bad["hard_reject_would_fire"] == True]  # noqa: E712
            already_caught_by_prod = int(bad_caught_by_a6["hard_override_fired"].apply(lambda x: bool(x) if pd.notna(x) else False).sum())
            marginal_new_catches = len(bad_caught_by_a6) - already_caught_by_prod

            report.append(f"--- {label}: n={n} (a6_applicable=True) ---")
            report.append(f"  hard_reject_would_fire overall: {ac.fmt_rate_ci(k_fire, n)}")
            report.append(f"  hard_reject_would_fire on known_good (n={len(good)}): "
                           f"{ac.fmt_rate_ci(k_fire_good, len(good))}  <- false-reject risk if A6 wired")
            report.append(f"  hard_reject_would_fire on known_bad (n={len(bad)}): "
                           f"{ac.fmt_rate_ci(k_fire_bad, len(bad))}  <- catch rate if A6 wired")
            report.append(f"  Of those {len(bad_caught_by_a6)} known_bad catches, "
                           f"{already_caught_by_prod} are ALREADY caught by current "
                           f"production (P1-P3 only, A6 off) -> {marginal_new_catches} "
                           f"are NET NEW catches attributable specifically to A6.")
            report.append("")

        # single vs multi sensitivity on the overlapping dataset_id set
        overlap_ids = set(single_app["dataset_id"]) & set(multi_app["dataset_id"])
        s = single_app[single_app["dataset_id"].isin(overlap_ids)].set_index("dataset_id")["hard_reject_would_fire"]
        m2 = multi_app[multi_app["dataset_id"].isin(overlap_ids)].set_index("dataset_id")["hard_reject_would_fire"]
        agree = (s == m2.reindex(s.index)).sum()
        agree_pct = f"{100*agree/len(overlap_ids):.1f}%" if len(overlap_ids) else "n/a"
        report.append(
            f"Single-source vs weighted-multi agreement on hard_reject_would_fire "
            f"(overlapping n={len(overlap_ids)}): {agree}/{len(overlap_ids)} agree "
            f"({agree_pct})."
        )
        report.append("")

        # EMSC/ISC spot check (nz, chile only -- N too small for a real arm)
        if A6_EMSC_PATH.exists() and A6_ISC_PATH.exists():
            emsc = pd.read_csv(A6_EMSC_PATH)
            isc = pd.read_csv(A6_ISC_PATH)
            report.append(
                f"Supplementary single-source spot check (NOT a full ablation arm -- "
                f"EMSC has {len(emsc)} rows, ISC has {len(isc)} row(s), covering only "
                f"nz/chile, the two catalogs large enough for every source to return "
                f"a non-trivial reference-complete stratum):"
            )
            for _, r in emsc.iterrows():
                report.append(f"  EMSC  {r['dataset_id']:<10s} matched_fraction={r['matched_fraction']:.4f} "
                               f"hard_reject_would_fire={r['hard_reject_would_fire']}")
            for _, r in isc.iterrows():
                report.append(f"  ISC   {r['dataset_id']:<10s} matched_fraction={r['matched_fraction']:.4f} "
                               f"hard_reject_would_fire={r['hard_reject_would_fire']}")
            report.append(
                "These agree qualitatively with the USGS/weighted-multi results above "
                "for the same two catalogs (see hard_reject_would_fire column), a "
                "reassuring but extremely low-N sensitivity signal, not a claim of "
                "general robustness across external catalog choice."
            )
            report.append("")

        ablation_a6_rows = []
        for label, path in (("single_usgs", A6_SINGLE_PATH), ("weighted_multi", A6_MULTI_PATH)):
            d = pd.read_csv(path)
            d_app = d[d["a6_applicable"] == True]  # noqa: E712
            ablation_a6_rows.append({
                "source": label, "n_total": len(d), "n_applicable": len(d_app),
                "hard_reject_would_fire_rate": d_app["hard_reject_would_fire"].mean() if len(d_app) else float("nan"),
            })
        pd.DataFrame(ablation_a6_rows).to_csv(OUT_DIR / "ablation_a6_mini.csv", index=False)

    report_text = "\n".join(report)
    print(report_text)
    (OUT_DIR / "ablation_report.txt").write_text(report_text, encoding="utf-8")
    print(f"\nReports written to {OUT_DIR}/")


if __name__ == "__main__":
    main()
