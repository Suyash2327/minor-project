"""
pipeline.py — End-to-end integration: Forecast -> Optimize -> Schedule
=====================================================================
One function that:
  1. Reads recent raw data (or uses the test split)
  2. Generates features
  3. Runs the best trained forecasting model
  4. Passes the forecast to the LP optimizer
  5. Runs the rule-based baseline for comparison
  6. Returns a results dict ready for the dashboard

Usage:
    python src/pipeline.py
"""

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
import joblib
from pathlib import Path

import tensorflow as tf

ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT / "models"
PROC_DIR   = ROOT / "data" / "processed"
RAW_DIR    = ROOT / "data" / "raw"

LSTM_WINDOW = 24
TARGET = "load_kw"

TREE_FEATURES = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_weekend", "month",
    "temperature", "solar_irradiance", "grid_price",
    "load_kw_lag1", "load_kw_lag24", "load_kw_lag168",
    "load_kw_roll3_mean", "load_kw_roll24_mean", "load_kw_roll24_std",
]


# ──────────────────────────────────────────────────────────
# Model loading helpers
# ──────────────────────────────────────────────────────────

def load_best_model():
    best_name = (MODELS_DIR / "best_model.txt").read_text().strip()
    scaler = joblib.load(MODELS_DIR / "scaler.joblib")

    if best_name == "random_forest":
        model = joblib.load(MODELS_DIR / "rf_model.joblib")
        return "tree", best_name, model, scaler
    elif best_name == "xgboost":
        model = joblib.load(MODELS_DIR / "xgb_model.joblib")
        return "tree", best_name, model, scaler
    else:  # lstm
        model = tf.keras.models.load_model(MODELS_DIR / "lstm_model.keras")
        lstm_scaler = joblib.load(MODELS_DIR / "lstm_scaler.joblib")
        lstm_features = json.loads((MODELS_DIR / "lstm_features.json").read_text())
        return "lstm", best_name, model, (lstm_scaler, lstm_features)


# ──────────────────────────────────────────────────────────
# Feature engineering helpers (mirrors data.py, no I/O)
# ──────────────────────────────────────────────────────────

def _add_time_features(df):
    df["hour"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(int)
    df["month"] = df.index.month
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"]  = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"]  = np.cos(2 * np.pi * df["day_of_week"] / 7)
    return df


def _engineer(df):
    df = _add_time_features(df)
    df["load_kw_lag1"]       = df[TARGET].shift(1)
    df["load_kw_lag24"]      = df[TARGET].shift(24)
    df["load_kw_lag168"]     = df[TARGET].shift(168)
    df["load_kw_roll3_mean"] = df[TARGET].shift(1).rolling(3).mean()
    df["load_kw_roll24_mean"]= df[TARGET].shift(1).rolling(24).mean()
    df["load_kw_roll24_std"] = df[TARGET].shift(1).rolling(24).std()
    df.dropna(inplace=True)
    return df


# ──────────────────────────────────────────────────────────
# Forecast function
# ──────────────────────────────────────────────────────────

def forecast_next_24(
    recent_df: pd.DataFrame,
    model_type: str,
    model,
    scaler,
) -> np.ndarray:
    """
    Given a DataFrame of recent engineered features, predict the next 24 hours.
    Uses the last 24 rows (or LSTM window) of recent_df.
    """
    if model_type == "tree":
        # Take the last 24 rows -> predict each independently
        X = recent_df[TREE_FEATURES].tail(24).values
        X_scaled = scaler.transform(X)
        return model.predict(X_scaled)

    else:  # LSTM
        lstm_scaler, lstm_features = scaler
        feats = [f for f in lstm_features if f in recent_df.columns]
        vals = lstm_scaler.transform(recent_df[feats].values)
        # Take the last LSTM_WINDOW rows as the input sequence
        window = vals[-LSTM_WINDOW:]  # shape (LSTM_WINDOW, n_features)
        predictions = []
        for _ in range(24):
            X_input = window[np.newaxis, :, :]  # (1, LSTM_WINDOW, n_features)
            y_scaled = model.predict(X_input, verbose=0)[0, 0]
            # Build a dummy inverse-transform
            dummy = np.zeros((1, lstm_scaler.n_features_in_))
            dummy[0, 0] = y_scaled
            y_kw = lstm_scaler.inverse_transform(dummy)[0, 0]
            predictions.append(y_kw)
            # Roll the window: drop oldest, append new row (copy last row, update load)
            new_row = window[-1].copy()
            new_row[0] = y_scaled  # update load channel
            window = np.vstack([window[1:], new_row[np.newaxis, :]])
        return np.array(predictions)


