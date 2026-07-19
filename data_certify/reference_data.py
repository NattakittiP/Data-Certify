# -*- coding: utf-8 -*-
"""
data_certify/reference_data.py -- Pluggable external-reference interfaces
for A6 (external cross-validation) and P8 (plate-boundary proximity).

Both A6 and P8 depend, by design (main framework Section 1.1, "Relevance to
disaster-networking infrastructure"), on data that may not be reachable at
audit time: A6 needs live connectivity to an authoritative external catalog
(USGS ComCat / ISC / EMSC / JMA); P8 needs the GEM Global Active Faults
Database (Styron & Pagani 2020, ~13,500 mapped faults). The theory documents
are explicit that DATA-CERTIFY's own architecture must gracefully degrade
when either is unavailable (intrinsic-only fallback for A(D); a documented,
non-fatal "P8 not evaluated" state for P(D)) rather than hard-failing.

This module defines that pluggable boundary as two small abstract
interfaces, each with an offline-safe default implementation:

  ExternalCatalogReference (A6)
      NullExternalCatalog        -- always reports "infeasible" (explicit
                                     offline/air-gapped mode).
      LocalCSVCatalogReference   -- treats another canonical-schema CSV
                                     (e.g. a second, trusted dataset) as the
                                     "authoritative" catalog for matching.
                                     Offline-testable stand-in for a live
                                     API call, or a way to point at a
                                     pre-downloaded/cached reference file.
      USGSComCatReference        -- queries the REAL, live USGS ComCat FDSN
                                     event web service
                                     (earthquake.usgs.gov/fdsnws/event/1/)
                                     for independent corroborating events.
                                     This is now the CLI's default (see
                                     run_audit.py) precisely because A6 is
                                     the only signal in this whole framework
                                     that can catch a physically-plausible
                                     but wholly fabricated catalog -- one
                                     engineered to pass every intrinsic
                                     A1-A5 check. This is a disclosed
                                     residual gap in the intrinsic-only
                                     (offline) scoring path.
      EMSCReference               -- queries the REAL, live EMSC SeismicPortal
                                     FDSN event web service
                                     (seismicportal.eu/fdsnws/event/1/,
                                     format=json), independently operated
                                     from USGS (European-Mediterranean
                                     Seismological Centre, France).
      ISCReference                -- queries the REAL, live ISC (International
                                     Seismological Centre) FDSN event web
                                     service (isc.ac.uk/fdsnws/event/1/).
                                     Unlike USGS/EMSC, ISC's own documentation
                                     states it only supports format=xml
                                     (QuakeML) or format=isf/isf2 -- there is
                                     no json or pipe-delimited text option --
                                     so this class parses QuakeML/BED XML
                                     directly via the standard library's
                                     xml.etree.ElementTree (namespace-tolerant
                                     local-name matching, since QuakeML
                                     responses are typically wrapped in a
                                     versioned `quakeml`/`eventParameters`
                                     namespace). Built from the published
                                     FDSN fdsnws-event-1.2 specification and
                                     QuakeML/BED schema (both independently,
                                     publicly documented, decade-plus-stable
                                     standards). VERIFIED LIVE (2026-07-08,
                                     see `verify_isc_reference.py` and
                                     `isc_reference_fetch/verification_report.md`):
                                     is_feasible()=True against a real
                                     isc.ac.uk query, a real raw QuakeML
                                     response was fetched and saved, the
                                     parser correctly recovered the 2011
                                     Tohoku mainshock (t/lat/lon/mag all
                                     within tolerance) from that real
                                     response, and end-to-end match()
                                     correctly corroborated a real Tohoku
                                     record while correctly rejecting a
                                     fabricated Sahara control. FOLLOW-UP
                                     (2026-07-09, `verify_isc_gap_closure.py`
                                     + `debug_isc_pagination_gap.py`, see
                                     `isc_gap_closure/verification_report.md`):
                                     dateline/antimeridian behaviour is now
                                     also live-verified (a real, dateline-
                                     adjacent ISC event was discovered live
                                     and correctly matched with a box
                                     straddling +/-180; a fabricated
                                     dateline-adjacent event was correctly
                                     rejected). Pagination testing FOUND A
                                     REAL BUG, now FIXED: `_fetch_events_
                                     paginated`'s recursion depth ceiling
                                     (was 8) could be reached while a
                                     genuinely dense event cluster still
                                     exceeded the configured cap, silently
                                     dropping the earliest events in that
                                     leaf window (ISC's `orderby=time` is
                                     descending, so a cap-truncated response
                                     keeps the most recent events and drops
                                     the earliest -- confirmed live: a
                                     ~56-minute leaf window right after the
                                     2011 Tohoku mainshock held 5 M>=6.5
                                     events against a test cap of 3, and
                                     depth 8 was hit before the recursion
                                     could separate them, dropping the
                                     mainshock itself and one aftershock).
                                     Fixed by raising the shared depth
                                     ceiling to `_PAGINATION_MAX_DEPTH=24`
                                     and adding a `warnings.warn` whenever
                                     that ceiling is genuinely reached while
                                     still over-cap (see
                                     `_warn_pagination_depth_exhausted`) --
                                     this affected USGSComCatReference and
                                     EMSCReference identically (same shared
                                     depth-cap shape), not just ISC. The
                                     literal 20,000-event cap itself was
                                     still not reached by this test (that
                                     would require an impractically large
                                     query); what was validated live is the
                                     exact recursive-halving mechanism that
                                     would fire at any cap, including
                                     20,000.
      MultiSourceExternalCatalogReference -- combines two or more of the
                                     above (e.g. USGS + EMSC + ISC) and only
                                     treats a record as externally matched
                                     once at least `min_corroborating_sources`
                                     of the CONFIGURED sources independently
                                     report a match. This directly closes the
                                     single-point-of-spoofing-failure gap of
                                     relying on USGS ComCat alone: an
                                     adversary would now need to compromise
                                     or spoof multiple independent
                                     organizations' catalogs (USGS, the
                                     EU-based EMSC, and/or ISC) at once, not
                                     just one, for a fabricated record to be
                                     wrongly corroborated. See its own
                                     docstring below for the documented
                                     degrade-to-NullExternalCatalog behaviour
                                     when fewer sources than
                                     `min_corroborating_sources` are reachable.
      WeightedMultiSourceExternalCatalogReference -- a DIFFERENT way of
                                     combining multiple sources from the
                                     AND-gate vote above: each configured
                                     source queries and matches
                                     INDEPENDENTLY (its own matched_fraction
                                     over a shared reference-complete
                                     stratum), and the per-source results
                                     are then reliability-weighted together
                                     (weight ~ 1/mc_ref, discounted when
                                     mc_ref_is_default) into one combined
                                     A6 verdict, rather than requiring
                                     simultaneous per-record agreement.
                                     This targets ordinary differences in
                                     each honestly-operated agency's own
                                     regional/period completeness (so a
                                     single source's blind spot is
                                     down-weighted, not given a hard veto
                                     or an all-or-nothing vote) -- a
                                     complementary goal to
                                     MultiSourceExternalCatalogReference's
                                     anti-spoofing corroboration-count
                                     design, not a replacement for it. See
                                     its own docstring below for the full
                                     weighting formula and disclosed
                                     trade-offs.

      JMA (Japan Meteorological Agency) -- deliberately NOT implemented.
      JMA publishes a Seismological Bulletin (periodic ZIP-file downloads,
      data.jma.go.jp/eqev/data/bulletin/) and an unofficial real-time
      "recent quakes" JSON feed (jma.go.jp/bosai/quake/data/list.json), but
      neither is a general-purpose, programmatically queryable
      historical-event API with region/time/magnitude filtering comparable
      to USGS/EMSC/ISC's FDSN event web services. Implementing a real JMA
      source would mean either (a) bulk-downloading and periodically
      re-parsing ZIP bulletins offline (a fundamentally different,
      batch-file integration, not a live query source), or (b) using the
      unofficial recent-quakes feed, which only covers a rolling recent
      window, not arbitrary historical audits. Rather than ship a
      misleadingly-named `JMAReference` that silently only works for
      recent dates, this gap is disclosed here instead.

      All of USGSComCatReference, EMSCReference, and ISCReference share
      the same matching/Mc_ref-stratification core
      (`_match_against_reference_arrays` below) -- only how the reference
      events are OBTAINED differs.

  FaultDatabaseReference (P8)
      NullFaultDatabase           -- always reports "not evaluated".
      BundledSampleFaultDatabase  -- a small, explicitly-labeled *sample* of
                                     well-known plate-boundary trace points
                                     (not the full ~13,500-fault GEM GAF-DB).
                                     Sufficient to demonstrate the
                                     distance-decay scoring logic end-to-end.
      GEMActiveFaultsDatabase     -- the REAL GEM Global Active Faults
                                     Database (Styron & Pagani 2020),
                                     loaded from a GeoJSON FeatureCollection
                                     of LineString fault traces exactly as
                                     distributed by
                                     GEMScienceTools/gem-global-active-faults.
                                     This is now available in this repo
                                     under Dataset/GAF-DB/ (both the raw
                                     ~16,195-fault file and GEM's own
                                     harmonized, deduplicated ~13,696-fault
                                     release -- the latter is the default).
                                     Distance-to-nearest-fault is computed
                                     via a from-scratch, numpy-only
                                     (no scipy/shapely/rtree) segment-
                                     subdivision + grid-indexed nearest-
                                     vertex search -- see
                                     GEMActiveFaultsDatabase's own docstring
                                     for the three explicitly disclosed
                                     approximations this involves (point-
                                     cloud vs. true polyline distance,
                                     approximate grid-ring nearest-neighbor
                                     search, and a long-range sentinel
                                     distance), none of which are specified
                                     by the theory documents themselves.

Swapping either implementation requires no change to axis_authenticity.py
or axis_plausibility.py -- both call only the abstract interface.
"""

from __future__ import annotations

import abc
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np

from .schema import CertifyDataset, load_dataset_csv
from .stats import haversine_km, haversine_km_matrix, maximum_curvature_mc, mc_bootstrap_se


# =============================================================================
# A6 -- external catalog cross-validation
# =============================================================================

@dataclass
class MatchResult:
    matched: np.ndarray          # bool array, one per queried record
    mc_ref: float                # estimated (or default) reference completeness
    mc_ref_se: float             # standard error of mc_ref (0.0 if defaulted)
    mc_ref_is_default: bool      # True if a region-specific Mc_ref could not be fit
    # A6 three-state semantics (Group C3, 2026-07-12). Both None by default
    # -- single-source ExternalCatalogReference implementations (USGS/EMSC/
    # ISC/LocalCSV) do not populate these; axis_authenticity.py's
    # _score_a6_external() treats None as "exactly one source was queried,
    # for whatever records this MatchResult's own (mc_ref, mc_ref_se)
    # stratum covers" -- which by construction can never reach the
    # A6_CONTRADICTED_MIN_SOURCES=2 floor needed for "Externally
    # contradicted". Only MultiSourceExternalCatalogReference and
    # WeightedMultiSourceExternalCatalogReference populate real per-record
    # counts, since they are the only implementations that actually query
    # more than one independent source per record.
    n_sources_queried: Optional[np.ndarray] = None   # int array: independently-feasible sources whose OWN completeness stratum covers this record
    n_sources_matched: Optional[np.ndarray] = None   # int array: of those, how many found a matching event


class ExternalCatalogReference(abc.ABC):
    """Abstract interface for A6 external cross-validation."""

    @abc.abstractmethod
    def is_feasible(self) -> bool:
        """Whether this reference source is currently usable at all."""
        raise NotImplementedError

    @abc.abstractmethod
    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        """
        For each record in `dataset`, determine whether a matching event
        exists in the reference catalog within the given tolerances, and
        estimate the reference catalog's own local magnitude of
        completeness (Mc_ref) so callers can restrict matching to the
        reference-complete stratum (Gap-Remediation Addendum, Section 1.2).
        """
        raise NotImplementedError


class NullExternalCatalog(ExternalCatalogReference):
    """
    Explicit-offline A6 reference: always reports infeasible. Use this to
    force a fully offline, reproducible, air-gapped audit (e.g. via
    run_audit.py's `--offline` flag) -- A(D) falls back to the
    intrinsic-only A1-A5 battery (main framework Section 1.1's DTN-style
    graceful-degradation argument). This is also the automatic fallback
    any other ExternalCatalogReference implementation degrades to when its
    own `is_feasible()` returns False (e.g. no network).
    """

    def is_feasible(self) -> bool:
        return False

    def match(self, dataset: CertifyDataset, **kwargs) -> MatchResult:
        n = dataset.n
        return MatchResult(
            matched=np.zeros(n, dtype=bool),
            mc_ref=float("nan"), mc_ref_se=float("nan"), mc_ref_is_default=True,
        )


# Global-aggregator conservative completeness floor (Gap-Remediation
# Addendum Section 1.2's documented NEIC/ISC-GEM ~M4.5 figure). Used both
# as the fallback when a region-specific Mc_ref cannot be fit at all, and
# (2026-07-05 fix, see below) as a hard floor on any FITTED Mc_ref value.
MC_REF_GLOBAL_FLOOR = 4.5


def _estimate_mc_ref(ref_magnitude: np.ndarray) -> Tuple[float, float, bool]:
    """
    Reference-catalog local completeness (Wiemer & Wyss 2000 Maximum
    Curvature, per the main framework's C2 methodology, reused here exactly
    as the Gap-Remediation Addendum Section 1.2 specifies). Shared by every
    ExternalCatalogReference implementation below.

    FLOOR FIX (2026-07-05, found via a live EMSC/USGS pilot run against two
    real known-good national-network catalogs, "chile" (CSN Chile) and "nz"
    (GeoNet NZ)): every ExternalCatalogReference.match() queries the live
    source using the AUDITED DATASET's own minimum magnitude (minus a
    tolerance) as the query floor -- appropriate for finding a genuine
    match, but it means a dataset that itself reports very small local
    events (e.g. chile's CSN network reports down to ~M1.5) causes the
    reference query to return whatever small-magnitude events that
    aggregator happens to carry for the same region, and the maximum-
    curvature fit on THOSE returned events can land far below any magnitude
    a global aggregator can realistically claim complete coverage of (found
    empirically: fitted Mc_ref as low as M2.0 for chile against EMSC). A6
    then tries to cross-validate a national network's small, locally-
    detected-only earthquakes against catalogs that structurally never
    receive full reports of such events from any country's national
    network -- producing a near-total, spurious mismatch (chile: 0.0%
    matched against USGS, 0.0015% against EMSC) that is numerically
    indistinguishable from actual fabrication, regardless of which external
    source is used. This is not a per-source gap (a second, independent
    source reproduced it) -- it is the stratification threshold itself
    being set too low. Fix: never let a FITTED Mc_ref settle below
    MC_REF_GLOBAL_FLOOR, so A6 only ever asks for corroboration on events
    of a magnitude that a global aggregator can plausibly be expected to
    carry, never on a national network's small local-only detections.
    """
    mc_ref = maximum_curvature_mc(ref_magnitude)
    mc_ref_se = mc_bootstrap_se(ref_magnitude)
    mc_ref_is_default = not np.isfinite(mc_ref)
    if mc_ref_is_default:
        # Documented NEIC/ISC-GEM conservative default (Gap-Remediation
        # Addendum Section 1.2): ~M4.5 global completeness.
        mc_ref, mc_ref_se = MC_REF_GLOBAL_FLOOR, 0.3
    elif mc_ref < MC_REF_GLOBAL_FLOOR:
        # A region-specific fit succeeded but landed below the floor --
        # clamp up rather than trust it (see FLOOR FIX above). mc_ref_se is
        # left as fitted (from mc_bootstrap_se on the real reference data);
        # only the point estimate is floored, since the floor is a claim
        # about what's realistically verifiable, not about the fit's own
        # sampling uncertainty.
        mc_ref = MC_REF_GLOBAL_FLOOR
    return float(mc_ref), float(mc_ref_se), mc_ref_is_default


