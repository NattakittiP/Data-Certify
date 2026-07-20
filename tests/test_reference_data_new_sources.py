# -*- coding: utf-8 -*-
"""
tests/test_reference_data_new_sources.py -- Tests for the EMSC/ISC/
MultiSource A6 external-reference sources added to harden A6 against a
single-source (USGS ComCat) spoofing/compromise scenario.

No real network calls are made: urllib.request.urlopen is monkeypatched
with fake in-memory responders, shaped like each service's REAL documented
response format:
  - EMSC: GeoJSON-like, verified against EMSC-CSEM's own published tutorial
    (github.com/EMSC-CSEM/webservices101, emsc_services.md) -- see
    EMSCReference's docstring in data_certify/reference_data.py.
  - ISC: QuakeML/BED XML, built from the published FDSN fdsnws-event-1.2
    specification and QuakeML/BED schema (NOT a live-verified sample --
    see ISCReference's docstring for the disclosed reason).
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
    EMSCReference,
    ISCReference,
    MultiSourceExternalCatalogReference,
    NullExternalCatalog,
    WeightedMultiSourceExternalCatalogReference,
)
from conftest import make_dataset


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


# ---------------------------------------------------------------------------
# EMSC fake network layer
# ---------------------------------------------------------------------------

def make_fake_emsc_urlopen(events, force_error: bool = False):
    """
    events: list of dict(time_iso=str, lat=float, lon=float, mag=float).
    Filters on starttime/endtime/minmagnitude (lat/lon box not simulated --
    same rationale as USGS's fake in test_reference_data.py: being lenient
    here only widens the candidate set, never narrows it, so the real
    distance/time/magnitude tolerance check is what's actually exercised).
    """
    def fake_urlopen(req, timeout=None):
        if force_error:
            raise urllib.error.URLError("simulated network failure")
        url = req.full_url if hasattr(req, "full_url") else str(req)
        params, path = _parse_query(url)
        assert path.endswith("/query"), f"EMSCReference should only ever hit /query, got {path}"
        assert params.get("format") == "json"
        start_ms = _iso_to_ms(params["starttime"])
        end_ms = _iso_to_ms(params["endtime"])
        min_mag = float(params.get("minmagnitude", "-10"))
        matched = [e for e in events
                   if start_ms <= _iso_to_ms(e["time_iso"]) <= end_ms and e["mag"] >= min_mag]
        limit = int(params.get("limit", 20000))
        features = [
            {
                "type": "Feature",
                "id": f"unid_{i}",
                "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"], -10.0]},
                "properties": {
                    "time": e["time_iso"], "mag": e["mag"], "lat": e["lat"], "lon": e["lon"],
                    "depth": 10.0, "auth": "EMSC",
                },
            }
            for i, e in enumerate(matched[:limit])
        ]
        payload = {"type": "FeatureCollection",
                   "metadata": {"totalCount": len(matched)},
                   "features": features}
        return _FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

    return fake_urlopen


class TestEMSCReference:
    def test_feasible_when_reachable_and_cached(self, monkeypatch):
        calls = {"n": 0}

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            payload = {"type": "FeatureCollection", "metadata": {"totalCount": 0}, "features": []}
            return _FakeHTTPResponse(json.dumps(payload).encode("utf-8"))

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = EMSCReference()
        assert ref.is_feasible() is True
        assert ref.is_feasible() is True
        assert calls["n"] == 1, "is_feasible() must cache, not re-probe every call"

    def test_infeasible_on_network_error(self, monkeypatch):
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_emsc_urlopen([], force_error=True),
        )
        ref = EMSCReference()
        assert ref.is_feasible() is False

    def test_falls_back_to_null_when_infeasible(self, monkeypatch):
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_emsc_urlopen([], force_error=True),
        )
        ds = make_dataset(n=5)
        result = EMSCReference().match(ds)
        null_result = NullExternalCatalog().match(ds)
        assert result.matched.tolist() == null_result.matched.tolist()
        assert math.isnan(result.mc_ref)

    def test_finds_corroborating_event_from_emsc_shaped_json(self, monkeypatch):
        ds = make_dataset(
            n=1,
            latitude=np.array([10.0]), longitude=np.array([20.0]),
            magnitude=np.array([5.0]),
            origin_time=np.array([np.datetime64("2020-01-01T00:00:00", "ns")]),
        )
        events = [{"time_iso": "2020-01-01T00:00:00.4Z", "lat": 10.001, "lon": 20.001, "mag": 5.02}]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_emsc_urlopen(events),
        )
        result = EMSCReference().match(ds)
        assert result.matched.tolist() == [True]

    def test_no_corroboration_found(self, monkeypatch):
        ds = make_dataset(n=3)
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_emsc_urlopen([]),
        )
        result = EMSCReference().match(ds)
        assert not result.matched.any()

    def test_pagination_via_metadata_totalcount(self, monkeypatch):
        # No dedicated /count endpoint for EMSC (unlike USGS) -- pagination
        # must trigger off metadata.totalCount returned inline with /query.
        base_ms = _iso_to_ms("2020-06-01T00:00:00")
        hour_ms = 3_600_000
        events = [
            {"time_iso": str(np.datetime64(base_ms + i * hour_ms, "ms")) + "Z",
             "lat": 0.0, "lon": 0.0, "mag": 5.0}
            for i in range(6)
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_emsc_urlopen(events),
        )
        origin_times = (np.datetime64("2020-06-01T00:00:00", "ns")
                         + np.arange(6) * np.timedelta64(1, "h"))
        ds = make_dataset(
            n=6, latitude=np.zeros(6), longitude=np.zeros(6),
            magnitude=np.full(6, 5.0), origin_time=origin_times,
        )
        ref = EMSCReference(max_events_per_query=2)
        result = ref.match(ds)
        assert result.matched.tolist() == [True] * 6


# ---------------------------------------------------------------------------
# ISC fake network layer (QuakeML/BED XML)
# ---------------------------------------------------------------------------

_QUAKEML_NS = "https://quakeml.org/xmlns/bed/1.2"
_QUAKEML_ROOT_NS = "https://quakeml.org/xmlns/quakeml/1.2"


def _build_quakeml(events):
    """events: list of dict(time_iso=str, lat=float, lon=float, mag=float)."""
    event_xml = []
    for i, e in enumerate(events):
        event_xml.append(f"""
      <event publicID="quakeml:test/event/{i}">
        <origin publicID="quakeml:test/origin/{i}">
          <time><value>{e['time_iso']}</value></time>
          <latitude><value>{e['lat']}</value></latitude>
          <longitude><value>{e['lon']}</value></longitude>
          <depth><value>10000</value></depth>
        </origin>
        <magnitude publicID="quakeml:test/magnitude/{i}">
          <mag><value>{e['mag']}</value></mag>
        </magnitude>
      </event>""")
    body = "".join(event_xml)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<q:quakeml xmlns:q="{_QUAKEML_ROOT_NS}" xmlns="{_QUAKEML_NS}">
  <eventParameters publicID="quakeml:test/eventParameters">{body}
  </eventParameters>
</q:quakeml>""".encode("utf-8")


def make_fake_isc_urlopen(events, force_error: bool = False):
    def fake_urlopen(req, timeout=None):
        if force_error:
            raise urllib.error.URLError("simulated network failure")
        url = req.full_url if hasattr(req, "full_url") else str(req)
        params, path = _parse_query(url)
        assert path.endswith("/query"), f"ISCReference should only ever hit /query, got {path}"
        assert params.get("format") == "xml"
        start_ms = _iso_to_ms(params["starttime"])
        end_ms = _iso_to_ms(params["endtime"])
        min_mag = float(params.get("minmagnitude", "-10"))
        matched = [e for e in events
                   if start_ms <= _iso_to_ms(e["time_iso"].rstrip("Z")) <= end_ms
                   and e["mag"] >= min_mag]
        limit = int(params.get("limit", 20000))
        return _FakeHTTPResponse(_build_quakeml(matched[:limit]))

    return fake_urlopen


class TestISCReference:
    def test_feasible_when_reachable_and_cached(self, monkeypatch):
        calls = {"n": 0}
        tohoku_event = [{"time_iso": "2011-03-11T05:46:24.0Z", "lat": 38.3, "lon": 142.4, "mag": 9.1}]

        def fake_urlopen(req, timeout=None):
            calls["n"] += 1
            return _FakeHTTPResponse(_build_quakeml(tohoku_event))

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = ISCReference()
        assert ref.is_feasible() is True
        assert ref.is_feasible() is True
        assert calls["n"] == 1, "is_feasible() must cache, not re-probe every call"

    def test_infeasible_on_network_error(self, monkeypatch):
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_isc_urlopen([], force_error=True),
        )
        assert ISCReference().is_feasible() is False

    def test_infeasible_when_probe_window_returns_no_events(self, monkeypatch):
        # The feasibility probe window is chosen to be virtually guaranteed
        # to contain events on a REAL ISC endpoint; a fake/mocked endpoint
        # that returns nothing for it must still be treated as infeasible
        # (not "reachable but the world had no earthquakes"), matching
        # ISCReference.is_feasible()'s documented behaviour.
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_isc_urlopen([]),
        )
        assert ISCReference().is_feasible() is False

    def test_finds_corroborating_event_from_quakeml(self, monkeypatch):
        tohoku_event = [{"time_iso": "2011-03-11T05:46:24.0Z", "lat": 38.3, "lon": 142.4, "mag": 9.1}]
        ds = make_dataset(
            n=1,
            latitude=np.array([10.0]), longitude=np.array([20.0]),
            magnitude=np.array([5.0]),
            origin_time=np.array([np.datetime64("2020-01-01T00:00:00", "ns")]),
        )
        events = tohoku_event + [
            {"time_iso": "2020-01-01T00:00:00.0Z", "lat": 10.001, "lon": 20.001, "mag": 5.02}
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_isc_urlopen(events),
        )
        result = ISCReference().match(ds)
        assert result.matched.tolist() == [True]

    def test_no_corroboration_found(self, monkeypatch):
        tohoku_event = [{"time_iso": "2011-03-11T05:46:24.0Z", "lat": 38.3, "lon": 142.4, "mag": 9.1}]
        ds = make_dataset(n=3)
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_isc_urlopen(tohoku_event),
        )
        result = ISCReference().match(ds)
        assert not result.matched.any()

    def test_pagination_via_returned_count_heuristic(self, monkeypatch):
        # ISC exposes no authoritative total (see class docstring) -- the
        # pagination heuristic triggers on "returned exactly `limit`
        # events," so this must still recover all 6 events when the cap
        # is forced down to 2 per sub-query.
        tohoku_event = {"time_iso": "2011-03-11T05:46:24.0Z", "lat": 38.3, "lon": 142.4, "mag": 9.1}
        base_ms = _iso_to_ms("2020-06-01T00:00:00")
        hour_ms = 3_600_000
        events = [tohoku_event] + [
            {"time_iso": str(np.datetime64(base_ms + i * hour_ms, "ms")) + "Z",
             "lat": 0.0, "lon": 0.0, "mag": 5.0}
            for i in range(6)
        ]
        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen",
            make_fake_isc_urlopen(events),
        )
        origin_times = (np.datetime64("2020-06-01T00:00:00", "ns")
                         + np.arange(6) * np.timedelta64(1, "h"))
        ds = make_dataset(
            n=6, latitude=np.zeros(6), longitude=np.zeros(6),
            magnitude=np.full(6, 5.0), origin_time=origin_times,
        )
        ref = ISCReference(assumed_max_events_per_query=2)
        result = ref.match(ds)
        assert result.matched.tolist() == [True] * 6


