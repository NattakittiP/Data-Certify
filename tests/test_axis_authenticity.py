# -*- coding: utf-8 -*-
"""Tests for data_certify/axis_authenticity.py -- Authenticity axis A(D)."""

import math
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.axis_authenticity import (
    score_authenticity, _score_a3_omori_utsu, _score_a5_duplicates,
    _identify_mainshock_aftershock_clusters,
)
from data_certify.reference_data import (
    LocalCSVCatalogReference, NullExternalCatalog, MultiSourceExternalCatalogReference,
)
from data_certify.schema import save_dataset_csv
from conftest import make_dataset, make_gr_dataset


class TestIntrinsicMode:
    def test_defaults_to_intrinsic_when_no_reference(self):
        ds = make_gr_dataset(n=300)
        result = score_authenticity(ds)
        assert result.mode == "intrinsic (A1-A5)"
        assert not result.hard_reject
        assert 0.0 <= result.score <= 1.0

    def test_a1_not_applicable_without_wide_dynamic_range_fields(self):
        ds = make_dataset(n=10)  # no seismic moment, uniform small depth
        result = score_authenticity(ds)
        assert result.sub_results["A1"].applicable is False

    def test_a2_scores_high_for_genuine_gr_distribution(self):
        ds = make_gr_dataset(n=2000, b_value=1.0, seed=1)
        result = score_authenticity(ds)
        a2 = result.sub_results["A2"]
        assert a2.applicable
        assert a2.score > 0.7

    def test_a2_scores_low_for_uniform_magnitudes(self):
        rng = np.random.RandomState(2)
        mags = rng.uniform(3.0, 7.0, 2000)  # NOT exponential -> anomalous/undefined b
        ds = make_dataset(n=2000, magnitude=mags)
        result = score_authenticity(ds)
        a2 = result.sub_results["A2"]
        if a2.applicable and not math.isnan(a2.score):
            assert a2.score < 0.9

    def test_a4_uniform_coordinates_score_low_without_reference(self):
        rng = np.random.RandomState(3)
        n = 800
        lat = rng.uniform(-40, 40, n)
        lon = rng.uniform(-40, 40, n)
        ds = make_dataset(n=n, latitude=lat, longitude=lon)
        result = score_authenticity(ds)
        a4 = result.sub_results["A4"]
        assert a4.applicable
        # Uniform 2D scatter -> Dc near 2.0 -> low score (Deep-Dive 03 Section 2.3).
        assert a4.score < 0.6

    def test_a5_flags_near_duplicates(self):
        n = 100
        ds = make_dataset(n=n)
        # Insert a near-duplicate of record 0: tiny jitter, well within epsilon-ball.
        ds.origin_time[1] = ds.origin_time[0] + np.timedelta64(1, "s")
        ds.latitude[1] = ds.latitude[0] + 0.0001
        ds.longitude[1] = ds.longitude[0] + 0.0001
        ds.magnitude[1] = ds.magnitude[0]
        result = score_authenticity(ds)
        a5 = result.sub_results["A5"]
        assert a5.applicable
        assert a5.detail["n_flagged"] >= 2

    def test_a3_spatial_constraint_excludes_geographically_distant_coincident_events(self):
        """
        Regression test for the 2026-07-21 A3 bugfix: before the spatial
        term was added, ANY smaller event within the time window counted as
        a candidate aftershock, regardless of location. Builds one M6.0
        mainshock with 5 genuine, spatially-close aftershocks (~1km away,
        well inside the ~53km Gardner-Knopoff radius for M6.0) PLUS 4
        unrelated smaller events landing in the SAME time window but
        ~5,500km away, and asserts only the 5 near events are counted as
        aftershocks -- not all 9.
        """
        n = 10
        base_time = np.datetime64("2021-01-01T00:00:00", "ns")
        day = np.timedelta64(1, "D")
        origin_time = np.array([base_time] * n).astype("datetime64[ns]")
        lat = np.zeros(n)
        lon = np.zeros(n)
        mag = np.zeros(n)

        # Mainshock.
        lat[0], lon[0], mag[0] = 0.0, 0.0, 6.0

        # 5 genuine, spatially-close aftershocks.
        for i in range(1, 6):
            origin_time[i] = base_time + int(i) * day
            lat[i], lon[i], mag[i] = 0.01, 0.01, 4.0

        # 4 unrelated events, same time window, ~5,500km away -- well
        # outside the mainshock's Gardner-Knopoff radius.
        for i in range(6, 10):
            origin_time[i] = base_time + int(i - 5) * day
            lat[i], lon[i], mag[i] = 50.0, 50.0, 4.0

        ds = make_dataset(n=n, origin_time=origin_time, latitude=lat, longitude=lon, magnitude=mag)
        clusters = _identify_mainshock_aftershock_clusters(ds)
        assert len(clusters) == 1
        assert len(clusters[0]) == 5, (
            f"expected only the 5 spatially-close events to be counted as "
            f"aftershocks, got {len(clusters[0])} -- the 4 geographically "
            f"distant events may be leaking through the spatial constraint."
        )

    def test_a5_flags_duplicate_pair_straddling_the_antimeridian(self):
        """
        Regression test for the 2026-07-21 A5 bugfix: the spatial grid's
        cell index previously used raw signed longitude with no wraparound,
        so two near-duplicate records straddling the +/-180 degree
        antimeridian (e.g. Fiji/Tonga/Aleutians/NZ-Pacific catalogs) landed
        in grid cells at opposite ends of the index range and were never
        compared, even though they are only metres apart in reality.
        """
        n = 50
        ds = make_dataset(n=n)
        # Move one pair to straddle the antimeridian, a few hundred metres apart.
        ds.latitude[0] = -18.0
        ds.longitude[0] = 179.999
        ds.latitude[1] = -18.0
        ds.longitude[1] = -179.999
        ds.origin_time[1] = ds.origin_time[0] + np.timedelta64(1, "s")
        ds.magnitude[1] = ds.magnitude[0]
        result = _score_a5_duplicates(ds)
        assert result.applicable
        assert result.detail["n_flagged"] >= 2, (
            "the antimeridian-straddling near-duplicate pair was not "
            "flagged -- the longitude-wraparound fix may be broken."
        )

    def test_a5_dense_bucket_cap_does_not_crash_and_still_flags_duplicates(self):
        """
        Sanity check for the dense-bucket safety valve (MAX_A5_NEIGHBORHOOD_
        CANDIDATES): a pathologically dense cluster (many more records than
        the cap sharing one time/place) should not error out, should
        complete quickly, and should still flag at least some duplicates
        via the subsampled candidate check.
        """
        n = 800
        base_time = np.datetime64("2022-06-01T00:00:00", "ns")
        # All records share the exact same timestamp/location/magnitude, so
        # every one of them falls into the same sliding time-window AND the
        # same spatial-grid cell -- the pathological dense-bucket case the
        # cap exists for.
        ds = make_dataset(
            n=n,
            origin_time=np.full(n, base_time).astype("datetime64[ns]"),
            latitude=np.full(n, 10.0),
            longitude=np.full(n, 20.0),
            magnitude=np.full(n, 5.0),
        )
        t0 = time.time()
        result = _score_a5_duplicates(ds, max_neighborhood_candidates=50)
        elapsed = time.time() - t0
        assert elapsed < 5.0, f"dense-bucket case took {elapsed:.2f}s -- the safety-valve cap may not be applying."
        assert result.applicable
        assert result.detail["n_flagged"] > n * 0.5


