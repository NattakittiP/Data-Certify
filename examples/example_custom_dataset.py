# -*- coding: utf-8 -*-
"""
Example: Custom Synthetic Dataset -- Three Audit Outcomes
============================================================

Demonstrates the full ADMIT / CONDITIONAL / REJECT decision space of the
DATA-CERTIFY audit protocol using three small, entirely synthetic catalogs
built in this script (no external files needed):

    1. "clean"      -- a genuine Gutenberg-Richter magnitude distribution,
                       plausible depths/coordinates, no anomalies. Should
                       score well on Authenticity and Plausibility.

    2. "fabricated" -- magnitudes drawn UNIFORMLY instead of exponentially
                       (violates the Gutenberg-Richter law that essentially
                       every real earthquake catalog obeys -- Deep-Dive 03,
                       Section 2.1) and coordinates that are suspiciously
                       uniform across a 2D box (fails A4's fractal-dimension
                       check). Demonstrates a LOW Authenticity score that
                       is not necessarily a hard REJECT -- fabrication
                       signals here are graded (A2, A4), not the A6
                       confirmed-fabrication floor.

    3. "corrupted"  -- a genuine GR catalog with a concentrated cluster of
                       physically impossible records (out-of-range
                       latitude/longitude on ~15% of rows). Demonstrates
                       the Stage-1 hard-override veto: REJECT fires
                       unconditionally, regardless of how good the rest of
                       the catalog's T(D) would otherwise be.

Usage:
    python examples/example_custom_dataset.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from data_certify import CertifyDataset, DataCertifyAuditor
from data_certify.schema import ALL_FIELDS


def banner(text: str) -> None:
    w = 65
    print(f"\n{'='*w}")
    print(f"  {text}")
    print(f"{'='*w}")


def section(text: str) -> None:
    dashes = max(0, 55 - len(text))
    print(f"\n-- {text} {'-'*dashes}")


def _blank_dataset(name: str, n: int, **overrides) -> CertifyDataset:
    """Build a CertifyDataset with sensible defaults for every field, so
    callers only need to specify the fields relevant to the scenario being
    demonstrated. Mirrors the pattern used throughout tests/conftest.py."""
    base_time = np.datetime64("2020-01-01T00:00:00", "ns")
    hour = np.timedelta64(1, "h")
    defaults = dict(
        name=name,
        n=n,
        origin_time=(base_time + np.arange(n) * hour).astype("datetime64[ns]"),
        latitude=np.zeros(n),
        longitude=np.zeros(n),
        depth_km=np.full(n, 10.0),
        magnitude=np.full(n, 4.0),
        magnitude_type=np.array([""] * n, dtype="<U16"),
        seismic_moment_n_m=np.full(n, np.nan),
        tsunami_flag=np.full(n, np.nan),
        mechanism=np.array([""] * n, dtype="<U32"),
        source=np.array([""] * n, dtype="<U64"),
        event_uid_source=np.array([""] * n, dtype="<U64"),
        revision_status=np.array([""] * n, dtype="<U16"),
        mmi=np.full(n, np.nan),
        station_distance_km=np.full(n, np.nan),
        rupture_length_km=np.full(n, np.nan),
        rupture_area_km2=np.full(n, np.nan),
        rupture_displacement_m=np.full(n, np.nan),
        azimuthal_gap_deg=np.full(n, np.nan),
    )
    defaults.update(overrides)
    return CertifyDataset(**{k: defaults[k] for k in ("name", "n", *ALL_FIELDS)})


def make_clean_catalog(n: int = 2000, seed: int = 1) -> CertifyDataset:
    """A genuine, physically plausible synthetic catalog: Gutenberg-Richter
    exponential magnitudes above a completeness floor, coordinates and
    depths scattered the way a real regional catalog's would be."""
    rng = np.random.RandomState(seed)
    mc, b_value = 3.0, 1.0
    beta = b_value * np.log(10.0)
    magnitude = mc + rng.exponential(1.0 / beta, size=n)
    latitude = rng.normal(-20.0, 8.0, n)   # clustered around a plausible fault zone
    longitude = rng.normal(-70.0, 8.0, n)
    depth_km = np.clip(rng.exponential(30.0, n), 0.1, 700.0)
    return _blank_dataset("clean", n, magnitude=magnitude, latitude=latitude,
                           longitude=longitude, depth_km=depth_km)


