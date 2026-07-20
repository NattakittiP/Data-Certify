# Group C3: A6 Three-State Semantics Validation Report

Input: `/sessions/charming-friendly-allen/mnt/DATA-CERTIFY/calibration/score_matrix_a6_multi.csv` (968 datasets)

Constants under test: `A6_CONTRADICTED_MIN_SOURCES=2`, `A6_CONTRADICTED_MIN_N_STRATUM=20`, `A6_CONTRADICTED_ALPHA=0.01`

## Q1: False-positive check

No known_good dataset reached 'Externally contradicted' -- safe.

## Q2: Security-property check (known_bad)

328/460 known_bad datasets had a contradicted-eligible stratum; 258 were confirmed and fire the hard-override.

## Q3: Threshold sensitivity

40 known_bad dataset(s) near the MIN_N_STRATUM cutoff; 2 near the ALPHA cutoff.


Full data: `/sessions/charming-friendly-allen/mnt/DATA-CERTIFY/calibration/group_c_reports/a6_three_state_report.json`
