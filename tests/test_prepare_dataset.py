# -*- coding: utf-8 -*-
"""
Tests for prepare_dataset.py -- specifically the date/time column
auto-detection logic (single combined column vs. separate date+time pair).

Regression coverage for a real bug found during manual verification: a raw
CSV with capitalized "Date"/"Time" columns was silently mis-handled because
CANDIDATES["origin_time"] (for a single, already-combined column) includes a
bare "time" -- so the single-column auto-detect pass matched "Time" alone
and ignored the sibling "Date" column entirely, defaulting every event's
date portion to *today's* date via pandas' bare-time parsing behavior. Fixed
by preferring the full date+time pair whenever the single-column match is
either absent or is exactly the time-half of an available pair.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from prepare_dataset import DATASETS_DIR, prepare


def _write_csv(tmp_path: Path, name: str, header: str, rows: list) -> Path:
    p = tmp_path / (name + ".csv")
    p.write_text(header + "\n" + "\n".join(rows) + "\n")
    return p


def _origin_times(out_path: Path) -> list:
    lines = out_path.read_text().splitlines()
    return [line.split(",")[0] for line in lines[1:]]


@pytest.fixture
def cleanup_dataset():
    """Track dataset names created during a test and remove their
    datasets/<name>/ output directory afterward, so repeated test runs
    don't accumulate stray folders under the real datasets/ tree."""
    created = []

    def _register(name: str) -> str:
        created.append(name)
        return name

    yield _register
    for name in created:
        shutil.rmtree(DATASETS_DIR / name, ignore_errors=True)


class TestDateTimeAutoDetection:
    def test_split_date_and_time_columns_auto_detected(self, tmp_path, cleanup_dataset):
        """A catalog splitting date and time into two separate, lower-case,
        underscore-suffixed columns (e.g. USGS-export-style "date_utc" /
        "time_utc") must be merged automatically, with no CLI flags."""
        name = cleanup_dataset("test_split_utc")
        csv = _write_csv(
            tmp_path, name,
            "event_id,date_utc,time_utc,latitude,longitude,depth_km,magnitude",
            ["1,2020-01-01,00:00:00,10.0,20.0,5.0,4.5",
             "2,2020-01-02,12:30:00,11.0,21.0,6.0,5.1"],
        )
        out = prepare(csv, name, {}, interactive=False)
        assert _origin_times(out) == [
            "2020-01-01T00:00:00.000000",
            "2020-01-02T12:30:00.000000",
        ]

    def test_single_combined_column_still_works(self, tmp_path, cleanup_dataset):
        """A single column that already holds a full timestamp (e.g.
        "datetime") must still be used directly, not routed through the
        pair-detection path."""
        name = cleanup_dataset("test_single_combined")
        csv = _write_csv(
            tmp_path, name,
            "id,datetime,lat,lon,depth,mag",
            ["1,2020-01-01T00:00:00,10.0,20.0,5.0,4.5",
             "2,2020-01-02T12:30:00,11.0,21.0,6.0,5.1"],
        )
        out = prepare(csv, name, {}, interactive=False)
        assert _origin_times(out) == [
            "2020-01-01T00:00:00.000000",
            "2020-01-02T12:30:00.000000",
        ]

    def test_capitalized_date_time_pair_not_mistaken_for_single_column(
        self, tmp_path, cleanup_dataset
    ):
        """REGRESSION TEST for the real bug found during manual verification:
        a capitalized "Date"/"Time" pair must be merged as a pair, not have
        the bare "Time" column alone treated as a full origin_time (which
        would silently default every event's date to today's date, since
        CANDIDATES["origin_time"] includes a bare "time" for catalogs where
        a single column genuinely holds a full timestamp named just
        "Time"). Uses non-today dates (2020) so the test would fail loudly
        under the old buggy behavior instead of coincidentally passing."""
        name = cleanup_dataset("test_date_time_pair_not_single")
        csv = _write_csv(
            tmp_path, name,
            "Date,Time,Latitude,Longitude,Depth,Magnitude",
            ["2020-01-01,00:00:00,10.0,20.0,5.0,4.5",
             "2020-01-02,12:30:00,11.0,21.0,6.0,5.1"],
        )
        out = prepare(csv, name, {}, interactive=False)
        origin_times = _origin_times(out)
        assert origin_times == [
            "2020-01-01T00:00:00.000000",
            "2020-01-02T12:30:00.000000",
        ]
        # Explicitly assert against the bug's actual failure mode: neither
        # row's date portion should be today's date (or any date other
        # than the 2020 dates actually in the CSV).
        for ts in origin_times:
            assert ts.startswith("2020-01-0"), (
                f"origin_time {ts!r} does not start with the CSV's own "
                f"2020-01-0x date -- the 'Date' column was likely dropped "
                f"and only 'Time' was used, defaulting the date portion."
            )

    def test_standalone_time_column_with_full_timestamp_and_no_date_sibling(
        self, tmp_path, cleanup_dataset
    ):
        """If a column is literally named "Time" but holds a FULL timestamp
        and there is no sibling "Date"-like column at all, the single-column
        path must still be used (pair-detection requires both halves)."""
        name = cleanup_dataset("test_time_is_full_timestamp")
        csv = _write_csv(
            tmp_path, name,
            "id,Time,lat,lon,depth,mag",
            ["1,2020-01-01T00:00:00,10.0,20.0,5.0,4.5",
             "2,2020-01-02T12:30:00,11.0,21.0,6.0,5.1"],
        )
        out = prepare(csv, name, {}, interactive=False)
        assert _origin_times(out) == [
            "2020-01-01T00:00:00.000000",
            "2020-01-02T12:30:00.000000",
        ]

    def test_explicit_origin_time_override_not_overridden_by_pair_detection(
        self, tmp_path, cleanup_dataset
    ):
        """An explicit --origin-time-col (column_overrides) must win outright
        even when a sibling "Date"-like column exists and would otherwise
        trigger pair-detection -- the user's explicit choice must never be
        silently second-guessed."""
        name = cleanup_dataset("test_explicit_override")
        csv = _write_csv(
            tmp_path, name,
            "Date,Time,lat,lon,depth,mag",
            ["2020-01-01,08:00:00,10.0,20.0,5.0,4.5",
             "2020-01-02,09:00:00,11.0,21.0,6.0,5.1"],
        )
        out = prepare(csv, name, {"origin_time": "Time"}, interactive=False)
        # With the override pinned to the bare 'Time' column (which here
        # holds ONLY a time-of-day, no date), pandas' bare-time parsing
        # fills in today's UTC date -- this is the user's explicit,
        # intentional choice, so it must be honored exactly, not "fixed up"
        # by auto-pairing with 'Date'.
        origin_times = _origin_times(out)
        assert origin_times[0].endswith("T08:00:00.000000")
        assert origin_times[1].endswith("T09:00:00.000000")
