# Threshold Calibration Report (real 968-dataset calibration corpus)

Corpus history: 71 -> 73 datasets (2026-07-05: an independent re-verification pass found and fixed a 2-file gap -- ishikawa_202401.json, japan_2023-.json; see corpus_gap_disclosure in the JSON report and calibration/parsers.py) -> 89 datasets (2026-07-07: seventh-pass expansion, 11 new real catalogs + 4 corrupted derivatives + 1 fabricated -- see calibration/build_corpus.py's STANDARD_FILES_V7/NEW_CORRUPTION_PLAN).

## Sixth-pass finding: no clean theta_reject separation exists

2026-07-06, sixth pass: a live `run_audit.py --dataset chile` sanity check revealed that every prior pass (including this project's own '0 false-admits, 0 false-rejects' claims) validated theta_reject against a formula production never actually runs -- see this script's module docstring for the full root-cause. Once corrected to match production exactly, known_good and known_bad T(D) distributions are heavily interleaved from ~0.17 to ~0.63 -- no theta_reject value cleanly separates them. theta_reject=0.20 was chosen to guarantee zero known_good false-rejects (the documented priority -- Deep-Dive 05 Section 2.1), at the disclosed cost that it now catches only 1 of 15 non-hard-override known_bad datasets by itself. theta_admit=0.75 is UNAFFECTED by this finding and remains safely validated (max known_bad T(D) under the corrected formula is 0.6276, an even larger margin than previously reported).

## Key finding that originally motivated the (now-superseded) theta_reject=0.45 revision

Real dataset 'chile' scores 0.5846 (CONDITIONAL) under the old AHP-only weights but 0.4089 under the new EWM-blended weights (968-dataset corpus) -- a byproduct of EWM reweighting A(D)'s budget toward A1 (Benford's Law), not any change in chile's underlying data. Under the OLD theta_reject=0.50 this would flip chile from CONDITIONAL to REJECT -- an unacceptable side effect on a real, known-good dataset. This finding is what motivates lowering theta_reject.

- chile T(D) under old AHP-only weights: **0.5846** (CONDITIONAL)
- chile T(D) under the CORRECTED production formula: **0.4089** (REJECT)

**Margin note (current corpus, corrected production formula)**:
- No known_bad dataset falls below theta_reject by T(D) alone at this level.
- Nearest known_good above theta_reject: `real_drc_rift_general_recent` at 0.340304 (0.140304 above the boundary).

## Final calibrated thresholds

| Threshold | Old (provisional) | New (calibrated) |
|---|---|---|
| theta_admit | 0.75 | 0.75 (unchanged, now empirically validated against the CORRECTED formula) |
| theta_reject | 0.5 | 0.2 (sixth-pass revision -- see finding above) |
| theta_auth | 0.5 | 0.5 (unchanged -- **not calibrated**, see note) |

theta_auth note: theta_auth is NOT calibrated by this script: A6 (external-catalog cross-match) is never exercised in this corpus's main scoring run (calibration/run_scoring.py uses no external reference, so A6 is applicable=False for every dataset -- there is no A6 column in score_matrix.csv at all). A SEPARATE, dedicated pipeline has since exercised A6 across the full corpus with a real USGS reference (calibration/run_a6_scoring.py / score_matrix_a6.csv + calibration/calibrate_theta_auth.py -- see calibration/theta_auth_report.md) and confirmed that no clean theta_auth value separates known_good from known_bad (a structural property of what A6 measures, not a data-volume artifact). theta_auth therefore remains at its original 0.50 as a considered, evidence-based non-change -- see Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Section 4's theta_auth row.

## Confusion counts: old thresholds (0.75/0.50) vs. CORRECTED production formula

```
{
  "theta_admit": 0.75,
  "theta_reject": 0.5,
  "n_known_good": 508,
  "n_known_bad": 460,
  "n_known_bad_soft": 434,
  "good_admitted": 71,
  "good_conditional": 395,
  "good_falsely_rejected": 42,
  "bad_falsely_admitted": 19,
  "bad_conditional": 222,
  "bad_rejected_by_T": 219,
  "bad_rejected_total_incl_hard_override": 240
}
```

## Confusion counts: new thresholds (0.75/0.20) vs. CORRECTED production formula

```
{
  "theta_admit": 0.75,
  "theta_reject": 0.2,
  "n_known_good": 508,
  "n_known_bad": 460,
  "n_known_bad_soft": 434,
  "good_admitted": 71,
  "good_conditional": 437,
  "good_falsely_rejected": 0,
  "bad_falsely_admitted": 19,
  "bad_conditional": 441,
  "bad_rejected_by_T": 0,
  "bad_rejected_total_incl_hard_override": 26
}
```

## known_good T(D), sorted ascending (all 508 -- shown in full given the no-clean-separation finding)

| dataset_id | T(D) |
|---|---|
| real_drc_rift_general_recent | 0.3403 |
| real_russia_baikal_general_early2 | 0.3472 |
| real_potvilla_2024012 | 0.3580 |
| real_afghanistan_2025_09_01 | 0.3650 |
| real_china_gansu_general_recent | 0.3666 |
| real_cuba_general_early2 | 0.3668 |
| real_croatia_petrinja_2020 | 0.3677 |
| real_taiwan_20240403_query | 0.3677 |
| real_turkey_202504 | 0.3678 |
| real_colombia_armenia_1999 | 0.3681 |
| real_dominicanrepublic_general | 0.3875 |
| real_romania_vrancea_general | 0.4011 |
| real_tokara_202506 | 0.4051 |
| nz | 0.4066 |
| chile | 0.4089 |
| real_bangladesh_general_early2 | 0.4210 |
| real_greenland_general_early3 | 0.4320 |
| real_romania_vrancea_general_early2 | 0.4324 |
| real_samoa_general_early3 | 0.4337 |
| real_madagascar_general | 0.4356 |
| real_myanmar_sagaing_general_early2 | 0.4448 |
| real_poland_general_early2 | 0.4516 |
| real_turkey_izmit_1999_recent | 0.4547 |
| real_nicaragua_general_early3 | 0.4577 |
| real_italy_sicily_etna_general_early | 0.4719 |
| real_colombia_armenia_1999_recent | 0.4736 |
| real_iceland_general | 0.4756 |
| real_norway_general_early | 0.4766 |
| real_usa_nevada_basinrange_general_early3 | 0.4772 |
| real_peru_pisco_2007_recent | 0.4786 |
| real_colombia_andes_general_early | 0.4834 |
| real_guam_general_early2 | 0.4850 |
| real_honduras_general_early2 | 0.4862 |
| real_jordan_general | 0.4889 |
| real_australia_general_early3 | 0.4894 |
| real_venezuela_general_early3 | 0.4939 |
| real_newcaledonia_general_early3 | 0.4948 |
| real_guam_general_early3 | 0.4953 |
| real_israel_deadsea_general | 0.4973 |
| real_chile_maule_2010 | 0.4979 |
| real_papuanewguinea_general_early3 | 0.4980 |
| real_austria_general_early2 | 0.4995 |
| real_dominicanrepublic_general_early2 | 0.5012 |
| real_iran_ahar_varzaghan_2012_recent | 0.5020 |
| real_peru_arequipa_2001 | 0.5024 |
| real_iceland_reykjanes_2021_recent | 0.5026 |
| real_guadeloupe_martinique_general_early2 | 0.5039 |
| real_elsalvador_2001 | 0.5080 |
| real_iceland_reykjanes_2021 | 0.5085 |
| real_azerbaijan_general_early | 0.5103 |
| real_algeria_boumerdes_2003_recent | 0.5110 |
| real_poland_general_early | 0.5111 |
| real_nicaragua_general_early2 | 0.5127 |
| real_tuvalu_kiribati_general_early2 | 0.5146 |
| real_tohoku_2005_2011 | 0.5151 |
| real_india_gujarat_bhuj_2001_recent | 0.5154 |
| real_haiti_2010 | 0.5158 |
| real_switzerland_general_early2 | 0.5161 |
| real_papuanewguinea_general | 0.5166 |
| real_china_taiwanstrait_general | 0.5166 |
| real_png_highlands_2018 | 0.5169 |
| real_usgs_main | 0.5175 |
| real_india_gujarat_bhuj_2001 | 0.5177 |
| real_vanuatu_general_early2 | 0.5199 |
| real_2025_03_myanmar | 0.5210 |
| real_pakistan_balochistan_2013_recent | 0.5212 |
| real_gorkha_nepal_2015 | 0.5213 |
| real_russia_sakhalin_general_recent | 0.5216 |
| real_argentina_sanjuan_general_early2 | 0.5233 |
| real_vietnam_general_recent | 0.5242 |
| real_trinidadtobago_general_early2 | 0.5243 |
| real_honduras_general_early | 0.5251 |
| real_usa_yellowstone_general_early2 | 0.5265 |
| real_india_andaman_general_early3 | 0.5270 |
| real_algeria_boumerdes_2003 | 0.5280 |
| real_india_uttarakhand_general_early2 | 0.5293 |
| real_guatemala_general_early | 0.5307 |
| real_fiji_general_early2 | 0.5311 |
| real_uzbekistan_general_recent | 0.5321 |
| real_india_assam_general_early2 | 0.5323 |
| real_indonesia_java_general_early3 | 0.5324 |
| real_peru_pisco_2007 | 0.5329 |
| real_russia_kurilislands_general_early3 | 0.5330 |
| real_bolivia_deep_general_early3 | 0.5338 |
| real_india_kashmir_2005 | 0.5340 |
| real_indonesia_sumatra_general_early2 | 0.5342 |
| real_india_kashmir_2005_recent | 0.5347 |
| real_haiti_2010_recent | 0.5354 |
| real_dominicanrepublic_general_recent | 0.5384 |
| real_cyprus_general_early2 | 0.5397 |
| real_iran_bam_2003_recent | 0.5400 |
| real_bangladesh_general_recent | 0.5409 |
| real_taiwan_20240423_query | 0.5418 |
| real_myanmar_sagaing_general_early3 | 0.5419 |
| real_canada_quebec_general_early | 0.5431 |
| real_southafrica_general_early2 | 0.5457 |
| real_ethiopia_general_early3 | 0.5466 |
| real_samoa_general_recent | 0.5468 |
| real_usa_cascadia_general_early | 0.5470 |
| real_vanuatu_general_early3 | 0.5478 |
| real_guatemala_general_early2 | 0.5485 |
| real_ecuador_general_early2 | 0.5494 |
| real_russia_sakhalin_general_early2 | 0.5497 |
| real_papuanewguinea_general_early2 | 0.5499 |
| real_bolivia_deep_general | 0.5500 |
| real_panama_general_early | 0.5518 |
| real_costarica_general_early2 | 0.5522 |
| real_chile_iquique_2014 | 0.5529 |
| real_bangladesh_general | 0.5535 |
| real_colombia_andes_general_early3 | 0.5540 |
| real_202507_Kamchatka | 0.5543 |
| real_botswana_general_early | 0.5544 |
| real_indonesia_sumatra_general_early3 | 0.5547 |
| real_ecuador_general_early3 | 0.5562 |
| real_puertorico_2020_ponce | 0.5571 |
| real_southafrica_general_early | 0.5583 |
| real_ishikawa_2024_query | 0.5585 |
| real_peru_arequipa_2001_recent | 0.5588 |
| real_philippines_luzon_general_early | 0.5590 |
| real_portugal_azores_general_recent | 0.5599 |
| real_newcaledonia_general_early | 0.5603 |
| real_italy_sicily_etna_general_early2 | 0.5608 |
| real_bulgaria_general_early | 0.5630 |
| real_china_tibet_plateau_general_early3 | 0.5632 |
| real_guam_general | 0.5635 |
| real_iceland_general_early | 0.5641 |
| real_indonesia_java_general_early2 | 0.5642 |
| real_mexico_oaxaca_general | 0.5658 |
| real_canada_quebec_general_early2 | 0.5668 |
| real_earthquake1 | 0.5673 |
| real_russia_kurilislands_general_early2 | 0.5676 |
| real_china_taiwanstrait_general_early | 0.5687 |
| real_usa_yellowstone_general_early3 | 0.5690 |
| real_china_hebei_general_early2 | 0.5701 |
| real_syria_general_early | 0.5719 |
| real_china_sichuan_2008 | 0.5729 |
| real_russia_caucasus_general_early2 | 0.5738 |
| real_canada_quebec_general | 0.5741 |
| real_poland_general_recent | 0.5751 |
| real_canada_britishcolumbia_general | 0.5755 |
| real_mexico_oaxaca_general_early2 | 0.5761 |
| real_ishikawa_202401 | 0.5761 |
| real_argentina_sanjuan_general_early | 0.5768 |
| real_nicaragua_general | 0.5770 |
| real_usa_nevada_basinrange_general_early2 | 0.5779 |
| real_samoa_general_early2 | 0.5791 |
| real_trinidadtobago_general_early | 0.5793 |
| real_turkey_izmit_1999 | 0.5795 |
| real_elsalvador_2001_recent | 0.5798 |
| real_panama_general_early3 | 0.5804 |
| real_southafrica_general_recent | 0.5813 |
| real_uzbekistan_general_early3 | 0.5813 |
| real_trinidadtobago_general | 0.5825 |
| real_china_taiwanstrait_general_early2 | 0.5826 |
| real_panama_general_early2 | 0.5837 |
| real_honduras_general_early3 | 0.5837 |
| real_canada_britishcolumbia_general_early2 | 0.5841 |
| real_india_uttarakhand_general | 0.5843 |
| real_vanuatu_general | 0.5845 |
| real_australia_general_early2 | 0.5849 |
| real_dominicanrepublic_general_early3 | 0.5860 |
| real_thailand_general_early2 | 0.5865 |
| real_china_qinghai_yushu_2010_recent | 0.5875 |
| real_venezuela_general_early2 | 0.5876 |
| real_fiji_general_recent | 0.5887 |
| real_pakistan_balochistan_2013 | 0.5889 |
| real_solomonislands_general_early2 | 0.5890 |
| real_all_month | 0.5893 |
| real_syria_general_recent | 0.5897 |
| real_slovenia_general_early2 | 0.5900 |
| real_russia_kurilislands_general_early | 0.5901 |
| real_newzealand_kaikoura_2016_recent | 0.5903 |
| real_yemen_general_early3 | 0.5917 |
| real_tohoku_202512 | 0.5923 |
| real_tanzania_rift_general_early2 | 0.5931 |
| real_morocco_alhoceima_2004 | 0.5931 |
| real_switzerland_general | 0.5934 |
| real_azerbaijan_general_early2 | 0.5942 |
| real_tohoku_202511 | 0.5948 |
| real_newcaledonia_general_recent | 0.5948 |
| real_russia_caucasus_general | 0.5960 |
| real_laos_general_early2 | 0.5962 |
| real_canada_britishcolumbia_general_early3 | 0.5963 |
| real_romania_vrancea_general_early | 0.5969 |
| real_fiji_general_early | 0.5971 |
| real_solomonislands_general_early3 | 0.5975 |
| real_guatemala_general_early3 | 0.5985 |
| real_iraq_halabja_2017_recent | 0.5989 |
| real_mexico_oaxaca_general_recent | 0.5990 |
| real_russia_kurilislands_general_recent | 0.5999 |
| real_morocco_alhoceima_2004_recent | 0.6013 |
| real_drc_rift_general_early2 | 0.6014 |
| real_cyprus_general_recent | 0.6022 |
| real_china_yunnan_general_early3 | 0.6029 |
| real_muisne_pedernales_ecuador_2016 | 0.6031 |
| real_venezuela_general | 0.6036 |
| real_indonesia_java_general_early | 0.6036 |
| real_philippines_mindanao_general_early3 | 0.6041 |
| real_newcaledonia_general_early2 | 0.6045 |
| real_china_taiwanstrait_general_recent | 0.6049 |
| real_egypt_general_early | 0.6054 |
| real_argentina_sanjuan_general_recent | 0.6060 |
| real_colombia_andes_general | 0.6061 |
| real_tanzania_rift_general_early3 | 0.6071 |
| real_syria_general_early2 | 0.6073 |
| real_guam_general_early | 0.6078 |
| real_yemen_general_early2 | 0.6079 |
| real_usa_virginia_2011_recent | 0.6081 |
| real_portugal_azores_general_early2 | 0.6082 |
| real_cuba_general | 0.6088 |
| real_colombia_andes_general_early2 | 0.6089 |
| real_newcaledonia_general | 0.6092 |
| real_indonesia_palu_2018 | 0.6107 |
| real_guatemala_general | 0.6130 |
| real_chile_iquique_2014_recent | 0.6138 |
| real_solomonislands_general_early | 0.6141 |
| real_malawi_general_early2 | 0.6142 |
| real_nicaragua_general_recent | 0.6151 |
| real_austria_general_early | 0.6159 |
| real_argentina_sanjuan_general_early3 | 0.6165 |
| real_pakistan_general_early3 | 0.6170 |
| real_philippines_luzon_general_early3 | 0.6171 |
| real_nicaragua_general_early | 0.6173 |
| real_bolivia_deep_general_early2 | 0.6176 |
| real_panama_general | 0.6186 |
| real_202606_philippines | 0.6200 |
| real_japan_20220319_query | 0.6205 |
| real_vanuatu_general_early | 0.6213 |
| real_china_gansu_general_early2 | 0.6214 |
| real_india_andaman_general_early | 0.6226 |
| real_mexico_oaxaca_general_early3 | 0.6231 |
| real_usa_oklahoma_induced_general_recent | 0.6231 |
| real_pakistan_general_early2 | 0.6236 |
| real_indonesia_java_general | 0.6244 |
| real_china_hebei_general_early3 | 0.6244 |
| real_iceland_general_recent | 0.6245 |
| real_amatrice_norcia_italy_2016 | 0.6247 |
| real_newzealand_kaikoura_2016 | 0.6250 |
| real_solomonislands_general | 0.6266 |
| real_usa_cascadia_general_early2 | 0.6273 |
| real_greenland_general_early | 0.6274 |
| real_taiwan_2024_query | 0.6277 |
| real_russia_kurilislands_general | 0.6279 |
| real_dominicanrepublic_general_early | 0.6281 |
| real_albania_durres_2019 | 0.6284 |
| real_india_assam_general_early | 0.6284 |
| real_chiapas_mexico_2017 | 0.6285 |
| real_argentina_sanjuan_general | 0.6286 |
| real_guatemala_general_recent | 0.6291 |
| real_australia_general_early | 0.6293 |
| real_honduras_general_recent | 0.6298 |
| real_canada_britishcolumbia_general_early | 0.6301 |
| real_china_tibet_plateau_general | 0.6302 |
| real_russia_baikal_general_early | 0.6309 |
| real_india_andaman_general | 0.6310 |
| real_costarica_general_early | 0.6317 |
| real_pakistan_general_recent | 0.6320 |
| real_tonga_20210101_20220117_query | 0.6322 |
| real_costarica_general_early3 | 0.6326 |
| real_indonesia_sumatra_general_early | 0.6326 |
| real_usa_newmadrid_general_recent | 0.6339 |
| real_iraq_halabja_2017 | 0.6344 |
| real_botswana_general_early2 | 0.6346 |
| real_202509_Kamchatka | 0.6351 |
| real_china_xinjiang_general_early3 | 0.6356 |
| real_iceland_general_early3 | 0.6356 |
| real_ethiopia_general_recent | 0.6358 |
| real_202510_philippines | 0.6364 |
| real_japan_2000_2023_query | 0.6365 |
| real_kenya_general_recent | 0.6367 |
| real_marianaislands_general_early2 | 0.6368 |
| real_turkey_van_2011 | 0.6368 |
| real_afghanistan_20231008_query | 0.6368 |
| real_china_shanxi_general | 0.6372 |
| real_switzerland_general_early | 0.6372 |
| real_japan_20190101-20211009_query | 0.6377 |
| real_jordan_general_early | 0.6385 |
| real_fiji_general_early3 | 0.6393 |
| real_mexico_baja_general_early | 0.6398 |
| real_bolivia_deep_general_recent | 0.6399 |
| real_usa_newmadrid_general_early | 0.6401 |
| real_puertorico_2020_ponce_recent | 0.6405 |
| real_china_qinghai_yushu_2010 | 0.6405 |
| real_portugal_azores_general | 0.6413 |
| real_centralasia_kyrgyzstan_tajikistan_early3 | 0.6416 |
| real_cyprus_general_early | 0.6422 |
| real_egypt_general | 0.6427 |
| real_bangladesh_general_early | 0.6434 |
| real_canada_britishcolumbia_general_recent | 0.6460 |
| real_bolivia_deep_general_early | 0.6461 |
| real_russia_baikal_general | 0.6472 |
| real_nepal_sikkim_general | 0.6475 |
| real_mexico_oaxaca_general_early | 0.6479 |
| real_india_assam_general_recent | 0.6503 |
| real_marianaislands_general_early | 0.6505 |
| real_usa_newmadrid_general_early2 | 0.6506 |
| real_ecuador_general_recent | 0.6516 |
| real_guadeloupe_martinique_general_early | 0.6517 |
| real_myanmar_sagaing_general_recent | 0.6523 |
| real_india_assam_general_early3 | 0.6526 |
| real_marianaislands_general | 0.6535 |
| real_germany_general_early2 | 0.6547 |
| real_kazakhstan_general_early3 | 0.6548 |
| real_india_assam_general | 0.6549 |
| real_tanzania_rift_general_early | 0.6552 |
| real_kahramanmaras_turkey_2023 | 0.6556 |
| real_costarica_general_recent | 0.6560 |
| real_bulgaria_general_early2 | 0.6562 |
| real_202604_tohoku_japan | 0.6566 |
| real_japan-20190101_20211203_query | 0.6574 |
| real_vanuatu_general_recent | 0.6575 |
| real_kenya_general | 0.6578 |
| real_philippines_mindanao_general_recent | 0.6578 |
| real_usa_hawaii_kilauea_2018 | 0.6584 |
| real_usa_puertorico_general | 0.6590 |
| real_samoa_general | 0.6591 |
| real_marianaislands_general_early3 | 0.6596 |
| real_centralasia_kyrgyzstan_tajikistan_early | 0.6596 |
| real_solomonislands_general_recent | 0.6611 |
| real_bulgaria_general | 0.6613 |
| real_india_andaman_general_recent | 0.6618 |
| real_colombia_andes_general_recent | 0.6620 |
| real_ethiopia_general_early2 | 0.6647 |
| real_mexico_baja_general_early2 | 0.6657 |
| real_france_general_early | 0.6659 |
| real_india_uttarakhand_general_early | 0.6666 |
| real_usa_utah_wasatch_general_early2 | 0.6667 |
| real_kermanshah_iran_2017 | 0.6672 |
| real_russia_caucasus_general_early | 0.6673 |
| real_indonesia_java_general_recent | 0.6684 |
| real_guam_general_recent | 0.6692 |
| real_germany_general_early | 0.6696 |
| real_myanmar_sagaing_general_early | 0.6696 |
| real_greenland_general_recent | 0.6703 |
| real_usa_puertorico_general_recent | 0.6711 |
| real_france_general_early2 | 0.6714 |
| real_kazakhstan_general_early2 | 0.6723 |
| real_germany_general | 0.6725 |
| real_usa_nevada_basinrange_general_early | 0.6729 |
| real_centralasia_kyrgyzstan_tajikistan_early2 | 0.6738 |
| real_papuanewguinea_general_early | 0.6740 |
| real_yemen_general_early | 0.6756 |
| real_ishikawa_202401_query | 0.6765 |
| real_indonesia_sumatra_general_recent | 0.6771 |
| real_philippines_mindanao_general_early2 | 0.6781 |
| real_usa_cascadia_general_early3 | 0.6783 |
| real_philippines_luzon_general_early2 | 0.6786 |
| real_morocco_20230908_query | 0.6789 |
| real_costarica_general | 0.6792 |
| real_usa_cascadia_general | 0.6794 |
| real_afghanistan_20231015_query | 0.6802 |
| real_pakistan_general_early | 0.6805 |
| real_india_andaman_general_early2 | 0.6811 |
| real_panama_general_recent | 0.6815 |
| real_usa_puertorico_general_early | 0.6816 |
| real_centralasia_kyrgyzstan_tajikistan | 0.6817 |
| real_usa_newmadrid_general | 0.6821 |
| real_greenland_general_early2 | 0.6833 |
| real_ethiopia_general_early | 0.6837 |
| real_albania_durres_2019_recent | 0.6850 |
| real_indonesia_sumatra_general | 0.6851 |
| real_centralasia_kyrgyzstan_tajikistan_recent | 0.6861 |
| real_france_general | 0.6865 |
| real_turkmenistan_general_recent | 0.6875 |
| real_miyazaki_2024-2025 | 0.6879 |
| real_ecuador_general | 0.6883 |
| real_kazakhstan_general | 0.6883 |
| real_venezuela_general_early | 0.6888 |
| real_iran_ahar_varzaghan_2012 | 0.6892 |
| real_mexico_baja_general_early3 | 0.6920 |
| real_kazakhstan_general_early | 0.6924 |
| real_greece_2024_2025 | 0.6925 |
| real_china_yunnan_general_early2 | 0.6927 |
| real_china_sichuan_2008_recent | 0.6938 |
| real_anchorage_alaska_2018 | 0.6944 |
| real_usa_oklahoma_induced_general | 0.6944 |
| real_chile_maule_2010_recent | 0.6951 |
| real_yemen_general_recent | 0.6956 |
| real_events_atkinson | 0.6961 |
| real_fiji_general | 0.6971 |
| real_philippines_mindanao_general_early | 0.6976 |
| real_tanzania_rift_general | 0.6984 |
| real_iceland_general_early2 | 0.6984 |
| real_china_yunnan_general_early | 0.6994 |
| real_usa_hawaii_kilauea_2018_recent | 0.7024 |
| real_turkmenistan_general_early3 | 0.7029 |
| real_syria_general | 0.7042 |
| real_china_xinjiang_general_early2 | 0.7049 |
| real_uzbekistan_general | 0.7052 |
| real_australia_general_recent | 0.7057 |
| real_usa_utah_wasatch_general_recent | 0.7061 |
| real_turkmenistan_general | 0.7074 |
| real_mongolia_gobialtai_general | 0.7091 |
| real_usa_california_southnapa_2014_recent | 0.7093 |
| real_drc_rift_general | 0.7107 |
| real_guadeloupe_martinique_general_recent | 0.7129 |
| real_malawi_general | 0.7133 |
| real_china_xinjiang_general | 0.7134 |
| real_turkmenistan_general_early | 0.7138 |
| real_usa_cascadia_general_recent | 0.7139 |
| real_mexico_baja_general_recent | 0.7147 |
| real_usa_yellowstone_general_early | 0.7147 |
| real_pakistan_general | 0.7150 |
| real_honduras_general | 0.7150 |
| real_southafrica_general | 0.7157 |
| real_drc_rift_general_early | 0.7160 |
| real_papuanewguinea_general_recent | 0.7174 |
| real_turkey_van_2011_recent | 0.7189 |
| real_usa_puertorico_general_early2 | 0.7202 |
| real_ecuador_general_early | 0.7215 |
| real_china_tibet_plateau_general_early | 0.7216 |
| real_usa_yellowstone_general_recent | 0.7226 |
| real_russia_sakhalin_general_early | 0.7227 |
| real_portugal_azores_general_early | 0.7234 |
| real_greenland_general | 0.7242 |
| real_azerbaijan_general_recent | 0.7249 |
| real_turkmenistan_general_early2 | 0.7250 |
| real_china_gansu_general | 0.7267 |
| real_ethiopia_general | 0.7269 |
| real_yemen_general | 0.7273 |
| real_uzbekistan_general_early | 0.7291 |
| real_azerbaijan_general | 0.7292 |
| real_tanzania_rift_general_recent | 0.7293 |
| real_philippines_luzon_general_recent | 0.7303 |
| real_usa_yellowstone_general | 0.7322 |
| real_china_tibet_plateau_general_recent | 0.7325 |
| real_china_yunnan_general | 0.7342 |
| real_slovenia_general_early | 0.7362 |
| real_china_tibet_plateau_general_early2 | 0.7377 |
| real_marianaislands_general_recent | 0.7393 |
| real_uzbekistan_general_early2 | 0.7410 |
| real_russia_sakhalin_general | 0.7411 |
| real_japan_2023- | 0.7413 |
| real_kazakhstan_general_recent | 0.7427 |
| real_australia_general | 0.7433 |
| real_china_xinjiang_general_early | 0.7442 |
| real_china_xinjiang_general_recent | 0.7464 |
| real_ridgecrest_california_2019 | 0.7529 |
| real_mexico_baja_general | 0.7596 |
| real_haiti_20210814_query | 0.7602 |
| real_venezuela_general_recent | 0.7731 |
| real_usa_nevada_basinrange_general_recent | 0.7755 |
| real_china_yunnan_general_recent | 0.7764 |
| real_usa_utah_wasatch_general_early | 0.7812 |
| real_guadeloupe_martinique_general_early3 | 0.7964 |
| real_usgs_current | 0.8281 |
| real_nankai_historical | 0.8512 |
| real_russia_caucasus_general_early3 | 0.9139 |
| real_tibet_202501 | 0.9413 |
| real_canada_quebec_general_recent | 0.9449 |
| real_usa_newmadrid_general_early3 | 0.9451 |
| real_norway_general_early2 | 0.9493 |
| real_usa_california_southnapa_2014 | 0.9494 |
| real_northkorea_general | 0.9509 |
| real_norway_general | 0.9510 |
| real_china_shanxi_general_early2 | 0.9512 |
| real_usa_oklahoma_induced_general_early | 0.9516 |
| real_southafrica_general_early3 | 0.9564 |
| real_botswana_general_early3 | 0.9593 |
| real_china_hebei_general | 0.9694 |
| real_vietnam_general_early2 | 0.9700 |
| real_cuba_general_recent | 0.9704 |
| real_china_hebei_general_early | 0.9777 |
| real_romania_vrancea_general_recent | 0.9790 |
| real_iran_bam_2003 | 0.9835 |
| real_india_uttarakhand_general_early3 | 0.9879 |
| real_tohoku_202606 | 0.9879 |
| real_india_uttarakhand_general_recent | 0.9885 |
| real_russia_sakhalin_general_early3 | 0.9886 |
| real_peru_20250616 | 0.9897 |
| real_vietnam_general_early | 0.9904 |
| real_russia_caucasus_general_recent | 0.9919 |
| real_france_general_recent | 0.9921 |
| real_japan_20220317_query | 0.9923 |
| real_samoa_general_early | 0.9930 |
| real_taiwan_202501 | 0.9931 |
| real_yamanashi_202606 | 0.9935 |
| real_egypt_general_early2 | 0.9935 |
| real_bhutan_general_early | 0.9937 |
| real_kenya_general_early2 | 0.9940 |
| real_bangladesh_general_early3 | 0.9944 |
| real_china_shanxi_general_early | 0.9946 |
| real_nepal_sikkim_general_early | 0.9947 |
| real_mozambique_general_early2 | 0.9949 |
| real_nepal_sikkim_general_recent | 0.9953 |
| real_portugal_azores_general_early3 | 0.9956 |
| real_mozambique_general | 0.9956 |
| real_russia_baikal_general_early3 | 0.9957 |
| real_azerbaijan_general_early3 | 0.9960 |
| real_malawi_general_early | 0.9962 |
| real_china_gansu_general_early | 0.9964 |
| real_jordan_general_early2 | 0.9965 |
| real_russia_baikal_general_recent | 0.9967 |
| real_drc_rift_general_early3 | 0.9967 |
| real_cuba_general_early | 0.9968 |
| real_usa_puertorico_general_early3 | 0.9969 |
| real_mongolia_gobialtai_general_early | 0.9971 |
| real_israel_deadsea_general_early | 0.9971 |
| real_mongolia_gobialtai_general_early2 | 0.9973 |
| real_ishikawa_202411_query | 0.9973 |
| real_202506_turkey | 0.9973 |
| real_202505_tokyo | 0.9974 |
| real_japan_saitama_202407_202501 | 0.9975 |
| real_lebanon_general | 0.9976 |
| real_laos_general_early | 0.9977 |
| real_usa_utah_wasatch_general_early3 | 0.9977 |
| real_venezuela_202606 | 0.9978 |
| real_thailand_general_early | 0.9978 |

## known_bad T(D), sorted ascending (all 460)

| dataset_id | T(D) | hard_override_fired |
|---|---|---|
| corrupt_real_lebanon_general_inject_duplicates_high | 0.2083 | False |
| corrupt_real_2025_03_myanmar_timestamp_collision_high | 0.2534 | False |
| corrupt_real_jordan_general_timestamp_collision_high | 0.2559 | False |
| corrupt_real_japan_20220319_query_timestamp_collision_high | 0.2571 | False |
| fabricated_level2_9 | 0.2659 | False |
| fabricated_level1_23 | 0.2660 | False |
| fabricated_level2_20 | 0.2676 | False |
| fabricated_level1_22 | 0.2685 | False |
| corrupt_real_china_qinghai_yushu_2010_inject_duplicates_high | 0.2976 | False |
| fabricated_level1_14 | 0.3064 | False |
| fabricated_level1_2 | 0.3077 | False |
| fabricated_level2_18 | 0.3092 | False |
| fabricated_level3_11 | 0.3120 | False |
| fabricated_level3_13 | 0.3131 | False |
| fabricated_level3_22 | 0.3135 | False |
| fabricated_level3_2 | 0.3140 | False |
| fabricated_level2_10 | 0.3145 | False |
| fabricated_level2_1 | 0.3157 | False |
| fabricated_level2_6 | 0.3171 | False |
| fabricated_level2_5 | 0.3171 | False |
| fabricated_level2_11 | 0.3197 | False |
| fabricated_level2_29 | 0.3199 | False |
| fabricated_level3_24 | 0.3200 | False |
| fabricated_level3_14 | 0.3205 | False |
| fabricated_level3_9 | 0.3210 | False |
| fabricated_level2_24 | 0.3216 | False |
| fabricated_level3_27 | 0.3220 | False |
| fabricated_level3_5 | 0.3223 | False |
| fabricated_level3_26 | 0.3225 | False |
| fabricated_level3_20 | 0.3229 | False |
| fabricated_level2_30 | 0.3230 | False |
| fabricated_naive_2 | 0.3233 | False |
| fabricated_level3_18 | 0.3235 | False |
| fabricated_level3_4 | 0.3236 | False |
| fabricated_level2_13 | 0.3237 | False |
| fabricated_level2_15 | 0.3237 | False |
| fabricated_level1_28 | 0.3237 | False |
| fabricated_level1_16 | 0.3239 | False |
| fabricated_level1_5 | 0.3240 | False |
| fabricated_level1_20 | 0.3241 | False |
| fabricated_level2_4 | 0.3242 | False |
| fabricated_naive_1 | 0.3244 | False |
| fabricated_level1_27 | 0.3245 | False |
| fabricated_level1_13 | 0.3247 | False |
| fabricated_level2_22 | 0.3247 | False |
| fabricated_level1_15 | 0.3250 | False |
| fabricated_level3_23 | 0.3250 | False |
| fabricated_level2_8 | 0.3251 | False |
| fabricated_level1_10 | 0.3251 | False |
| fabricated_level2_14 | 0.3253 | False |
| fabricated_naive_3 | 0.3253 | False |
| fabricated_naive_8 | 0.3254 | False |
| fabricated_level1_25 | 0.3256 | False |
| fabricated_level3_10 | 0.3257 | False |
| fabricated_level1_24 | 0.3257 | False |
| fabricated_level1_21 | 0.3260 | False |
| fabricated_level1_12 | 0.3262 | False |
| fabricated_level1_6 | 0.3264 | False |
| fabricated_level1_9 | 0.3265 | False |
| fabricated_level3_7 | 0.3265 | False |
| fabricated_level1_8 | 0.3265 | False |
| fabricated_level2_12 | 0.3265 | False |
| fabricated_level3_15 | 0.3268 | False |
| fabricated_level2_16 | 0.3269 | False |
| fabricated_level1_7 | 0.3270 | False |
| fabricated_level3_30 | 0.3271 | False |
| fabricated_level1_19 | 0.3272 | False |
| fabricated_naive_6 | 0.3275 | False |
| fabricated_level1_11 | 0.3275 | False |
| fabricated_level1_18 | 0.3275 | False |
| fabricated_level3_25 | 0.3275 | False |
| fabricated_level3_29 | 0.3279 | False |
| fabricated_level1_26 | 0.3280 | False |
| fabricated_level1_1 | 0.3286 | False |
| fabricated_level1_3 | 0.3287 | False |
| fabricated_level1_30 | 0.3287 | False |
| fabricated_level3_19 | 0.3289 | False |
| fabricated_level2_3 | 0.3292 | False |
| fabricated_naive_7 | 0.3296 | False |
| fabricated_level1_17 | 0.3298 | False |
| fabricated_level2_17 | 0.3299 | False |
| fabricated_level3_1 | 0.3299 | False |
| fabricated_level2_27 | 0.3300 | False |
| fabricated_level2_19 | 0.3300 | False |
| fabricated_level3_28 | 0.3308 | False |
| fabricated_naive_5 | 0.3308 | False |
| fabricated_level2_7 | 0.3309 | False |
| fabricated_naive_4 | 0.3309 | False |
| fabricated_level2_25 | 0.3311 | False |
| fabricated_level1_29 | 0.3311 | False |
| fabricated_level3_17 | 0.3312 | False |
| fabricated_level3_3 | 0.3316 | False |
| fabricated_level1_4 | 0.3323 | False |
| fabricated_level3_12 | 0.3334 | False |
| fabricated_level3_16 | 0.3335 | False |
| fabricated_level2_23 | 0.3339 | False |
| fabricated_level3_21 | 0.3355 | False |
| fabricated_level2_26 | 0.3356 | False |
| fabricated_level3_6 | 0.3361 | False |
| fabricated_level2_21 | 0.3369 | False |
| fabricated_level2_2 | 0.3379 | False |
| fabricated_level2_28 | 0.3421 | False |
| corrupt_real_potvilla_2024012_inject_missingness_low | 0.3517 | False |
| corrupt_nz_inject_missingness_high | 0.3583 | False |
| fabricated_level3_8 | 0.3591 | False |
| fabricated_level4_1 | 0.3628 | False |
| corrupt_real_tibet_202501_magnitude_gr_violation_med | 0.3634 | False |
| corrupt_real_afghanistan_2025_09_01_depth_implausible_med | 0.3650 | True |
| corrupt_real_taiwan_20240403_query_depth_implausible_med | 0.3677 | True |
| corrupt_real_turkey_202504_magnitude_gr_violation_med | 0.3678 | False |
| fabricated_level7_9 | 0.3898 | False |
| fabricated_level7_8 | 0.3910 | False |
| corrupt_real_dominicanrepublic_general_inject_missingness_low | 0.3979 | False |
| corrupt_real_muisne_pedernales_ecuador_2016_timestamp_collision_high | 0.4025 | False |
| corrupt_chile_depth_implausible_high | 0.4089 | True |
| corrupt_chile_depth_implausible_low | 0.4089 | True |
| fabricated_level7_13 | 0.4142 | False |
| corrupt_nz_inject_missingness_med | 0.4148 | False |
| fabricated_level7_20 | 0.4177 | False |
| fabricated_level4_28 | 0.4182 | False |
| fabricated_level4_8 | 0.4210 | False |
| fabricated_level5_8 | 0.4226 | False |
| fabricated_level4_22 | 0.4241 | False |
| fabricated_level4_21 | 0.4242 | False |
| fabricated_level4_13 | 0.4256 | False |
| fabricated_sophisticated_3 | 0.4257 | False |
| corrupt_nz_inject_missingness_low | 0.4267 | False |
| fabricated_level4_19 | 0.4268 | False |
| fabricated_level4_16 | 0.4279 | False |
| fabricated_level4_25 | 0.4282 | False |
| fabricated_sophisticated_2 | 0.4283 | False |
| fabricated_level4_15 | 0.4295 | False |
| fabricated_level4_26 | 0.4296 | False |
| fabricated_level4_23 | 0.4298 | False |
| fabricated_level4_29 | 0.4303 | False |
| fabricated_level4_18 | 0.4308 | False |
| fabricated_level4_20 | 0.4318 | False |
| fabricated_level4_24 | 0.4321 | False |
| fabricated_level4_27 | 0.4323 | False |
| fabricated_sophisticated_7 | 0.4323 | False |
| fabricated_level4_30 | 0.4323 | False |
| fabricated_level4_17 | 0.4337 | False |
| fabricated_level4_12 | 0.4347 | False |
| corrupt_real_madagascar_general_depth_implausible_med | 0.4356 | True |
| fabricated_sophisticated_5 | 0.4381 | False |
| fabricated_level4_9 | 0.4385 | False |
| fabricated_level4_4 | 0.4396 | False |
| fabricated_level4_7 | 0.4396 | False |
| fabricated_level4_14 | 0.4403 | False |
| fabricated_level7_10 | 0.4414 | False |
| fabricated_sophisticated_4 | 0.4416 | False |
| fabricated_level4_6 | 0.4423 | False |
| fabricated_sophisticated_1 | 0.4427 | False |
| fabricated_level5_7 | 0.4428 | False |
| fabricated_level4_11 | 0.4432 | False |
| fabricated_level4_5 | 0.4435 | False |
| fabricated_level4_2 | 0.4436 | False |
| fabricated_level4_10 | 0.4451 | False |
| fabricated_sophisticated_9 | 0.4457 | False |
| fabricated_level4_3 | 0.4457 | False |
| fabricated_sophisticated_6 | 0.4478 | False |
| corrupt_real_china_gansu_general_timestamp_collision_high | 0.4504 | False |
| fabricated_level5_14 | 0.4559 | False |
| corrupt_real_peru_20250616_inject_duplicates_high | 0.4564 | False |
| fabricated_sophisticated_8 | 0.4620 | False |
| fabricated_level5_15 | 0.4628 | False |
| corrupt_real_tohoku_2005_2011_inject_duplicates_high | 0.4633 | False |
| fabricated_level7_12 | 0.4640 | False |
| corrupt_real_taiwan_20240423_query_timestamp_collision_high | 0.4661 | False |
| fabricated_level6_26 | 0.4662 | False |
| fabricated_level7_14 | 0.4666 | False |
| fabricated_level7_15 | 0.4671 | False |
| corrupt_real_all_month_coordinate_jitter_high | 0.4686 | False |
| fabricated_level5_4 | 0.4693 | False |
| fabricated_level7_23 | 0.4700 | False |
| fabricated_level7_7 | 0.4711 | False |
| fabricated_level5_11 | 0.4740 | False |
| fabricated_level7_26 | 0.4746 | False |
| fabricated_level5_17 | 0.4751 | False |
| fabricated_level7_11 | 0.4773 | False |
| fabricated_level7_21 | 0.4792 | False |
| fabricated_level5_20 | 0.4805 | False |
| fabricated_level7_24 | 0.4807 | False |
| fabricated_level5_12 | 0.4807 | False |
| fabricated_level5_28 | 0.4807 | False |
| corrupt_real_nicaragua_general_inject_missingness_low | 0.4809 | False |
| fabricated_level7_3 | 0.4810 | False |
| corrupt_real_iceland_general_inject_missingness_low | 0.4810 | False |
| fabricated_level7_29 | 0.4815 | False |
| fabricated_level7_1 | 0.4819 | False |
| fabricated_level7_17 | 0.4829 | False |
| fabricated_level7_30 | 0.4833 | False |
| fabricated_level7_2 | 0.4865 | False |
| fabricated_level7_18 | 0.4865 | False |
| fabricated_level6_12 | 0.4876 | False |
| fabricated_level7_22 | 0.4884 | False |
| fabricated_level7_4 | 0.4889 | False |
| corrupt_real_canada_britishcolumbia_general_timestamp_collision_high | 0.4890 | False |
| fabricated_level9_8 | 0.4900 | False |
| fabricated_level7_27 | 0.4910 | False |
| fabricated_level5_10 | 0.4916 | False |
| fabricated_level7_19 | 0.4917 | False |
| fabricated_level5_19 | 0.4925 | False |
| fabricated_level5_29 | 0.4930 | False |
| fabricated_level7_16 | 0.4931 | False |
| corrupt_real_ecuador_general_timestamp_collision_high | 0.4935 | False |
| corrupt_real_israel_deadsea_general_coordinate_jitter_low | 0.4937 | False |
| corrupt_real_202507_Kamchatka_inject_duplicates_high | 0.4944 | False |
| fabricated_level6_29 | 0.4961 | False |
| fabricated_level6_22 | 0.4978 | False |
| fabricated_level7_5 | 0.4979 | False |
| corrupt_real_indonesia_java_general_coordinate_jitter_low | 0.4981 | False |
| fabricated_level6_15 | 0.4982 | False |
| fabricated_level7_28 | 0.4983 | False |
| fabricated_level7_25 | 0.4987 | False |
| fabricated_level5_6 | 0.4987 | False |
| corrupt_real_guam_general_coordinate_jitter_low | 0.4990 | False |
| corrupt_real_chile_maule_2010_coordinate_jitter_low | 0.4990 | False |
| fabricated_level5_2 | 0.4997 | False |
| fabricated_level5_16 | 0.5043 | False |
| fabricated_level5_26 | 0.5051 | False |
| fabricated_level5_13 | 0.5054 | False |
| fabricated_level5_27 | 0.5058 | False |
| corrupt_real_chile_iquique_2014_inject_duplicates_high | 0.5064 | False |
| fabricated_level6_24 | 0.5067 | False |
| fabricated_level7_6 | 0.5068 | False |
| fabricated_level5_21 | 0.5071 | False |
| fabricated_level6_5 | 0.5079 | False |
| fabricated_level5_1 | 0.5083 | False |
| fabricated_level6_25 | 0.5090 | False |
| fabricated_level6_23 | 0.5109 | False |
| corrupt_real_bolivia_deep_general_timestamp_collision_high | 0.5126 | False |
| corrupt_real_romania_vrancea_general_coordinate_jitter_low | 0.5146 | False |
| fabricated_level5_5 | 0.5156 | False |
| corrupt_real_papuanewguinea_general_depth_implausible_med | 0.5166 | True |
| fabricated_level9_17 | 0.5173 | False |
| corrupt_real_earthquake1_inject_duplicates_med | 0.5174 | False |
| corrupt_real_mexico_oaxaca_general_inject_duplicates_high | 0.5185 | False |
| fabricated_level5_18 | 0.5187 | False |
| fabricated_level5_25 | 0.5195 | False |
| fabricated_level5_23 | 0.5196 | False |
| corrupt_real_tanzania_rift_general_coordinate_jitter_low | 0.5199 | False |
| fabricated_level5_24 | 0.5200 | False |
| fabricated_level6_6 | 0.5209 | False |
| corrupt_real_portugal_azores_general_timestamp_collision_high | 0.5219 | False |
| fabricated_level6_21 | 0.5225 | False |
| fabricated_level6_3 | 0.5227 | False |
| fabricated_level6_17 | 0.5231 | False |
| corrupt_real_turkey_izmit_1999_timestamp_collision_high | 0.5239 | False |
| fabricated_level6_7 | 0.5244 | False |
| corrupt_real_usgs_main_inject_duplicates_high | 0.5251 | False |
| fabricated_level5_30 | 0.5253 | False |
| fabricated_level9_29 | 0.5257 | False |
| fabricated_level6_20 | 0.5260 | False |
| fabricated_level5_9 | 0.5265 | False |
| corrupt_real_haiti_2010_inject_missingness_low | 0.5270 | False |
| corrupt_real_tokara_202506_coordinate_jitter_low | 0.5277 | False |
| fabricated_level6_11 | 0.5278 | False |
| fabricated_level6_27 | 0.5281 | False |
| corrupt_real_usa_hawaii_kilauea_2018_inject_missingness_low | 0.5284 | False |
| corrupt_real_trinidadtobago_general_timestamp_collision_high | 0.5290 | False |
| fabricated_level6_18 | 0.5294 | False |
| fabricated_level6_30 | 0.5303 | False |
| corrupt_real_ishikawa_202401_query_timestamp_collision_high | 0.5317 | False |
| fabricated_level5_22 | 0.5319 | False |
| fabricated_level8_22 | 0.5321 | False |
| corrupt_real_russia_caucasus_general_coordinate_jitter_low | 0.5327 | False |
| fabricated_level6_13 | 0.5340 | False |
| fabricated_level6_28 | 0.5362 | False |
| fabricated_level9_26 | 0.5377 | False |
| fabricated_level6_4 | 0.5382 | False |
| fabricated_level9_1 | 0.5410 | False |
| fabricated_level5_3 | 0.5429 | False |
| fabricated_level9_27 | 0.5430 | False |
| fabricated_level6_19 | 0.5443 | False |
| corrupt_real_morocco_20230908_query_timestamp_collision_high | 0.5449 | False |
| corrupt_real_bangladesh_general_inject_missingness_low | 0.5452 | False |
| fabricated_level6_1 | 0.5460 | False |
| corrupt_real_usgs_main_inject_duplicates_low | 0.5473 | False |
| corrupt_real_kenya_general_inject_duplicates_high | 0.5474 | False |
| fabricated_level9_3 | 0.5484 | False |
| corrupt_real_russia_kurilislands_general_inject_duplicates_high | 0.5492 | False |
| fabricated_level9_25 | 0.5499 | False |
| corrupt_real_algeria_boumerdes_2003_coordinate_jitter_low | 0.5510 | False |
| corrupt_real_china_taiwanstrait_general_coordinate_jitter_low | 0.5514 | False |
| corrupt_real_turkmenistan_general_timestamp_collision_high | 0.5515 | False |
| fabricated_level6_9 | 0.5515 | False |
| fabricated_level9_18 | 0.5519 | False |
| corrupt_real_afghanistan_20231015_query_inject_missingness_low | 0.5519 | False |
| fabricated_level6_16 | 0.5528 | False |
| corrupt_real_202604_tohoku_japan_coordinate_jitter_low | 0.5529 | False |
| fabricated_level6_2 | 0.5530 | False |
| fabricated_level6_14 | 0.5535 | False |
| corrupt_real_greece_2024_2025_timestamp_collision_med | 0.5550 | False |
| fabricated_level9_23 | 0.5557 | False |
| fabricated_level8_17 | 0.5568 | False |
| corrupt_real_vanuatu_general_coordinate_jitter_low | 0.5568 | False |
| corrupt_real_puertorico_2020_ponce_depth_implausible_med | 0.5571 | True |
| fabricated_level6_10 | 0.5580 | False |
| corrupt_real_panama_general_inject_duplicates_high | 0.5587 | False |
| corrupt_real_tonga_20210101_20220117_query_coordinate_jitter_med | 0.5590 | False |
| fabricated_level6_8 | 0.5593 | False |
| corrupt_real_colombia_andes_general_inject_duplicates_high | 0.5610 | False |
| corrupt_real_india_gujarat_bhuj_2001_magnitude_gr_violation_med | 0.5617 | False |
| corrupt_real_elsalvador_2001_coordinate_jitter_low | 0.5657 | False |
| fabricated_level9_10 | 0.5661 | False |
| fabricated_level9_21 | 0.5664 | False |
| fabricated_level9_9 | 0.5672 | False |
| corrupt_real_iceland_reykjanes_2021_coordinate_jitter_low | 0.5691 | False |
| corrupt_real_honduras_general_timestamp_collision_high | 0.5699 | False |
| corrupt_real_peru_arequipa_2001_magnitude_gr_violation_med | 0.5712 | False |
| fabricated_level9_24 | 0.5721 | False |
| corrupt_real_all_month_coordinate_jitter_low | 0.5726 | False |
| fabricated_level8_5 | 0.5729 | False |
| corrupt_real_gorkha_nepal_2015_magnitude_gr_violation_med | 0.5730 | False |
| fabricated_level9_2 | 0.5733 | False |
| fabricated_level9_15 | 0.5761 | False |
| fabricated_level9_4 | 0.5769 | False |
| fabricated_level9_7 | 0.5775 | False |
| corrupt_real_china_shanxi_general_inject_duplicates_high | 0.5785 | False |
| corrupt_real_usa_oklahoma_induced_general_timestamp_collision_high | 0.5788 | False |
| corrupt_real_australia_general_timestamp_collision_high | 0.5805 | False |
| corrupt_real_afghanistan_20231008_query_inject_duplicates_high | 0.5807 | False |
| fabricated_level9_5 | 0.5831 | False |
| fabricated_level9_6 | 0.5833 | False |
| fabricated_level9_16 | 0.5838 | False |
| corrupt_real_202606_philippines_magnitude_gr_violation_med | 0.5838 | False |
| corrupt_real_guatemala_general_inject_missingness_low | 0.5839 | False |
| fabricated_level9_14 | 0.5841 | False |
| fabricated_level9_30 | 0.5848 | False |
| fabricated_level8_26 | 0.5849 | False |
| fabricated_level9_13 | 0.5858 | False |
| corrupt_real_india_uttarakhand_general_depth_implausible_med | 0.5867 | True |
| corrupt_real_peru_pisco_2007_coordinate_jitter_low | 0.5870 | False |
| corrupt_real_events_atkinson_inject_missingness_med | 0.5885 | False |
| fabricated_level9_11 | 0.5885 | False |
| fabricated_level9_12 | 0.5888 | False |
| corrupt_real_amatrice_norcia_italy_2016_magnitude_gr_violation_med | 0.5897 | False |
| fabricated_level9_20 | 0.5908 | False |
| corrupt_real_iraq_halabja_2017_magnitude_gr_violation_med | 0.5914 | False |
| fabricated_level8_15 | 0.5922 | False |
| corrupt_real_tohoku_202512_depth_implausible_med | 0.5923 | True |
| corrupt_real_anchorage_alaska_2018_inject_duplicates_high | 0.5925 | False |
| corrupt_real_switzerland_general_depth_implausible_med | 0.5934 | True |
| corrupt_real_chiapas_mexico_2017_inject_duplicates_med | 0.5939 | False |
| corrupt_real_ishikawa_2024_query_magnitude_gr_violation_med | 0.5957 | False |
| corrupt_real_samoa_general_inject_duplicates_high | 0.5963 | False |
| corrupt_real_drc_rift_general_coordinate_jitter_low | 0.5978 | False |
| corrupt_real_japan-20190101_20211203_query_inject_duplicates_high | 0.5992 | False |
| corrupt_real_japan_20190101-20211009_query_inject_missingness_low | 0.6016 | False |
| fabricated_level9_22 | 0.6024 | False |
| fabricated_level9_28 | 0.6027 | False |
| corrupt_real_bulgaria_general_inject_duplicates_high | 0.6038 | False |
| fabricated_level8_1 | 0.6040 | False |
| fabricated_level8_18 | 0.6043 | False |
| corrupt_real_marianaislands_general_timestamp_collision_high | 0.6046 | False |
| corrupt_real_india_kashmir_2005_magnitude_gr_violation_med | 0.6048 | False |
| fabricated_level8_9 | 0.6048 | False |
| corrupt_real_india_assam_general_inject_duplicates_high | 0.6057 | False |
| corrupt_real_pakistan_balochistan_2013_inject_missingness_low | 0.6072 | False |
| corrupt_real_cuba_general_depth_implausible_med | 0.6088 | True |
| corrupt_real_newcaledonia_general_depth_implausible_med | 0.6092 | True |
| fabricated_level8_16 | 0.6099 | False |
| fabricated_level9_19 | 0.6108 | False |
| fabricated_level8_7 | 0.6128 | False |
| corrupt_real_china_sichuan_2008_coordinate_jitter_low | 0.6128 | False |
| corrupt_real_indonesia_sumatra_general_timestamp_collision_high | 0.6130 | False |
| fabricated_level8_4 | 0.6153 | False |
| fabricated_level8_2 | 0.6162 | False |
| fabricated_level8_3 | 0.6168 | False |
| fabricated_level8_6 | 0.6193 | False |
| fabricated_level8_14 | 0.6201 | False |
| corrupt_real_japan_2000_2023_query_magnitude_gr_violation_high | 0.6206 | False |
| corrupt_real_ethiopia_general_timestamp_collision_high | 0.6224 | False |
| corrupt_real_russia_baikal_general_inject_missingness_low | 0.6228 | False |
| corrupt_real_japan_2000_2023_query_magnitude_gr_violation_low | 0.6241 | False |
| corrupt_real_newzealand_kaikoura_2016_inject_missingness_low | 0.6249 | False |
| corrupt_real_turkey_van_2011_inject_missingness_low | 0.6255 | False |
| corrupt_real_germany_general_magnitude_gr_violation_med | 0.6255 | False |
| fabricated_level8_27 | 0.6259 | False |
| fabricated_level8_28 | 0.6263 | False |
| fabricated_level8_19 | 0.6271 | False |
| fabricated_level8_13 | 0.6274 | False |
| corrupt_real_taiwan_2024_query_depth_implausible_med | 0.6277 | True |
| corrupt_real_china_tibet_plateau_general_inject_missingness_low | 0.6283 | False |
| corrupt_real_albania_durres_2019_depth_implausible_med | 0.6284 | True |
| corrupt_real_202509_Kamchatka_inject_missingness_low | 0.6284 | False |
| corrupt_real_argentina_sanjuan_general_depth_implausible_med | 0.6286 | True |
| fabricated_level8_8 | 0.6288 | False |
| corrupt_real_kazakhstan_general_inject_missingness_low | 0.6295 | False |
| fabricated_level8_21 | 0.6313 | False |
| corrupt_real_usa_newmadrid_general_inject_duplicates_high | 0.6335 | False |
| corrupt_real_india_andaman_general_inject_missingness_low | 0.6345 | False |
| corrupt_real_indonesia_palu_2018_timestamp_collision_high | 0.6347 | False |
| corrupt_real_nepal_sikkim_general_depth_implausible_med | 0.6369 | True |
| corrupt_real_china_yunnan_general_coordinate_jitter_low | 0.6378 | False |
| corrupt_real_egypt_general_magnitude_gr_violation_med | 0.6395 | False |
| corrupt_real_kahramanmaras_turkey_2023_timestamp_collision_med | 0.6403 | False |
| corrupt_real_centralasia_kyrgyzstan_tajikistan_magnitude_gr_violation_med | 0.6409 | False |
| corrupt_real_france_general_coordinate_jitter_low | 0.6467 | False |
| fabricated_level8_23 | 0.6471 | False |
| fabricated_level8_11 | 0.6487 | False |
| corrupt_real_costarica_general_magnitude_gr_violation_med | 0.6490 | False |
| fabricated_level8_25 | 0.6501 | False |
| fabricated_level8_24 | 0.6526 | False |
| fabricated_level8_10 | 0.6530 | False |
| fabricated_level8_20 | 0.6535 | False |
| fabricated_level8_12 | 0.6549 | False |
| corrupt_real_venezuela_general_magnitude_gr_violation_med | 0.6570 | False |
| corrupt_real_morocco_alhoceima_2004_inject_missingness_low | 0.6573 | False |
| corrupt_real_solomonislands_general_coordinate_jitter_low | 0.6574 | False |
| corrupt_real_png_highlands_2018_coordinate_jitter_med | 0.6587 | False |
| corrupt_real_india_assam_general_early_inject_missingness_low | 0.6589 | False |
| corrupt_real_canada_quebec_general_magnitude_gr_violation_med | 0.6600 | False |
| corrupt_real_china_xinjiang_general_inject_duplicates_high | 0.6604 | False |
| fabricated_level8_29 | 0.6609 | False |
| corrupt_real_morocco_20230908_query_timestamp_collision_low | 0.6625 | False |
| fabricated_level8_30 | 0.6665 | False |
| corrupt_real_kermanshah_iran_2017_depth_implausible_med | 0.6672 | True |
| corrupt_real_greenland_general_inject_duplicates_high | 0.6735 | False |
| corrupt_real_haiti_20210814_query_magnitude_gr_violation_med | 0.6760 | False |
| corrupt_real_southafrica_general_magnitude_gr_violation_med | 0.6762 | False |
| corrupt_real_miyazaki_2024-2025_magnitude_gr_violation_med | 0.6781 | False |
| corrupt_real_usa_cascadia_general_depth_implausible_med | 0.6794 | True |
| corrupt_real_china_yunnan_general_early_magnitude_gr_violation_med | 0.6803 | False |
| corrupt_real_russia_sakhalin_general_inject_duplicates_high | 0.6819 | False |
| corrupt_real_china_xinjiang_general_early_inject_duplicates_high | 0.6890 | False |
| corrupt_real_iran_ahar_varzaghan_2012_depth_implausible_med | 0.6892 | True |
| corrupt_real_fiji_general_magnitude_gr_violation_med | 0.6908 | False |
| corrupt_real_202510_philippines_depth_implausible_med | 0.6924 | True |
| corrupt_real_uzbekistan_general_inject_missingness_low | 0.6997 | False |
| corrupt_real_mexico_baja_general_inject_missingness_low | 0.7064 | False |
| corrupt_real_tohoku_202511_inject_missingness_low | 0.7077 | False |
| corrupt_real_pakistan_general_depth_implausible_med | 0.7150 | True |
| corrupt_real_usa_puertorico_general_coordinate_jitter_low | 0.7189 | False |
| corrupt_real_malawi_general_magnitude_gr_violation_med | 0.7234 | False |
| corrupt_real_mongolia_gobialtai_general_depth_implausible_med | 0.7250 | True |
| corrupt_real_usgs_current_inject_duplicates_high | 0.7285 | False |
| corrupt_real_yemen_general_inject_missingness_low | 0.7286 | False |
| corrupt_real_usa_yellowstone_general_depth_implausible_med | 0.7322 | True |
| corrupt_real_syria_general_depth_implausible_med | 0.7359 | True |
| corrupt_real_azerbaijan_general_magnitude_gr_violation_med | 0.7688 | False |
| corrupt_real_ridgecrest_california_2019_coordinate_jitter_low | 0.7916 | False |
| corrupt_real_iran_bam_2003_inject_duplicates_high | 0.8755 | False |
| corrupt_real_tohoku_202606_timestamp_collision_high | 0.8967 | False |
| corrupt_real_croatia_petrinja_2020_timestamp_collision_high | 0.9136 | False |
| corrupt_real_colombia_armenia_1999_timestamp_collision_high | 0.9141 | False |
| corrupt_real_usa_california_southnapa_2014_depth_implausible_med | 0.9494 | True |
| corrupt_real_northkorea_general_magnitude_gr_violation_med | 0.9509 | False |
| corrupt_real_norway_general_magnitude_gr_violation_med | 0.9510 | False |
| corrupt_real_china_hebei_general_magnitude_gr_violation_med | 0.9694 | False |
| corrupt_real_ishikawa_202411_query_coordinate_jitter_low | 0.9890 | False |
| corrupt_real_taiwan_202501_coordinate_jitter_low | 0.9894 | False |
| corrupt_real_venezuela_202606_inject_missingness_low | 0.9920 | False |
| corrupt_real_japan_20220317_query_depth_implausible_med | 0.9923 | False |
| corrupt_real_yamanashi_202606_depth_implausible_med | 0.9935 | True |
| corrupt_real_japan_saitama_202407_202501_coordinate_jitter_low | 0.9953 | False |
| corrupt_real_mozambique_general_magnitude_gr_violation_med | 0.9956 | False |
| corrupt_real_202505_tokyo_coordinate_jitter_low | 0.9971 | False |
| corrupt_real_202506_turkey_magnitude_gr_violation_med | 0.9973 | False |
