# -*- coding: utf-8 -*-
"""
tests/test_reference_data.py -- Tests for data_certify/reference_data.py,
focused on the new USGSComCatReference (live A6 external catalog).

No real network calls are made: urllib.request.urlopen is monkeypatched
with a fake in-memory USGS ComCat-shaped responder (`make_fake_urlopen`)
built from the real API's response shape, verified live against
earthquake.usgs.gov during this project's development (see
data_certify/reference_data.py's docstring and Docs/01_Deep_Dives/DATA-CERTIFY_Code_to_Theory_Mapping.md).
"""

from __future__ import annotations

import json
import math
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.reference_data import (
    USGSComCatReference,
    LocalCSVCatalogReference,
    NullExternalCatalog,
    _compact_lon_bounds,
    _estimate_mc_ref,
    _match_against_reference_arrays,
    _split_lon_range,
)
from conftest import make_dataset, make_gr_dataset


# ---------------------------------------------------------------------------
# Fake USGS ComCat network layer -- no real HTTP calls in this file.
# ---------------------------------------------------------------------------

class _FakeHTTPResponse:
    def __init__(self, data: bytes):
        self._data = data

    def read(self, *a, **kw):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _parse_query(url: str):
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    return {k: v[0] for k, v in qs.items()}, parsed.path


def _iso_to_ms(iso: str) -> int:
    return int(np.datetime64(iso).astype("datetime64[ms]").astype(np.int64))


def make_fake_urlopen(events, force_error: bool = False):
    """
    events: list of dict(time_ms=int, lat=float, lon=float, mag=float).
    Returns a callable usable as urllib.request.urlopen's replacement,
    serving the /count and /query (geojson) endpoints by filtering `events`
    on starttime/endtime/minmagnitude (lat/lon bounding-box filtering is
    deliberately NOT simulated here -- the real distance/time/magnitude
    tolerance check in `_match_against_reference_arrays` is what actually
    needs to be correct, and is exercised for real by these tests; being
    lenient here only means the fake may hand back a slightly wider
    candidate set than the real API would, never a narrower one).
    """
    def fake_urlopen(req, timeout=None):
        if force_error:
            raise urllib.error.URLError("simulated network failure")
        url = req.full_url if hasattr(req, "full_url") else str(req)
        params, path = _parse_query(url)
        start_ms = _iso_to_ms(params["starttime"])
        end_ms = _iso_to_ms(params["endtime"])
        min_mag = float(params.get("minmagnitude", "-10"))
        matched = [e for e in events
                   if start_ms <= e["time_ms"] <= end_ms and e["mag"] >= min_mag]
        if path.endswith("/count"):
            return _FakeHTTPResponse(str(len(matched)).encode("utf-8"))
        features = [
            {
                "type": "Feature",
                "properties": {"mag": e["mag"], "time": e["time_ms"]},
                "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"], 10.0]},
            }
            for e in matched
        ]
        payload = {"type": "FeatureCollection", "features": features}
        return _FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

    return fake_urlopen


# ---------------------------------------------------------------------------
# is_feasible(): connectivity probe, caching, graceful failure
# ---------------------------------------------------------------------------

class TestIsFeasible:
    def test_feasible_when_reachable_and_cached(self, monkeypatch):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            return _FakeHTTPResponse(b"3")

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = USGSComCatReference()
        assert ref.is_feasible() is True
        assert ref.is_feasible() is True
        assert calls["n"] == 1, "is_feasible() must cache, not re-probe every call"

    def test_infeasible_on_network_error(self, monkeypatch):
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([], force_error=True),
        )
        ref = USGSComCatReference()
        assert ref.is_feasible() is False

    def test_infeasible_on_garbage_response(self, monkeypatch):
        def fake_urlopen(req, timeout=None):
            return _FakeHTTPResponse(b"not-a-number")
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = USGSComCatReference()
        assert ref.is_feasible() is False


# ---------------------------------------------------------------------------
# match(): graceful fallback, corroboration found/not found, pagination
# ---------------------------------------------------------------------------

