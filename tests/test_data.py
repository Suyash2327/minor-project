"""
tests/test_data.py — Unit tests for the data pipeline
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from src.data import (
    build_raw_dataframe,
    clean,
    engineer_features,
    chronological_split,
    generate_timestamps,
    generate_load,
    generate_temperature,
    generate_solar_irradiance,
    N,
)


class TestRawDataGeneration:
    def test_row_count(self):
        df = build_raw_dataframe()
        assert len(df) == N, f"Expected {N} rows, got {len(df)}"

    def test_columns_present(self):
        df = build_raw_dataframe()
        for col in ["load_kw", "solar_kw", "grid_price", "temperature", "solar_irradiance"]:
            assert col in df.columns, f"Missing column: {col}"

    def test_load_non_negative(self):
        df = build_raw_dataframe()
        df = clean(df)
        assert (df["load_kw"] >= 0).all(), "Load has negative values"

    def test_solar_bounded(self):
        df = build_raw_dataframe()
        df = clean(df)
        assert (df["solar_kw"] >= 0).all(), "Solar power < 0"
        assert (df["solar_kw"] <= 5.5).all(), "Solar power exceeds physical limit"

    def test_grid_price_positive(self):
        df = build_raw_dataframe()
        df = clean(df)
        assert (df["grid_price"] > 0).all(), "Grid price ≤ 0"

    def test_index_is_datetime(self):
        df = build_raw_dataframe()
        assert isinstance(df.index, pd.DatetimeIndex)


class TestFeatureEngineering:
    def setup_method(self):
        raw = build_raw_dataframe()
        self.df = engineer_features(clean(raw))

    def test_time_feature_columns(self):
        for col in ["hour", "day_of_week", "is_weekend", "month",
                    "hour_sin", "hour_cos", "dow_sin", "dow_cos"]:
            assert col in self.df.columns

    def test_lag_feature_columns(self):
        for col in ["load_kw_lag1", "load_kw_lag24", "load_kw_lag168"]:
            assert col in self.df.columns

    def test_rolling_feature_columns(self):
        for col in ["load_kw_roll3_mean", "load_kw_roll24_mean", "load_kw_roll24_std"]:
            assert col in self.df.columns

    def test_no_nan_after_dropna(self):
        assert not self.df.isnull().any().any(), "NaN values remain after feature engineering"

    def test_hour_cyclical_range(self):
        assert self.df["hour_sin"].between(-1, 1).all()
        assert self.df["hour_cos"].between(-1, 1).all()

    def test_is_weekend_binary(self):
        assert set(self.df["is_weekend"].unique()).issubset({0, 1})


class TestChronologicalSplit:
    def setup_method(self):
        raw = build_raw_dataframe()
        self.feat = engineer_features(clean(raw))

    def test_no_overlap(self):
        train, val, test = chronological_split(self.feat)
        assert train.index.max() < val.index.min()
        assert val.index.max() < test.index.min()

    def test_total_rows_preserved(self):
        train, val, test = chronological_split(self.feat)
        assert len(train) + len(val) + len(test) == len(self.feat)

    def test_approximate_fractions(self):
        train, val, test = chronological_split(self.feat)
        n = len(self.feat)
        assert abs(len(train) / n - 0.70) < 0.02
        assert abs(len(val) / n - 0.15) < 0.02


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