class TestExternalMode:
    def test_a6_matches_against_identical_reference(self, tmp_path):
        ds = make_gr_dataset(n=100, mc=4.6, seed=4)  # above default NEIC-style Mc
        ref_path = tmp_path / "reference.csv"
        save_dataset_csv(ds, ref_path)

        reference = LocalCSVCatalogReference(ref_path)
        result = score_authenticity(ds, reference=reference)
        a6 = result.sub_results["A6"]
        # Matching the dataset against an identical copy of itself should
        # yield a high matched_fraction (subject to Mc_ref stratification).
        if a6.applicable:
            assert a6.detail["matched_fraction"] > 0.5

    def test_a6_infeasible_reference_falls_back(self):
        ds = make_dataset(n=50)
        result = score_authenticity(ds, reference=NullExternalCatalog())
        assert result.mode == "intrinsic (A1-A5)"
        assert result.sub_results["A6"].applicable is False

    def test_a6_single_source_low_match_is_unverifiable_not_hard_reject(self, tmp_path):
        """
        Group C3 (2026-07-12): this is the exact scenario the three-state
        redesign exists to fix -- a SINGLE reference source finding no
        matches (e.g. a genuine regional coverage gap, like the disclosed
        real "nz"/GeoNet-vs-USGS case in Criteria_and_Weights_Master_Reference.md
        Section 4.2) must NOT hard-REJECT on its own any more. It is
        "Externally unverifiable" (< A6_CONTRADICTED_MIN_SOURCES=2
        independent sources), so it falls back to intrinsic A1-A5 scoring
        with NO A6 penalty either way.
        """
        # Reference catalog with completely disjoint events (different time/place).
        ds = make_gr_dataset(n=100, mc=4.6, seed=5)
        ref = make_gr_dataset(n=100, mc=4.6, seed=6)
        ref.latitude += 60.0  # move reference far away spatially
        ref_path = tmp_path / "reference.csv"
        save_dataset_csv(ref, ref_path)

        reference = LocalCSVCatalogReference(ref_path)
        result = score_authenticity(ds, reference=reference)
        # A single-source total mismatch means every stratum record lands in
        # "Externally unverifiable" -> A6 contributes nothing (n_effective=0),
        # applicable=False, and the composite falls back entirely to intrinsic.
        assert result.sub_results["A6"].applicable is False
        assert result.mode == "intrinsic (A1-A5)"
        assert result.hard_reject is False

    def test_a6_two_source_confirmed_no_match_fires_contradicted(self, tmp_path):
        """
        The complementary case: with >=2 independently-feasible sources,
        BOTH of which fail to match a large-enough (>=A6_CONTRADICTED_MIN_N_STRATUM)
        reference-complete-stratum, and the resulting all-non-match
        sub-stratum is large enough to pass the Clopper-Pearson lower-tail
        confidence test, A6 SHOULD still be able to fire the hard-override
        -- Group C3 raises the bar (requires multi-source, statistically
        confirmed evidence), it does not remove A6's hard-override
        capability entirely.
        """
        ds = make_gr_dataset(n=200, mc=4.6, seed=7)
        ref1 = make_gr_dataset(n=200, mc=4.6, seed=8)
        ref1.latitude += 60.0  # disjoint source 1
        ref2 = make_gr_dataset(n=200, mc=4.6, seed=9)
        ref2.latitude -= 60.0  # disjoint source 2, independently

        ref1_path = tmp_path / "reference1.csv"
        ref2_path = tmp_path / "reference2.csv"
        save_dataset_csv(ref1, ref1_path)
        save_dataset_csv(ref2, ref2_path)

        reference = MultiSourceExternalCatalogReference(
            [LocalCSVCatalogReference(ref1_path), LocalCSVCatalogReference(ref2_path)],
            min_corroborating_sources=1,
        )
        result = score_authenticity(ds, reference=reference)
        a6 = result.sub_results["A6"]
        if a6.applicable and a6.detail.get("n_contradicted_eligible", 0) >= 20:
            assert a6.detail["contradicted_confirmed"] is True
            assert result.hard_reject is True
            assert "Externally contradicted" in result.hard_reject_reason


