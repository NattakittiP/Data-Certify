# theta_auth Calibration Report

Input: `calibration/score_matrix_a6.csv` (89 total datasets, 83 A6-feasible / 6 excluded as not-applicable).

Current `THETA_AUTH` (provisional prior): **0.5**

## known_good matched_fraction (ascending -- worst case first)

| dataset_id | matched_fraction | n_stratum |
|---|---|---|
| nz | 0.3913 | 184 |
| chile | 0.7652 | 5456 |
| real_events_atkinson | 0.8688 | 343 |
| real_potvilla_2024012 | 0.9167 | 12 |
| real_japan_20220319_query | 0.9167 | 12 |
| real_taiwan_20240423_query | 0.9647 | 85 |
| real_202507_Kamchatka | 0.9716 | 141 |
| real_usgs_main | 0.9743 | 2729 |
| real_202606_philippines | 0.9756 | 41 |
| real_202509_Kamchatka | 0.9971 | 1036 |
| real_earthquake1 | 0.9973 | 23232 |
| real_japan-20190101_20211203_query | 0.9979 | 937 |
| real_tonga_20210101_20220117_query | 0.9988 | 1662 |
| real_afghanistan_20231015_query | 1.0000 | 70 |
| real_afghanistan_2025_09_01 | 1.0000 | 10 |
| real_all_month | 1.0000 | 358 |
| real_ishikawa_2024_query | 1.0000 | 46 |
| real_ishikawa_202401_query | 1.0000 | 50 |
| real_haiti_20210814_query | 1.0000 | 7 |
| real_greece_2024_2025 | 1.0000 | 64 |
| real_japan_saitama_202407_202501 | 1.0000 | 3 |
| real_miyazaki_2024-2025 | 1.0000 | 15 |
| real_japan_2000_2023_query | 1.0000 | 11132 |
| real_japan_20190101-20211009_query | 1.0000 | 655 |
| real_peru_20250616 | 1.0000 | 7 |
| real_morocco_20230908_query | 1.0000 | 273 |
| real_taiwan_20240403_query | 1.0000 | 8 |
| real_taiwan_2024_query | 1.0000 | 130 |
| real_afghanistan_20231008_query | 1.0000 | 56 |
| real_202510_philippines | 1.0000 | 34 |
| real_2025_03_myanmar | 1.0000 | 17 |
| real_202604_tohoku_japan | 1.0000 | 9 |
| real_tohoku_202511 | 1.0000 | 49 |
| real_tohoku_2005_2011 | 1.0000 | 2293 |
| real_tibet_202501 | 1.0000 | 6 |
| real_taiwan_202501 | 1.0000 | 10 |
| real_tokara_202506 | 1.0000 | 46 |
| real_usgs_current | 1.0000 | 8 |
| real_tohoku_202606 | 1.0000 | 9 |
| real_tohoku_202512 | 1.0000 | 49 |
| real_yamanashi_202606 | 1.0000 | 3 |
| real_venezuela_202606 | 1.0000 | 2 |
| real_ishikawa_202401 | 1.0000 | 30 |
| real_japan_2023_2024 | 1.0000 | 476 |
| real_amatrice_norcia_italy_2016 | 1.0000 | 15 |
| real_anchorage_alaska_2018 | 1.0000 | 16 |
| real_chiapas_mexico_2017 | 1.0000 | 113 |
| real_gorkha_nepal_2015 | 1.0000 | 66 |
| real_haiti_2010 | 1.0000 | 22 |
| real_indonesia_palu_2018 | 1.0000 | 69 |
| real_kahramanmaras_turkey_2023 | 1.0000 | 119 |
| real_kermanshah_iran_2017 | 1.0000 | 26 |
| real_muisne_pedernales_ecuador_2016 | 1.0000 | 34 |
| real_png_highlands_2018 | 1.0000 | 108 |
| real_ridgecrest_california_2019 | 1.0000 | 35 |

