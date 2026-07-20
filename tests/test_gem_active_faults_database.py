# -*- coding: utf-8 -*-
"""
tests/test_gem_active_faults_database.py -- unit tests for
GEMActiveFaultsDatabase (data_certify/reference_data.py), the real GEM
Global Active Faults Database (Styron & Pagani 2020) backed P8 reference.

All tests use small, synthetic GeoJSON fixtures written to `tmp_path` --
none of them load the real, ~12MB bundled Dataset/GAF-DB/ files (those are
exercised separately, informally, in this project's own development, since
loading a 190k-point database in every test run would be slow and would
make these tests depend on a large binary fixture rather than a minimal,
self-contained one). See the class's own docstring for the three
explicitly disclosed approximations these tests are designed around:
point-cloud vs. true polyline distance, approximate grid-ring nearest-
neighbor search, and the long-range sentinel distance.
"""

import json
import math

import numpy as np
import pytest

from data_certify.reference_data import (
    GEMActiveFaultsDatabase,
    _GEM_SENTINEL_DISTANCE_KM,
    default_gem_geojson_path,
)
from data_certify.stats import haversine_km


def _write_geojson(tmp_path, features, name="faults.geojson"):
    path = tmp_path / name
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _line_feature(coords):
    """coords: list of [lon, lat] pairs."""
    return {
        "type": "Feature",
        "properties": {"name": "test fault"},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _multiline_feature(lines):
    """lines: list of list of [lon, lat] pairs."""
    return {
        "type": "Feature",
        "properties": {"name": "test multi-fault"},
        "geometry": {"type": "MultiLineString", "coordinates": lines},
    }


class TestLoading:
    def test_loads_valid_short_linestring(self, tmp_path):
        # Two points ~1 km apart -- well under the default 10 km
        # subdivision threshold, so no extra points should be inserted.
        path = _write_geojson(tmp_path, [_line_feature([[0.0, 0.0], [0.0, 0.009]])])
        db = GEMActiveFaultsDatabase(path)
        assert db.is_available() is True
        assert db.load_error is None
        assert db.n_points == 2

    def test_missing_file_is_unavailable(self, tmp_path):
        db = GEMActiveFaultsDatabase(str(tmp_path / "does_not_exist.geojson"))
        assert db.is_available() is False
        assert db.load_error is not None
        assert "could not read/parse" in db.load_error

    def test_malformed_json_is_unavailable(self, tmp_path):
        path = tmp_path / "broken.geojson"
        path.write_text("{not valid json", encoding="utf-8")
        db = GEMActiveFaultsDatabase(str(path))
        assert db.is_available() is False
        assert db.load_error is not None

    def test_no_usable_geometry_is_unavailable(self, tmp_path):
        # Only a Point feature -- this loader understands LineString /
        # MultiLineString fault traces only, per its docstring.
        point_feature = {
            "type": "Feature",
            "properties": {},
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0]},
        }
        path = _write_geojson(tmp_path, [point_feature])
        db = GEMActiveFaultsDatabase(path)
        assert db.is_available() is False
        assert "no usable" in db.load_error

    def test_multilinestring_parsed(self, tmp_path):
        feat = _multiline_feature([
            [[0.0, 0.0], [0.0, 0.01]],
            [[5.0, 5.0], [5.0, 5.01]],
        ])
        path = _write_geojson(tmp_path, [feat])
        db = GEMActiveFaultsDatabase(path)
        assert db.is_available() is True
        assert db.n_points == 4

    def test_single_point_linestring_degenerate_case(self, tmp_path):
        # A malformed/degenerate 1-point "LineString" should still be
        # ingested as a single point, not crash the loader.
        path = _write_geojson(tmp_path, [_line_feature([[1.0, 1.0]])])
        db = GEMActiveFaultsDatabase(path)
        assert db.is_available() is True
        assert db.n_points == 1


class TestSubdivision:
    def test_long_segment_is_subdivided(self, tmp_path):
        # ~100 km segment (roughly 0.9 degrees of latitude) with a 10 km
        # max_segment_km should be subdivided into multiple sub-points.
        path = _write_geojson(tmp_path, [_line_feature([[0.0, 0.0], [0.0, 0.9]])])
        db = GEMActiveFaultsDatabase(path, max_segment_km=10.0)
        assert db.is_available() is True
        assert db.n_points > 2

    def test_short_segment_is_not_subdivided(self, tmp_path):
        # ~1 km segment with a 10 km threshold: no subdivision needed.
        path = _write_geojson(tmp_path, [_line_feature([[0.0, 0.0], [0.0, 0.009]])])
        db = GEMActiveFaultsDatabase(path, max_segment_km=10.0)
        assert db.n_points == 2