class TestMatch:
    def test_falls_back_to_null_when_infeasible(self, monkeypatch):
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([], force_error=True),
        )
        ds = make_dataset(n=10)
        ref = USGSComCatReference()
        result = ref.match(ds)
        null_result = NullExternalCatalog().match(ds)
        assert result.matched.tolist() == null_result.matched.tolist()
        assert result.mc_ref_is_default == null_result.mc_ref_is_default
        assert math.isnan(result.mc_ref)

    def test_finds_corroborating_event(self, monkeypatch):
        ds = make_dataset(
            n=1,
            latitude=np.array([10.0]), longitude=np.array([20.0]),
            magnitude=np.array([5.0]),
            origin_time=np.array([np.datetime64("2020-01-01T00:00:00", "ns")]),
        )
        event_time_ms = _iso_to_ms("2020-01-01T00:00:00")
        events = [{"time_ms": event_time_ms, "lat": 10.001, "lon": 20.001, "mag": 5.02}]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen(events),
        )
        ref = USGSComCatReference()
        result = ref.match(ds)
        assert result.matched.tolist() == [True]

    def test_no_corroboration_found(self, monkeypatch):
        ds = make_dataset(n=3)
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen([]),
        )
        ref = USGSComCatReference()
        result = ref.match(ds)
        assert not result.matched.any()

    def test_event_outside_tolerance_does_not_match(self, monkeypatch):
        ds = make_dataset(
            n=1,
            latitude=np.array([10.0]), longitude=np.array([20.0]),
            magnitude=np.array([5.0]),
            origin_time=np.array([np.datetime64("2020-01-01T00:00:00", "ns")]),
        )
        # Same time, but a magnitude far outside mag_tol (default 0.5).
        event_time_ms = _iso_to_ms("2020-01-01T00:00:00")
        events = [{"time_ms": event_time_ms, "lat": 10.001, "lon": 20.001, "mag": 7.5}]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen(events),
        )
        ref = USGSComCatReference()
        result = ref.match(ds)
        assert result.matched.tolist() == [False]

    def test_pagination_recovers_all_events_when_over_cap(self, monkeypatch):
        # 6 synthetic events spread over 6 hours; force max_events_per_query
        # down to 2 so the recursive time-halving pagination path MUST
        # trigger (and must not lose or duplicate any event) for this test
        # to pass -- a regression guard for the pagination logic itself.
        base_ms = _iso_to_ms("2020-06-01T00:00:00")
        hour_ms = 3_600_000
        events = [
            {"time_ms": base_ms + i * hour_ms, "lat": 0.0, "lon": 0.0, "mag": 5.0}
            for i in range(6)
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_urlopen(events),
        )
        origin_times = (np.datetime64("2020-06-01T00:00:00", "ns")
                         + np.arange(6) * np.timedelta64(1, "h"))
        ds = make_dataset(
            n=6, latitude=np.zeros(6), longitude=np.zeros(6),
            magnitude=np.full(6, 5.0), origin_time=origin_times,
        )
        ref = USGSComCatReference(max_events_per_query=2)
        result = ref.match(ds)
        assert result.matched.tolist() == [True] * 6

    def test_no_valid_records_falls_back_without_network_query(self, monkeypatch):
        # All-NaN coordinates -- match() should short-circuit to
        # NullExternalCatalog behaviour without even probing feasibility
        # for the match itself (is_feasible() may still be called, but no
        # count/query fetch should be attempted).
        ds = make_dataset(n=5, latitude=np.full(5, np.nan), longitude=np.full(5, np.nan))

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            _, path = _parse_query(url)
            if path.endswith("/count") and "starttime=2020-01-01" in url:
                return _FakeHTTPResponse(b"3")  # feasibility probe only
            raise AssertionError(f"unexpected network call for all-NaN dataset: {url}")

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = USGSComCatReference()
        result = ref.match(ds)
        assert not result.matched.any()


# ---------------------------------------------------------------------------
# _compact_lon_bounds: antimeridian/dateline handling
# ---------------------------------------------------------------------------

class TestCompactLonBounds:
    def test_normal_range_away_from_dateline(self):
        lo, hi = _compact_lon_bounds(np.array([10.0, 20.0, 15.0]))
        assert (lo, hi) == pytest.approx((10.0, 20.0))

    def test_dateline_crossing_returns_compact_wrapped_box(self):
        # NZ-Kermadec-like: points clustered right across +/-180.
        lo, hi = _compact_lon_bounds(np.array([178.0, 179.5, -179.0, -178.5]))
        assert hi > 180.0, "dateline-crossing box should be expressed as lon_max > 180"
        assert (hi - lo) < 10.0, "wrapped box should be compact, not near-global"

    def test_empty_input_returns_full_range(self):
        lo, hi = _compact_lon_bounds(np.array([]))
        assert (lo, hi) == (-180.0, 180.0)