# ---------------------------------------------------------------------------
# Antimeridian handling for ISC specifically -- ISC's own published
# parameter table only lists the ordinary [-180, 180] minlongitude/
# maxlongitude range with no "wraps at +/-180" extension mentioned
# (unlike USGS, live-verified during this review, and EMSC, whose own
# fdsn-wsevent.html documentation explicitly states its range is -360 to
# 360 "intelligently wrapping at +/-180"). A dateline-crossing bounding
# box must therefore never be sent to ISC as a single out-of-range box;
# `_split_lon_range` (see test_reference_data.py's own dedicated tests)
# is relied on here to always emit ordinary, valid [-180, 180] sub-boxes.
# ---------------------------------------------------------------------------

class TestISCDatelineHandling:
    def test_isc_match_never_sees_out_of_range_longitude_across_dateline(self, monkeypatch):
        tohoku_event = {"time_iso": "2011-03-11T05:46:24.0Z", "lat": 38.3, "lon": 142.4, "mag": 9.1}
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
            {"time_iso": "2020-01-01T00:00:00.0Z", "lat": -29.001, "lon": -177.501, "mag": 6.02},
            {"time_iso": "2020-01-01T01:00:00.0Z", "lat": -29.001, "lon": 179.001, "mag": 6.52},
        ]
        seen_lon_bounds = []

        def fake_urlopen(req, timeout=None):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            params, path = _parse_query(url)
            if params.get("starttime", "").startswith("2011-03"):
                # ISC's feasibility probe: a fixed 2011 Tohoku window that
                # happens to ALSO carry an explicit, already-valid
                # minlongitude=-180/maxlongitude=180 (unlike USGS/EMSC's
                # probes) -- it must be served from the Tohoku event, not
                # filtered against this test's unrelated dataset-specific
                # `events` list.
                return _FakeHTTPResponse(_build_quakeml([tohoku_event]))
            lon_min = float(params["minlongitude"])
            lon_max = float(params["maxlongitude"])
            assert -180.0 <= lon_min <= 180.0, (
                f"ISCReference must never emit an out-of-[-180,180] "
                f"minlongitude (ISC's spec has no dateline-wrap "
                f"extension): got {lon_min}"
            )
            assert -180.0 <= lon_max <= 180.0, (
                f"ISCReference must never emit an out-of-[-180,180] "
                f"maxlongitude: got {lon_max}"
            )
            seen_lon_bounds.append((lon_min, lon_max))
            start_ms = _iso_to_ms(params["starttime"])
            end_ms = _iso_to_ms(params["endtime"])
            min_mag = float(params.get("minmagnitude", "-10"))
            matched = [
                e for e in events
                if start_ms <= _iso_to_ms(e["time_iso"].rstrip("Z")) <= end_ms
                and e["mag"] >= min_mag and lon_min <= e["lon"] <= lon_max
            ]
            limit = int(params.get("limit", 20000))
            return _FakeHTTPResponse(_build_quakeml(matched[:limit]))

        monkeypatch.setattr(
            "data_certify.reference_data.urllib.request.urlopen", fake_urlopen)
        ref = ISCReference()
        result = ref.match(ds, time_tol_sec=60.0, dist_tol_km=100.0, mag_tol=0.5)

        assert len(seen_lon_bounds) == 2, (
            f"expected exactly 2 sub-box /query requests for a dateline-"
            f"crossing dataset, got {len(seen_lon_bounds)}: {seen_lon_bounds}"
        )
        assert result.matched.tolist() == [True, True]