class TestDistanceQueries:
    def test_finds_nearest_of_two_widely_separated_points(self, tmp_path):
        path = _write_geojson(tmp_path, [
            _line_feature([[0.0, 0.0], [0.0, 0.001]]),   # near the equator/prime meridian
            _line_feature([[50.0, 50.0], [50.0, 50.001]]),  # far away
        ])
        db = GEMActiveFaultsDatabase(path)
        # Query point very close to the first fault.
        d = db.distance_to_nearest_boundary_km(0.01, 0.01)
        expected = haversine_km(0.01, 0.01, 0.0, 0.0)
        assert d == pytest.approx(expected, abs=1.0)

    def test_scalar_matches_vectorized_batch(self, tmp_path):
        path = _write_geojson(tmp_path, [_line_feature([[10.0, 10.0], [10.0, 10.01]])])
        db = GEMActiveFaultsDatabase(path)
        lats = np.array([10.0, 20.0, -5.0])
        lons = np.array([10.0, 20.0, -5.0])
        batch = db.distances_to_nearest_boundary_km(lats, lons)
        scalars = np.array([
            db.distance_to_nearest_boundary_km(lat, lon)
            for lat, lon in zip(lats, lons)
        ])
        np.testing.assert_allclose(batch, scalars)

    def test_finds_neighbor_across_grid_cell_boundary(self, tmp_path):
        # Fault point at (0.95, 0.95) sits in grid cell (0, 0) under the
        # default 1.0-degree cell size; query point at (1.05, 1.05) sits
        # in cell (1, 1) -- an adjacent cell, not the same one. This
        # exercises the "search one extra ring beyond the first hit"
        # boundary-safety logic (class docstring, approximation #2).
        path = _write_geojson(tmp_path, [_line_feature([[0.95, 0.95], [0.95, 0.951]])])
        db = GEMActiveFaultsDatabase(path, cell_deg=1.0)
        d = db.distance_to_nearest_boundary_km(1.05, 1.05)
        expected = haversine_km(1.05, 1.05, 0.95, 0.95)
        assert d == pytest.approx(expected, rel=0.05)

    def test_nan_query_coordinates_yield_nan_without_crashing(self, tmp_path):
        path = _write_geojson(tmp_path, [_line_feature([[0.0, 0.0], [0.0, 0.01]])])
        db = GEMActiveFaultsDatabase(path)
        lats = np.array([0.0, np.nan, 5.0])
        lons = np.array([0.0, 1.0, np.nan])
        out = db.distances_to_nearest_boundary_km(lats, lons)
        assert np.isfinite(out[0])
        assert np.isnan(out[1])
        assert np.isnan(out[2])

    def test_sentinel_distance_when_nothing_within_max_ring(self, tmp_path):
        # A single fault point ~50 degrees away, with max_ring small
        # enough that the grid search gives up before reaching it -- the
        # long-range sentinel (approximation #3) should be returned.
        path = _write_geojson(tmp_path, [_line_feature([[50.0, 50.0], [50.0, 50.001]])])
        db = GEMActiveFaultsDatabase(path, cell_deg=1.0, max_ring=2)
        d = db.distance_to_nearest_boundary_km(0.0, 0.0)
        assert d == _GEM_SENTINEL_DISTANCE_KM

    def test_unavailable_database_returns_nan(self, tmp_path):
        db = GEMActiveFaultsDatabase(str(tmp_path / "missing.geojson"))
        d = db.distance_to_nearest_boundary_km(0.0, 0.0)
        assert math.isnan(d)
        arr = db.distances_to_nearest_boundary_km(np.array([0.0, 1.0]), np.array([0.0, 1.0]))
        assert np.all(np.isnan(arr))


