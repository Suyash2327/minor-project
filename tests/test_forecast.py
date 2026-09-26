"""
tests/test_forecast.py — Unit tests for the forecasting module
(These require trained models. Run after: python src/forecast.py)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
PROC_DIR   = Path(__file__).resolve().parent.parent / "data" / "processed"


@pytest.fixture(scope="module")
def trained_models():
    """Load all saved models — skip if not yet trained."""
    if not (MODELS_DIR / "best_model.txt").exists():
        pytest.skip("Models not trained yet. Run: python src/forecast.py")

    import joblib
    rf  = joblib.load(MODELS_DIR / "rf_model.joblib")
    xgb = joblib.load(MODELS_DIR / "xgb_model.joblib")
    sc  = joblib.load(MODELS_DIR / "scaler.joblib")
    return rf, xgb, sc


@pytest.fixture(scope="module")
def test_data():
    path = PROC_DIR / "test.csv"
    if not path.exists():
        pytest.skip("Processed data not found. Run: python src/data.py")
    return pd.read_csv(path, index_col=0, parse_dates=True)


TREE_FEATURES = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_weekend", "month",
    "temperature", "solar_irradiance", "grid_price",
    "load_kw_lag1", "load_kw_lag24", "load_kw_lag168",
    "load_kw_roll3_mean", "load_kw_roll24_mean", "load_kw_roll24_std",
]


class TestForecastOutputShape:
    def test_rf_output_shape(self, trained_models, test_data):
        rf, _, scaler = trained_models
        X = scaler.transform(test_data[TREE_FEATURES].values)
        preds = rf.predict(X)
        assert len(preds) == len(test_data), "RF prediction count mismatch"

    def test_xgb_output_shape(self, trained_models, test_data):
        _, xgb, scaler = trained_models
        X = scaler.transform(test_data[TREE_FEATURES].values)
        preds = xgb.predict(X)
        assert len(preds) == len(test_data), "XGB prediction count mismatch"

    def test_rf_predictions_positive(self, trained_models, test_data):
        rf, _, scaler = trained_models
        X = scaler.transform(test_data[TREE_FEATURES].values)
        preds = rf.predict(X)
        # Most predictions should be positive (load ≥ 0)
        assert np.mean(preds > 0) > 0.95, "Too many negative predictions"

    def test_rf_predictions_in_reasonable_range(self, trained_models, test_data):
        rf, _, scaler = trained_models
        X = scaler.transform(test_data[TREE_FEATURES].values)
        preds = rf.predict(X)
        # Load should be between 0 and 15 kW for a household microgrid
        assert preds.max() < 20, "RF predicts unrealistically high load"
        assert preds.min() > -1, "RF predicts unrealistically negative load"


class TestBestModelFile:
    def test_best_model_txt_exists(self):
        if not (MODELS_DIR / "best_model.txt").exists():
            pytest.skip("Run forecast.py first")
        content = (MODELS_DIR / "best_model.txt").read_text().strip()
        assert content in ["random_forest", "xgboost", "lstm"], \
            f"Unexpected best model name: '{content}'"

    def test_metrics_csv_exists(self):
        if not (MODELS_DIR / "metrics.csv").exists():
            pytest.skip("Run forecast.py first")
        df = pd.read_csv(MODELS_DIR / "metrics.csv")
        assert "MAE" in df.columns
        assert "RMSE" in df.columns
        assert len(df) >= 3, "Expected at least 3 model rows in metrics.csv"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