# ---------------------------------------------------------------------------
# _split_lon_range: turning a (possibly dateline-crossing) box into
# ordinary, always-FDSN-valid [-180, 180] sub-ranges.
#
# BUGFIX (scientific-validity review pass): USGS ComCat and EMSC both
# document/exhibit a "wraps at +/-180" minlongitude/maxlongitude extension
# (live-verified against USGS during this review: maxlongitude=190 returns
# real events), but ISC's own published parameter table only lists the
# ordinary [-180, 180] range with no such extension mentioned -- matching
# the base FDSN fdsnws-event-1.2 spec, which has no dateline convention at
# all. Emitting a raw (170, 190)-style box (as `_compact_lon_bounds` plus
# a distance buffer can produce) risks an HTTP 400 or undefined behaviour
# against a strict FDSN implementation. `_split_lon_range` removes this
# risk uniformly for USGS/EMSC/ISC by always sending ordinary sub-boxes.
# ---------------------------------------------------------------------------

class TestSplitLonRange:
    def test_ordinary_range_is_not_split(self):
        assert _split_lon_range(-10.0, 10.0) == [(-10.0, 10.0)]

    def test_dateline_crossing_range_splits_into_two_valid_boxes(self):
        parts = _split_lon_range(170.0, 190.0)
        assert len(parts) == 2
        for lo, hi in parts:
            assert -180.0 <= lo < hi <= 180.0
        total_width = sum(hi - lo for lo, hi in parts)
        assert total_width == pytest.approx(20.0)

    def test_negative_side_dateline_crossing_also_splits(self):
        parts = _split_lon_range(-190.0, -170.0)
        assert len(parts) == 2

        for lo, hi in parts:
            assert -180.0 <= lo < hi <= 180.0

    def test_small_buffer_overflow_past_minus_180_is_handled(self):
        # A non-crossing box that just barely dips past -180 due to the
        # distance-tolerance buffer (not a genuine dateline-spanning
        # dataset) must still produce only valid sub-ranges.
        parts = _split_lon_range(-181.0, -179.0)
        for lo, hi in parts:
            assert -180.0 <= lo < hi <= 180.0

    def test_whole_globe_width_collapses_to_single_full_range(self):
        assert _split_lon_range(-500.0, 500.0) == [(-180.0, 180.0)]

    def test_usgs_match_issues_two_sub_box_queries_across_dateline(self, monkeypatch):
        # End-to-end check (not just the helper in isolation): a dataset
        # whose records straddle +/-180 must result in USGSComCatReference
        # issuing exactly two /query requests, each with a valid
        # [-180, 180] longitude box, and BOTH sub-boxes' events must be
        # found and matched -- regression guard for the antimeridian
        # pagination bug this function fixes.
        ds = make_dataset(
            n=2,
            latitude=np.array([-29.0, -29.0]),
            longitude=np.array([-177.5, 179.0]),  # crosses the dateline
            magnitude=np.array([6.0, 6.5]),
            origin_time=np.array([
                np.datetime64("2020-01-01T00:00:00", "ns"),
                np.datetime64("2020-01-01T01:00:00", "ns"),
            ]),
        )
        events = [
            {"time_ms": _iso_to_ms("2020-01-01T00:00:00"), "lat": -29.001, "lon": -177.501, "mag": 6.02},
            {"time_ms": _iso_to_ms("2020-01-01T01:00:00"), "lat": -29.001, "lon": 179.001, "mag": 6.52},
        ]

        seen_query_lon_bounds = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            params, path = _parse_query(url)
            if "minlongitude" not in params:
                # The one-time feasibility probe (a fixed, dataset-independent
                # date range) carries no lon/lat box at all -- only the
                # dataset-driven /count and /query calls below need checking.
                return _FakeHTTPResponse(b"1")
            lon_min = float(params["minlongitude"])
            lon_max = float(params["maxlongitude"])
            assert -180.0 <= lon_min <= 180.0, f"minlongitude out of FDSN-safe range: {lon_min}"
            assert -180.0 <= lon_max <= 180.0, f"maxlongitude out of FDSN-safe range: {lon_max}"
            start_ms = _iso_to_ms(params["starttime"])
            end_ms = _iso_to_ms(params["endtime"])
            min_mag = float(params.get("minmagnitude", "-10"))
            matched = [
                e for e in events
                if start_ms <= e["time_ms"] <= end_ms and e["mag"] >= min_mag
                and lon_min <= e["lon"] <= lon_max
            ]
            if path.endswith("/count"):
                return _FakeHTTPResponse(str(len(matched)).encode("utf-8"))
            seen_query_lon_bounds.append((lon_min, lon_max))
            features = [
                {
                    "type": "Feature",
                    "properties": {"mag": e["mag"], "time": e["time_ms"]},
                    "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"], 10.0]},
                }
                for e in matched
            ]
            payload = {"type": "FeatureCollection", "features": features}
            return _FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = USGSComCatReference()
        result = ref.match(ds, time_tol_sec=60.0, dist_tol_km=100.0, mag_tol=0.5)

        assert len(seen_query_lon_bounds) == 2, (
            f"expected exactly 2 sub-box /query requests for a dateline-"
            f"crossing dataset, got {len(seen_query_lon_bounds)}: {seen_query_lon_bounds}"
        )
        assert result.matched.tolist() == [True, True], (
            "both records (one on each side of the dateline) should be "
            "corroborated once the box is correctly split"
        )