## known_bad matched_fraction (descending -- best case first)

| dataset_id | matched_fraction | n_stratum |
|---|---|---|
| corrupt_real_chiapas_mexico_2017_inject_duplicates_med | 1.0000 | 160 |
| corrupt_real_taiwan_2024_query_depth_implausible_med | 1.0000 | 130 |
| corrupt_real_earthquake1_inject_duplicates_med | 0.9972 | 32989 |
| corrupt_real_usgs_main_inject_duplicates_high | 0.9752 | 4441 |
| corrupt_real_usgs_main_inject_duplicates_low | 0.9751 | 3456 |
| corrupt_real_morocco_20230908_query_timestamp_collision_low | 0.6777 | 273 |
| corrupt_real_japan_2000_2023_query_magnitude_gr_violation_low | 0.6266 | 11132 |
| corrupt_real_all_month_coordinate_jitter_low | 0.6061 | 358 |
| corrupt_real_kahramanmaras_turkey_2023_timestamp_collision_med | 0.5798 | 119 |
| corrupt_real_greece_2024_2025_timestamp_collision_med | 0.5469 | 64 |
| corrupt_real_tonga_20210101_20220117_query_coordinate_jitter_med | 0.3905 | 1662 |
| corrupt_real_png_highlands_2018_coordinate_jitter_med | 0.3519 | 108 |
| corrupt_real_morocco_20230908_query_timestamp_collision_high | 0.3260 | 273 |
| corrupt_real_events_atkinson_inject_missingness_med | 0.3041 | 194 |
| corrupt_real_japan_2000_2023_query_magnitude_gr_violation_high | 0.2824 | 11132 |
| corrupt_real_gorkha_nepal_2015_magnitude_gr_violation_med | 0.2303 | 152 |
| corrupt_nz_inject_missingness_low | 0.1286 | 140 |
| corrupt_nz_inject_missingness_med | 0.1284 | 109 |
| corrupt_real_all_month_coordinate_jitter_high | 0.1173 | 358 |
| corrupt_real_haiti_20210814_query_magnitude_gr_violation_med | 0.0455 | 66 |
| corrupt_nz_inject_missingness_high | 0.0339 | 59 |
| corrupt_chile_depth_implausible_low | 0.0000 | 4226 |
| corrupt_chile_depth_implausible_high | 0.0000 | 4226 |
| fabricated_naive_1 | 0.0000 | 894 |
| fabricated_sophisticated_3 | 0.0000 | 42 |
| fabricated_sophisticated_2 | 0.0000 | 85 |
| fabricated_sophisticated_1 | 0.0000 | 33 |
| fabricated_naive_2 | 0.0000 | 417 |

## Result

**OVERLAP FOUND -- no single threshold cleanly separates known_good from known_bad.** The known_bad dataset `corrupt_real_chiapas_mexico_2017_inject_duplicates_med` scores 1.0000, which is >= the known_good dataset `nz`'s 0.3913. `THETA_AUTH` is **NOT** recommended to change automatically here -- any value that admits `nz` would also admit `corrupt_real_chiapas_mexico_2017_inject_duplicates_med`, and any value that rejects `corrupt_real_chiapas_mexico_2017_inject_duplicates_med` would also wrongly hard-reject `nz`. This needs a human decision: either investigate `nz` further for a real, undiscovered data bug (the same way chile's three stacked bugs were found), or accept this as a genuine, disclosed limitation of a single-external-reference A6 check and leave `nz` to be manually reviewed via the CONDITIONAL/disclosed-caveat path rather than fully automated ADMIT.

Confusion at CURRENT theta_auth (0.5):
```
{
  "theta_auth": 0.5,
  "n_known_good_evaluated": 55,
  "n_known_bad_evaluated": 28,
  "good_wrongly_hard_rejected": 1,
  "bad_correctly_hard_rejected": 18,
  "bad_missed_by_a6_alone": 10
}
```
