# -*- coding: utf-8 -*-
"""Tests for data_certify/schema.py -- canonical schema and CSV I/O."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_certify.schema import ALL_FIELDS, REQUIRED_FIELDS, load_dataset_csv, save_dataset_csv
from conftest import make_dataset


class TestCertifyDataset:
    def test_required_missingness_all_present(self):
        ds = make_dataset(n=20)
        missing = ds.required_missingness()
        assert set(missing.keys()) == set(REQUIRED_FIELDS)
        assert all(v == 0.0 for v in missing.values())

    def test_required_missingness_detects_nan(self):
        ds = make_dataset(n=10)
        ds.magnitude[:3] = np.nan
        missing = ds.required_missingness()
        assert missing["magnitude"] == pytest.approx(0.3)

    def test_origin_time_days_monotonic_for_sorted_input(self):
        ds = make_dataset(n=10)
        days = ds.origin_time_days()
        assert np.all(np.diff(days) > 0)

    def test_subset_reduces_length_consistently(self):
        ds = make_dataset(n=10)
        mask = np.array([True] * 5 + [False] * 5)
        sub = ds.subset(mask)
        assert sub.n == 5
        assert len(sub.latitude) == 5

    def test_sort_by_time_handles_nat(self):
        ds = make_dataset(n=5)
        ds.origin_time[2] = np.datetime64("NaT")
        sorted_ds = ds.sort_by_time()
        assert sorted_ds.n == 5


class TestCSVRoundTrip:
    def test_save_then_load_roundtrip(self, tmp_path):
        ds = make_dataset(n=15)
        ds.magnitude_type[0] = "Mw"
        ds.seismic_moment_n_m[0] = 1.2e18
        out_path = tmp_path / "records.csv"
        save_dataset_csv(ds, out_path)

        loaded = load_dataset_csv(out_path, name="roundtrip")
        assert loaded.n == 15
        assert loaded.magnitude_type[0] == "Mw"
        assert loaded.seismic_moment_n_m[0] == pytest.approx(1.2e18, rel=1e-6)
        np.testing.assert_allclose(loaded.magnitude, ds.magnitude)

    def test_missing_required_column_raises(self, tmp_path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("latitude,longitude,depth_km,magnitude\n1,2,3,4\n")
        with pytest.raises(ValueError):
            load_dataset_csv(bad_csv)

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_dataset_csv(tmp_path / "does_not_exist.csv")

    def test_empty_file_raises(self, tmp_path):
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text(",".join(ALL_FIELDS) + "\n")
        with pytest.raises(ValueError):
            load_dataset_csv(empty_csv)
