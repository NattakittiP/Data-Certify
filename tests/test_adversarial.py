# -*- coding: utf-8 -*-
"""
tests/test_adversarial.py -- Adversarial fabrication tests.

Context: examples/example_custom_dataset.py's own "fabricated" demo catalog
(uniform magnitudes + uniform 2D coordinates) was a DELIBERATELY naive
fabrication -- it still landed in the same CONDITIONAL zone as the "clean"
catalog, because T(D) alone doesn't cleanly separate them (that example's
own printed note says so). This file goes one step further and asks: what
if the fabricator actually knows DATA-CERTIFY's formulas and specifically
engineers a catalog to defeat them (genuine-looking GR b-value, fault-like
clustered coordinates instead of uniform scatter, no exact-duplicate
timestamps, physically plausible depths)? Before this session's change
(wiring USGSComCatReference in as A6's default), NOTHING in this framework
could catch that -- A6 (the only check that verifies a dataset against the
outside world, rather than checking it for internal self-consistency) was
off by default. These tests demonstrate the gap explicitly (still present
at the library level, since DataCertifyAuditor's own default remains
NullExternalCatalog for test determinism -- see run_audit.py for the CLI
default that actually changed) AND confirm it closes once A6 is supplied,
AND document the one adversarial scenario that remains unsolved (a spoofed
external catalog) rather than overclaiming full coverage.

UPDATED (Group C3, 2026-07-12, A6 three-state semantics -- see
data_certify/_constants.py's A6_CONTRADICTED_* block): "closes once A6 is
supplied" now has a disclosed condition attached. A SINGLE reference
source's non-match is "Externally unverifiable", not "Externally
contradicted" -- it no longer fires the non-compensable hard-override on
its own (this is what fixes the real, previously-disclosed false-positive
risk of a single source's regional coverage gap, e.g. "nz" vs USGS ComCat
alone). The gamed-fabrication catalogs in this file are NOT falsely
ADMITted under single-source A6 (they still fall back to intrinsic-only
scoring and land in CONDITIONAL, not ADMIT, in the cases tested here), but
the STRONGER "automatic REJECT via Stage-1 veto" guarantee this file
originally set out to demonstrate now requires >=2 independently reachable
reference sources (`--reference-source multi`/`weighted-multi`). Both the
single-source (now CONDITIONAL, not hard-rejected) and multi-source (still
hard-rejected) outcomes are tested explicitly below.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.decision import CertifyDecision, DataCertifyAuditor
from data_certify.reference_data import (
    USGSComCatReference, EMSCReference, MultiSourceExternalCatalogReference,
)
from conftest import make_dataset
from test_reference_data import make_fake_urlopen, _iso_to_ms


def make_gamed_fabricated_catalog(n: int = 3000, seed: int = 123):
    """
    A catalog specifically engineered, WITH full knowledge of DATA-CERTIFY's
    own published formulas, to pass every intrinsic (A1-A5) and physical
    (P1-P3) check:
      - magnitudes: a genuine Gutenberg-Richter exponential distribution
        with b~1.0 (defeats A2's "score decays away from b_hat=1.0" check)
      - coordinates: clustered along fault-like line segments (the same
        construction used in test_scientific_validity.py's
        TestCorrelationDimension.test_clustered_pattern_scores_lower_than_uniform,
        Dc~1.3), not a uniform 2D scatter (defeats A4's Dc->2.0 tell)
      - depths: plausible shallow-crustal range, well inside the [-5, 750] km hard bound
        (defeats P1-P3's hard gates)
      - distinct, non-duplicate timestamps (defeats P7)
    It does NOT correspond to any real, independently corroborated seismic
    event -- by construction, since every field is synthetic. This is
    exactly the class of fabrication A6 exists to catch, and -- by
    design -- the only class every other check in this framework cannot.
    """
    rng = np.random.RandomState(seed)
    mc, b_value = 3.0, 1.0
    beta = b_value * np.log(10.0)
    magnitude = mc + rng.exponential(1.0 / beta, size=n)

    seg_id = rng.randint(0, 5, n)
    angles = seg_id * 0.7
    along = rng.uniform(0, 40, n)
    jitter = rng.normal(0, 1.0, n)
    latitude = -20.0 + along * np.cos(angles) + jitter * np.sin(angles)
    longitude = -70.0 + along * np.sin(angles) - jitter * np.cos(angles)

    depth_km = np.clip(rng.exponential(15.0, n), 1.0, 60.0)

    base_time = np.datetime64("2021-01-01T00:00:00", "ns")
    hour_offsets = rng.permutation(n)  # all distinct -> no exact-duplicate timestamps
    origin_time = (base_time + hour_offsets * np.timedelta64(1, "h")).astype("datetime64[ns]")

    return make_dataset(
        n=n, magnitude=magnitude, latitude=latitude, longitude=longitude,
        depth_km=depth_km, origin_time=origin_time,
    )


class TestAdversarialFabrication:
    def test_gamed_fabrication_evades_intrinsic_only_scoring(self):
        """
        BEFORE: demonstrates the actual gap this session's A6 change closes.
        With no external reference (the library-level default, preserved
        for test determinism -- see run_audit.py for the CLI's new live-API
        default), a catalog engineered to pass every intrinsic/physical
        check is NOT caught by the hard-override gate.
        """
        ds = make_gamed_fabricated_catalog()
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.hard_override.fired is False, (
            "a catalog engineered to pass every intrinsic/physical check should NOT "
            "be caught by the hard-override gate without an external corroboration "
            "source -- this is the exact residual gap A6 exists to close"
        )

    def test_gamed_fabrication_single_source_is_flagged_conditional_not_hard_rejected(self, monkeypatch):
        """
        UPDATED for Group C3 (2026-07-12, A6 three-state semantics): with a
        SINGLE reference source (USGSComCatReference), finding no matching
        real events is now "Externally unverifiable" (< A6_CONTRADICTED_
        MIN_SOURCES=2 independent sources), NOT "Externally contradicted" --
        it no longer fires the hard-override on its own (see
        data_certify/_constants.py's A6_CONTRADICTED_* block for why: a
        single source's non-match is exactly the same signal a genuine
        regional coverage gap produces, e.g. the disclosed real "nz" case).
        A6 becomes inapplicable for this catalog and the composite score
        falls back to intrinsic-only A1-A5 -- which still is NOT fooled
        into ADMIT here (T(D) lands well below theta_admit, CONDITIONAL),
        so the catalog is still flagged for scrutiny, just not by the
        stronger non-compensable Stage-1 veto. See
        test_gamed_fabrication_multi_source_is_hard_rejected below for how
        to restore the full hard-override guarantee against this class of
        attack (requires >=2 independent reference sources).
        """
        ds = make_gamed_fabricated_catalog()
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([]),  # no real corroborating events exist anywhere
        )
        auditor = DataCertifyAuditor(reference=USGSComCatReference())
        result = auditor.audit(ds)
        assert result.hard_override.fired is False
        assert result.axis_results["A"].sub_results["A6"].applicable is False
        assert result.trust_score is not None
        assert result.trust_score < 0.75, (
            "even without A6's hard-override, the gamed catalog must not score "
            "high enough to ADMIT under intrinsic-only fallback scoring"
        )
        assert result.decision != CertifyDecision.ADMIT

    def test_gamed_fabrication_multi_source_is_hard_rejected(self, monkeypatch):
        """
        The complementary case: configuring >=2 independent reference
        sources (USGS + EMSC) restores the full non-compensable
        hard-override guarantee against this exact attack, since neither
        source finds a matching event and the resulting all-non-match
        sub-stratum is large enough and confirmed via the Clopper-Pearson
        lower-tail test -- "Externally contradicted" fires. This is the
        disclosed, correct way to retain A6's strongest security property
        after Group C3 (single-source deployments trade it for fewer false
        positives against genuine regional-coverage-gap catalogs like "nz").
        """
        ds = make_gamed_fabricated_catalog()
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([]),  # no real corroborating events exist anywhere, in EITHER source
        )
        reference = MultiSourceExternalCatalogReference(
            [USGSComCatReference(), EMSCReference()], min_corroborating_sources=1,
        )
        auditor = DataCertifyAuditor(reference=reference)
        result = auditor.audit(ds)
        assert result.decision == CertifyDecision.REJECT
        assert result.hard_override.fired is True
        assert any("Externally contradicted" in r for r in result.hard_override.reasons)
        assert result.trust_score is None, "composite score must not be consulted once A6 fires"

    def test_genuine_catalog_with_real_corroboration_is_not_falsely_rejected(self, monkeypatch):
        """
        Sanity/false-positive check: a catalog that DOES have real external
        corroboration (simulated here by having the fake external catalog
        contain matching events) must NOT be hard-rejected by A6 just for
        having the same statistical profile as the gamed catalog above --
        confirms the fix targets the *lack of corroboration*, not the
        statistical shape.
        """
        ds = make_gamed_fabricated_catalog(n=200, seed=99)
        corroborating_events = [
            {
                "time_ms": int(ds.origin_time[i].astype("datetime64[ms]").astype(np.int64)),
                "lat": float(ds.latitude[i]) + 0.001,
                "lon": float(ds.longitude[i]) + 0.001,
                "mag": float(ds.magnitude[i]) + 0.01,
            }
            for i in range(ds.n)
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen(corroborating_events),
        )
        auditor = DataCertifyAuditor(reference=USGSComCatReference())
        result = auditor.audit(ds)
        assert result.hard_override.fired is False

    def test_disclosed_limitation_adversary_who_also_spoofs_external_catalog(self, monkeypatch):
        """
        Documents, rather than hides, a real residual limitation: if the
        external reference ITSELF is spoofed/compromised to return matching
        fake events, A6 cannot help -- this is a fundamentally different,
        much harder threat model (compromising or spoofing the external
        corroboration source, e.g. USGS ComCat, itself) than anything a
        dataset-side audit can address. Not a bug in this implementation;
        a boundary of what A6-style cross-validation can ever guarantee,
        stated explicitly per this project's honesty-first documentation
        culture rather than silently assumed away.
        """
        ds = make_gamed_fabricated_catalog(n=200, seed=7)
        spoofed_events = [
            {
                "time_ms": int(ds.origin_time[i].astype("datetime64[ms]").astype(np.int64)),
                "lat": float(ds.latitude[i]), "lon": float(ds.longitude[i]),
                "mag": float(ds.magnitude[i]),
            }
            for i in range(ds.n)
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen(spoofed_events),
        )
        auditor = DataCertifyAuditor(reference=USGSComCatReference())
        result = auditor.audit(ds)
        assert result.hard_override.fired is False, (
            "expected limitation: A6 cannot detect fabrication when the external "
            "reference itself is spoofed to corroborate it"
        )


class TestGraduatedFabricationLadder:
    """
    Held-out adversarial probe for calibration/corrupt.py's 10-level
    graduated fabrication ladder (fabricate_level1..fabricate_level10_
    adversarial). Levels 1-9 are deliberately calibrated-corpus material
    (see calibration/build_corpus.py's build_fabricated_datasets -- they
    DO feed into EWM/threshold calibration, same as fabricate_naive/
    fabricate_sophisticated always have). Level 10 specifically does NOT:
    per the explicit 2026-07-10 user decision to keep the most-realistic
    tier out of calibration (avoiding a circular "calibrate thresholds
    against the exact adversary being evaluated" trade-off), it is
    generated fresh here, in-memory, and only ever scored -- never written
    into datasets/ or corpus_manifest.csv. See
    calibration/build_adversarial_corpus.py for the standalone script that
    generates a held-out level-10 corpus to disk for manual inspection
    (also never fed into build_corpus.py's pipeline).
    """

    def test_level1_naive_is_readily_caught_by_intrinsic_checks(self):
        """Bookend sanity check: the 'obviously fake' floor of the ladder
        should score poorly on intrinsic checks alone (no A6 needed) --
        confirms the ladder's low end is genuinely easy, not accidentally
        already realistic."""
        from calibration import corrupt as _corrupt
        ds = _corrupt.fabricate_level1(500, np.random.RandomState(42), name="test_level1")
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.trust_score is not None
        assert result.trust_score < 0.75, (
            "level 1 (uniform magnitude + uniform scatter + uniform depth + "
            "evenly-spaced timestamps) should not come close to ADMIT without "
            "any external corroboration"
        )

    def test_level10_adversarial_evades_intrinsic_only_scoring(self):
        """Top of the ladder: by construction (fault-clustered coordinates,
        genuine GR b-value, Omori-like... note: level 10 reuses the L4/L5
        spatial/temporal construction plus every metadata/field realism
        property from levels 6-9), this should evade intrinsic-only
        scoring exactly like fabricate_sophisticated already does --
        confirming A6 external cross-validation remains the load-bearing
        defense against the hardest tier, not a redundant one."""
        from calibration import corrupt as _corrupt
        ds = _corrupt.fabricate_level10_adversarial(500, np.random.RandomState(42), name="test_level10")
        auditor = DataCertifyAuditor()
        result = auditor.audit(ds)
        assert result.hard_override.fired is False, (
            "level 10 is specifically engineered to defeat every intrinsic/physical "
            "check without external corroboration -- this is expected, not a bug, "
            "and is exactly why it is held out of calibration rather than folded in"
        )

    def test_level10_single_source_is_not_hard_rejected(self, monkeypatch):
        """
        UPDATED for Group C3 (2026-07-12): same reasoning as
        test_gamed_fabrication_single_source_is_flagged_conditional_not_hard_rejected
        -- a single reference source's non-match is "Externally
        unverifiable", not "Externally contradicted", so it no longer
        fires the hard-override on its own. See
        test_level10_multi_source_is_hard_rejected below for the
        >=2-source case that restores the full guarantee.
        """
        from calibration import corrupt as _corrupt
        ds = _corrupt.fabricate_level10_adversarial(300, np.random.RandomState(7), name="test_level10b")
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([]),
        )
        auditor = DataCertifyAuditor(reference=USGSComCatReference())
        result = auditor.audit(ds)
        assert result.hard_override.fired is False
        assert result.axis_results["A"].sub_results["A6"].applicable is False

    def test_level10_multi_source_is_hard_rejected(self, monkeypatch):
        """>=2 independent sources restores the full hard-override guarantee
        against level 10 too -- see test_gamed_fabrication_multi_source_is_hard_rejected
        for the identical reasoning.

        BUGFIX (verification pass, 2026-07-16): this fixture used to pass
        n=300 to fabricate_level10_adversarial(). Level 10's magnitude
        distribution is a genuine Gutenberg-Richter draw (mc=3.0, b=1.0,
        see calibration/corrupt.py's fabricate_graduated()), so only
        events >= the reference stratum's magnitude-of-completeness floor
        (mc_ref + mc_ref_se, empirically 4.5+0.3=4.8 here) are ever queried
        against the external sources at all -- and P(mag>=4.8) under this
        GR draw is only ~1.6%, so n=300 produced just 3 stratum-eligible
        records (confirmed empirically with this exact seed=7). That is
        far below A6_CONTRADICTED_MIN_N_STRATUM=20 (data_certify/_constants.py),
        so 'Externally contradicted' could never be statistically confirmed
        here regardless of how correct the underlying non-match signal was
        (all 3 records failed to match either source) -- this made the
        test fail (CONDITIONAL, not REJECT) even though the production
        code was behaving exactly as designed; the test's OWN fixture just
        didn't generate enough qualifying evidence. n=3000 empirically
        yields 45 stratum-eligible records with this seed, comfortably
        clearing MIN_N_STRATUM=20 with margin, matching how
        test_gamed_fabrication_multi_source_is_hard_rejected above already
        relies on make_gamed_fabricated_catalog()'s own default n being
        large enough for the same reason.
        """
        from calibration import corrupt as _corrupt
        ds = _corrupt.fabricate_level10_adversarial(3000, np.random.RandomState(7), name="test_level10c")
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([]),
        )
        reference = MultiSourceExternalCatalogReference(
            [USGSComCatReference(), EMSCReference()], min_corroborating_sources=1,
        )
        auditor = DataCertifyAuditor(reference=reference)
        result = auditor.audit(ds)
        assert result.decision == CertifyDecision.REJECT
        assert result.hard_override.fired is True
        assert any("Externally contradicted" in r for r in result.hard_override.reasons)