def make_fabricated_catalog(n: int = 2000, seed: int = 2) -> CertifyDataset:
    """Magnitudes drawn uniformly (violates Gutenberg-Richter) and
    coordinates scattered uniformly across a 2D box (fails A4's
    fractal-dimension check, which expects real seismicity to cluster
    along lower-dimensional fault structures, not fill 2D space evenly)."""
    rng = np.random.RandomState(seed)
    magnitude = rng.uniform(3.0, 7.5, n)
    latitude = rng.uniform(-40.0, 40.0, n)
    longitude = rng.uniform(-40.0, 40.0, n)
    depth_km = rng.uniform(0.0, 700.0, n)
    return _blank_dataset("fabricated", n, magnitude=magnitude, latitude=latitude,
                           longitude=longitude, depth_km=depth_km)


def make_corrupted_catalog(n: int = 2000, seed: int = 3,
                            corrupt_fraction: float = 0.15) -> CertifyDataset:
    """A genuine GR catalog with a concentrated cluster of physically
    impossible latitude/longitude values injected -- demonstrates the
    hard-override veto (P1's Clopper-Pearson non-trivial-fraction test)."""
    clean = make_clean_catalog(n=n, seed=seed)
    n_corrupt = int(n * corrupt_fraction)
    idx = np.arange(n_corrupt)  # concentrated, not scattered -- see hard_override.py
    corrupted_lat = clean.latitude.copy()
    corrupted_lon = clean.longitude.copy()
    corrupted_lat[idx] = 999.0
    corrupted_lon[idx] = 999.0
    return _blank_dataset("corrupted", n, magnitude=clean.magnitude,
                           latitude=corrupted_lat, longitude=corrupted_lon,
                           depth_km=clean.depth_km)


def print_result(result) -> None:
    print(str(result))


def main() -> None:
    banner("DATA-CERTIFY: Custom Synthetic Dataset Example")

    clean = make_clean_catalog()
    fabricated = make_fabricated_catalog()
    corrupted = make_corrupted_catalog()

    auditor = DataCertifyAuditor()

    section("1. Clean catalog (genuine Gutenberg-Richter, plausible geometry)")
    r_clean = auditor.audit(clean)
    print_result(r_clean)

    section("2. Fabricated catalog (uniform magnitudes + uniform 2D coordinates)")
    r_fab = auditor.audit(fabricated)
    print_result(r_fab)
    a2 = r_fab.axis_results["A"].sub_results.get("A2")
    a4 = r_fab.axis_results["A"].sub_results.get("A4")
    print("  Diagnostic detail:")
    if a2 is not None and a2.applicable:
        print(f"    A2 (Gutenberg-Richter fit) score = {a2.score:.4f}  -- {a2.note}")
    if a4 is not None and a4.applicable:
        print(f"    A4 (fractal dimension)    score = {a4.score:.4f}  -- {a4.note}")
    print("\n  NOTE: A2 still scores this uniform-magnitude catalog fairly (>0.8) -- its")
    print("  score is a soft linear decay around b_hat=1.0 (main framework Section 3.1),")
    print("  which gives partial credit to any MLE-fitted b-value within ~0.5 of 1.0")
    print("  regardless of whether the underlying distribution is actually exponential.")
    print("  A4 (fractal dimension) is what actually catches this fabrication -- real")
    print("  seismicity clusters along lower-dimensional fault structures, so a")
    print("  suspiciously uniform 2D scatter (Dc -> 2.0) scores poorly. This is exactly")
    print("  why A(D) combines multiple independent sub-tests rather than relying on")
    print("  any single one.")

    section("3. Corrupted catalog (15% concentrated lat/lon violations)")
    r_corrupt = auditor.audit(corrupted)
    print_result(r_corrupt)
    print(f"  Quarantined record count: {len(r_corrupt.hard_override.quarantined_indices)}")

    section("Summary")
    print(f"  {'Scenario':<14} {'Decision':<14} {'T(D)':>8} {'A(D)':>8}  Hard override")
    for label, r in (("clean", r_clean), ("fabricated", r_fab), ("corrupted", r_corrupt)):
        ts = "N/A" if r.trust_score is None else f"{r.trust_score:.4f}"
        a_axis = r.axis_results.get("A")
        a_str = f"{a_axis.score:.4f}" if a_axis is not None else "N/A"
        print(f"  {label:<14} {r.decision.value:<14} {ts:>8} {a_str:>8}  {r.hard_override.fired}")
    print("\n  Note T(D) alone does not cleanly separate clean vs. fabricated here (both")
    print("  land in the same indifference zone) -- but A(D), the axis fabrication")
    print("  actually targets, correctly ranks clean above fabricated. This is a real,")
    print("  disclosed limitation of the current, provisional weights/thresholds,")
    print("  not a hidden one.")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