# ---------------------------------------------------------------------------
# MultiSourceExternalCatalogReference
# ---------------------------------------------------------------------------

class _StubSource:
    """A minimal, directly-controllable ExternalCatalogReference stand-in
    for testing the combining logic in isolation from any real HTTP/XML/
    JSON transport concerns (those are covered by the classes above)."""

    def __init__(self, feasible, matched, mc_ref=4.5, mc_ref_se=0.3, mc_ref_is_default=False):
        self._feasible = feasible
        self._matched = np.asarray(matched, dtype=bool)
        self._mc_ref = mc_ref
        self._mc_ref_se = mc_ref_se
        self._mc_ref_is_default = mc_ref_is_default

    def is_feasible(self):
        return self._feasible

    def match(self, dataset, time_tol_sec=30.0, dist_tol_km=50.0, mag_tol=0.5):
        from data_certify.reference_data import MatchResult
        return MatchResult(matched=self._matched, mc_ref=self._mc_ref,
                            mc_ref_se=self._mc_ref_se, mc_ref_is_default=self._mc_ref_is_default)


class TestMultiSourceExternalCatalogReference:
    def test_requires_at_least_one_source(self):
        with pytest.raises(ValueError):
            MultiSourceExternalCatalogReference(sources=[])

    def test_is_feasible_if_any_source_feasible(self):
        combo = MultiSourceExternalCatalogReference(
            sources=[_StubSource(False, [True]), _StubSource(True, [True])])
        assert combo.is_feasible() is True

    def test_two_of_two_corroboration_required_and_met(self):
        ds = make_dataset(n=3)
        s1 = _StubSource(True, [True, True, False])
        s2 = _StubSource(True, [True, False, False])
        combo = MultiSourceExternalCatalogReference(sources=[s1, s2], min_corroborating_sources=2)
        result = combo.match(ds)
        # Only record 0 has BOTH sources reporting a match.
        assert result.matched.tolist() == [True, False, False]

    def test_one_of_two_corroboration_is_lenient_or(self):
        ds = make_dataset(n=3)
        s1 = _StubSource(True, [True, True, False])
        s2 = _StubSource(True, [True, False, False])
        combo = MultiSourceExternalCatalogReference(sources=[s1, s2], min_corroborating_sources=1)
        result = combo.match(ds)
        # Either source reporting a match is enough.
        assert result.matched.tolist() == [True, True, False]

    def test_degrades_to_null_when_insufficient_sources_reachable(self):
        # Policy requires 2 corroborating sources, but only 1 is reachable
        # -- must NOT silently fall back to requiring just 1 (see class
        # docstring: this is the exact denial-of-service scenario the
        # class is designed to resist).
        ds = make_dataset(n=3)
        s1 = _StubSource(True, [True, True, True])
        s2 = _StubSource(False, [True, True, True])  # unreachable
        combo = MultiSourceExternalCatalogReference(sources=[s1, s2], min_corroborating_sources=2)
        result = combo.match(ds)
        null_result = NullExternalCatalog().match(ds)
        assert result.matched.tolist() == null_result.matched.tolist()
        assert math.isnan(result.mc_ref)

    def test_mc_ref_combined_conservatively_as_max(self):
        ds = make_dataset(n=2)
        s1 = _StubSource(True, [True, True], mc_ref=4.0, mc_ref_se=0.1)
        s2 = _StubSource(True, [True, True], mc_ref=5.5, mc_ref_se=0.2)
        combo = MultiSourceExternalCatalogReference(sources=[s1, s2], min_corroborating_sources=1)
        result = combo.match(ds)
        assert result.mc_ref == pytest.approx(5.5)
        assert result.mc_ref_se == pytest.approx(0.2)

    def test_all_sources_unreachable_degrades_to_null(self):
        ds = make_dataset(n=3)
        combo = MultiSourceExternalCatalogReference(
            sources=[_StubSource(False, [True, True, True])], min_corroborating_sources=1)
        result = combo.match(ds)
        assert not result.matched.any()
        assert math.isnan(result.mc_ref)


