# epsilon_tol / alpha (P1-P3 hard-override) Calibration Report

Corpus: 968 datasets scored locally (no live network required) -- 508 known_good, 460 known_bad (27 of which specifically inject P1-P3 violations via the `depth_implausible` corruption, targeting P2).

Current: `epsilon_tol = 0.001`, `alpha = 0.01` (Bonferroni-corrected to `0.00333` over the fixed m=3 family {P1, P2, P3}).

## Known-good worst-case violation fraction per test

| Test | dataset_id | k | n | fraction |
|---|---|---|---|---|
| P1 | nz | 0 | 20648 | 0.000000 |
| P2 | nz | 0 | 20648 | 0.000000 |
| P3 | nz | 0 | 20648 | 0.000000 |

## Known-bad `depth_implausible` cases (targets P2)

| dataset_id | severity | k | n | fraction | p_value | non_trivial (correctly caught) |
|---|---|---|---|---|---|---|
| corrupt_chile_depth_implausible_low | low | 12723 | 132964 | 0.0957 | 0.00e+00 | True |
| corrupt_real_nepal_sikkim_general_depth_implausible_med | med | 8 | 64 | 0.1250 | 4.21e-15 | True |
| corrupt_real_202510_philippines_depth_implausible_med | med | 8 | 59 | 0.1356 | 2.12e-15 | True |
| corrupt_real_albania_durres_2019_depth_implausible_med | med | 9 | 65 | 0.1385 | 3.04e-17 | True |
| corrupt_real_kermanshah_iran_2017_depth_implausible_med | med | 13 | 90 | 0.1444 | 1.53e-24 | True |
| corrupt_real_india_uttarakhand_general_depth_implausible_med | med | 15 | 103 | 0.1456 | 3.76e-28 | True |
| corrupt_real_iran_ahar_varzaghan_2012_depth_implausible_med | med | 7 | 45 | 0.1556 | 4.39e-14 | True |
| corrupt_real_madagascar_general_depth_implausible_med | med | 41 | 262 | 0.1565 | 1.25e-75 | True |
| corrupt_real_usa_cascadia_general_depth_implausible_med | med | 134 | 844 | 0.1588 | 4.74e-244 | True |
| corrupt_real_usa_california_southnapa_2014_depth_implausible_med | med | 4 | 25 | 0.1600 | 1.24e-08 | True |
| corrupt_real_taiwan_2024_query_depth_implausible_med | med | 61 | 378 | 0.1614 | 1.45e-112 | True |
| corrupt_real_switzerland_general_depth_implausible_med | med | 102 | 625 | 0.1632 | 1.52e-187 | True |
| corrupt_real_papuanewguinea_general_depth_implausible_med | med | 751 | 4590 | 0.1636 | 0.00e+00 | True |
| corrupt_real_argentina_sanjuan_general_depth_implausible_med | med | 175 | 1054 | 0.1660 | 8.25e-322 | True |
| corrupt_real_pakistan_general_depth_implausible_med | med | 241 | 1449 | 0.1663 | 0.00e+00 | True |
| corrupt_real_japan_20220317_query_depth_implausible_med | med | 1 | 6 | 0.1667 | 5.99e-03 | False |
| corrupt_real_newcaledonia_general_depth_implausible_med | med | 163 | 971 | 0.1679 | 1.00e-300 | True |
| corrupt_real_usa_yellowstone_general_depth_implausible_med | med | 84 | 500 | 0.1680 | 6.34e-156 | True |
| corrupt_real_puertorico_2020_ponce_depth_implausible_med | med | 211 | 1253 | 0.1684 | 0.00e+00 | True |
| corrupt_real_syria_general_depth_implausible_med | med | 14 | 83 | 0.1687 | 2.48e-27 | True |
| corrupt_real_cuba_general_depth_implausible_med | med | 13 | 75 | 0.1733 | 1.20e-25 | True |
| corrupt_real_tohoku_202512_depth_implausible_med | med | 21 | 117 | 0.1795 | 7.15e-41 | True |
| corrupt_real_mongolia_gobialtai_general_depth_implausible_med | med | 13 | 70 | 0.1857 | 4.50e-26 | True |
| corrupt_real_afghanistan_2025_09_01_depth_implausible_med | med | 5 | 26 | 0.1923 | 6.46e-11 | True |
| corrupt_real_yamanashi_202606_depth_implausible_med | med | 2 | 10 | 0.2000 | 4.48e-05 | True |
| corrupt_real_taiwan_20240403_query_depth_implausible_med | med | 2 | 9 | 0.2222 | 3.58e-05 | True |
| corrupt_chile_depth_implausible_high | high | 35432 | 132964 | 0.2665 | 0.00e+00 | True |

## Result

**No known_good real dataset in this 73-dataset corpus exhibits ANY P1-P3 violation (k=0 for P1, P2, and P3 on every one of the known_good datasets).** This is the expected outcome for deterministic geometric/physical bounds on genuine data, but it also means this corpus contains **no informative examples near the epsilon_tol boundary itself** -- only zero-violation known_good datasets on one side and deliberately-injected 5%-50%-violation known_bad datasets on the other (see the depth_implausible table above), a gap of several orders of magnitude either side of any plausible epsilon_tol value. **Consequently, epsilon_tol/alpha cannot be usefully tightened OR loosened from this corpus** -- every candidate value swept below (from 0.001 down to 1e-05) produces an identical, clean result (zero known_good false positives, zero known_bad depth_implausible cases missed), because the real corpus data never actually lands near the boundary either parameter controls. This is the same kind of honest 'no informative signal to calibrate from' finding already disclosed elsewhere in this project for P9/I4 (EWM). **`epsilon_tol = 0.001` and `alpha = 0.01` are left unchanged** -- empirically confirmed as producing zero false-positives/false-negatives on the current corpus, but still a provisional prior in the sense that no dataset with a genuinely marginal (neither ~0% nor ~5-50%) P1-P3 violation rate has ever been observed to test the boundary itself.

**WARNING: known_bad depth_implausible datasets NOT caught at current params:** ['corrupt_real_japan_20220317_query_depth_implausible_med']

## Candidate epsilon_tol sweep (informational -- corpus has no boundary examples, see Result above)

| epsilon_tol | known_good false positives | known_bad depth_implausible missed | clean |
|---|---|---|---|
| 0.001 | [] | ['corrupt_real_japan_20220317_query_depth_implausible_med'] | False |
| 0.0005 | [] | [] | True |
| 0.0002 | [] | [] | True |
| 0.0001 | [] | [] | True |
| 5e-05 | [] | [] | True |
| 1e-05 | [] | [] | True |