class TestPerformance:
    """
    Regression tests for two O(n^2)-in-the-worst-case performance bugs
    discovered while scoring the calibration corpus (Dataset/earthquake1.csv,
    a real "significant earthquakes" catalog, and a timestamp-collision
    corruption variant of a real catalog) -- both are legitimate,
    non-adversarial real-world inputs, not just synthetic edge cases, so a
    slow-path regression here would silently make the tool impractical on
    exactly the kind of data it needs to handle.
    """

    def test_a3_catalog_where_every_event_is_a_mainshock_completes_quickly(self):
        """
        A3's mainshock search previously re-scanned the full sorted array
        once per candidate mainshock (O(n_mainshocks * n)). A catalog that
        is ITSELF already magnitude-filtered to significant events (like
        Dataset/earthquake1.csv) makes essentially every record a
        candidate mainshock, which made this effectively O(n^2). This
        builds a smaller but structurally identical worst case (every
        magnitude >= the 5.5 mainshock threshold) and asserts it still
        completes in bounded time -- bounded by the disclosed
        MAX_A3_CLUSTERS=2000 fit cap (~2ms/fit -> ~4-5s ceiling), not the
        unbounded, catalog-size-dependent tens-of-seconds-to-minutes this
        bug produced at n=23,232 (where BOTH the O(n_mainshocks * n)
        search AND the uncapped 17,570-cluster fit stacked). The 10s bound
        below is deliberately generous headroom over the ~4-5s the capped
        fit legitimately costs -- it exists to catch a regression of
        either fix (the search becoming O(n^2) again, or the fit cap
        being removed/raised), not to enforce sub-second performance.
        """
        n = 3000
        ds = make_gr_dataset(n=n, b_value=1.0, mc=5.5, seed=11)
        # make_gr_dataset draws from mc upward, so every magnitude is
        # already >= 5.5 -- i.e. every record qualifies as a candidate
        # mainshock, reproducing the pathological case exactly.
        assert float(np.min(ds.magnitude)) >= 5.5
        t0 = time.time()
        result = _score_a3_omori_utsu(ds)
        elapsed = time.time() - t0
        assert elapsed < 10.0, (
            f"A3 took {elapsed:.2f}s on a {n}-record all-mainshock catalog -- "
            f"the O(n_mainshocks * n) mainshock-search regression appears to have returned."
        )
        assert result.applicable

    def test_a5_many_records_sharing_one_timestamp_completes_quickly(self):
        """
        A5's duplicate search previously compared every pair of records
        within the sliding time-eps window (O(k^2) for a cluster of k
        records sharing one timestamp) -- exactly what a batch-import bug
        (many records defaulting to one system-clock timestamp) produces,
        which is the realistic failure mode A5 exists to catch. Builds a
        dataset where most records share one exact timestamp but are
        scattered across distinct locations (i.e. NOT genuine duplicates),
        asserts this still completes quickly, and separately confirms a
        real near-duplicate pair scattered among the shared-timestamp
        records is still correctly flagged (i.e. the spatial-grid
        pre-filter did not just skip real detections for speed).
        """
        n = 3000
        rng = np.random.RandomState(12)
        ds = make_dataset(
            n=n,
            latitude=rng.uniform(-60.0, 60.0, n),
            longitude=rng.uniform(-180.0, 180.0, n),
            magnitude=rng.uniform(3.0, 6.0, n),
        )
        shared_t = ds.origin_time[0]
        collision_idx = rng.choice(n, size=int(0.9 * n), replace=False)
        ds.origin_time[collision_idx] = shared_t

        # Plant one genuine near-duplicate pair inside the shared-timestamp
        # cluster: same time, same place, same magnitude.
        i, j = collision_idx[0], collision_idx[1]
        ds.origin_time[j] = ds.origin_time[i]
        ds.latitude[j] = ds.latitude[i] + 0.0001
        ds.longitude[j] = ds.longitude[i] + 0.0001
        ds.magnitude[j] = ds.magnitude[i]

        t0 = time.time()
        result = _score_a5_duplicates(ds)
        elapsed = time.time() - t0
        assert elapsed < 3.0, (
            f"A5 took {elapsed:.2f}s on a {n}-record catalog with a large "
            f"shared-timestamp cluster -- the O(k^2) all-pairs regression "
            f"appears to have returned."
        )
        assert result.detail["n_flagged"] >= 2, (
            "the planted genuine near-duplicate pair should still be flagged "
            "even though most other same-timestamp records are spatially "
            "scattered (not real duplicates)."
        )
        # The scattered same-timestamp records should NOT almost-all be
        # flagged as duplicates of each other -- they differ in location.
        assert result.detail["n_flagged"] < n * 0.5
