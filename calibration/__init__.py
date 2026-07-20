# -*- coding: utf-8 -*-
"""
calibration/ -- Tooling for building the >=50-dataset real+synthetic
calibration corpus used to derive Entropy Weight Method (EWM) weights
and to empirically calibrate theta_admit/theta_reject/theta_auth, per
Docs/02_Calibration_and_Validation/DATA-CERTIFY_Criteria_and_Weights_Master_Reference.md Sections 4-5.

This package is separate from the numpy-only `data_certify` core and
from `prepare_dataset.py`'s single-file CLI: it is a one-time (re-run
whenever the corpus or corruption logic changes) research/calibration
toolchain, not part of the audited production pipeline.
"""