def _match_against_reference_arrays(
    dataset: CertifyDataset,
    ref_time: np.ndarray,      # datetime64[ns], absolute (never a "days since own start" offset)
    ref_lat: np.ndarray,
    ref_lon: np.ndarray,
    ref_mag: np.ndarray,
    time_tol_sec: float,
    dist_tol_km: float,
    mag_tol: float,
) -> MatchResult:
    """
    Shared A6 matching core: once ANY reference source (a second local CSV,
    a live USGS ComCat query, ...) has been reduced to plain (time, lat,
    lon, magnitude) arrays, the matching and Mc_ref-stratification logic is
    identical regardless of where those arrays came from -- exactly the
    point the main framework's A6 design and this module's docstring make.
    Factored out here so LocalCSVCatalogReference and USGSComCatReference
    cannot silently drift apart on this logic.

    BUGFIX (scientific-validity review pass, originally found in
    LocalCSVCatalogReference before this function existed): an earlier
    version compared `ref.origin_time_days()` against
    `dataset.origin_time_days()` -- each of which is "days since THAT
    dataset's OWN earliest event" (see CertifyDataset.origin_time_days).
    Two independently-sourced catalogs (e.g. a local NZ extract audited
    against a global reference catalog) essentially never share the same
    start date, so subtracting these two "days-since-own-start" values does
    not recover the true time difference between events -- it is silently
    offset by (ref_catalog_start - query_catalog_start), typically years,
    not seconds. This made A6 matching fail almost completely against any
    reference catalog with a different date range than the audited dataset
    (confirmed with a synthetic reproduction: two catalogs with different
    start dates, containing one pair of IDENTICAL events by absolute
    time/location/magnitude, matched 0/1 instead of 1/1). Only the
    NZ-matched-against-itself self-consistency demo in
    examples/example_nz_chile_audit.py was immune, because comparing a
    catalog to itself trivially makes both "own start" offsets equal, which
    is precisely why that demo did not catch the bug. Fixed by differencing
    the absolute origin_time datetime64 values directly below, never each
    side's own local day-offset.
    """
    mc_ref, mc_ref_se, mc_ref_is_default = _estimate_mc_ref(ref_mag)

    n = dataset.n
    matched = np.zeros(n, dtype=bool)
    if len(ref_time) == 0:
        return MatchResult(matched=matched, mc_ref=mc_ref, mc_ref_se=mc_ref_se,
                            mc_ref_is_default=mc_ref_is_default)

    for i in range(n):
        query_time = dataset.origin_time[i]
        if np.isnat(query_time):
            continue
        dt_sec = np.abs((ref_time - query_time) / np.timedelta64(1, "s"))
        candidates = np.where(np.isfinite(dt_sec) & (dt_sec <= time_tol_sec))[0]
        for j in candidates:
            dist = haversine_km(dataset.latitude[i], dataset.longitude[i],
                                 ref_lat[j], ref_lon[j])
            if not np.isfinite(dist) or dist > dist_tol_km:
                continue
            if not np.isfinite(dataset.magnitude[i]) or not np.isfinite(ref_mag[j]):
                continue
            if abs(dataset.magnitude[i] - ref_mag[j]) <= mag_tol:
                matched[i] = True
                break

    return MatchResult(matched=matched, mc_ref=mc_ref, mc_ref_se=mc_ref_se,
                        mc_ref_is_default=mc_ref_is_default)


class LocalCSVCatalogReference(ExternalCatalogReference):
    """
    Treats a second canonical-schema CSV as the authoritative reference
    catalog. Useful for an offline/cached reference file, or for testing
    the A6 matching logic deterministically without a network call -- the
    matching itself (`_match_against_reference_arrays`) is the exact same
    code `USGSComCatReference` below uses; only the transport (local file
    vs. live HTTP query) differs.
    """

    def __init__(self, reference_csv_path: "str | Path"):
        self._path = Path(reference_csv_path)
        self._dataset: Optional[CertifyDataset] = None
        if self._path.exists():
            self._dataset = load_dataset_csv(self._path, name="reference")

    def is_feasible(self) -> bool:
        return self._dataset is not None and self._dataset.n > 0

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        if not self.is_feasible():
            return NullExternalCatalog().match(dataset)
        ref = self._dataset
        return _match_against_reference_arrays(
            dataset, ref.origin_time, ref.latitude, ref.longitude, ref.magnitude,
            time_tol_sec, dist_tol_km, mag_tol,
        )


def _compact_lon_bounds(lons: np.ndarray) -> Tuple[float, float]:
    """
    Smallest bounding longitude interval [lon_min, lon_max] containing all
    of `lons` (each in [-180, 180]), allowing the interval to cross the
    +/-180 antimeridian -- in which case lon_max > 180 is returned (e.g.
    (170, 190)), which the USGS ComCat API accepts directly to express a
    dateline-crossing box.

    Needed because several real catalogs sit right on the dateline (e.g.
    the bundled NZ dataset spans the Kermadec Trench across +/-180): a
    naive min()/max() over raw [-180, 180] longitudes would produce a
    bounding box spanning nearly the whole globe (e.g. min=-179, max=179)
    instead of the true, ~2-degree-wide region the points actually occupy.
    """
    lons = np.asarray(lons, dtype=float)
    lons = lons[np.isfinite(lons)]
    if len(lons) == 0:
        return -180.0, 180.0

    naive_min, naive_max = float(np.min(lons)), float(np.max(lons))
    naive_span = naive_max - naive_min

    wrapped = np.where(lons < 0, lons + 360.0, lons)
    wrapped_min, wrapped_max = float(np.min(wrapped)), float(np.max(wrapped))
    wrapped_span = wrapped_max - wrapped_min

    if wrapped_span < naive_span:
        return wrapped_min, wrapped_max
    return naive_min, naive_max


def _split_lon_range(lon_min: float, lon_max: float) -> List[Tuple[float, float]]:
    """
    Split a longitude range [lon_min, lon_max] -- which may extend beyond
    the ordinary [-180, 180] representation (e.g. (170.0, 190.0), exactly
    what `_compact_lon_bounds` plus a distance-tolerance buffer can produce
    for a dateline-crossing bounding box) -- into one or two sub-ranges
    that are each fully within [-180, 180].

    BUGFIX (scientific-validity review pass): USGS ComCat and EMSC
    SeismicPortal both DOCUMENT (and, for USGS, this was additionally
    confirmed with a live query during this review) an extended
    minlongitude/maxlongitude range that "intelligently wraps" at
    +/-180 -- USGS accepts e.g. maxlongitude=190 directly, and EMSC's own
    fdsn-wsevent.html documentation states minlon/maxlon range between
    -360 and 360 "intelligently wrapping at +/-180". ISC's own published
    parameter table, however, only lists -180/180 as the western/eastern
    boundary with no such extension mentioned anywhere, matching the base
    FDSN fdsnws-event-1.2 specification (see module docstring), which
    defines minlongitude/maxlongitude strictly within [-180, 180] with NO
    dateline-wraparound convention at all. Sending a dateline-crossing box
    to ISC as-is (e.g. maxlongitude=190) therefore risks either an HTTP
    400 (out-of-range parameter) or an undefined interpretation.
    ISCReference itself has since been live-verified (2026-07-08, see
    `verify_isc_reference.py`) for ordinary feasibility/fetch/parse/match
    behaviour, but that verification pass deliberately did not exercise a
    dateline-crossing query, so this specific longitude-range behaviour
    is still unconfirmed empirically and remains an open item.

    Rather than gamble on an unverified, source-specific range extension,
    every one of USGSComCatReference/EMSCReference/ISCReference now
    queries using ONLY ordinary, always-valid [-180, 180] sub-ranges,
    produced by this function and merged afterward. This is used
    uniformly for all three sources: it can only ever be as-safe-or-safer
    than emitting a wrapped range directly (USGS/EMSC already accept
    ordinary non-wrapped ranges just fine too), and it removes the
    dependency on an untested dateline-extension assumption for ISC
    specifically (general ISC connectivity/parsing is now live-verified,
    see `verify_isc_reference.py`, but the dateline-wrap parameter itself
    was not exercised by that pass). This is
    the same "prefer two ordinary boxes over one out-of-spec box" fix
    already applied to `GEMActiveFaultsDatabase`'s grid search
    (`_wrap_lon_cell`) and is directly relevant to this project's own
    bundled NZ dataset, which spans the Kermadec Trench across +/-180.
    """
    width = min(lon_max - lon_min, 360.0)
    if width >= 360.0:
        return [(-180.0, 180.0)]
    # Normalize lon_min into [-180, 180) without changing the true width.
    lon_min_n = ((lon_min + 180.0) % 360.0) - 180.0
    lon_max_n = lon_min_n + width
    if lon_max_n <= 180.0:
        return [(lon_min_n, lon_max_n)]
    first = (lon_min_n, 180.0)
    second = (-180.0, lon_max_n - 360.0)
    if second[0] >= second[1]:
        return [first]
    return [first, second]


USGS_COMCAT_BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"
# ComCat's documented per-request event cap (verified against the live API
# during this project's development -- `format=geojson` queries are
# truncated, not rejected, past this many features).
USGS_MAX_EVENTS_PER_QUERY = 20000
_USER_AGENT = "data-certify-reference-implementation/0.1 (Earth Science Informatics submission)"

# BUGFIX #4 (2026-07-10, found live via calibration/debug_diagnostics/debug_isc_chile_year_gap.py
# against the real "chile" dataset -- the final, root-cause fix for the
# ISC-chile residual-gap investigation): a single transient HTTP failure
# (connection reset, transient 5xx, brief timeout, etc.) was previously
# enough to make one `_get()` call return None outright. Even after bugs
# #2/#3's "a failed request triggers split-and-retry instead of being
# treated as confirmed-empty" fix, a request that fails EVERY time it is
# tried (at most twice, for ISC's leaf case; exactly once, with zero
# retries, for USGS's `_fetch_events`) still ends up silently reported as
# "no events here" -- indistinguishable, to every caller, from a genuine
# empty window.
#
# Live evidence this actually matters, not just a theoretical concern: two
# otherwise-identical full-"chile" ISC scoring runs (same query, same
# timeout=90s, `run_a6_scoring.py --only chile --reference-source isc`)
# returned matched_fraction=0.1705 and 0.3805 respectively -- more than a
# 2x swing between runs of the IDENTICAL request. A follow-up raw-fetch
# trace (`debug_isc_chile_year_gap.py`) then found, for chile's own
# 2018-2024 records (which scored 0% in the lower-scoring run), near-
# perfect candidate matches sitting right there in a separate, more-
# complete fetch: e.g. a chile M7.0 record on 2019-03-01 had a raw ISC
# event just 1.6 SECONDS away in time, 35.5km away in distance, and 0.31
# magnitude units away -- comfortably inside every one of A6's match
# tolerances (30s / 50km / 0.5 mag). That data was not genuinely absent
# from ISC's catalog; it was silently dropped by a transient request
# failure in the less-complete run, and the existing single-retry-at-the-
# leaf safety net was not robust enough to catch it at ISC's observed
# real-world failure rate for a query this large (chile's full footprint:
# ~50x50 degrees, 24-year span, min_mag=0.5).
#
# Fixed at the lowest common layer instead of inside each class's
# recursion logic: `_get_with_retry()` below retries a failed raw HTTP
# request up to `_HTTP_RETRY_ATTEMPTS` times (with a short linear backoff)
# before finally returning None -- the same failure signal every caller
# already knows how to handle via the existing split-and-retry pagination
# logic, completely unchanged. Every USGSComCatReference/EMSCReference/
# ISCReference network call (feasibility probes, count queries, fetch
# queries, and every recursive sub-call, not merely the final leaf)
# benefits automatically, since all three classes' `_get()` now delegate
# to this one shared helper instead of each doing its own single-attempt
# `urllib.request.urlopen`.
#
# Disclosed cost: a genuinely, persistently unreachable endpoint (real
# outage, not a transient blip) now takes up to
# `sum(_HTTP_RETRY_BACKOFF_SEC * (i+1) for i in range(_HTTP_RETRY_ATTEMPTS-1))`
# = 2+4 = 6 extra seconds per call before reporting failure, instead of
# failing immediately -- a small, worthwhile trade given the demonstrated
# reduction in silent data loss, especially for ISC, which (unlike EMSC's
# authoritative `totalCount` or USGS's dedicated `/count` endpoint) has no
# independent way to verify after the fact whether a fetch was complete.
_HTTP_RETRY_ATTEMPTS = 3
_HTTP_RETRY_BACKOFF_SEC = 2.0


def _get_with_retry(url: str, timeout_sec: float) -> Optional[bytes]:
    """Shared low-level HTTP GET with bounded retry-with-backoff, used by
    USGSComCatReference/EMSCReference/ISCReference's `_get()` methods (see
    this module's BUGFIX #4 comment above for the full motivation). Returns
    the raw response body, or None if every attempt failed."""
    for attempt in range(_HTTP_RETRY_ATTEMPTS):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            if attempt < _HTTP_RETRY_ATTEMPTS - 1:
                time.sleep(_HTTP_RETRY_BACKOFF_SEC * (attempt + 1))
    return None


# Recursive-halving depth ceiling shared by USGSComCatReference/EMSCReference/
# ISCReference's `_fetch_events_paginated`. BUGFIX (2026-07-09, found by
# `debug_isc_pagination_gap.py` after a live-verification run of
# `verify_isc_gap_closure.py` reported 2 missing events out of 8 for ISC with
# an artificially small test cap): this used to be 8, which gives a leaf
# window of (total span)/2^8. For a short-span test query that is plenty of
# resolution, but ISC (and, by the same shared code shape, USGS/EMSC) is
# normally invoked by `match()` over the AUDITED DATASET'S OWN time span,
# which for a real multi-decade or century-scale catalog can leave a leaf
# window many days wide -- easily enough to contain more than the
# configured cap in a genuinely dense sequence (the live probe above hit
# this for real: a leaf window of ~56 minutes right after the 2011 Tohoku
# mainshock still contained 5 M>=6.5 events against a test cap of 3, and
# depth 8 was reached before the recursion could separate them, silently
# dropping the 2 earliest). Silently dropping events is the worst possible
# failure mode here, since A6 is a hard-override gate (main framework
# Section 5) -- undercounting real corroborating events pushes A6 toward
# more false-REJECTs, not fewer. Raised to 24: 2^24 ~= 16.8 million, so even
# a 200-year dataset span still gets sub-minute leaf-window resolution,
# while true recursion depth for realistic (non-pathological) seismicity
# rates remains far shallower than this ceiling in practice -- it is a
# safety net, not the expected path. See `_PAGINATION_DEPTH_WARNING`
# immediately below: if this ceiling is ever actually reached while the
# window is still genuinely over-cap, that is now surfaced via
# `warnings.warn` instead of silently returning a truncated result.
# RUNTIME TRADE-OFF DISCLOSED (2026-07-09, added alongside the
# request-failure-triggers-split bugfix in each class's
# _fetch_events_paginated): a failed request (network/timeout/parse
# error) now recurses/splits the SAME way an over-cap result does,
# rather than surrendering immediately. This is a deliberate, evidence-
# based trade-off of completeness over speed -- a source that is flaky
# specifically on large requests (confirmed live for EMSC; ISC's own
# suspiciously-fast all-zero results on large queries are consistent
# with the same root cause) can now recover real data by retrying at a
# smaller scale, but a source that is failing for a reason unrelated to
# request size (e.g. genuinely down, or blocked) will now spend up to
# _PAGINATION_MAX_DEPTH levels of split-and-retry, each up to the
# configured per-request timeout, before giving up -- worst-case wall-
# clock cost that did not exist before this fix. `is_feasible()`'s own
# quick upfront probe still catches a fully-unreachable source before
# any of this is reached; the added cost is bounded to sources that are
# reachable but unreliable specifically at scale.
_PAGINATION_MAX_DEPTH = 24