# ──────────────────────────────────────────────────────────
# Main pipeline function
# ──────────────────────────────────────────────────────────

def run_pipeline(
    horizon: int = 24,
    init_soc: float = 0.5,
    use_period: str = "test",   # "test" | "val"
) -> dict:
    """
    Full pipeline: load data -> forecast -> optimize -> baseline.

    Returns a dict with keys:
      timestamps       : list of datetime strings
      actual_load      : actual load (kW)
      forecast_load    : model forecast (kW)
      solar_available  : solar power (kW)
      grid_prices      : price per kWh
      optimized        : DataFrame from LP optimizer
      baseline         : DataFrame from rule-based controller
      model_name       : name of the forecasting model used
      metrics          : MAE/RMSE/MAPE of the forecast on this period
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error

    # ── Load data ────────────────────────────────────────
    feat_df = pd.read_csv(PROC_DIR / f"{use_period}.csv", index_col=0, parse_dates=True)

    # Ensure we have at least horizon + LSTM_WINDOW rows
    context_rows = LSTM_WINDOW + 168  # 1 week of history to build lags
    if len(feat_df) < context_rows + horizon:
        raise ValueError(f"Not enough rows in {use_period}.csv")

    # Context window: history used to feed the model
    context = feat_df.iloc[:context_rows]
    # Forecast window: next `horizon` hours (the period we predict)
    target_slice = feat_df.iloc[context_rows : context_rows + horizon]

    actual_load     = target_slice[TARGET].values
    solar_available = target_slice["solar_kw"].values
    grid_prices     = target_slice["grid_price"].values
    timestamps      = target_slice.index.strftime("%Y-%m-%d %H:%M").tolist()

    # ── Load model ────────────────────────────────────────
    model_type, model_name, model, scaler = load_best_model()

    # ── Forecast ─────────────────────────────────────────
    # Build a combined context that includes target hours (for tree feature lookup)
    combined = pd.concat([context, target_slice])
    combined = _engineer(combined.copy())

    forecast_load = forecast_next_24(combined, model_type, model, scaler)
    forecast_load = np.clip(forecast_load, 0, None)[:horizon]

    # ── Metrics ──────────────────────────────────────────
    mae  = float(mean_absolute_error(actual_load[:horizon], forecast_load))
    rmse = float(np.sqrt(mean_squared_error(actual_load[:horizon], forecast_load)))
    mask = np.abs(actual_load) > 0.5
    mape_val = float(
        np.mean(np.abs((actual_load[mask] - forecast_load[mask]) / actual_load[mask])) * 100
    ) if mask.sum() > 0 else float("nan")

    # ── Optimize ─────────────────────────────────────────
    from src.optimize import lp_optimize, rule_based_dispatch

    optimized = lp_optimize(forecast_load, solar_available, grid_prices, init_soc=init_soc)
    baseline  = rule_based_dispatch(actual_load, solar_available, grid_prices, init_soc=init_soc)

    return {
        "timestamps":      timestamps,
        "actual_load":     actual_load.tolist(),
        "forecast_load":   forecast_load.tolist(),
        "solar_available": solar_available.tolist(),
        "grid_prices":     grid_prices.tolist(),
        "optimized":       optimized,
        "baseline":        baseline,
        "model_name":      model_name,
        "metrics":         {"MAE": mae, "RMSE": rmse, "MAPE": mape_val},
    }


# ──────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────

def main():
    import sys
    print("=" * 55)
    print("  Running end-to-end pipeline ...")
    print("=" * 55)

    results = run_pipeline(horizon=24)

    print(f"\n[RUN]  Model used: {results['model_name'].upper()}")
    print(f"[METRICS]  Forecast metrics over 24 hours:")
    m = results["metrics"]
    print(f"    MAE  = {m['MAE']:.4f} kW")
    print(f"    RMSE = {m['RMSE']:.4f} kW")
    print(f"    MAPE = {m['MAPE']:.2f} %")

    opt_cost  = results["optimized"]["cost"].sum()
    base_cost = results["baseline"]["cost"].sum()
    saving    = (base_cost - opt_cost) / base_cost * 100 if base_cost > 0 else 0

    print(f"\n[COST]  24-hour cost comparison:")
    print(f"    Optimized : £{opt_cost:.2f}")
    print(f"    Baseline  : £{base_cost:.2f}")
    print(f"    Saving    : {saving:.1f}%")

    print("\n[OK]  Pipeline ran successfully. Launch dashboard with:")
    print("    streamlit run dashboard/dashboard.py")


if __name__ == "__main__":
    # Allow importing from parent directory
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