# ---------------------------------------------------------------------------
# Shared matching core, exercised directly (also indirectly covered via
# LocalCSVCatalogReference in test_axis_authenticity.py)
# ---------------------------------------------------------------------------

class TestSharedMatchingCore:
    def test_estimate_mc_ref_defaults_on_too_little_data(self):
        mc, se, is_default = _estimate_mc_ref(np.array([5.0]))
        assert is_default is True
        assert mc == pytest.approx(4.5)
        assert se == pytest.approx(0.3)

    def test_estimate_mc_ref_floors_a_low_fitted_value(self):
        # Regression test for the 2026-07-05 MC_REF_GLOBAL_FLOOR fix: found
        # via a live pilot run where EMSCReference's own query (bounded by
        # the audited "chile" dataset's own very low minimum magnitude, per
        # match()'s "query floor = dataset's own min magnitude - tolerance"
        # design) returned enough small-magnitude regional events that the
        # maximum-curvature fit on the REFERENCE data alone landed at
        # Mc_ref~=2.0 -- far below any magnitude a global/regional
        # aggregator can realistically claim complete coverage of. A
        # genuine, successful fit (not the "too little data" NaN-fallback
        # path above) must still never be trusted below MC_REF_GLOBAL_FLOOR.
        rng = np.random.RandomState(0)
        true_mc = 2.0
        beta = 1.0 * math.log(10.0)  # b=1.0
        mags = np.round(true_mc + rng.exponential(1.0 / beta, size=5000), 1)

        # Sanity check: the unfloored fit really would have landed near the
        # low true_mc (confirms this test exercises the floor, not the
        # "too little data" NaN-fallback branch already covered above).
        from data_certify.stats import maximum_curvature_mc
        raw_fit = maximum_curvature_mc(mags)
        assert raw_fit < 3.0, f"test setup issue: raw fit {raw_fit} not low enough to exercise the floor"

        mc, se, is_default = _estimate_mc_ref(mags)
        assert is_default is False  # this WAS a successful fit, just a low one
        assert mc == pytest.approx(4.5)  # floored up, not left at the raw ~2.0 fit

    def test_match_against_reference_arrays_empty_reference(self):
        ds = make_dataset(n=4)
        result = _match_against_reference_arrays(
            ds,
            ref_time=np.array([], dtype="datetime64[ns]"),
            ref_lat=np.array([]), ref_lon=np.array([]), ref_mag=np.array([]),
            time_tol_sec=30.0, dist_tol_km=50.0, mag_tol=0.5,
        )
        assert not result.matched.any()
        assert result.mc_ref_is_default is True

    def test_local_csv_reference_still_works_after_refactor(self, tmp_path):
        # Regression check: LocalCSVCatalogReference must behave identically
        # after being refactored to call the shared
        # _match_against_reference_arrays helper.
        from data_certify.schema import save_dataset_csv

        ds = make_gr_dataset(n=100, mc=4.6, seed=4)
        ref_path = tmp_path / "reference.csv"
        save_dataset_csv(ds, ref_path)
        reference = LocalCSVCatalogReference(ref_path)
        assert reference.is_feasible() is True
        result = reference.match(ds)
        assert result.matched.sum() > 0