# ---------------------------------------------------------------------------
# WeightedMultiSourceExternalCatalogReference
# ---------------------------------------------------------------------------

class TestWeightedMultiSourceExternalCatalogReference:
    def test_requires_at_least_one_source(self):
        with pytest.raises(ValueError):
            WeightedMultiSourceExternalCatalogReference(sources=[])

    def test_rejects_out_of_range_discount(self):
        s = _StubSource(True, [True])
        with pytest.raises(ValueError):
            WeightedMultiSourceExternalCatalogReference(sources=[s], default_mc_ref_weight_discount=0.0)
        with pytest.raises(ValueError):
            WeightedMultiSourceExternalCatalogReference(sources=[s], default_mc_ref_weight_discount=1.5)

    def test_is_feasible_if_any_source_feasible(self):
        combo = WeightedMultiSourceExternalCatalogReference(
            sources=[_StubSource(False, [True]), _StubSource(True, [True])])
        assert combo.is_feasible() is True

    def test_degrades_to_null_when_no_source_feasible(self):
        ds = make_dataset(n=3)
        combo = WeightedMultiSourceExternalCatalogReference(
            sources=[_StubSource(False, [True, True, True])])
        result = combo.match(ds)
        null_result = NullExternalCatalog().match(ds)
        assert result.matched.tolist() == null_result.matched.tolist()
        assert math.isnan(result.mc_ref)

    def test_degrades_to_null_when_no_source_has_finite_mc_ref(self):
        ds = make_dataset(n=2)
        s1 = _StubSource(True, [True, True], mc_ref=float("nan"))
        combo = WeightedMultiSourceExternalCatalogReference(sources=[s1])
        result = combo.match(ds)
        null_result = NullExternalCatalog().match(ds)
        assert result.matched.tolist() == null_result.matched.tolist()
        assert math.isnan(result.mc_ref)

    def test_non_finite_mc_ref_source_excluded_from_blend(self):
        # s1 has no reference events in scope at all (nan mc_ref) -- it
        # must contribute nothing to the weighted blend rather than being
        # assigned an arbitrary weight, so the combined result should be
        # IDENTICAL to s2 acting alone.
        ds = make_dataset(n=2)
        s1 = _StubSource(True, [True, True], mc_ref=float("nan"))
        s2 = _StubSource(True, [False, True], mc_ref=5.0)
        combo = WeightedMultiSourceExternalCatalogReference(sources=[s1, s2])
        result = combo.match(ds)
        assert result.matched == pytest.approx([0.0, 1.0])
        assert result.mc_ref == pytest.approx(5.0)

    def test_weighted_combination_matches_manual_calculation(self):
        # s1: mc_ref=4.0 (more complete) -> higher weight.
        # s2: mc_ref=8.0 (less complete) -> lower weight.
        # raw weights: 1/4.0=0.25, 1/8.0=0.125 -> normalized 2/3, 1/3.
        ds = make_dataset(n=3)
        s1 = _StubSource(True, [True, True, False], mc_ref=4.0, mc_ref_se=0.1)
        s2 = _StubSource(True, [False, True, True], mc_ref=8.0, mc_ref_se=0.2)
        combo = WeightedMultiSourceExternalCatalogReference(sources=[s1, s2])
        result = combo.match(ds)
        w1, w2 = 2.0 / 3.0, 1.0 / 3.0
        expected = [w1 * 1 + w2 * 0, w1 * 1 + w2 * 1, w1 * 0 + w2 * 1]
        assert result.matched == pytest.approx(expected, abs=1e-9)
        # Shared stratum mc_ref combined conservatively as the max (least
        # complete), same rationale/policy as MultiSourceExternalCatalogReference.
        assert result.mc_ref == pytest.approx(8.0)
        assert result.mc_ref_se == pytest.approx(0.2)

    def test_defaulted_mc_ref_source_is_discounted(self):
        # Both sources have the same numeric mc_ref, but s2's is a
        # defaulted (non-region-fitted) estimate -- it must end up with
        # LESS weight than s1's actually-fitted estimate of the same value.
        ds = make_dataset(n=2)
        s1 = _StubSource(True, [True, True], mc_ref=4.0, mc_ref_is_default=False)
        s2 = _StubSource(True, [True, False], mc_ref=4.0, mc_ref_is_default=True)
        combo = WeightedMultiSourceExternalCatalogReference(
            sources=[s1, s2], default_mc_ref_weight_discount=0.5)
        result = combo.match(ds)
        # raw weights: 1/4.0=0.25 (s1), (1/4.0)*0.5=0.125 (s2) -> normalized 2/3, 1/3.
        w1, w2 = 2.0 / 3.0, 1.0 / 3.0
        expected = [w1 * 1 + w2 * 1, w1 * 1 + w2 * 0]
        assert result.matched == pytest.approx(expected, abs=1e-9)

    def test_stronger_discount_reduces_defaulted_source_influence(self):
        # A harsher discount (0.1 vs 0.5) should pull the combined result
        # further toward s1-alone's verdict.
        ds = make_dataset(n=1)
        s1 = _StubSource(True, [True], mc_ref=4.0, mc_ref_is_default=False)
        s2 = _StubSource(True, [False], mc_ref=4.0, mc_ref_is_default=True)
        mild = WeightedMultiSourceExternalCatalogReference(
            sources=[s1, s2], default_mc_ref_weight_discount=0.5).match(ds)
        harsh = WeightedMultiSourceExternalCatalogReference(
            sources=[s1, s2], default_mc_ref_weight_discount=0.1).match(ds)
        assert harsh.matched[0] > mild.matched[0]  # closer to s1's "True" (1.0)

    def test_weights_sum_to_one_reproduces_full_agreement(self):
        # Sanity check: if every contributing source agrees on every
        # record, the combined result must be unanimous too, regardless
        # of how weights are distributed (weights always sum to 1).
        ds = make_dataset(n=4)
        s1 = _StubSource(True, [True, False, True, False], mc_ref=4.2)
        s2 = _StubSource(True, [True, False, True, False], mc_ref=6.7)
        s3 = _StubSource(True, [True, False, True, False], mc_ref=5.1, mc_ref_is_default=True)
        combo = WeightedMultiSourceExternalCatalogReference(sources=[s1, s2, s3])
        result = combo.match(ds)
        assert result.matched == pytest.approx([1.0, 0.0, 1.0, 0.0])
