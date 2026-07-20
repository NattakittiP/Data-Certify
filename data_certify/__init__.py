# -*- coding: utf-8 -*-
"""
DATA-CERTIFY: A Dataset Trustworthiness Audit Framework for Disaster
Seismic Data.

A computer-implemented pre-ingestion admissibility audit for disaster
seismic/earthquake catalogs -- it certifies whether the DATASET ITSELF is
trustworthy enough to enter any downstream disaster-response ML pipeline,
independent of and upstream from any downstream model-selection audit
that pipeline might also employ.

Four-axis scoring framework:
    A(D)  Authenticity                      (A1-A6)
    P(D)  Physical & Logical Plausibility   (P1-P9, P1-P3 are hard gates)
    C(D)  Completeness & Coverage            (C1-C4)
    I(D)  Instrumentation & Pipeline Integrity (I1-I5)

Composite trust score and three-way decision:
    T(D) = w_A.A(D) + w_P.P(D) + w_C.C(D) + w_I.I(D)
    ADMIT / CONDITIONAL / REJECT, with a non-compensable hard-override veto
    gate (P1-P3 non-trivial-fraction; A6 confirmed-fabrication floor) that
    sits OUTSIDE the weighted sum -- fabrication cannot be diluted by
    completeness.

Reference Implementation -- theoretical-framework companion code
Author: Nattakitti Piyavechvirat

Every formula, weight, and threshold here is derived, cited, and (where
applicable) explicitly disclosed as a provisional prior tied to the
internal calibration corpus used to derive it -- see `_constants.py` for
the canonical values and inline citations.
"""

from .decision import CertifyDecision, CertifyResult, DataCertifyAuditor, UncertaintyResult
from .hard_override import HardOverrideResult, check_hard_override
from .results import AxisResult, SubTestResult
from .schema import CertifyDataset, load_dataset_csv, save_dataset_csv
from .reference_data import (
    BundledSampleFaultDatabase,
    EMSCReference,
    ExternalCatalogReference,
    FaultDatabaseReference,
    GEMActiveFaultsDatabase,
    ISCReference,
    LocalCSVCatalogReference,
    MultiSourceExternalCatalogReference,
    NullExternalCatalog,
    NullFaultDatabase,
    USGSComCatReference,
    WeightedMultiSourceExternalCatalogReference,
    default_gem_geojson_path,
)
from .axis_authenticity import score_authenticity
from .axis_completeness import score_completeness
from .axis_instrumentation import score_instrumentation
from .axis_plausibility import score_plausibility

from ._constants import (
    ALPHA, ALPHA_CORRECTED, AXIS_WEIGHTS, EPSILON_TOL,
    THETA_ADMIT, THETA_AUTH, THETA_REJECT,
    WITHIN_A, WITHIN_C, WITHIN_I, WITHIN_P,
)

__version__ = "0.1.1"
__all__ = [
    # Core protocol
    "DataCertifyAuditor",
    "CertifyResult",
    "CertifyDecision",
    "UncertaintyResult",
    # Hard override (Stage 1)
    "check_hard_override",
    "HardOverrideResult",
    # Axis scoring (Stage 2 inputs)
    "score_authenticity",
    "score_plausibility",
    "score_completeness",
    "score_instrumentation",
    "AxisResult",
    "SubTestResult",
    # Data
    "CertifyDataset",
    "load_dataset_csv",
    "save_dataset_csv",
    # Pluggable references
    "ExternalCatalogReference",
    "NullExternalCatalog",
    "LocalCSVCatalogReference",
    "USGSComCatReference",
    "EMSCReference",
    "ISCReference",
    "MultiSourceExternalCatalogReference",
    "WeightedMultiSourceExternalCatalogReference",
    "FaultDatabaseReference",
    "NullFaultDatabase",
    "BundledSampleFaultDatabase",
    "GEMActiveFaultsDatabase",
    "default_gem_geojson_path",
    # Canonical constants
    "AXIS_WEIGHTS", "WITHIN_A", "WITHIN_P", "WITHIN_C", "WITHIN_I",
    "THETA_ADMIT", "THETA_REJECT", "THETA_AUTH",
    "EPSILON_TOL", "ALPHA", "ALPHA_CORRECTED",
]