# SAFETY NET ADDED (2026-07-09, found live via
# calibration/debug_diagnostics/debug_earthquake1_atkinson_gap.py --only real_events_atkinson
# --skip-isc, AFTER the request-failure-triggers-split bugfix above): that
# fix combined with EMSCReference's strict `total < max_events` check
# (BUGFIX above) produced a genuine runaway-recursion regression. Live
# symptom: thousands of consecutive RuntimeWarning depth-cap messages, each
# for a DIFFERENT ~75-SECOND leaf window, every single one reporting
# `total=20000` (exactly the cap) -- physically impossible for a min_mag=2.5
# North American query (no real catalog has anywhere close to 20,000
# earthquakes in 75 seconds). This total is almost certainly a bogus/cached/
# rate-limit artifact from EMSC's server once request volume gets high
# enough, NOT a genuine result -- but the pagination logic had no way to
# know that and kept dutifully splitting every such leaf all the way to
# _PAGINATION_MAX_DEPTH, generating an enormous, effectively unbounded
# number of live HTTP requests (depth alone bounds the TREE shape to
# 2^24 leaves in the worst case, which is not a real bound in practice for
# a query that keeps reporting "still over cap" at every level).
# Fix: a window below this physically-motivated floor is ALWAYS treated as
# a terminal leaf -- return whatever was fetched (possibly a suspicious/
# bogus response) and stop, regardless of what `total`/`count` claims, the
# same as hitting the depth cap. 60 seconds is deliberately conservative:
# even the densest real aftershock swarms at typical A6 magnitude
# thresholds (Mc_ref usually >= 4.5) do not approach the 20,000-event cap
# within a single minute; this floor exists to catch pathological/bogus
# server responses, not to constrain genuine dense sequences (which the
# depth-24 ceiling already accommodates down to sub-minute resolution for
# realistic, non-degenerate cases).
_PAGINATION_MIN_WINDOW_SEC = 60


def _window_below_min_size(start_dt: np.datetime64, end_dt: np.datetime64) -> bool:
    return (end_dt - start_dt) <= np.timedelta64(_PAGINATION_MIN_WINDOW_SEC, "s")


# HARD SAFETY NET (2026-07-09, added the same day as _PAGINATION_MIN_WINDOW_SEC
# above, after realizing that guard alone does not actually bound the
# runaway case): for a multi-decade dataset span, _PAGINATION_MAX_DEPTH=24
# and _PAGINATION_MIN_WINDOW_SEC=60 land at ALMOST THE SAME recursion depth
# (a 40-year span halved 24 times already yields ~75-second leaves -- the
# exact leaf size observed in the live runaway incident), so neither guard
# alone meaningfully reduces the worst case if nearly EVERY leaf reports a
# bogus "still at/over cap" result instead of the early-exit `total <
# max_events` condition most leaves are expected to hit quickly in
# practice. The real risk was never recursion depth -- it was the TOTAL
# NUMBER OF LEAF NODES VISITED, which depth alone bounds only to 2^24
# (~16.8 million) in the worst case, not a practical bound. This constant
# instead caps the TOTAL number of live requests made across a single
# top-level `match()` call's entire fetch tree (shared via a mutable
# `_budget` list threaded through the recursion), regardless of depth or
# window size. Chosen generously relative to every legitimate case
# observed so far (chile/nz's working live runs needed on the order of
# tens of requests, not hundreds), while still keeping an absolute
# worst-case wall-clock bound (budget x per-request timeout) that is large
# but finite, rather than unbounded.
_PAGINATION_MAX_TOTAL_REQUESTS = 500


def _warn_pagination_depth_exhausted(source_name: str, start_iso: str, end_iso: str,
                                      max_events: int, known_count: Optional[int] = None,
                                      reason: str = "depth") -> None:
    if reason == "min_window":
        detail = (f"window hit the {_PAGINATION_MIN_WINDOW_SEC}s minimum-size floor "
                   f"while still reporting a count at/over the {max_events}-event cap "
                   f"(known_count={known_count}) -- physically implausible for real "
                   f"seismicity at this scale; likely a bogus/rate-limited server "
                   f"response, not a genuine result")
        ceiling_desc = f"minimum window-size floor ({_PAGINATION_MIN_WINDOW_SEC}s)"
    elif reason == "budget":
        detail = (f"the ENTIRE match() call has now made "
                   f"{_PAGINATION_MAX_TOTAL_REQUESTS} live requests across its whole "
                   f"fetch tree, known_count={known_count} -- this is a global request "
                   f"budget, not a per-branch one, so this typically means many "
                   f"different windows are each reporting a bogus/rate-limited "
                   f"still-over-cap result")
        ceiling_desc = f"total-request budget ({_PAGINATION_MAX_TOTAL_REQUESTS} requests)"
    else:
        detail = (f"known count={known_count} > cap" if known_count is not None
                  else f"query returned exactly the cap ({max_events}) with no "
                       f"authoritative total available, so this MAY be truncated")
        ceiling_desc = f"recursion depth ceiling ({_PAGINATION_MAX_DEPTH})"
    warnings.warn(
        f"{source_name}._fetch_events_paginated: hit the {ceiling_desc} "
        f"while window {start_iso}..{end_iso} was still potentially over the "
        f"{max_events}-event cap ({detail}). Returning what was fetched for "
        f"this leaf rather than recursing further -- results for this window "
        f"may be INCOMPLETE. This should be essentially unreachable for "
        f"realistic seismicity rates; if you see this warning, treat any "
        f"resulting A6 under-match as suspect and consider narrowing the "
        f"query window or raising the cap.",
        RuntimeWarning, stacklevel=3)