class TestAntimeridian:
    """
    Regression tests for the antimeridian (+/-180 degree) grid-wraparound
    bug (scientific-validity review pass): `_candidate_indices_for_cell`
    generates longitude cell x-coordinates as `cx +/- ring` with no
    wraparound, so a query point near -179.5 deg could not find fault
    points indexed near +179.5 deg (359 grid cells apart despite being
    ~1 degree apart in true geography), silently falling back to the
    5000 km "nothing found" sentinel. This is directly relevant to this
    project's own bundled NZ dataset, which spans the Kermadec Trench
    across +/-180 -- see USGSComCatReference's `_compact_lon_bounds`
    docstring for the analogous, already-fixed bug in a different code
    path. Fixed via `GEMActiveFaultsDatabase._wrap_lon_cell`.
    """

    def test_cross_dateline_query_finds_nearby_fault(self, tmp_path):
        # Fault trace at lon 179.0 to 179.8 deg -- just west of the
        # dateline. A query point at lon -179.5 deg is only ~1 degree
        # (roughly 60-100 km at this latitude) away across the dateline,
        # but before the fix this was reported as the 5000 km sentinel
        # because grid cells on either side of +/-180 were never searched
        # together.
        path = _write_geojson(tmp_path, [
            _line_feature([[179.0, -40.0], [179.8, -39.0]])
        ])
        db = GEMActiveFaultsDatabase(path)
        d_cross = db.distance_to_nearest_boundary_km(-39.5, -179.5)
        assert d_cross < 200.0, (
            f"expected a nearby fault (<200 km) across the dateline, got "
            f"{d_cross} km -- looks like the antimeridian grid-wraparound "
            f"bug has regressed"
        )
        assert d_cross != _GEM_SENTINEL_DISTANCE_KM

    def test_cross_dateline_matches_same_side_control(self, tmp_path):
        # Sanity check: a query on the SAME side of the dateline as the
        # fault should already have worked before the fix, and should
        # give a materially smaller (truly nearest) distance than the
        # cross-dateline query above once both are correct.
        path = _write_geojson(tmp_path, [
            _line_feature([[179.0, -40.0], [179.8, -39.0]])
        ])
        db = GEMActiveFaultsDatabase(path)
        d_control = db.distance_to_nearest_boundary_km(-39.5, 179.5)
        assert d_control < 50.0

    def test_wrap_lon_cell_is_consistent_with_grid_indexing(self, tmp_path):
        # Direct unit check on the wrap helper itself: wrapping a cell
        # index that is already in-range must be a no-op, and wrapping
        # one 360 degrees (in cell units) away must land on the same cell.
        path = _write_geojson(tmp_path, [_line_feature([[0.0, 0.0], [0.0, 0.01]])])
        db = GEMActiveFaultsDatabase(path, cell_deg=1.0)
        n_lon_cells = round(360.0 / 1.0)
        for cx in (-180, -1, 0, 1, 179, 180, 359, -359):
            assert db._wrap_lon_cell(cx) == db._wrap_lon_cell(cx + n_lon_cells)
            assert -180 <= db._wrap_lon_cell(cx) < 180


class TestDefaultPathDetection:
    def test_default_gem_geojson_path_finds_repo_bundled_file(self):
        # This repo ships Dataset/GAF-DB/gem_active_faults_harmonized.geojson
        # (or the raw gem_active_faults.geojson) -- default_gem_geojson_path()
        # should locate one of them relative to the installed package,
        # with no arguments, so `run_audit.py --fault-db-source gem` works
        # out of the box in this reference implementation's own checkout.
        path = default_gem_geojson_path()
        assert path is not None
        assert path.endswith(".geojson")


class TestIntegrationWithP8Scoring:
    def test_p8_scores_high_near_synthetic_fault_low_far_away(self, tmp_path):
        from data_certify.axis_plausibility import score_plausibility
        from conftest import make_dataset

        path = _write_geojson(tmp_path, [_line_feature([[175.0, -40.0], [175.1, -40.1]])])
        fault_db = GEMActiveFaultsDatabase(path)

        near = make_dataset(n=1, latitude=np.array([-40.0]), longitude=np.array([175.0]))
        far = make_dataset(n=1, latitude=np.array([50.0]), longitude=np.array([10.0]))

        r_near = score_plausibility(near, fault_db=fault_db)
        r_far = score_plausibility(far, fault_db=fault_db)
        assert r_near.sub_results["P8"].score >= r_far.sub_results["P8"].score
