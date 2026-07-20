# -*- coding: utf-8 -*-
"""
calibration/calibrate_thresholds.py -- Empirically calibrate
theta_admit / theta_reject / theta_auth from the scored 73-dataset
calibration corpus (calibration/score_matrix.csv +
calibration/corpus_manifest.csv), using the EWM-blended axis weights
computed by calibration/compute_ewm.py (calibration/ewm_report.json).

METHODOLOGY (per Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md
Section 4's own instruction: "run the full scoring pipeline against the
real corpus... inspect where genuinely good and genuinely bad datasets
actually land on the T(D) scale, adjusting theta_admit/theta_reject so
the boundaries track that empirical separation"):

theta_admit: set to the largest clean round value such that ZERO
known_bad datasets (all 23, corrupted + fabricated) clear it. This
directly implements the project's own stated asymmetric-cost principle
(a false ADMIT of bad data is the costliest error) -- ADMIT should
require clearing every bad example actually observed in the corpus,
not just a majority of them.

theta_reject: set to a clean value that (a) sits strictly BELOW the
lowest-scoring known_good real dataset, so no genuine real catalog is
auto-rejected by T(D) alone, while (b) sitting strictly ABOVE at least
the worst known_bad case, so REJECT still does some real work. This is
a materially different design principle than theta_admit's "catch
everything bad" rule -- CONDITIONAL (the zone between theta_reject and
theta_admit) is a low-cost, disclosed "flagged for scrutiny" outcome,
not a wrongful rejection, so it is FAR better to let a marginal real
dataset land in CONDITIONAL than to let theta_reject auto-REJECT it.

theta_auth: LEFT UNCHANGED (provisional). A6 (external-catalog
cross-match) was never exercised anywhere in this scoring run --
calibration/run_scoring.py calls score_authenticity() with no
`reference` argument, so every one of the 73 datasets scored under
NullExternalCatalog/no-reference and A6 is `applicable=False`
throughout (verified: score_matrix.csv has no A6 column at all,
because run_scoring.py never had a non-NaN A6 score to record). Wiring
up a live external reference (e.g. USGSComCatReference) across 73
datasets would mean ~73 external API calls, which is unreliable,
slow, and out of scope for this local-corpus calibration pass. There
is therefore NO empirical data in this corpus that could inform
theta_auth one way or the other -- changing it here would be exactly
the kind of "guess without being told" this project's methodology
explicitly forbids. theta_auth remains its original provisional value,
disclosed as still-provisional pending a future live-A6 corpus run.

UPDATE (2026-07-07/08): that future live-A6 corpus run has since
happened -- see calibration/calibrate_theta_auth.py (a separate script,
downstream of calibration/debug_diagnostics/run_a6_scoring_from_manual_fetch.py's
manually-fetched USGS reference data), which exercised A6 across the
full 89-dataset corpus. The result was a CONFIRMED structural finding
(not a data-volume gap): theta_auth still cannot be cleanly separated
because a known-good dataset ("nz", matched_fraction=0.3913) scores
below two known-bad datasets that score a perfect matched_fraction=1.0.
theta_auth was left unchanged at its original value as a result -- see
data_certify/_constants.py's THETA_AUTH comment and
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Section 4 for
the full disclosure. This script (calibrate_thresholds.py) itself still
never touches A6 -- the paragraph above describing why remains accurate
for THIS script's own scope (it only calibrates against
calibration/score_matrix.csv, which has no A6 column).

KEY FINDING that motivates the theta_reject revision (documented in
this script and in the report it writes, per the project's disclose-
everything culture): the real "chile" dataset's T(D) score DROPS from
0.5644 (CONDITIONAL) under the old AHP-only weights to ~0.469 under
the new EWM-blended weights -- purely a byproduct of the EWM
reweighting, since chile's underlying axis scores did not change. This
happens because EWM's entropy-based reweighting pushed a large share
of the A-axis budget onto A1 (Benford's Law conformity), and A(D)
itself now dominates the composite (0.667 of T(D), up from 0.514).
chile's A1/A(D) sub-scores are moderate -- plausibly reflecting benign,
real-world small-catalog sampling effects rather than any authenticity
defect -- so its already-marginal T(D) score falls further under the
new weighting. Left at the OLD theta_reject=0.50, this would have
flipped a known-good, real dataset from CONDITIONAL to REJECT purely
as a side effect of reweighting, which is not an acceptable outcome.
This is disclosed as a genuine, documented LIMITATION of EWM-driven
reweighting on a modest corpus: entropy rewards any HIGH-VARIANCE
criterion as "more discriminative" without regard to WHETHER that
variance actually separates good data from bad, or just reflects
benign differences in catalog size/region/reporting practice. The
theta_reject revision below is the corrective response to this
concrete finding, not a routine tuning choice.

DISCLOSED FOLLOW-UP #1 FROM AN INDEPENDENT RE-VERIFICATION PASS
(2026-07-05, same day): this corpus originally had 71 datasets. A
rigorous re-check of the corpus against the user's original file list
found 2 real USGS ComCat catalogs (ishikawa_202401.json,
japan_2023-.json) that had been present in that list but silently
missed by the initial build -- neither included nor recorded as
excluded. Both were confirmed genuine and distinct (not duplicates of
already-included exports) and added as known_good, growing the corpus
to 73 datasets.

DISCLOSED FOLLOW-UP #2 FROM THE SAME RE-VERIFICATION PASS (a more
significant finding than #1): the first attempt to re-score the
corrected 73-dataset corpus produced axis-level A/P/C/I values that
were INCONSISTENT across rows -- the 2 newly-added datasets were scored
while data_certify/_constants.py's WITHIN_A/P/C/I already held this
session's BLENDED weights (not the AHP prior), while the original 71
datasets had been scored back when those constants still held the pure
AHP prior. This is a genuine circularity in the calibration pipeline's
architecture (calibration/run_scoring.py calls the PRODUCTION axis-
scoring functions, which by design read whatever within-axis weights
are currently live in _constants.py) -- see
calibration/compute_ewm.py's recompute_axis_columns_from_ahp_prior
docstring for the full finding and fix. Both compute_ewm.py and this
script were made self-correcting: they now unconditionally recompute
the axis-level A/P/C/I (and, here, trust_score_ahp_only) columns from
the underlying, weight-independent sub-criteria, using the fixed
AHP_PRIOR weights, rather than trusting whatever score_matrix.csv
happens to already contain. After this fix, the axis-level blended
weights came out close to (not identical to) the original 71-dataset
run (e.g. A: 0.6857 -> 0.6820, a small, plausible shift from adding 2
datasets -- not the much larger, spurious 0.6857 -> 0.6667 shift the
circularity bug had produced), and theta_admit=0.75 / theta_reject=0.45
both hold with a comfortable (not thin) margin on every boundary case:
see the confusion counts and margin note below for the exact numbers.

*** SIXTH-PASS CORRECTNESS FIX (2026-07-06, THE MOST CONSEQUENTIAL FINDING
IN THIS SCRIPT'S HISTORY -- found via a live `run_audit.py --dataset chile`
sanity check, NOT by re-reading this script or its reports) ***: fix #2
above ("recompute A/P/C/I under the AHP_PRIOR weights") solved the
row-to-row inconsistency problem correctly, but every pass from the
2026-07-05 re-verification pass through the fifth pass then made a
SECOND, unrelated mistake on top of that fix: they combined those
AHP-prior-recomputed A/P/C/I columns with the BLENDED AXIS_WEIGHTS to
get `T_new` -- a hybrid formula `DataCertifyAuditor.audit()` never
actually computes. Production combines sub-criteria into A/P/C/I using
the BLENDED WITHIN_A/P/C/I (whatever this pass's compute_ewm.py just
wrote to ewm_report.json, and will shortly be written to
_constants.py), not the AHP prior. For a high-variance criterion like A1
(Benford), whose blended weight (~53%) is far above its AHP prior
(~30%), the two formulas diverge sharply: 'chile' -- the flagship
example this whole theta_reject narrative was built around --
recomputes to A(D)~0.49 under the AHP-prior basis (the previously
reported T(D)=0.4741, CONDITIONAL, "0 known_good falsely rejected") but
the ACTUAL live-production A(D) is ~0.24 (T(D)~0.22, REJECT) -- verified
directly via `score_authenticity()` and cross-checked against a live CLI
run. Once `load_scored_corpus()` below is fixed to combine sub-criteria
using THIS pass's own blended within-axis weights (matching production
exactly, see `recompute_axis_columns_from_blended`'s docstring), the
true picture is far more sobering than every prior pass's "0 false
admits, 0 false rejects" claim: **12 of the 50 known_good datasets --
not just chile -- score below any plausible theta_reject**, and
known_good/known_bad T(D) distributions are heavily interleaved across
nearly the ENTIRE range (e.g. the known_bad
`corrupt_real_morocco_20230908_query_timestamp_collision_high` scores
0.6276, higher than all but 12 of the 50 known_good datasets). No value
of theta_reject can cleanly separate the two populations -- see the
module-level NEW_THETA_REJECT comment and threshold_report.md's
"no-clean-separation" section for the full numeric picture and the
principled (not arbitrary) choice made here in response.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_certify._constants import AXIS_WEIGHTS_AHP_PRIOR
from calibration.compute_ewm import recompute_axis_columns_from_ahp_prior, recompute_axis_columns_from_blended

SCORE_MATRIX_PATH = HERE / "score_matrix.csv"
MANIFEST_PATH = HERE / "corpus_manifest.csv"
EWM_REPORT_PATH = HERE / "ewm_report.json"
REPORT_JSON_PATH = HERE / "threshold_report.json"
REPORT_MD_PATH = HERE / "threshold_report.md"

# Original (pre-calibration) provisional values, from data_certify/_constants.py,
# reproduced here as literals (not imported) so this report is self-contained
# and still meaningful even after _constants.py is updated with the new values.
OLD_THETA_ADMIT = 0.75
OLD_THETA_REJECT = 0.50
OLD_THETA_AUTH = 0.50

# Final calibrated values (see module docstring for the full justification).
NEW_THETA_ADMIT = 0.75   # empirically unchanged: already clears every known_bad case with margin
                          # (sixth pass, 73-dataset corpus: max known_bad T(D) under the CORRECTED
                          # production formula was 0.6276 -- an even larger margin than the
                          # pre-sixth-pass 0.7372 figure. SEVENTH-PASS UPDATE, 2026-07-07,
                          # 89-dataset corpus: value still holds; max known_bad is now 0.6824
                          # (corrupt_real_kahramanmaras_turkey_2023_timestamp_collision_med),
                          # margin 0.0676 -- see _constants.py's SEVENTH CALIBRATION PASS note).
NEW_THETA_REJECT = 0.20  # SIXTH-PASS REVISION (down from 0.45): once validated against the
                          # CORRECTED production formula (see the sixth-pass docstring above), no
                          # value of theta_reject achieves the original "0 known_good falsely
                          # rejected AND catches at least one known_bad" goal cleanly -- known_good
                          # and known_bad T(D) distributions are heavily interleaved from ~0.17 to
                          # ~0.63. Per this project's own stated asymmetric-cost principle (a false
                          # REJECT of genuine data is far less costly than a false ADMIT of bad
                          # data, but still a real cost -- Deep-Dive 05 Section 2.1), the choice made
                          # here PROTECTS known_good data: 0.20 is the largest clean round value
                          # strictly below every known_good dataset (sixth pass, 73-dataset
                          # corpus: true minimum chile at 0.2195), so theta_reject still achieves
                          # ZERO false rejects of real data. The tradeoff, disclosed rather than
                          # hidden: at this level, theta_reject only catches 1 non-hard-override
                          # known_bad dataset by itself (corrupt_nz_inject_missingness_high;
                          # sixth pass: 1 of 15, at 0.1707) -- the rest rely on CONDITIONAL's
                          # "flagged for scrutiny" outcome or on the Stage-1 hard-override gate
                          # rather than on this threshold. SEVENTH-PASS UPDATE (2026-07-07,
                          # 89-dataset corpus): value still holds with zero known_good
                          # false-rejects (new known_good minimum: chile at 0.2469), but the
                          # margin over the nearest known_bad SHRANK sharply, 0.0293 -> 0.0076
                          # (corrupt_nz_inject_missingness_high now at 0.1924); theta_reject
                          # alone now catches 1 of 20 non-hard-override known_bad datasets, and
                          # the hard-override gate independently catches 8 of 28. See
                          # threshold_report.md's "no-clean-separation" section and
                          # _constants.py's SEVENTH CALIBRATION PASS note for the full numeric
                          # picture.
NEW_THETA_AUTH = 0.50    # unchanged: NOT calibrated here, A6 never exercised in this corpus (see docstring)


def load_scored_corpus() -> pd.DataFrame:
    """
    *** CRITICAL CORRECTNESS FIX #1 (2026-07-05 independent re-verification
    pass) *** -- score_matrix.csv's own A/P/C/I columns are NOT trusted
    as-is: they were computed by calling the production axis-scoring
    functions / DataCertifyAuditor, which combine sub-criteria using
    whatever WITHIN_A/P/C/I happen to be LIVE in data_certify/_constants.py
    at scoring time -- which, after the first calibration pass, are the
    BLENDED (not AHP-prior) values, and can vary row-to-row if datasets
    were scored at different points in the session. See
    calibration/compute_ewm.py's recompute_axis_columns_from_ahp_prior
    docstring for the full finding.

    *** CRITICAL CORRECTNESS FIX #2 (2026-07-06 sixth pass, found via a
    live `run_audit.py` sanity check, not by re-reading this script) ***
    -- fix #1's AHP-prior recomputation is the wrong basis for THIS
    script's purpose. Every prior pass computed `T_new` (used for the
    confusion matrix and the theta_reject/theta_admit validation below)
    from AHP-prior-recomputed A/P/C/I columns combined with the BLENDED
    AXIS_WEIGHTS -- a formula DataCertifyAuditor.audit() never actually
    computes: production combines sub-criteria into A/P/C/I using the
    BLENDED WITHIN_A/P/C/I, not the AHP prior. For high-variance criteria
    like A1 (Benford), whose blended weight (~53%) is far above its AHP
    prior (~30%), this produced dramatically different scores for the
    same dataset: 'chile' recomputed to A(D)~0.49 under the AHP-prior
    basis (giving the previously-reported T(D)=0.4741, CONDITIONAL) but
    the ACTUAL live-production A(D) is ~0.24 (giving T(D)~0.22, REJECT) --
    confirmed by calling score_authenticity() directly and cross-checked
    against a live `run_audit.py --dataset chile` run. Every prior pass's
    "0 known_good falsely rejected" claim was therefore validated against
    a formula production does not actually run. Fixed here: recompute
    A/P/C/I using recompute_axis_columns_from_blended() with THIS pass's
    own freshly-computed blended within-axis weights (read from
    ewm_report.json, written by compute_ewm.py immediately before this
    script runs) -- mathematically identical to what audit() will compute
    once those weights are live in _constants.py. See
    Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Section 4.2
    (or its sixth-pass update) for the full, sobering result: no clean
    theta_reject value exists once validated this way -- known_good and
    known_bad datasets are heavily interleaved across nearly the entire
    T(D) range.

    `trust_score_ahp_only` is a SEPARATE, intentional comparison point
    (the "what would this dataset have scored under the original, wholly
    AHP-only design, before ANY empirical calibration" baseline used in
    the chile_regression_finding narrative below) -- it is deliberately
    computed from the AHP-prior-recomputed axis columns AND
    AXIS_WEIGHTS_AHP_PRIOR, i.e. fully AHP-only end-to-end, which is
    internally consistent and was never the source of the bug above.
    """
    s = pd.read_csv(SCORE_MATRIX_PATH)

    with open(EWM_REPORT_PATH) as f:
        ewm = json.load(f)
    blended_within = {
        "A": ewm["within_A"]["blended_weights"],
        "P": ewm["within_P"]["blended_weights"],
        "C": ewm["within_C"]["blended_weights"],
        "I": ewm["within_I"]["blended_weights"],
    }
    w = ewm["axis"]["blended_weights"]

    s_ahp = recompute_axis_columns_from_ahp_prior(s)

    def _trust_ahp_only(row):
        applicable = {k: row[k] for k in ("A", "P", "C", "I") if pd.notna(row[k])}
        if not applicable:
            return float("nan")
        w_sum = sum(AXIS_WEIGHTS_AHP_PRIOR[k] for k in applicable)
        return sum(AXIS_WEIGHTS_AHP_PRIOR[k] * v for k, v in applicable.items()) / w_sum

    s_ahp["trust_score_ahp_only"] = s_ahp.apply(_trust_ahp_only, axis=1)

    s = recompute_axis_columns_from_blended(s, blended_within)
    s["trust_score_ahp_only"] = s_ahp["trust_score_ahp_only"]

    m = pd.read_csv(MANIFEST_PATH)
    df = s.merge(m[["dataset_id", "label", "category"]], on="dataset_id")
    df["hard_override_fired"] = df["hard_override_fired"].astype(bool)

    def _trust_prod(row):
        applicable = {k: row[k] for k in ("A", "P", "C", "I") if pd.notna(row[k])}
        if not applicable:
            return float("nan")
        w_sum = sum(w[k] for k in applicable)
        return sum(w[k] * v for k, v in applicable.items()) / w_sum

    df["T_new"] = df.apply(_trust_prod, axis=1)
    return df


def confusion_counts(df: pd.DataFrame, theta_admit: float, theta_reject: float) -> dict:
    good = df[df.label == "known_good"]
    bad = df[df.label == "known_bad"]
    bad_soft = bad[~bad.hard_override_fired]
    return {
        "theta_admit": theta_admit,
        "theta_reject": theta_reject,
        "n_known_good": int(len(good)),
        "n_known_bad": int(len(bad)),
        "n_known_bad_soft": int(len(bad_soft)),
        "good_admitted": int((good.T_new >= theta_admit).sum()),
        "good_conditional": int(((good.T_new >= theta_reject) & (good.T_new < theta_admit)).sum()),
        "good_falsely_rejected": int((good.T_new < theta_reject).sum()),
        "bad_falsely_admitted": int((bad.T_new >= theta_admit).sum()),
        "bad_conditional": int(((bad.T_new >= theta_reject) & (bad.T_new < theta_admit)).sum()),
        "bad_rejected_by_T": int((bad.T_new < theta_reject).sum()),
        "bad_rejected_total_incl_hard_override": int(
            ((bad.T_new < theta_reject) | bad.hard_override_fired).sum()
        ),
    }


def main() -> None:
    df = load_scored_corpus()

    chile_old = float(df.loc[df.dataset_id == "chile", "trust_score_ahp_only"].iloc[0])
    chile_new = float(df.loc[df.dataset_id == "chile", "T_new"].iloc[0])

    old_conf = confusion_counts(df, OLD_THETA_ADMIT, OLD_THETA_REJECT)
    new_conf = confusion_counts(df, NEW_THETA_ADMIT, NEW_THETA_REJECT)

    good_sorted = df[df.label == "known_good"].sort_values("T_new")
    bad_sorted = df[df.label == "known_bad"].sort_values("T_new")

    report = {
        "chile_regression_finding": {
            "description": (
                f"Real dataset 'chile' scores {chile_old:.4f} (CONDITIONAL) under "
                f"the old AHP-only weights but {chile_new:.4f} under the new "
                f"EWM-blended weights ({len(df)}-dataset corpus) -- a byproduct of EWM "
                "reweighting A(D)'s budget toward A1 (Benford's Law), not any "
                "change in chile's underlying data. Under the OLD "
                "theta_reject=0.50 this would flip chile from CONDITIONAL to "
                "REJECT -- an unacceptable side effect on a real, known-good "
                "dataset. This finding is what motivates lowering theta_reject."
            ),
            "chile_T_ahp_only": chile_old,
            "chile_T_new_blended": chile_new,
        },
        "old_thresholds": {
            "theta_admit": OLD_THETA_ADMIT, "theta_reject": OLD_THETA_REJECT, "theta_auth": OLD_THETA_AUTH,
        },
        "new_thresholds": {
            "theta_admit": NEW_THETA_ADMIT, "theta_reject": NEW_THETA_REJECT, "theta_auth": NEW_THETA_AUTH,
        },
        "theta_auth_note": (
            "theta_auth is NOT calibrated by this script: A6 (external-catalog "
            "cross-match) is never exercised in this corpus's main scoring run "
            "(calibration/run_scoring.py uses no external reference, so A6 is "
            "applicable=False for every dataset -- there is no A6 column in "
            "score_matrix.csv at all). A SEPARATE, dedicated pipeline has since "
            "exercised A6 across the full corpus with a real USGS reference "
            "(calibration/run_a6_scoring.py / score_matrix_a6.csv + "
            "calibration/calibrate_theta_auth.py -- see "
            "calibration/theta_auth_report.md) and confirmed that no clean "
            "theta_auth value separates known_good from known_bad (a structural "
            "property of what A6 measures, not a data-volume artifact). "
            "theta_auth therefore remains at its original 0.50 as a considered, "
            "evidence-based non-change -- see "
            "Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_"
            "Weights_Master_Reference.md Section 4's theta_auth row."
        ),
        "corpus_gap_disclosure": (
            "This corpus was originally built with 71 datasets. An independent "
            "re-verification pass on 2026-07-05 found that ishikawa_202401.json "
            "and japan_2023-.json -- present in the user's original file list -- "
            "had been missed by the initial build (neither included nor recorded "
            "as excluded). Both were confirmed genuine, distinct real USGS "
            "ComCat catalogs and added as known_good, growing the corpus to 73. "
            "The SAME re-verification pass also found and fixed a more "
            "significant bug: a circularity where axis-level A/P/C/I columns "
            "were computed using whatever within-axis weights happened to be "
            "live in _constants.py at scoring time (see "
            "calibration/compute_ewm.py's recompute_axis_columns_from_ahp_prior "
            "docstring). Both this script and compute_ewm.py now unconditionally "
            "recompute those columns from the underlying sub-criteria under a "
            "fixed weight basis before doing anything else."
        ),
        "sixth_pass_no_clean_separation_finding": (
            "2026-07-06, sixth pass: a live `run_audit.py --dataset chile` sanity "
            "check revealed that every prior pass (including this project's own "
            "'0 false-admits, 0 false-rejects' claims) validated theta_reject "
            "against a formula production never actually runs -- see this "
            "script's module docstring for the full root-cause. Once corrected "
            "to match production exactly, known_good and known_bad T(D) "
            "distributions are heavily interleaved from ~0.17 to ~0.63 -- no "
            "theta_reject value cleanly separates them. theta_reject=0.20 was "
            "chosen to guarantee zero known_good false-rejects (the documented "
            "priority -- Deep-Dive 05 Section 2.1), at the disclosed cost that "
            "it now catches only 1 of 15 non-hard-override known_bad datasets by "
            "itself. theta_admit=0.75 is UNAFFECTED by this finding and remains "
            "safely validated (max known_bad T(D) under the corrected formula is "
            "0.6276, an even larger margin than previously reported)."
        ),
        "confusion_counts_with_old_thresholds_and_new_weights": old_conf,
        "confusion_counts_with_new_thresholds_and_new_weights": new_conf,
        "known_good_sorted_T_new": good_sorted[["dataset_id", "T_new"]].to_dict("records"),
        "known_bad_sorted_T_new": bad_sorted[["dataset_id", "T_new", "hard_override_fired"]].to_dict("records"),
    }

    with open(REPORT_JSON_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"JSON report -> {REPORT_JSON_PATH}")

    # Generic nearest-neighbor margin note (replaces the old hardcoded
    # fabricated_naive_2 reference, which is no longer the dataset nearest
    # the boundary under the corrected formula): find the known_bad
    # (non-hard-override) case closest to, but below, theta_reject, and the
    # known_good case closest to, but above, theta_reject.
    bad_soft_df = df[(df.label == "known_bad") & (~df.hard_override_fired)]
    below = bad_soft_df[bad_soft_df.T_new < NEW_THETA_REJECT].sort_values("T_new", ascending=False)
    good_df = df[df.label == "known_good"].sort_values("T_new")
    margin_lines = []
    if len(below):
        nearest_bad = below.iloc[0]
        margin_lines.append(
            f"- Nearest known_bad below theta_reject: `{nearest_bad.dataset_id}` at "
            f"{nearest_bad.T_new:.6f} ({NEW_THETA_REJECT - nearest_bad.T_new:.6f} below the boundary)."
        )
    else:
        margin_lines.append("- No known_bad dataset falls below theta_reject by T(D) alone at this level.")
    nearest_good = good_df.iloc[0]
    margin_lines.append(
        f"- Nearest known_good above theta_reject: `{nearest_good.dataset_id}` at "
        f"{nearest_good.T_new:.6f} ({nearest_good.T_new - NEW_THETA_REJECT:.6f} above the boundary)."
    )
    margin_note = ("\n**Margin note (current corpus, corrected production formula)**:\n"
                   + "\n".join(margin_lines) + "\n")

    lines = []
    lines.append(f"# Threshold Calibration Report (real {len(df)}-dataset calibration corpus)\n")
    lines.append(
        "Corpus history: 71 -> 73 datasets (2026-07-05: an independent re-verification "
        "pass found and fixed a 2-file gap -- ishikawa_202401.json, japan_2023-.json; "
        "see corpus_gap_disclosure in the JSON report and calibration/parsers.py) "
        "-> 89 datasets (2026-07-07: seventh-pass expansion, 11 new real catalogs + "
        "4 corrupted derivatives + 1 fabricated -- see calibration/build_corpus.py's "
        "STANDARD_FILES_V7/NEW_CORRUPTION_PLAN).\n"
    )
    lines.append("## Sixth-pass finding: no clean theta_reject separation exists\n")
    lines.append(report["sixth_pass_no_clean_separation_finding"] + "\n")
    lines.append("## Key finding that originally motivated the (now-superseded) theta_reject=0.45 revision\n")
    lines.append(report["chile_regression_finding"]["description"] + "\n")
    lines.append(f"- chile T(D) under old AHP-only weights: **{chile_old:.4f}** (CONDITIONAL)")
    lines.append(f"- chile T(D) under the CORRECTED production formula: **{chile_new:.4f}** (REJECT)")
    lines.append(margin_note)
    lines.append("## Final calibrated thresholds\n")
    lines.append("| Threshold | Old (provisional) | New (calibrated) |")
    lines.append("|---|---|---|")
    lines.append(f"| theta_admit | {OLD_THETA_ADMIT} | {NEW_THETA_ADMIT} (unchanged, now empirically validated against the CORRECTED formula) |")
    lines.append(f"| theta_reject | {OLD_THETA_REJECT} | {NEW_THETA_REJECT} (sixth-pass revision -- see finding above) |")
    lines.append(f"| theta_auth | {OLD_THETA_AUTH} | {NEW_THETA_AUTH} (unchanged -- **not calibrated**, see note) |")
    lines.append("")
    lines.append("theta_auth note: " + report["theta_auth_note"] + "\n")
    lines.append("## Confusion counts: old thresholds (0.75/0.50) vs. CORRECTED production formula\n")
    lines.append(f"```\n{json.dumps(old_conf, indent=2)}\n```\n")
    lines.append("## Confusion counts: new thresholds (0.75/0.20) vs. CORRECTED production formula\n")
    lines.append(f"```\n{json.dumps(new_conf, indent=2)}\n```\n")
    lines.append(f"## known_good T(D), sorted ascending (all {len(report['known_good_sorted_T_new'])} -- shown in full given the no-clean-separation finding)\n")
    lines.append("| dataset_id | T(D) |")
    lines.append("|---|---|")
    for row in report["known_good_sorted_T_new"]:
        lines.append(f"| {row['dataset_id']} | {row['T_new']:.4f} |")
    lines.append("")
    lines.append(f"## known_bad T(D), sorted ascending (all {len(report['known_bad_sorted_T_new'])})\n")
    lines.append("| dataset_id | T(D) | hard_override_fired |")
    lines.append("|---|---|---|")
    for row in report["known_bad_sorted_T_new"]:
        lines.append(f"| {row['dataset_id']} | {row['T_new']:.4f} | {row['hard_override_fired']} |")
    lines.append("")
    with open(REPORT_MD_PATH, "w") as f:
        f.write("\n".join(lines))
    print(f"Markdown report -> {REPORT_MD_PATH}")

    print("")
    print("=" * 70)
    print(f"theta_admit:  {OLD_THETA_ADMIT} -> {NEW_THETA_ADMIT}")
    print(f"theta_reject: {OLD_THETA_REJECT} -> {NEW_THETA_REJECT}")
    print(f"theta_auth:   {OLD_THETA_AUTH} -> {NEW_THETA_AUTH} (unchanged, not calibrated -- see note)")
    print("=" * 70)


if __name__ == "__main__":
    main()