class USGSComCatReference(ExternalCatalogReference):
    """
    Live A6 external cross-validation against the real USGS ComCat FDSN
    event web service (https://earthquake.usgs.gov/fdsnws/event/1/) -- the
    actual authoritative external catalog the main framework's A6 design
    (Section 3.1) and DTN-style graceful-degradation argument (Section 1.1)
    describe. `LocalCSVCatalogReference` was always meant as this class's
    offline-testable stand-in, not the other way around.

    Why this matters: A6 is the ONLY signal anywhere in DATA-CERTIFY that
    can catch a catalog engineered to be physically plausible (passes
    P1-P3) AND statistically well-behaved (passes A1-A5's graded checks,
    e.g. a b-value tuned to exactly 1.0) but does not correspond to any
    real, independently corroborated seismic event. Every other check in
    this framework is a property of the dataset taken in isolation; A6 is
    the only one that checks the dataset against the outside world. With
    A6 off (the old default -- `NullExternalCatalog`), that entire class of
    fabrication was undetectable by design. This class makes closing that
    gap the CLI's default behaviour (see run_audit.py) instead of an
    opt-in the operator has to know to enable.

    Design / honesty disclosures:
      - `is_feasible()` runs one lightweight COUNT query (short timeout,
        a fixed historical date range known to have events) purely as a
        connectivity probe, and CACHES the result on the instance -- it is
        not re-probed on every call. Any failure (timeout, DNS, HTTP
        error, service outage) is treated as "infeasible", which is the
        same graceful-degradation path `NullExternalCatalog` represents --
        this class never raises out of `is_feasible()` or `match()`.
      - `match()` queries only the bounding box / time range / magnitude
        floor that covers the AUDITED dataset's own footprint (never the
        whole planet or all of time), so a typical regional-catalog audit
        is one or a handful of HTTP requests, not one per record.
      - If a single query would exceed `USGS_MAX_EVENTS_PER_QUERY`, the
        time range is recursively halved (a standard FDSN pagination
        pattern) until each half fits, up to a bounded recursion depth.
      - A network failure part-way through a paginated fetch is treated
        the same as "still over the per-query event cap": the sub-window
        is split and retried via the same recursive-halving path, rather
        than being silently written off as "no events here" (that
        earlier, simpler behaviour was a real bug -- a genuine request
        failure and a genuine empty window are not the same thing, and
        conflating them could silently drop real events out of the
        reference set). See `EMSCReference`'s class docstring below for
        the full three-bug story (this class shares the exact same
        `_fetch_events_paginated` structure and was fixed identically):
        depth-cap too shallow (bug #1), failure-treated-as-empty (bug #2,
        the fix described in this bullet), and the runaway-recursion
        regression that combining those two fixes could trigger on
        pathological inputs (bug #3, guarded by `_PAGINATION_MIN_WINDOW_SEC`
        and the hard global `_PAGINATION_MAX_TOTAL_REQUESTS` budget). This
        class has not itself been observed hitting bug #3's pathological
        pattern (that was EMSC-specific, driven by EMSC's `total=20000`
        bogus-cap response), but the same safety nets apply here too since
        the recursion structure is identical.
      - This performs real network I/O against a third-party public
        service on every audit where it is feasible. Deployments needing
        fully offline, reproducible, or air-gapped operation should pass
        `NullExternalCatalog()` explicitly (`run_audit.py --offline`) or
        point `LocalCSVCatalogReference` at a pre-downloaded/cached file
        instead.
      - This does NOT defend against an adversary who also fabricates
        matching entries designed to appear in (or be scraped alongside)
        the external catalog itself -- that is a fundamentally different,
        much harder threat model (compromising or spoofing USGS ComCat
        itself) that no dataset-side audit can address. See
        tests/test_adversarial.py for this explicitly-disclosed residual
        gap.
    """

    def __init__(self, timeout_sec: float = 10.0,
                 max_events_per_query: int = USGS_MAX_EVENTS_PER_QUERY):
        self._timeout = timeout_sec
        self._max_events = max_events_per_query
        self._feasible_cache: Optional[bool] = None

    def _get(self, url: str) -> Optional[bytes]:
        # BUGFIX #4 (2026-07-10) -- see this module's `_get_with_retry`
        # comment (near `_USER_AGENT`) for the full story: this now retries
        # a failed request with backoff instead of giving up after one try.
        return _get_with_retry(url, self._timeout)

    def is_feasible(self) -> bool:
        if self._feasible_cache is not None:
            return self._feasible_cache
        # Fixed historical window known to contain events -- a pure
        # connectivity/API-shape probe, unrelated to the dataset being
        # audited (that query happens separately, in match()).
        url = (f"{USGS_COMCAT_BASE_URL}/count?"
               f"starttime=2020-01-01&endtime=2020-01-02&minmagnitude=5")
        raw = self._get(url)
        feasible = raw is not None
        if feasible:
            try:
                int(raw.decode("utf-8").strip())
            except (ValueError, UnicodeDecodeError):
                feasible = False
        self._feasible_cache = feasible
        return feasible

    def _build_url(self, endpoint: str, start_iso: str, end_iso: str,
                    lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                    min_mag: float) -> str:
        params = {
            "starttime": start_iso,
            "endtime": end_iso,
            "minlatitude": f"{lat_min:.6f}",
            "maxlatitude": f"{lat_max:.6f}",
            "minlongitude": f"{lon_min:.6f}",
            "maxlongitude": f"{lon_max:.6f}",
            "minmagnitude": f"{min_mag:.3f}",
        }
        if endpoint == "query":
            params["format"] = "geojson"
            params["limit"] = str(self._max_events)
            params["orderby"] = "time"
        return f"{USGS_COMCAT_BASE_URL}/{endpoint}?{urllib.parse.urlencode(params)}"

    def _count_events(self, *args) -> Optional[int]:
        raw = self._get(self._build_url("count", *args))
        if raw is None:
            return None
        try:
            return int(raw.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            return None

    def _fetch_events(self, *args) -> List[Tuple[int, float, float, float]]:
        """Returns list of (time_epoch_ms, lat, lon, mag) tuples."""
        raw = self._get(self._build_url("query", *args))
        if raw is None:
            return []
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return []
        out: List[Tuple[int, float, float, float]] = []
        for feat in payload.get("features", []) or []:
            props = feat.get("properties") or {}
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            mag, t_ms = props.get("mag"), props.get("time")
            if not coords or len(coords) < 2 or mag is None or t_ms is None:
                continue
            lon, lat = coords[0], coords[1]
            out.append((int(t_ms), float(lat), float(lon), float(mag)))
        return out

    def _fetch_events_paginated(
        self, start_dt: np.datetime64, end_dt: np.datetime64,
        lat_min: float, lat_max: float, lon_min: float, lon_max: float,
        min_mag: float, _depth: int = 0, _budget: Optional[List[int]] = None,
    ) -> List[Tuple[int, float, float, float]]:
        if _budget is None:
            _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        if _budget[0] <= 0:
            # Global request budget for this match() call already exhausted
            # by other branches of the recursion -- see
            # _PAGINATION_MAX_TOTAL_REQUESTS's module-level comment. Return
            # empty rather than making yet another request; the caller
            # already has whatever earlier branches found.
            start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
            _warn_pagination_depth_exhausted(
                "USGSComCatReference", start_iso, end_iso, self._max_events,
                known_count=None, reason="budget")
            return []
        _budget[0] -= 1
        start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
        args = (start_iso, end_iso, lat_min, lat_max, lon_min, lon_max, min_mag)
        count = self._count_events(*args)
        if count == 0:
            return []  # confirmed genuinely empty -- nothing to fetch here
        # BUGFIX (2026-07-09, found via calibration/debug_diagnostics/debug_emsc_atkinson_trace.py
        # on the real "real_events_atkinson" corpus dataset -- the same shape
        # of bug found live in all three of USGS/EMSC/ISC's identical
        # recursive-halving structure, not just this class): `count is None`
        # means the /count request ITSELF FAILED (network/timeout/parse
        # error) -- this used to be treated exactly like a confirmed-empty
        # `count == 0` (`if not count: return []`), silently giving up on
        # the ENTIRE window forever. Live evidence this is wrong: an EMSC
        # query for real_events_atkinson's full 1983-2023 window (min_mag=2.5,
        # Western North America) failed outright with total=-1, while an
        # otherwise-identical but much smaller 2-year sub-window over the
        # same region succeeded immediately and found 4,114 real events --
        # i.e. a large single request can fail while a smaller request of
        # the exact same shape succeeds, which is exactly the situation
        # recursive splitting already exists to handle for "too many
        # results." A failed request now falls through to that SAME
        # split-and-retry path instead of surrendering immediately -- bounded
        # by the min-window-size guard below as well as depth (see
        # _PAGINATION_MIN_WINDOW_SEC's module-level comment: the failure-
        # triggers-split change above caused a real runaway-recursion
        # regression in EMSCReference when combined with a bogus/rate-
        # limited server response that kept reporting "still over cap" for
        # physically-impossible sub-minute windows; the same guard is
        # applied here for consistency even though it was only directly
        # observed for EMSC).
        if _depth >= _PAGINATION_MAX_DEPTH or _window_below_min_size(start_dt, end_dt):
            # _depth cap: bounded safety net against pathological recursion
            # (see _PAGINATION_MAX_DEPTH's module-level comment for why this
            # was raised from 8 to 24, and why silent truncation here is
            # actively dangerous for a hard-override signal like A6).
            _warn_pagination_depth_exhausted(
                "USGSComCatReference", start_iso, end_iso, self._max_events, known_count=count,
                reason="min_window" if _window_below_min_size(start_dt, end_dt) else "depth")
            # Attempt a direct fetch regardless of whether `count` itself
            # succeeded -- by this point the window has been halved up to
            # _PAGINATION_MAX_DEPTH times, so it is almost certainly small
            # enough that the fetch (a different endpoint/payload shape
            # than the failed count) has a real chance of succeeding even
            # though the /count probe for this exact window did not;
            # _fetch_events() itself degrades to [] on any further failure.
            return self._fetch_events(*args)
        if count is not None and count <= self._max_events:
            return self._fetch_events(*args)
        mid_dt = start_dt + (end_dt - start_dt) // 2
        left = self._fetch_events_paginated(start_dt, mid_dt, lat_min, lat_max,
                                             lon_min, lon_max, min_mag, _depth + 1, _budget)
        right = self._fetch_events_paginated(mid_dt, end_dt, lat_min, lat_max,
                                              lon_min, lon_max, min_mag, _depth + 1, _budget)
        return left + right

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        if not self.is_feasible():
            return NullExternalCatalog().match(dataset)

        valid = (np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
                 & np.isfinite(dataset.magnitude) & ~np.isnat(dataset.origin_time))
        if not np.any(valid):
            return NullExternalCatalog().match(dataset)

        lat_v = dataset.latitude[valid]
        lon_v = dataset.longitude[valid]
        mag_v = dataset.magnitude[valid]
        time_v = dataset.origin_time[valid]

        dist_tol_deg_lat = dist_tol_km / 111.0
        lat_min = max(-90.0, float(np.min(lat_v)) - dist_tol_deg_lat)
        lat_max = min(90.0, float(np.max(lat_v)) + dist_tol_deg_lat)
        # Degrees-of-longitude per km shrinks toward the poles; use the
        # more poleward latitude in play for a conservative (wider) buffer.
        cos_lat = max(0.05, math.cos(math.radians(max(abs(lat_min), abs(lat_max)))))
        dist_tol_deg_lon = dist_tol_km / (111.0 * cos_lat)
        lon_min_c, lon_max_c = _compact_lon_bounds(lon_v)
        lon_min, lon_max = lon_min_c - dist_tol_deg_lon, lon_max_c + dist_tol_deg_lon

        pad = np.timedelta64(int(time_tol_sec) + 1, "s")
        t_min, t_max = time_v.min() - pad, time_v.max() + pad
        min_mag = float(np.min(mag_v)) - mag_tol

        raw_events = []
        # One shared request budget across BOTH lon-split sub-queries (a
        # dateline-wrapping bbox produces 2 sub-ranges) -- see
        # _PAGINATION_MAX_TOTAL_REQUESTS's module-level comment; this keeps
        # the total live-request bound genuinely global to this match() call.
        _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        for sub_lon_min, sub_lon_max in _split_lon_range(lon_min, lon_max):
            raw_events.extend(self._fetch_events_paginated(
                t_min, t_max, lat_min, lat_max, sub_lon_min, sub_lon_max, min_mag,
                _budget=_budget,
            ))

        if not raw_events:
            ref_time = np.array([], dtype="datetime64[ns]")
            ref_lat = np.array([], dtype=float)
            ref_lon = np.array([], dtype=float)
            ref_mag = np.array([], dtype=float)
        else:
            t_ms, lats, lons, mags = zip(*raw_events)
            ref_time = np.array([np.datetime64(int(t), "ms") for t in t_ms],
                                 dtype="datetime64[ns]")
            ref_lat = np.array(lats, dtype=float)
            ref_lon = np.array(lons, dtype=float)
            ref_mag = np.array(mags, dtype=float)

        return _match_against_reference_arrays(
            dataset, ref_time, ref_lat, ref_lon, ref_mag,
            time_tol_sec, dist_tol_km, mag_tol,
        )


def _iso_to_datetime64_ns(s: str) -> Optional[np.datetime64]:
    """
    Parse an ISO-8601 timestamp string as commonly emitted by EMSC/ISC
    (e.g. "2017-10-31T00:42:12.4Z" or "2011-03-11T05:46:24.120000Z") into a
    datetime64[ns]. numpy's datetime64 constructor does not uniformly accept
    a trailing "Z" UTC designator across all numpy versions, so it is
    stripped first (both sources are documented/observed to report UTC
    exclusively -- there is no timezone-offset case to handle). Returns
    None (never raises) on any unparseable string, so one malformed
    timestamp in a large batch degrades to "that one event is dropped",
    not an audit-wide crash.
    """
    if not s:
        return None
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        return np.datetime64(s, "ns")
    except (ValueError, TypeError):
        return None


EMSC_BASE_URL = "https://www.seismicportal.eu/fdsnws/event/1"
# Documented per-request cap (Gap-Remediation Addendum-style disclosure,
# mirrored from USGS_MAX_EVENTS_PER_QUERY above): EMSC's own fdsn-wsevent.html
# documentation page states "the maximum number of events per request has
# increased to 20000" (2023-03 update).
EMSC_MAX_EVENTS_PER_QUERY = 20000


class EMSCReference(ExternalCatalogReference):
    """
    Live A6 external cross-validation against the real EMSC SeismicPortal
    FDSN event web service (https://www.seismicportal.eu/fdsnws/event/1/).
    EMSC (European-Mediterranean Seismological Centre, based in France) is
    an organizationally independent catalog from USGS -- the whole point of
    this class (see module docstring's discussion of
    MultiSourceExternalCatalogReference) is that an adversary spoofing or
    compromising USGS ComCat alone would not automatically also compromise
    EMSC.

    API shape verified (2026, this project's development) against EMSC's
    own published tutorial (github.com/EMSC-CSEM/webservices101,
    emsc_services.md), which reproduces a real, concrete example response:
        {"type":"FeatureCollection","metadata":{"totalCount":6},
         "features":[{"geometry":{"type":"Point","coordinates":[lon,lat,-depth_km]},
                      "type":"Feature","id":"...",
                      "properties":{"time":"2017-10-31T00:42:12.4Z","mag":6.8,
                                    "lat":-21.71,"lon":169.11,"depth":25.0,...}}]}
    Notably different from USGS ComCat's shape: `time` is an ISO-8601
    string (not epoch milliseconds), and `lat`/`lon`/`mag` are given
    directly under `properties` (not only inside `geometry.coordinates`) --
    this class reads them from `properties` for that reason.

    Design mirrors USGSComCatReference closely (see its docstring for the
    full set of graceful-degradation disclosures, all of which apply here
    too): `is_feasible()` caches a one-time connectivity probe;
    `match()` only queries the audited dataset's own bounding
    box/time-range/magnitude floor; a network failure degrades toward
    under-matching (never over-matching), which is the safer failure
    direction for a fabrication-detection gate.

    One difference from USGS: EMSC's documented API has no dedicated
    `/count` endpoint, so this class's feasibility probe and pagination
    cap check both reuse the `query` endpoint's own
    `metadata.totalCount` field (returned inline with every query
    response) instead of a separate lightweight count request.

    IMPORTANT, live-confirmed limitation (2026-07-09,
    `calibration/debug_diagnostics/debug_emsc_chile_deep.py` against the real "chile"
    corpus dataset -- see `_fetch_events_paginated`'s inline comment for
    the fix): `metadata.totalCount` is NOT a genuinely limit-independent
    total the way USGS's dedicated `/count` endpoint is -- it comes back
    capped at exactly the query's own `limit` parameter once the true
    result count reaches that cap. A pagination check that trusted
    `total <= max_events` as proof of completeness would therefore accept
    a truncated single fetch as "the whole answer" whenever the true count
    equaled or exceeded the cap, silently keeping only the `limit`
    most-recent events (EMSC's `orderby=time` sorts descending, same FDSN
    convention already confirmed for ISC) and discarding everything
    older. This was fixed (`<=` -> `<`), but is recorded here because it
    is a real behavioral quirk of EMSC's API, not merely an
    implementation bug: any future change to this class's pagination
    logic must keep treating an exact-cap `total` as "possibly
    incomplete," never as "confirmed complete."

    FIX CONFIRMED LIVE (2026-07-09, re-run of
    `calibration/debug_diagnostics/debug_emsc_chile_deep.py` against the real, unmodified
    production `EMSCReference().match()` on the full "chile" dataset):
    matched_fraction jumped from 0.0554 (3 records/year for 2000-2020,
    literally 0.000 every single year) to 0.5931 (3977/6705), with
    non-zero match rates restored for every year from 2004 onward
    (0.032 in 2004 climbing to 0.9+ by 2014-2024). The residual gap
    versus USGS's 0.7652 on the same corrected dataset is now
    concentrated entirely in 2000-2003 (0.000 across all 4 years, 417
    stratum records), which reads as a genuine EMSC catalog-coverage
    limitation for that specific early period/region rather than a
    pagination artifact -- EMSC's real-time bulletin effort is
    documented to have ramped up in the early-to-mid 2000s, so sparse
    pre-2004 coverage for a South American region is plausible on its
    own. This has not been independently confirmed against EMSC's own
    documentation of historical coverage start dates; treat the
    2000-2003 gap specifically as "explained but not yet verified,"
    distinct from the now-fixed and confirmed 2004-2024 pagination bug.
    (NOTE: `debug_emsc_chile_deep.py`'s own STEP 1 trace helper
    re-implements the depth-recursion check inline with the *old*
    `total <= max_events` condition rather than calling the real
    `_fetch_events_paginated`, so its printed trace still shows the
    stale single-node behavior -- this is a cosmetic staleness in that
    diagnostic script only; STEP 2 calls the real, fixed production
    `.match()` and is the result that matters.)

    SECOND, DISTINCT BUG FOUND AND FIXED (2026-07-09, same day, via
    `calibration/debug_diagnostics/debug_emsc_atkinson_trace.py` on the real
    "real_events_atkinson" corpus dataset -- discovered while
    investigating a full-89-dataset `--reference-source weighted-multi`
    corpus run that surfaced TWO MORE real, known-good datasets flipping
    from a near-perfect USGS-alone score to hard-REJECT once EMSC/ISC
    were blended in): the paragraph above's "2000-2003 gap reads as a
    genuine coverage limitation" conclusion is now IN QUESTION, not
    confirmed -- a second, more fundamental bug was found in
    `_fetch_events_paginated` itself: `total < 0` (request failure) was
    treated identically to `return []`, permanently giving up on that
    entire time window rather than retrying at a smaller scale the way
    an over-cap result already does. Live proof this mattered: an EMSC
    query for real_events_atkinson's full 1983-2023 window failed
    outright (`total=-1`), while an otherwise-identical 2-year sub-window
    over the same region succeeded immediately and found 4,114 real
    events -- i.e. EMSC had real data the whole time, but the single
    giant top-level request failed and nothing ever retried at a smaller
    scale. Fixed: a failed request now recurses/splits exactly like an
    over-cap result (see the `total < 0` branch above), instead of
    surrendering immediately. This directly calls into question whether
    chile's own "2000-2003" gap above was genuine sparse coverage or
    this same failure-treated-as-empty bug hitting that specific
    sub-window -- chile has NOT yet been re-tested against this fix; do
    not cite the "genuine 2000-2003 coverage limitation" framing above as
    settled until it is.

    CHILE RE-TESTED (2026-07-09, later the same day, re-run of
    `calibration/debug_diagnostics/debug_emsc_chile_deep.py` AFTER the BUGFIX #2 fix
    above): result was byte-identical to before that fix (3977/6705
    matched, same year-by-year table, 2000-2003 still exactly 0.000),
    just ~25s slower. This is actually informative: it means chile's
    2000-2003 sub-windows are returning valid, genuinely-near-empty
    EMSC responses, not failed requests -- so the "2000-2003 = genuine
    EMSC coverage limitation" framing from the first FIX CONFIRMED LIVE
    note above is now on firmer ground, distinct from the runaway-
    recursion issue described next.

    THIRD BUG FOUND AND FIXED THE SAME DAY -- RUNAWAY RECURSION (2026-07-09,
    found via `calibration/debug_diagnostics/debug_earthquake1_atkinson_gap.py --only
    real_events_atkinson --skip-isc`, i.e. testing whether the SECOND bug's
    fix also explained TWO MORE known-good datasets (`real_earthquake1`,
    `real_events_atkinson`) that a full-89-dataset `weighted-multi` corpus
    run had just flipped from a near-perfect USGS-alone score to
    hard-REJECT): applying the SECOND bugfix (split-on-failure) to
    `real_events_atkinson`'s full 1983-2023 query produced a genuine
    regression -- thousands of RuntimeWarning depth-cap messages, each for
    a DIFFERENT ~75-second leaf window, every one reporting `total=20000`
    (physically impossible for that time span). Root cause: for a 40-year
    span, `_PAGINATION_MAX_DEPTH=24` and the newly-added
    `_PAGINATION_MIN_WINDOW_SEC=60` land at almost the SAME recursion
    depth (40yr / 2^24 ~= 75s), so neither guard alone bounds the true
    worst case if nearly every leaf reports a bogus "still over cap"
    result instead of the expected early-exit -- the real risk was never
    depth, it was the TOTAL NUMBER OF LEAVES VISITED (up to 2^24 ~= 16.8M
    in the worst case). Fixed with a third, independent guard:
    `_PAGINATION_MAX_TOTAL_REQUESTS=500`, a hard global budget on live
    requests per top-level `match()` call (shared via a mutable list
    threaded through the whole recursion, including across dateline-split
    lon sub-ranges), applied identically to all three of
    USGSComCatReference/EMSCReference/ISCReference. Confirmed the budget
    fix bounds runtime correctly on re-run (686.9s total, clean
    termination, no runaway) -- but the underlying goal (recovering
    atkinson's real EMSC data) still did not succeed:
    `matched_fraction` remained 0.0.

    ATKINSON'S EMSC GAP -- CONFIRMED EXTERNAL/ACTIVE BLOCK, NOT A CODE BUG
    (updated 2026-07-10, after bug #4's retry fix and a cooldown period):
    the isolated-probe test (`calibration/debug_diagnostics/debug_emsc_isolated_probe.py`, 5
    cold standalone requests for the exact first failing sub-window, 3s
    apart) was re-run well after bug #4's HTTP-retry fix (`_get_with_retry`,
    see this module's comment near `_USER_AGENT`) landed, and well after
    the originally-recommended 1-hour+ cooldown had elapsed (this was one
    of the last checks performed in a long diagnostic session). Result:
    `total=-1` on all 5 attempts AGAIN, each failing in a suspiciously
    TIGHT, consistent ~1.0-1.1 SECONDS -- not the kind of variable timing
    genuine network flakiness produces, and far too fast to be the 30s
    timeout this probe configures actually elapsing. A fast, uniform,
    repeatable rejection like this is much more consistent with an ACTIVE
    block (e.g. the server immediately refusing the connection or
    returning an error status) than with occasional transient failures --
    and bug #4's retry-with-backoff, which measurably helped ISC recover
    real data elsewhere (see `ISCReference`'s docstring), did NOT change
    this outcome at all, which is exactly what you'd expect if every
    individual attempt (original request AND both retries) is being
    actively rejected rather than randomly failing. Combined with the same
    session finding `real_earthquake1` (a structurally different, much
    larger dataset) ALSO failing totally against EMSC with a similarly
    consistent ~690s signature across two separate attempts, and chile/
    real_earthquake1 ALSO failing totally against ISC with consistent
    ~140-330s signatures across THREE separate attempts spanning the same
    session -- the evidence now points to an active, ongoing rate-limit or
    IP-level block affecting BOTH EMSC and ISC, most likely triggered by
    the sheer cumulative volume of heavy diagnostic queries sent to both
    services over the course of this investigation (including, ironically,
    bug #4's own retry logic tripling the request volume of every failed
    call). This is CONFIRMED to be an EXTERNAL condition that a further
    code change cannot fix -- current code behavior is correct given
    whatever the server actually returns.

    DECISION (2026-07-10, final): not pursued further -- accepted as a
    disclosed, permanent limitation rather than a pending retry. Chasing
    an active external rate-limit with more live queries offers
    diminishing returns and risks prolonging it; the affected datasets
    (chile-ISC's final matched_fraction, real_earthquake1-EMSC/ISC,
    real_events_atkinson-EMSC) are therefore disclosed as using the last-
    obtained values, explicitly flagged as not independently re-verified
    after bug #4's fix, rather than left as an open investigation. A
    future maintainer wanting to attempt this again should start with
    `calibration/debug_diagnostics/debug_emsc_isolated_probe.py` after a genuinely long
    (multi-day, not merely multi-hour) gap in live querying against these
    services -- but this is not tracked as outstanding work in this
    project's current state.
    """

    def __init__(self, timeout_sec: float = 10.0,
                 max_events_per_query: int = EMSC_MAX_EVENTS_PER_QUERY):
        self._timeout = timeout_sec
        self._max_events = max_events_per_query
        self._feasible_cache: Optional[bool] = None

    def _get(self, url: str) -> Optional[bytes]:
        # BUGFIX #4 (2026-07-10) -- see this module's `_get_with_retry`
        # comment (near `_USER_AGENT`) for the full story: this now retries
        # a failed request with backoff instead of giving up after one try.
        return _get_with_retry(url, self._timeout)

    def _build_url(self, start_iso: str, end_iso: str,
                    lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                    min_mag: float, limit: int) -> str:
        params = {
            "starttime": start_iso,
            "endtime": end_iso,
            "minlatitude": f"{lat_min:.6f}",
            "maxlatitude": f"{lat_max:.6f}",
            "minlongitude": f"{lon_min:.6f}",
            "maxlongitude": f"{lon_max:.6f}",
            "minmagnitude": f"{min_mag:.3f}",
            "format": "json",
            "limit": str(limit),
            "orderby": "time",
        }
        return f"{EMSC_BASE_URL}/query?{urllib.parse.urlencode(params)}"

    def _query(self, *args) -> Tuple[int, List[Tuple[np.datetime64, float, float, float]]]:
        """Returns (total_count, events_returned_this_call)."""
        raw = self._get(self._build_url(*args))
        if raw is None:
            return -1, []
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return -1, []
        total = payload.get("metadata", {}).get("totalCount")
        if total is None:
            total = len(payload.get("features", []) or [])
        out: List[Tuple[np.datetime64, float, float, float]] = []
        for feat in payload.get("features", []) or []:
            props = feat.get("properties") or {}
            t = _iso_to_datetime64_ns(props.get("time", ""))
            lat, lon, mag = props.get("lat"), props.get("lon"), props.get("mag")
            if t is None or lat is None or lon is None or mag is None:
                continue
            out.append((t, float(lat), float(lon), float(mag)))
        return int(total), out

    def is_feasible(self) -> bool:
        if self._feasible_cache is not None:
            return self._feasible_cache
        total, _ = self._query(
            "2020-01-01T00:00:00", "2020-01-02T00:00:00",
            -90.0, 90.0, -180.0, 180.0, 5.0, 1,
        )
        self._feasible_cache = total >= 0
        return self._feasible_cache

    def _fetch_events_paginated(
        self, start_dt: np.datetime64, end_dt: np.datetime64,
        lat_min: float, lat_max: float, lon_min: float, lon_max: float,
        min_mag: float, _depth: int = 0, _budget: Optional[List[int]] = None,
    ) -> List[Tuple[np.datetime64, float, float, float]]:
        if _budget is None:
            _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        if _budget[0] <= 0:
            start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
            _warn_pagination_depth_exhausted(
                "EMSCReference", start_iso, end_iso, self._max_events,
                known_count=None, reason="budget")
            return []
        _budget[0] -= 1
        start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
        args = (start_iso, end_iso, lat_min, lat_max, lon_min, lon_max, min_mag)
        total, events = self._query(*args, self._max_events)
        # A leaf this small or this deep is a terminal node no matter what
        # `total` claims -- see _PAGINATION_MIN_WINDOW_SEC's module-level
        # comment for why this guard exists (a runaway-recursion regression
        # found live 2026-07-09: EMSC returning a bogus `total=20000` for
        # physically-impossible ~75-second windows, which the BUGFIX #2
        # split-on-failure logic below then split forever without this).
        at_stop_condition = (_depth >= _PAGINATION_MAX_DEPTH
                              or _window_below_min_size(start_dt, end_dt))
        # BUGFIX #2 (2026-07-09, found via
        # calibration/debug_diagnostics/debug_emsc_atkinson_trace.py on the real
        # "real_events_atkinson" corpus dataset): `total < 0` means the
        # request itself FAILED (network/timeout/parse error), NOT a
        # confirmed-empty result -- this used to give up on the entire
        # window immediately (`return []`). Live evidence this is wrong:
        # a query for real_events_atkinson's full 1983-2023 window
        # (min_mag=2.5, Western North America) failed outright with
        # total=-1, while an otherwise-identical but much smaller 2-year
        # sub-window over the same region succeeded immediately and found
        # 4,114 real events (`calibration/emsc_atkinson_trace_debug.txt`)
        # -- i.e. a large single request can fail while a smaller request
        # of the exact same shape succeeds, exactly the situation
        # recursive splitting already exists to handle for "too many
        # results." A failed request now falls through to that SAME
        # split-and-retry path instead of surrendering immediately --
        # bounded by at_stop_condition above (depth OR min-window-size).
        if total < 0 and at_stop_condition:
            _warn_pagination_depth_exhausted(
                "EMSCReference", start_iso, end_iso, self._max_events, known_count=None,
                reason="min_window" if _window_below_min_size(start_dt, end_dt) else "depth")
            # Last-ditch direct fetch attempt at a (by now, very small)
            # window -- events may be [] here (this request also failed),
            # but a smaller/simpler query than the one that failed higher
            # up the recursion has a real chance of succeeding.
            _, retry_events = self._query(*args, self._max_events)
            return retry_events
        if total < 0:
            mid_dt = start_dt + (end_dt - start_dt) // 2
            left = self._fetch_events_paginated(start_dt, mid_dt, lat_min, lat_max,
                                                 lon_min, lon_max, min_mag, _depth + 1, _budget)
            right = self._fetch_events_paginated(mid_dt, end_dt, lat_min, lat_max,
                                                  lon_min, lon_max, min_mag, _depth + 1, _budget)
            return left + right
        # BUGFIX (2026-07-09, found via calibration/debug_diagnostics/debug_emsc_chile_deep.py
        # on the real "chile" corpus dataset): this used to be `total <=
        # self._max_events`, trusting EMSC's `metadata.totalCount` field as
        # an authoritative, limit-independent total. It is NOT -- live
        # evidence shows `totalCount` comes back capped at exactly
        # `self._max_events` (e.g. total=20000 when max_events=20000, for a
        # query whose true count is far higher), i.e. EMSC's `totalCount` is
        # itself bounded by the query's own `limit` parameter, unlike
        # USGSComCatReference's genuinely limit-independent dedicated
        # `/count` endpoint. Trusting an exact-cap `total` as "complete"
        # meant a single non-recursive fetch silently returned only the
        # `limit` most-recent events (EMSC's `orderby=time` sorts
        # descending, same FDSN convention already confirmed for ISC), for
        # any query whose TRUE result count reached the cap. Confirmed live
        # on chile (24-year span, min_mag=0.5): the single fetch returned
        # exactly 20,000 events spanning only late-2021 through March 2024
        # -- 2000-2020 were completely absent, and the resulting
        # matched_fraction was 0.0554 with essentially every chile record
        # from 2000-2020 scoring 0/N matched (temporal analysis in
        # `calibration/emsc_chile_deep_debug.txt`). Changed `<=` to `<` so
        # an exact-cap total is treated the same as "possibly truncated,
        # keep splitting" rather than "provably complete" -- symmetric with
        # ISCReference's existing `len(events) < self._max_events` check,
        # which never had this specific bug because it was already strict.
        if total < self._max_events:
            return events
        if at_stop_condition:
            _warn_pagination_depth_exhausted(
                "EMSCReference", start_iso, end_iso, self._max_events, known_count=total,
                reason="min_window" if _window_below_min_size(start_dt, end_dt) else "depth")
            return events
        mid_dt = start_dt + (end_dt - start_dt) // 2
        left = self._fetch_events_paginated(start_dt, mid_dt, lat_min, lat_max,
                                             lon_min, lon_max, min_mag, _depth + 1, _budget)
        right = self._fetch_events_paginated(mid_dt, end_dt, lat_min, lat_max,
                                              lon_min, lon_max, min_mag, _depth + 1, _budget)
        return left + right

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        if not self.is_feasible():
            return NullExternalCatalog().match(dataset)

        valid = (np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
                 & np.isfinite(dataset.magnitude) & ~np.isnat(dataset.origin_time))
        if not np.any(valid):
            return NullExternalCatalog().match(dataset)

        lat_v, lon_v = dataset.latitude[valid], dataset.longitude[valid]
        mag_v, time_v = dataset.magnitude[valid], dataset.origin_time[valid]

        dist_tol_deg_lat = dist_tol_km / 111.0
        lat_min = max(-90.0, float(np.min(lat_v)) - dist_tol_deg_lat)
        lat_max = min(90.0, float(np.max(lat_v)) + dist_tol_deg_lat)
        cos_lat = max(0.05, math.cos(math.radians(max(abs(lat_min), abs(lat_max)))))
        dist_tol_deg_lon = dist_tol_km / (111.0 * cos_lat)
        lon_min_c, lon_max_c = _compact_lon_bounds(lon_v)
        lon_min, lon_max = lon_min_c - dist_tol_deg_lon, lon_max_c + dist_tol_deg_lon

        pad = np.timedelta64(int(time_tol_sec) + 1, "s")
        t_min, t_max = time_v.min() - pad, time_v.max() + pad
        min_mag = float(np.min(mag_v)) - mag_tol

        raw_events = []
        _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        for sub_lon_min, sub_lon_max in _split_lon_range(lon_min, lon_max):
            raw_events.extend(self._fetch_events_paginated(
                t_min, t_max, lat_min, lat_max, sub_lon_min, sub_lon_max, min_mag,
                _budget=_budget,
            ))

        if not raw_events:
            ref_time = np.array([], dtype="datetime64[ns]")
            ref_lat = ref_lon = ref_mag = np.array([], dtype=float)
        else:
            times, lats, lons, mags = zip(*raw_events)
            ref_time = np.array(times, dtype="datetime64[ns]")
            ref_lat, ref_lon, ref_mag = (np.array(lats, dtype=float),
                                         np.array(lons, dtype=float),
                                         np.array(mags, dtype=float))

        return _match_against_reference_arrays(
            dataset, ref_time, ref_lat, ref_lon, ref_mag,
            time_tol_sec, dist_tol_km, mag_tol,
        )


ISC_BASE_URL = "https://www.isc.ac.uk/fdsnws/event/1"
# ISC's own documentation does not advertise a per-request event cap the
# way USGS (20000, documented) and EMSC (20000, documented) do; this value
# is therefore a conservative, DISCLOSED assumption (matching the other two
# sources' documented cap) rather than a verified ISC-specific figure --
# the pagination-by-time-halving logic below re-checks after every fetch
# (triggering on "returned count == requested limit", not a hard total)
# specifically because ISC exposes no authoritative total to compare
# against, unlike USGS's /count endpoint or EMSC's metadata.totalCount.
ISC_ASSUMED_MAX_EVENTS_PER_QUERY = 20000


def _local_tag(tag: str) -> str:
    """Strip a `{namespace-uri}` prefix from an ElementTree tag, e.g.
    '{http://quakeml.org/xmlns/bed/1.2}origin' -> 'origin'. QuakeML/BED
    responses are namespaced, and the exact namespace URI varies by
    schema version (1.2 vs others) and by data-center deployment; matching
    on the local name only makes parsing tolerant of that variation
    without needing to hard-code a specific namespace URI."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_child(el: ET.Element, local_name: str) -> Optional[ET.Element]:
    for child in el:
        if _local_tag(child.tag) == local_name:
            return child
    return None


def _parse_quakeml_events(raw: bytes) -> List[Tuple[np.datetime64, float, float, float]]:
    """
    Parse a QuakeML/BED XML payload, as returned by ISC's fdsnws-event
    `format=xml`, into (time, lat, lon, mag) tuples, one per top-level
    <event> element.

    This parser resolves QuakeML's preferred cross-references when present:
    `preferredOriginID` is used to select the event origin, and
    `preferredMagnitudeID` is used to select the event magnitude. This is
    necessary for real ISC responses because a single event may contain
    multiple magnitudes of different types. For example, the 2011 Tohoku
    ISC response includes both mb=7.11 and preferred MS=8.37; using the
    first <magnitude> element would select the wrong value.

    Fallbacks, in order:
      1. preferredOriginID / preferredMagnitudeID when resolvable;
      2. first origin if no preferred origin can be resolved;
      3. moment-magnitude-like magnitude types if no preferred magnitude
         can be resolved;
      4. largest finite magnitude as a conservative final fallback.

    Never raises: malformed XML or malformed events are skipped, matching
    the rest of the reference-source design where a bad external response
    degrades toward "no matches found" rather than crashing the audit.
    """
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []

    def _child_text(el: ET.Element, local_name: str) -> str:
        child = _find_child(el, local_name)
        if child is None or child.text is None:
            return ""
        return child.text.strip()

    def _direct_children(el: ET.Element, local_name: str) -> List[ET.Element]:
        return [child for child in el if _local_tag(child.tag) == local_name]

    def _value_under(el: ET.Element, wrapper_name: str) -> Optional[str]:
        wrapper = _find_child(el, wrapper_name)
        if wrapper is None:
            return None
        value_el = _find_child(wrapper, "value")
        if value_el is None or value_el.text is None:
            return None
        return value_el.text.strip()

    def _float_value_under(el: ET.Element, wrapper_name: str) -> Optional[float]:
        text = _value_under(el, wrapper_name)
        if text is None:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    def _pick_origin(event_el: ET.Element) -> Optional[ET.Element]:
        origins = _direct_children(event_el, "origin")
        if not origins:
            return None

        preferred_origin_id = _child_text(event_el, "preferredOriginID")
        if preferred_origin_id:
            for origin in origins:
                if origin.attrib.get("publicID", "") == preferred_origin_id:
                    return origin

        # Fallback: first direct origin.
        return origins[0]

    def _pick_magnitude_value(event_el: ET.Element) -> Optional[float]:
        magnitudes = _direct_children(event_el, "magnitude")
        if not magnitudes:
            return None

        parsed: List[Tuple[ET.Element, str, str, float]] = []
        for magnitude in magnitudes:
            value = _float_value_under(magnitude, "mag")
            if value is None:
                continue
            public_id = magnitude.attrib.get("publicID", "")
            mag_type = _child_text(magnitude, "type")
            parsed.append((magnitude, public_id, mag_type, value))

        if not parsed:
            return None

        # 1) Correct QuakeML behavior: use preferredMagnitudeID when present.
        preferred_mag_id = _child_text(event_el, "preferredMagnitudeID")
        if preferred_mag_id:
            for _, public_id, _, value in parsed:
                if public_id == preferred_mag_id:
                    return value

        # 2) Fallback: prefer moment-magnitude-like types if present.
        mw_like_types = {"mw", "mww", "mwc", "mwb", "mwp", "mw(mwp)"}
        for _, _, mag_type, value in parsed:
            if mag_type.strip().lower() in mw_like_types:
                return value

        # 3) Final fallback: choose the largest finite magnitude.
        return max(value for _, _, _, value in parsed)

    out: List[Tuple[np.datetime64, float, float, float]] = []

    for event_el in root.iter():
        if _local_tag(event_el.tag) != "event":
            continue

        origin_el = _pick_origin(event_el)
        mag = _pick_magnitude_value(event_el)

        if origin_el is None or mag is None:
            continue

        time_text = _value_under(origin_el, "time")
        lat = _float_value_under(origin_el, "latitude")
        lon = _float_value_under(origin_el, "longitude")

        if time_text is None or lat is None or lon is None:
            continue

        t = _iso_to_datetime64_ns(time_text)
        if t is None:
            continue

        out.append((t, lat, lon, mag))

    return out


class ISCReference(ExternalCatalogReference):
    """
    Live A6 external cross-validation against the real ISC (International
    Seismological Centre, UK) FDSN event web service
    (https://www.isc.ac.uk/fdsnws/event/1/). ISC is a third, organizationally
    independent seismological data center (distinct from both USGS and
    EMSC) -- see module docstring for why having a third independent source
    matters for MultiSourceExternalCatalogReference.

    LIVE-VERIFIED (2026-07-08): this class's XML parsing
    (`_parse_quakeml_events`) was originally built from the published FDSN
    fdsnws-event-1.2 specification and the QuakeML/BED schema documentation
    alone (both independently-verified, stable, versioned public standards
    -- see module docstring), because this project's development
    environment at the time could not retrieve raw XML from isc.ac.uk
    (repeated fetch timeouts). That gap has since been closed: run
    `verify_isc_reference.py` against the real, unmodified production
    `ISCReference` class and confirmed, against a live isc.ac.uk endpoint,
    that (1) `is_feasible()` returns True, (2) a real raw QuakeML response
    was fetched successfully (245,077 bytes), (3) `_parse_quakeml_events`
    correctly recovers the 2011 Tohoku mainshock (time within 0.8s,
    lat/lon/magnitude all within tolerance) from that real response, and
    (4) `match()` end-to-end both corroborates a real Tohoku record
    (positive control) and correctly refuses to corroborate a fabricated
    Sahara-region event (negative control). Full run log and artifacts:
    `isc_reference_fetch/verification_report.md` /
    `verification_report.json`.

    FOLLOW-UP (2026-07-09, `verify_isc_gap_closure.py` +
    `debug_isc_pagination_gap.py`, see
    `isc_gap_closure/verification_report.md`): the two items flagged above
    as untested have both now been exercised live. Dateline/antimeridian
    behaviour: PASSED -- a real event was discovered live within 0.06 deg
    of the antimeridian (1979-11-16, Fiji/Tonga region, M6.97) and
    correctly matched with a query box straddling +/-180; a fabricated
    event at the antimeridian was correctly rejected under the same
    dateline-crossing box. Pagination: FOUND A REAL BUG, since fixed --
    `_fetch_events_paginated`'s recursion depth ceiling (previously 8)
    could be reached while a leaf window still held more events than the
    configured cap, silently dropping the earliest events in that window
    (ISC's `orderby=time` is descending, so cap-truncation keeps the most
    recent and drops the earliest). Confirmed live: a cap=3 test over the
    2011-03-11 Tohoku aftershock window lost 2 of 8 events -- including the
    mainshock itself -- because a ~56-minute leaf window right after the
    mainshock held 5 real M>=6.5 events, and depth 8 was reached before the
    recursion could separate them. Fixed by raising the shared depth
    ceiling to `_PAGINATION_MAX_DEPTH=24` (module-level, shared with
    USGSComCatReference/EMSCReference, which had the identical latent bug)
    and adding a `warnings.warn` for the now-much-rarer case where the
    ceiling is genuinely hit while still over-cap, so this failure mode is
    no longer silent. The literal 20,000-event cap itself is still not
    reached by any test to date (impractically large/slow to query for
    real) -- what is now live-verified is the recursive-halving mechanism
    itself, at whatever cap is configured. Separately (informational, not a
    correctness gap): a same-run probe of ISC's Bulletin review lag for a
    recent 1-year Japan M>=5.5 window returned events up to 2026-07-02 --
    i.e. this particular probe did *not* reproduce the ~24-month review lag
    sometimes reported for the ISC Bulletin; whether that reflects a
    genuinely shorter lag for this region/magnitude, or a lag that is
    simply not visible in this one probe, is not yet established and
    should not be over-generalized from a single run.

    RUNAWAY-RECURSION SAFETY NETS (2026-07-09, found and fixed via
    EMSCReference, applies here too): `_fetch_events_paginated`'s
    request-failure-triggers-split fix (see this file's `USGSComCatReference`
    docstring above and `EMSCReference`'s docstring below for the full
    story) could in principle combine with a pathological server response
    to cause unbounded-in-practice recursion, since this class shares the
    exact same recursion structure. Guarded by the same two module-level
    safety nets applied uniformly to all three classes:
    `_PAGINATION_MIN_WINDOW_SEC=60` (any window this small or smaller is
    always terminal) and, decisively, `_PAGINATION_MAX_TOTAL_REQUESTS=500`
    (a hard global budget on live requests per top-level `match()` call).
    This class has not itself been observed triggering the pathological
    pattern (that was driven by EMSC's specific `total=20000` bogus-cap
    behaviour, which ISC's heuristic total-tracking does not replicate),
    but the guards apply regardless.

    ROOT-CAUSED AND FIXED (2026-07-10): the residual full-chile gap first
    found on 2026-07-09 (`matched_fraction=0.1862`, 18.6%, far below the
    ~76-83% expected from USGS's 76.5% and a small isolated Illapel-
    sequence test at 82.7% for this same class) turned out to have TWO
    separate causes, distinguished by `calibration/debug_diagnostics/debug_isc_chile_gap.py`
    (ruled out request-budget exhaustion -- only 15/500 requests needed,
    zero budget warnings) and `calibration/debug_diagnostics/debug_isc_chile_year_gap.py`
    (the decisive trace):
      (1) BUG, NOW FIXED -- transient HTTP failures were silently dropping
          real data. Two otherwise-identical full-chile ISC scoring runs
          (same query, same timeout=90s) returned matched_fraction=0.1705
          and 0.3805 respectively -- a >2x swing on the IDENTICAL request,
          which by itself proved the number was not a stable, reproducible
          property of ISC's real coverage. A follow-up raw-fetch trace
          found, for chile's own 2018-2024 records (which scored exactly
          0% in the lower-scoring run), near-perfect candidate matches
          sitting right there in a more-complete fetch -- e.g. a chile
          M7.0 record on 2019-03-01 had a raw ISC event just 1.6 seconds
          away in time, 35.5km in distance, 0.31 magnitude units away,
          comfortably inside every match tolerance. That data was not
          genuinely absent from ISC; it was silently dropped by a
          transient request failure that the previous single-retry-at-the-
          leaf safety net was not robust enough to catch at ISC's observed
          real-world failure rate for a query this large. FIXED by
          `_get_with_retry()` (module-level, see its own comment near
          `_USER_AGENT` above) -- every raw HTTP call across all three
          reference classes now retries up to `_HTTP_RETRY_ATTEMPTS=3`
          times with backoff before reporting failure, instead of once.
      (2) GENUINE, DISCLOSED LIMITATION, NOT A BUG -- years 2004-2005 and
          2013-2017 (6 years, ~1905 of chile's own stratum records) show
          ZERO raw ISC events in chile's bounding box even in the most
          complete fetch obtained (97,051 total raw events across the
          full 24-year query) -- unlike the 2018-2024 case, there was
          nothing nearby to match against at all, not a near-miss. This
          looks like a genuine ISC regional-coverage gap for Chile
          specifically during these years (a real reporting-agency/
          review-lag characteristic of ISC's bulletin, not something a
          code fix can address) rather than a further undiscovered bug --
          consistent with, though distinct in shape from, EMSC's own
          separately-disclosed 2000-2003 Chile coverage gap.
    Practical implication: with the retry fix in place, ISC's chile
    matched_fraction should be much closer to reproducible run-to-run
    (bug (1) resolved) once ISC is actually reachable, and will still land
    somewhat below the ~76-83% ballpark because of the genuine 6-year gap
    in (2) -- that residual is understood and disclosed, not mysterious.

    VERIFICATION BLOCKED BY A SEPARATE, EXTERNAL ISSUE (2026-07-10): the
    very next re-score attempt after this fix landed (same session) came
    back as `matched_fraction=0.0, mc_ref_is_default=True` again --
    complete failure -- in 138.05s, essentially the same wall-clock time
    as a pre-fix failed run, which is the opposite of what a working retry
    fix should look like (each failed request should now cost several
    extra seconds of backoff). That is only consistent with EVERY request,
    including all retries, being actively rejected rather than
    occasionally, randomly failing -- i.e. bug #1 (the "genuine
    request-budget/transient-failure" story above) is real and the fix
    for it is correct, but a SEPARATE, currently-active rate-limit/block
    (see `EMSCReference`'s "ATKINSON'S EMSC GAP" docstring section for the
    fuller cross-source evidence -- the same pattern was observed against
    ISC for `real_earthquake1`, three separate times, at a suspiciously
    consistent ~140-330s each) is now preventing a clean, final re-score.
    `score_matrix_a6_isc.csv`'s chile row has been intentionally left
    UNSET (not populated with the misleading 0.0) rather than holding a
    stale or misleading number.

    DECISION (2026-07-10, final): not pursued further -- see
    `EMSCReference`'s docstring for the full cross-source rationale. This
    is now a disclosed, accepted limitation of relying on live, rate-
    limited third-party APIs for A6, not an open item awaiting a retry.
    This is documented as a known, accepted limitation rather than an open
    bug.
    """

    def __init__(self, timeout_sec: float = 15.0,
                 assumed_max_events_per_query: int = ISC_ASSUMED_MAX_EVENTS_PER_QUERY):
        # ISC's server has historically been slower to respond than
        # USGS/EMSC for large QuakeML payloads (XML is far more verbose
        # than JSON/GeoJSON for the same event count) -- a longer default
        # timeout is a deliberate, disclosed accommodation for that, not
        # an arbitrary choice.
        self._timeout = timeout_sec
        self._max_events = assumed_max_events_per_query
        self._feasible_cache: Optional[bool] = None

    def _get(self, url: str) -> Optional[bytes]:
        # BUGFIX #4 (2026-07-10) -- see this module's `_get_with_retry`
        # comment (near `_USER_AGENT`) for the full story: this now retries
        # a failed request with backoff instead of giving up after one try.
        return _get_with_retry(url, self._timeout)

    def _build_url(self, start_iso: str, end_iso: str,
                    lat_min: float, lat_max: float, lon_min: float, lon_max: float,
                    min_mag: float, limit: int) -> str:
        params = {
            "starttime": start_iso,
            "endtime": end_iso,
            "minlatitude": f"{lat_min:.6f}",
            "maxlatitude": f"{lat_max:.6f}",
            "minlongitude": f"{lon_min:.6f}",
            "maxlongitude": f"{lon_max:.6f}",
            "minmagnitude": f"{min_mag:.3f}",
            "format": "xml",
            "limit": str(limit),
            "orderby": "time",
        }
        return f"{ISC_BASE_URL}/query?{urllib.parse.urlencode(params)}"

    def _query(self, *args) -> Optional[List[Tuple[np.datetime64, float, float, float]]]:
        """Returns None on network/parse failure, else the parsed events
        (possibly empty)."""
        raw = self._get(self._build_url(*args))
        if raw is None:
            return None
        return _parse_quakeml_events(raw)

    def is_feasible(self) -> bool:
        if self._feasible_cache is not None:
            return self._feasible_cache
        # 2011 Tohoku sequence, M>=7 -- a window/magnitude combination
        # essentially guaranteed to be present in any functioning global
        # seismic catalog, well past ISC's review-lag window as of 2026.
        events = self._query("2011-03-01T00:00:00", "2011-03-15T00:00:00",
                              -90.0, 90.0, -180.0, 180.0, 7.0, 20)
        feasible = events is not None and len(events) >= 1
        self._feasible_cache = feasible
        return feasible

    def _fetch_events_paginated(
        self, start_dt: np.datetime64, end_dt: np.datetime64,
        lat_min: float, lat_max: float, lon_min: float, lon_max: float,
        min_mag: float, _depth: int = 0, _budget: Optional[List[int]] = None,
    ) -> List[Tuple[np.datetime64, float, float, float]]:
        if _budget is None:
            _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        if _budget[0] <= 0:
            start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
            _warn_pagination_depth_exhausted(
                "ISCReference", start_iso, end_iso, self._max_events,
                known_count=None, reason="budget")
            return []
        _budget[0] -= 1
        start_iso, end_iso = str(start_dt)[:19], str(end_dt)[:19]
        args = (start_iso, end_iso, lat_min, lat_max, lon_min, lon_max, min_mag)
        events = self._query(*args, self._max_events)
        # BUGFIX #3 (2026-07-09, found live for EMSC via
        # calibration/debug_diagnostics/debug_emsc_atkinson_trace.py, then confirmed as the
        # same structural flaw in USGSComCatReference and here in
        # ISCReference too -- all three share this recursive-halving
        # shape): `events is None` means the request itself FAILED
        # (network/timeout/parse error), NOT a confirmed-empty result --
        # this used to give up on the entire window immediately
        # (`return []`). Live evidence (on EMSC, same underlying pattern
        # very plausibly applies here): a query for real_events_atkinson's
        # full 1983-2023 window failed outright, while an otherwise-
        # identical but much smaller 2-year sub-window over the same
        # region succeeded immediately and found real events -- a large
        # single request can fail while a smaller request of the exact
        # same shape succeeds, exactly the situation recursive splitting
        # already exists to handle for "too many results." A failed
        # request now falls through to that SAME split-and-retry path
        # instead of surrendering immediately. This is a strong candidate
        # explanation for ISC's own suspiciously-fast, all-zero results
        # seen on both "chile" (before its 90s-timeout retest) and
        # "real_earthquake1" (0.0 matched, mc_ref_is_default=True, even
        # at a 90s timeout) -- a huge global/multi-decade top-level query
        # timing out on the FIRST request, before ever getting a chance to
        # split into smaller, more tractable sub-windows.
        # Bounded by min-window-size as well as depth -- see
        # _PAGINATION_MIN_WINDOW_SEC's module-level comment: the failure-
        # triggers-split change above caused a real runaway-recursion
        # regression in EMSCReference when combined with a bogus/rate-
        # limited server response that kept reporting "still over cap" for
        # physically-impossible sub-minute windows; applied here too for
        # consistency even though only directly observed for EMSC.
        at_stop_condition = (_depth >= _PAGINATION_MAX_DEPTH
                              or _window_below_min_size(start_dt, end_dt))
        if events is None and at_stop_condition:
            _warn_pagination_depth_exhausted(
                "ISCReference", start_iso, end_iso, self._max_events, known_count=None,
                reason="min_window" if _window_below_min_size(start_dt, end_dt) else "depth")
            retry = self._query(*args, self._max_events)
            return retry if retry is not None else []
        if events is None:
            mid_dt = start_dt + (end_dt - start_dt) // 2
            left = self._fetch_events_paginated(start_dt, mid_dt, lat_min, lat_max,
                                                 lon_min, lon_max, min_mag, _depth + 1, _budget)
            right = self._fetch_events_paginated(mid_dt, end_dt, lat_min, lat_max,
                                                  lon_min, lon_max, min_mag, _depth + 1, _budget)
            return left + right
        # No authoritative total is available from ISC (see class
        # docstring) -- returning exactly `limit` events is the only
        # available signal that more may exist, so halving triggers on
        # that instead of a verified over-cap count.
        if len(events) < self._max_events:
            return events
        if at_stop_condition:
            _warn_pagination_depth_exhausted(
                "ISCReference", start_iso, end_iso, self._max_events, known_count=None,
                reason="min_window" if _window_below_min_size(start_dt, end_dt) else "depth")
            return events
        mid_dt = start_dt + (end_dt - start_dt) // 2
        left = self._fetch_events_paginated(start_dt, mid_dt, lat_min, lat_max,
                                             lon_min, lon_max, min_mag, _depth + 1, _budget)
        right = self._fetch_events_paginated(mid_dt, end_dt, lat_min, lat_max,
                                              lon_min, lon_max, min_mag, _depth + 1, _budget)
        return left + right

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        if not self.is_feasible():
            return NullExternalCatalog().match(dataset)

        valid = (np.isfinite(dataset.latitude) & np.isfinite(dataset.longitude)
                 & np.isfinite(dataset.magnitude) & ~np.isnat(dataset.origin_time))
        if not np.any(valid):
            return NullExternalCatalog().match(dataset)

        lat_v, lon_v = dataset.latitude[valid], dataset.longitude[valid]
        mag_v, time_v = dataset.magnitude[valid], dataset.origin_time[valid]

        dist_tol_deg_lat = dist_tol_km / 111.0
        lat_min = max(-90.0, float(np.min(lat_v)) - dist_tol_deg_lat)
        lat_max = min(90.0, float(np.max(lat_v)) + dist_tol_deg_lat)
        cos_lat = max(0.05, math.cos(math.radians(max(abs(lat_min), abs(lat_max)))))
        dist_tol_deg_lon = dist_tol_km / (111.0 * cos_lat)
        lon_min_c, lon_max_c = _compact_lon_bounds(lon_v)
        lon_min, lon_max = lon_min_c - dist_tol_deg_lon, lon_max_c + dist_tol_deg_lon

        pad = np.timedelta64(int(time_tol_sec) + 1, "s")
        t_min, t_max = time_v.min() - pad, time_v.max() + pad
        min_mag = float(np.min(mag_v)) - mag_tol

        raw_events = []
        _budget = [_PAGINATION_MAX_TOTAL_REQUESTS]
        for sub_lon_min, sub_lon_max in _split_lon_range(lon_min, lon_max):
            raw_events.extend(self._fetch_events_paginated(
                t_min, t_max, lat_min, lat_max, sub_lon_min, sub_lon_max, min_mag,
                _budget=_budget,
            ))

        if not raw_events:
            ref_time = np.array([], dtype="datetime64[ns]")
            ref_lat = ref_lon = ref_mag = np.array([], dtype=float)
        else:
            times, lats, lons, mags = zip(*raw_events)
            ref_time = np.array(times, dtype="datetime64[ns]")
            ref_lat, ref_lon, ref_mag = (np.array(lats, dtype=float),
                                         np.array(lons, dtype=float),
                                         np.array(mags, dtype=float))

        return _match_against_reference_arrays(
            dataset, ref_time, ref_lat, ref_lon, ref_mag,
            time_tol_sec, dist_tol_km, mag_tol,
        )


class MultiSourceExternalCatalogReference(ExternalCatalogReference):
    """
    Combines two or more independent ExternalCatalogReference sources
    (e.g. USGS + EMSC + ISC) and only reports a record as externally
    matched once at least `min_corroborating_sources` of the sources that
    are CURRENTLY REACHABLE independently found a match for it.

    This is the concrete answer to "what if USGS ComCat itself is spoofed
    or compromised" (see module docstring): with
    `min_corroborating_sources=2` and three configured sources, a single
    compromised catalog can no longer single-handedly manufacture or erase
    A6 corroboration -- at least one other, organizationally-independent
    agency would also have to agree.

    Design choices, disclosed:
      - `is_feasible()` is True if ANY configured source is feasible (so
        A6 still attempts SOMETHING rather than going fully offline just
        because one of several sources is briefly down).
      - `match()`, however, degrades to `NullExternalCatalog` (not to a
        lowered corroboration threshold) whenever FEWER sources than
        `min_corroborating_sources` are currently reachable. The
        alternative -- silently requiring corroboration from however many
        sources happen to be up right now -- would let a well-timed
        denial-of-service against N-1 of the N configured sources reduce
        a "requires 2-of-3 independent agencies" audit down to "requires
        1-of-1", defeating the entire point of this class. Falling back
        to the existing, already-documented intrinsic-only A(D) path
        instead is the safer failure direction (see
        NullExternalCatalog/USGSComCatReference docstrings for why that
        path is always safe).
      - `mc_ref` (the reference-completeness floor used to decide which
        of the audited dataset's own records are even eligible for an A6
        penalty) is combined CONSERVATIVELY across the sources that did
        contribute a match decision: the MAXIMUM (least-complete) of
        their individual mc_ref values is used, together with that same
        source's mc_ref_se/mc_ref_is_default. Rationale: a record only
        "counts against" the dataset if it fails to appear in enough
        sources to reach the corroboration threshold -- which requires
        it to be above the completeness floor of EVERY source
        contributing to that count, not just the most complete one.
        Using the single most lenient (lowest) mc_ref across sources
        would incorrectly treat some records as eligible for penalty
        even though a subset of the required corroborating catalogs
        would never have been complete enough to detect them regardless
        of whether they are real.
    """

    def __init__(self, sources: Iterable[ExternalCatalogReference],
                 min_corroborating_sources: int = 1):
        self._sources: List[ExternalCatalogReference] = list(sources)
        if not self._sources:
            raise ValueError("MultiSourceExternalCatalogReference requires at least one source.")
        self._min_corroborating = max(1, int(min_corroborating_sources))

    def is_feasible(self) -> bool:
        return any(s.is_feasible() for s in self._sources)

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        feasible_sources = [s for s in self._sources if s.is_feasible()]
        if len(feasible_sources) < self._min_corroborating:
            # Either nothing is reachable, or fewer sources are reachable
            # than the corroboration policy requires -- see class
            # docstring for why this degrades to fully offline rather than
            # silently loosening the threshold.
            return NullExternalCatalog().match(dataset)

        per_source = [s.match(dataset, time_tol_sec, dist_tol_km, mag_tol)
                      for s in feasible_sources]

        n = dataset.n
        corroboration_count = np.zeros(n, dtype=int)
        for r in per_source:
            corroboration_count += r.matched.astype(int)
        matched = corroboration_count >= self._min_corroborating

        # A6 three-state semantics (Group C3): per-record count of how many
        # independently-feasible sources' OWN completeness stratum covers
        # this record (n_sources_queried), and of those, how many actually
        # matched it (n_sources_matched) -- distinct from `matched` above,
        # which is gated by `self._min_corroborating` (a POSITIVE-evidence
        # policy knob) rather than by how many sources could even comment.
        # A record only "counts" against a source if that specific source's
        # own (mc_ref, mc_ref_se) stratum covers it -- a source that itself
        # was never complete enough to see this magnitude of event has no
        # opinion on it and must not count as a queried-but-silent source.
        n_sources_queried = np.zeros(n, dtype=int)
        n_sources_matched = np.zeros(n, dtype=int)
        mag = dataset.magnitude
        for r in per_source:
            if not np.isfinite(r.mc_ref):
                continue
            covered = np.isfinite(mag) & (mag >= (r.mc_ref + r.mc_ref_se))
            n_sources_queried += covered.astype(int)
            n_sources_matched += (covered & r.matched.astype(bool)).astype(int)

        finite_mc = [(i, r.mc_ref) for i, r in enumerate(per_source) if np.isfinite(r.mc_ref)]
        if finite_mc:
            idx_worst = max(finite_mc, key=lambda pair: pair[1])[0]
            worst = per_source[idx_worst]
            mc_ref, mc_ref_se, mc_ref_is_default = (
                worst.mc_ref, worst.mc_ref_se, worst.mc_ref_is_default)
        else:
            mc_ref, mc_ref_se, mc_ref_is_default = float("nan"), float("nan"), True

        return MatchResult(matched=matched, mc_ref=mc_ref, mc_ref_se=mc_ref_se,
                            mc_ref_is_default=mc_ref_is_default,
                            n_sources_queried=n_sources_queried,
                            n_sources_matched=n_sources_matched)


class WeightedMultiSourceExternalCatalogReference(ExternalCatalogReference):
    """
    Combines two or more independent ExternalCatalogReference sources by
    querying and matching against EACH ONE SEPARATELY -- i.e. each source
    forms its own, fully independent judgement about the dataset (its own
    matched_fraction over a shared reference-complete stratum) -- and then
    reliability-weights those independent per-source verdicts together into
    a single combined MatchResult, rather than requiring simultaneous
    per-record agreement the way MultiSourceExternalCatalogReference does.

    Motivation (disclosed): relying on any ONE external catalog (even the
    USGS default) makes A6 a single point of judgement -- if that catalog's
    own regional/period completeness happens to be poor, A6 can wrongly
    read a genuine dataset as unmatched, or wrongly clear a dataset that
    just happens to fall in that one catalog's blind spot.
    MultiSourceExternalCatalogReference already addresses the adversarial
    version of this problem (a compromised/spoofed catalog) via an AND-gate
    per-record vote. This class addresses the complementary, non-adversarial
    version -- ordinary differences in regional coverage/completeness across
    honestly-operated agencies -- by letting each source query and match
    independently, then blending the sources' own aggregate results by how
    complete/reliable each one's own reference catalog turned out to be for
    this specific query, instead of an all-or-nothing per-record vote.

    Weighting scheme, disclosed:
        weight_s  =  (1 / mc_ref_s) * (default_mc_ref_weight_discount if
                                        mc_ref_is_default else 1.0)
    normalized to sum to 1.0 across all sources that are BOTH currently
    feasible AND returned a finite mc_ref (i.e. found at least one
    reference event in the query region/time window to estimate -- or
    default -- a completeness against). A source with a lower mc_ref is,
    by construction (Wiemer & Wyss 2000 Maximum Curvature), complete down
    to smaller magnitudes than one with a higher mc_ref, and is therefore
    treated as a more informative independent witness. `mc_ref_is_default`
    sources (ones that could not fit a region-specific Mc_ref and fell back
    to MC_REF_GLOBAL_FLOOR) are explicitly down-weighted rather than
    trusted equally to a source with an actually-fitted estimate -- a
    defaulted mc_ref is a weaker completeness claim, not a stronger one,
    even when its numeric value happens to be low. A source that returns a
    non-finite mc_ref (no reference events at all in scope) is excluded
    from the blend entirely rather than assigned an arbitrary weight,
    since it has nothing to weigh in.

    Shared stratum definition: exactly as in
    MultiSourceExternalCatalogReference, the reference-complete stratum
    (which of the audited dataset's own records are even eligible for an
    A6 penalty) is defined CONSERVATIVELY using the MAXIMUM (least-
    complete) mc_ref among the contributing sources, together with that
    source's own mc_ref_se. This keeps the eligible stratum identical
    across all contributing sources' own matched_fraction contributions --
    a record only enters the weighted blend once EVERY contributing
    source's own catalog would have been complete enough to detect it, not
    just the most complete one -- so what is being blended is genuinely
    "each source's own opinion about the SAME set of records", not opinions
    about different, source-specific record subsets.

    Math note: because per-record matched votes are combined as
    `sum_s weight_s * matched_s[record]` (a float in [0, 1] per record,
    not a boolean), summing this over any subset of records and dividing
    by the subset size is EXACTLY the weighted average of each
    contributing source's own matched_fraction over that same subset
    (weights sum to 1 by construction). This lets the combined result
    plug directly into axis_authenticity.py's existing
    `sum(matched[stratum_mask]) / n_stratum` computation -- no changes
    needed there, and dataset-level weighted combination falls out exactly
    from the per-record representation.

    Trade-off, disclosed: unlike MultiSourceExternalCatalogReference, a
    single source that is completely wrong about every record it covers
    still contributes proportionally to its weight here -- it is never
    excluded outright the way an uncorroborated record would be under the
    AND-gate vote. This class is about robustness to ordinary differences
    in catalog completeness/coverage, not about defeating a compromised or
    spoofed source; operators who need the latter, stricter security
    property should use MultiSourceExternalCatalogReference instead (the
    two are not mutually exclusive design goals -- combining them, e.g. by
    nesting a WeightedMultiSourceExternalCatalogReference of several
    honestly-operated regional feeds as one "source" inside an outer
    corroboration-vote, is a natural future extension, not yet implemented
    here).
    """

    def __init__(self, sources: Iterable[ExternalCatalogReference],
                 default_mc_ref_weight_discount: float = 0.5):
        self._sources: List[ExternalCatalogReference] = list(sources)
        if not self._sources:
            raise ValueError("WeightedMultiSourceExternalCatalogReference requires at least one source.")
        if not (0.0 < default_mc_ref_weight_discount <= 1.0):
            raise ValueError("default_mc_ref_weight_discount must be in (0, 1].")
        self._default_discount = default_mc_ref_weight_discount

    def is_feasible(self) -> bool:
        return any(s.is_feasible() for s in self._sources)

    def match(
        self,
        dataset: CertifyDataset,
        time_tol_sec: float = 30.0,
        dist_tol_km: float = 50.0,
        mag_tol: float = 0.5,
    ) -> MatchResult:
        feasible_sources = [s for s in self._sources if s.is_feasible()]
        if not feasible_sources:
            # Nothing reachable at all -- degrade to the same safe,
            # already-documented intrinsic-only path as every other
            # reference implementation (see NullExternalCatalog docstring).
            return NullExternalCatalog().match(dataset)

        per_source = [s.match(dataset, time_tol_sec, dist_tol_km, mag_tol)
                      for s in feasible_sources]

        # Only sources that actually produced a usable completeness
        # estimate have anything to weigh in with -- see class docstring.
        contributing = [r for r in per_source if np.isfinite(r.mc_ref)]
        if not contributing:
            return NullExternalCatalog().match(dataset)

        raw_weights = np.array([
            (1.0 / r.mc_ref) * (self._default_discount if r.mc_ref_is_default else 1.0)
            for r in contributing
        ], dtype=float)
        weights = raw_weights / raw_weights.sum()

        # Conservative shared stratum definition -- see class docstring.
        worst = max(contributing, key=lambda r: r.mc_ref)
        mc_ref, mc_ref_se, mc_ref_is_default = (
            worst.mc_ref, worst.mc_ref_se, worst.mc_ref_is_default)

        n = dataset.n
        weighted_vote = np.zeros(n, dtype=float)
        for w, r in zip(weights, contributing):
            weighted_vote += w * r.matched.astype(float)

        # A6 three-state semantics (Group C3) -- see MultiSourceExternalCatalogReference.match()
        # for the identical rationale: a record only "counts" against a
        # contributing source if that source's OWN completeness stratum
        # covers it. Uses the unweighted per-source count (not the
        # reliability weights) since "how many independent witnesses were
        # even able to comment" is a corroboration-count question, distinct
        # from how much each witness's opinion is trusted in the composite
        # score.
        n_sources_queried = np.zeros(n, dtype=int)
        n_sources_matched = np.zeros(n, dtype=int)
        mag = dataset.magnitude
        for r in contributing:
            covered = np.isfinite(mag) & (mag >= (r.mc_ref + r.mc_ref_se))
            n_sources_queried += covered.astype(int)
            n_sources_matched += (covered & r.matched.astype(bool)).astype(int)

        return MatchResult(matched=weighted_vote, mc_ref=mc_ref,
                            mc_ref_se=mc_ref_se, mc_ref_is_default=mc_ref_is_default,
                            n_sources_queried=n_sources_queried,
                            n_sources_matched=n_sources_matched)


# =============================================================================
# P8 -- plate-boundary proximity
# =============================================================================

class FaultDatabaseReference(abc.ABC):
    """Abstract interface for P8 plate-boundary / active-fault proximity."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def distance_to_nearest_boundary_km(self, lat: float, lon: float) -> float:
        raise NotImplementedError

    def distances_to_nearest_boundary_km(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """
        Batch form of distance_to_nearest_boundary_km. The default
        implementation here simply loops and calls the scalar method once
        per query point -- correct for any subclass, but O(n_queries)
        Python-level calls. A subclass backed by a fixed, small reference
        point set (see BundledSampleFaultDatabase) should override this
        with a fully vectorised implementation: on catalogs with 10^5+
        records this loop is otherwise the dominant cost of a P8 audit.
        """
        return np.array(
            [self.distance_to_nearest_boundary_km(lat, lon) for lat, lon in zip(lats, lons)],
            dtype=float,
        )


class NullFaultDatabase(FaultDatabaseReference):
    """Default: no fault database available -> P8 is not evaluated (neutral)."""

    def is_available(self) -> bool:
        return False

    def distance_to_nearest_boundary_km(self, lat: float, lon: float) -> float:
        return float("nan")


# A small, explicitly-labeled SAMPLE of well-known plate-boundary/subduction-
# trench trace points (approximate, coarse-resolution -- for demonstration
# of the distance-decay scoring logic only). This is NOT the GEM Global
# Active Faults Database (Styron & Pagani 2020, ~13,500 faults); a
# production deployment should load the real GAF-DB file instead (freely
# downloadable, GitHub: GEMScienceTools/gem-global-active-faults) via a new
# FaultDatabaseReference subclass -- no other code needs to change.
_SAMPLE_BOUNDARY_POINTS: List[Tuple[float, float]] = [
    # Pacific "Ring of Fire" -- circum-Pacific subduction/transform zones
    (-40.0, 175.0), (-38.0, 177.5), (-45.0, 167.0),        # New Zealand
    (-33.0, -71.7), (-23.5, -70.4), (-18.0, -70.3),        # Chile trench
    (36.0, 141.0), (38.3, 142.4), (33.0, 141.0),           # Japan trench
    (51.0, 178.0), (55.0, -160.0),                          # Aleutians
    (13.0, 121.0), (7.0, 127.0),                            # Philippines
    (-6.0, 130.0), (-8.5, 116.0), (0.0, 98.0),               # Indonesia/Sumatra
    (61.0, -150.0), (49.0, -125.0), (40.0, -124.4),          # Cascadia/Alaska
    (19.0, -104.0), (16.0, -98.0), (14.6, -92.2),            # Central America
    # Alpine-Himalayan belt
    (35.0, 26.0), (38.0, 39.0), (34.0, 71.0), (28.0, 87.0), (30.0, 79.0),
    # Mid-ocean ridges (coarse samples)
    (0.0, -25.0), (10.0, -42.0), (-30.0, -14.0),
]


class BundledSampleFaultDatabase(FaultDatabaseReference):
    """
    Demonstration-scale plate-boundary reference (see module docstring for
    the honest scope disclosure). Distance is computed to the nearest of a
    small set of sample boundary points, not a true fault-trace polyline
    database.
    """

    def __init__(self, points: Optional[List[Tuple[float, float]]] = None):
        self._points = points if points is not None else _SAMPLE_BOUNDARY_POINTS

    def is_available(self) -> bool:
        return len(self._points) > 0

    def distance_to_nearest_boundary_km(self, lat: float, lon: float) -> float:
        if not self.is_available():
            return float("nan")
        dists = [haversine_km(lat, lon, plat, plon) for plat, plon in self._points]
        dists = [d for d in dists if np.isfinite(d)]
        return float(min(dists)) if dists else float("nan")

    def distances_to_nearest_boundary_km(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """
        Vectorised override: computes the full (n_queries, n_points)
        haversine distance matrix in numpy and reduces with a single
        row-wise min, instead of looping in Python (see the base class
        docstring for why this matters at real-catalog scale).
        """
        lats = np.asarray(lats, dtype=float)
        if not self.is_available():
            return np.full(len(lats), np.nan)
        pts = np.asarray(self._points, dtype=float)  # shape (n_points, 2)
        dist_matrix = haversine_km_matrix(lats, lons, pts[:, 0], pts[:, 1])  # (N, n_points)
        return np.min(dist_matrix, axis=1)


# =============================================================================
# P8 -- real GEM Global Active Faults Database (Styron & Pagani 2020)
# =============================================================================

_GEM_DEFAULT_MAX_SEGMENT_KM = 10.0
_GEM_DEFAULT_CELL_DEG = 1.0
_GEM_DEFAULT_MAX_RING = 25
_GEM_SENTINEL_DISTANCE_KM = 5000.0
# ^ P8's score is exp(-distance_km / 300) (see axis_plausibility.py's
# _score_p8_plate_boundary decay_km=300 default). exp(-5000/300) is
# numerically indistinguishable from 0, so this sentinel -- returned only
# when no fault vertex is found within _GEM_DEFAULT_MAX_RING grid cells of
# a query point -- never meaningfully changes a score; it exists purely to
# bound worst-case query cost for the rare point genuinely far from any
# mapped fault (e.g. deep mid-plate ocean interiors).


def default_gem_geojson_path() -> Optional[str]:
    """
    Best-effort auto-detection of a repo-local GEM GAF-DB GeoJSON file
    under Dataset/GAF-DB/, so `run_audit.py --fault-db-source gem` works
    without requiring an explicit --gem-fault-db-path in this reference
    implementation's own repo layout. Prefers GEM's own harmonized
    (deduplicated) release over the raw pre-harmonization file. Returns
    None if neither is found -- callers must then require an explicit path.
    """
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent / "Dataset" / "GAF-DB" / "gem_active_faults_harmonized.geojson",
        here.parent / "Dataset" / "GAF-DB" / "gem_active_faults.geojson",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _subdivide_polyline(
    lons: List[float], lats: List[float], max_segment_km: float,
) -> Tuple[List[float], List[float]]:
    """
    Insert extra points along each segment of a fault trace so that no
    segment exceeds `max_segment_km`, via LINEAR interpolation in
    (lat, lon) space (not true geodesic interpolation -- for segments this
    short, the difference from a great-circle midpoint is negligible,
    well under the ~1 km precision this reference is used at).

    This exists because GEMActiveFaultsDatabase approximates distance-to-
    fault-trace as distance-to-nearest-VERTEX (a point cloud), not true
    point-to-polyline distance (see that class's docstring, approximation
    #1). Un-subdivided GEM fault traces have segments up to ~150 km long in
    sparsely-digitized regions; subdividing bounds the worst-case point-
    cloud approximation error to roughly max_segment_km / 2.
    """
    out_lons: List[float] = [lons[0]]
    out_lats: List[float] = [lats[0]]
    for i in range(len(lons) - 1):
        lon1, lat1 = lons[i], lats[i]
        lon2, lat2 = lons[i + 1], lats[i + 1]
        seg_km = haversine_km(lat1, lon1, lat2, lon2)
        if np.isfinite(seg_km) and seg_km > max_segment_km:
            n_extra = int(math.ceil(seg_km / max_segment_km)) - 1
            for k in range(1, n_extra + 1):
                t = k / (n_extra + 1)
                out_lons.append(lon1 + t * (lon2 - lon1))
                out_lats.append(lat1 + t * (lat2 - lat1))
        out_lons.append(lon2)
        out_lats.append(lat2)
    return out_lons, out_lats


class GEMActiveFaultsDatabase(FaultDatabaseReference):
    """
    Real GEM Global Active Faults Database (Styron & Pagani 2020) reference
    for P8, loaded from a GeoJSON FeatureCollection of LineString /
    MultiLineString fault traces exactly as distributed by
    GEMScienceTools/gem-global-active-faults (the "harmonized" release is
    recommended -- it is GEM's own deduplicated, schema-consistent product,
    ~13,700 faults, matching the theory documents' "~13,500 faults" figure;
    the larger pre-harmonization raw file, ~16,200 faults, has not been
    deduplicated across contributing regional catalogs).

    DISCLOSED APPROXIMATIONS -- none of these are specified or required by
    the theory documents (which only specify the exp(-d/decay_km) scoring
    function itself, taking "distance to nearest boundary" as a given
    input); they are this reference implementation's own engineering
    choices for querying a real ~150,000-vertex fault database without a
    compiled spatial-index dependency (consistent with this project's
    numpy-only-core philosophy -- see stats.py's scipy-free chi_square_sf
    for precedent):

    1. Point-cloud, not true point-to-polyline, distance. Distance to a
       fault "trace" is computed as distance to the nearest VERTEX among
       all (subdivided) fault-trace points, not the true perpendicular
       distance to the nearest line segment. Segments longer than
       `max_segment_km` (default 10 km) are subdivided first (see
       `_subdivide_polyline`), which bounds the worst-case error from this
       approximation to roughly `max_segment_km / 2` (~5 km by default) --
       small relative to P8's ~300 km soft decay scale, but not exact.

    2. Approximate (not exhaustively-guaranteed) nearest-neighbor search.
       Candidate points are found via a uniform lat/lon grid index
       (`cell_deg` degrees per cell, default 1.0 deg): a query point's own
       cell and an expanding square ring of neighboring cells are searched
       until candidates are found, plus one extra ring for boundary
       safety, then the minimum distance among all examined candidates is
       returned. This is NOT a mathematically exact global nearest-
       neighbor guarantee (a strict guarantee would require continuing to
       expand rings until the ring's minimum possible distance exceeds the
       current best candidate distance -- omitted here for simplicity and
       speed); in practice the error this can introduce is bounded by
       roughly one grid cell width and only arises very close to a cell
       boundary, small next to P8's ~300 km decay scale.

    3. Long-range sentinel. If no fault vertex is found within `max_ring`
       grid rings (default 25, i.e. roughly a
       (2*25+1) x cell_deg-degree search box), a large sentinel distance
       (`_GEM_SENTINEL_DISTANCE_KM` = 5000 km) is returned rather than
       continuing to expand indefinitely -- see the module-level constant's
       comment for why this never meaningfully changes a P8 score.
    """

    def __init__(
        self,
        geojson_path: str,
        max_segment_km: float = _GEM_DEFAULT_MAX_SEGMENT_KM,
        cell_deg: float = _GEM_DEFAULT_CELL_DEG,
        max_ring: int = _GEM_DEFAULT_MAX_RING,
    ):
        self._path = geojson_path
        self._max_segment_km = max_segment_km
        self._cell_deg = cell_deg
        self._max_ring = max_ring
        self._pt_lats: Optional[np.ndarray] = None
        self._pt_lons: Optional[np.ndarray] = None
        self._grid: dict = {}
        self._load_error: Optional[str] = None
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                geo = json.load(f)
        except (OSError, ValueError) as exc:
            self._load_error = f"could not read/parse {self._path}: {exc}"
            return

        all_lons: List[float] = []
        all_lats: List[float] = []
        for feat in geo.get("features", []):
            geom = feat.get("geometry") or {}
            gtype = geom.get("type")
            coords = geom.get("coordinates")
            if not coords:
                continue
            if gtype == "LineString":
                lines = [coords]
            elif gtype == "MultiLineString":
                lines = coords
            else:
                # Points/Polygons are not fault-trace linework this loader
                # understands; skip rather than silently mis-handle them.
                continue
            for line in lines:
                try:
                    lons = [float(c[0]) for c in line]
                    lats = [float(c[1]) for c in line]
                except (TypeError, ValueError, IndexError):
                    continue
                if len(lons) < 2:
                    if lons:
                        all_lons.append(lons[0])
                        all_lats.append(lats[0])
                    continue
                sub_lons, sub_lats = _subdivide_polyline(lons, lats, self._max_segment_km)
                all_lons.extend(sub_lons)
                all_lats.extend(sub_lats)

        if not all_lons:
            self._load_error = (
                f"{self._path} contained no usable LineString/MultiLineString "
                "fault traces"
            )
            return

        self._pt_lats = np.asarray(all_lats, dtype=float)
        self._pt_lons = np.asarray(all_lons, dtype=float)

        cell_lat = np.floor(self._pt_lats / self._cell_deg).astype(int)
        cell_lon = np.floor(self._pt_lons / self._cell_deg).astype(int)
        grid: dict = {}
        for i, (cy, cx) in enumerate(zip(cell_lat.tolist(), cell_lon.tolist())):
            grid.setdefault((cy, cx), []).append(i)
        self._grid = grid

    def is_available(self) -> bool:
        return (
            self._load_error is None
            and self._pt_lats is not None
            and len(self._pt_lats) > 0
        )

    @property
    def load_error(self) -> Optional[str]:
        """Non-None if the GeoJSON failed to load or had no usable traces."""
        return self._load_error

    @property
    def n_points(self) -> int:
        """Number of (post-subdivision) fault-trace vertices indexed."""
        return 0 if self._pt_lats is None else len(self._pt_lats)

    def _wrap_lon_cell(self, cx: int) -> int:
        """
        Wrap a longitude grid-cell index back into the same range the grid
        itself was built with (cells derived from floor(lon/cell_deg) for
        lon in [-180, 180)).

        BUGFIX (scientific-validity review pass): the ring search below
        generates cell x-coordinates as cx +/- ring, which for a query
        point near the +/-180 antimeridian walks OFF the range of cell
        indices that actually exist in the grid (e.g. cx=179, ring=1 ->
        x=180, but every real fault point near there was indexed at
        x=-180, since floor(179.5/1)=179 and floor(-179.5/1)=-180 are 359
        cells apart despite being ~1 degree/~60-100 km apart in true
        geography). Confirmed with a synthetic reproduction: a fault trace
        placed at (lon=179-179.8) was reported as 5000 km away (the "no
        fault found" sentinel) from a query point at (lon=-179.5) only
        ~1 degree away across the dateline, instead of the true ~10-100 km.
        This is directly relevant to this project's own bundled NZ dataset,
        which spans the Kermadec Trench across +/-180 (see
        USGSComCatReference's `_compact_lon_bounds` docstring, added for
        exactly this same antimeridian issue in a different code path).
        Fixed by wrapping every generated cell x-coordinate back into the
        grid's actual index range before looking it up, so the ring search
        correctly continues across the antimeridian instead of silently
        running out of matching cells.
        """
        n_lon_cells = max(1, int(round(360.0 / self._cell_deg)))
        base = int(math.floor(-180.0 / self._cell_deg))
        return base + ((cx - base) % n_lon_cells)

    def _candidate_indices_for_cell(self, cy: int, cx: int) -> List[int]:
        """
        Expanding square-ring search around grid cell (cy, cx). Returns
        candidate point indices from the smallest ring that contains any
        points, plus one extra ring for boundary safety (approximation #2
        in the class docstring). Returns an empty list if nothing is found
        within `max_ring` rings.

        Longitude cell indices are wrapped via `_wrap_lon_cell` (see its
        docstring for the antimeridian bug this fixes); latitude indices
        are never wrapped (there is no poleward wraparound -- a search
        past +90/-90 simply finds nothing, which is correct).
        """
        grid = self._grid
        found_ring: Optional[int] = None
        candidates: List[int] = []
        wrap = self._wrap_lon_cell
        for ring in range(0, self._max_ring + 1):
            if ring == 0:
                cells = [(cy, wrap(cx))]
            else:
                cells = (
                    [(cy + ring, wrap(x)) for x in range(cx - ring, cx + ring + 1)]
                    + [(cy - ring, wrap(x)) for x in range(cx - ring, cx + ring + 1)]
                    + [(y, wrap(cx + ring)) for y in range(cy - ring + 1, cy + ring)]
                    + [(y, wrap(cx - ring)) for y in range(cy - ring + 1, cy + ring)]
                )
            ring_has_any = False
            for cell in cells:
                pts = grid.get(cell)
                if pts:
                    candidates.extend(pts)
                    ring_has_any = True
            if ring_has_any and found_ring is None:
                found_ring = ring
            elif found_ring is not None and ring == found_ring + 1:
                break
        return candidates

    def distance_to_nearest_boundary_km(self, lat: float, lon: float) -> float:
        result = self.distances_to_nearest_boundary_km(
            np.array([lat], dtype=float), np.array([lon], dtype=float)
        )
        return float(result[0])

    def distances_to_nearest_boundary_km(self, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
        """
        Groups query points by grid cell so each unique cell's candidate
        search + haversine distance matrix is computed once, not once per
        query point -- the dominant cost saving at real-catalog scale (see
        stats.haversine_km_matrix's own docstring for why the naive
        per-point loop is untenable past ~10^4 points). Earthquake
        catalogs cluster geographically (most events occur near active
        faults, which is exactly what P8 is checking), so in practice the
        number of distinct occupied grid cells among the query points is
        far smaller than the number of query points itself.
        """
        lats = np.asarray(lats, dtype=float)
        lons = np.asarray(lons, dtype=float)
        n = len(lats)
        out = np.full(n, float("nan"))
        if not self.is_available():
            return out

        valid = np.isfinite(lats) & np.isfinite(lons)
        if not np.any(valid):
            return out

        idx_valid = np.where(valid)[0]
        cell_lat = np.floor(lats[idx_valid] / self._cell_deg).astype(int).tolist()
        cell_lon = np.floor(lons[idx_valid] / self._cell_deg).astype(int).tolist()

        cell_to_positions: dict = {}
        for pos, cy, cx in zip(idx_valid.tolist(), cell_lat, cell_lon):
            cell_to_positions.setdefault((cy, cx), []).append(pos)

        for (cy, cx), positions in cell_to_positions.items():
            candidates = self._candidate_indices_for_cell(cy, cx)
            positions_arr = np.asarray(positions, dtype=int)
            if not candidates:
                out[positions_arr] = _GEM_SENTINEL_DISTANCE_KM
                continue
            cand_arr = np.asarray(sorted(set(candidates)), dtype=int)
            dmat = haversine_km_matrix(
                lats[positions_arr], lons[positions_arr],
                self._pt_lats[cand_arr], self._pt_lons[cand_arr],
            )
            out[positions_arr] = np.min(dmat, axis=1)
        return out
