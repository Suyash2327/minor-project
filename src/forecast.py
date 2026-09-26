"""
forecast.py — Train, evaluate, and save forecasting models
===========================================================
Models trained:
  1. Random Forest Regressor
  2. XGBoost Regressor
  3. LSTM (TensorFlow / Keras) with a sliding-window input

Evaluation metrics per model: MAE, RMSE, MAPE
Best model (lowest RMSE on validation set) is saved as 'best_model'.

Outputs:
  models/rf_model.joblib
  models/xgb_model.joblib
  models/lstm_model.keras
  models/scaler.joblib        ← StandardScaler fitted on training features
  models/best_model.txt       ← name of the best model
  models/metrics.csv          ← evaluation table
"""

import warnings
warnings.filterwarnings("ignore")

import os
import json
import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")   # headless rendering
import matplotlib.pyplot as plt
from pathlib import Path

from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error
import xgboost as xgb

import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping

# ──────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
PROC_DIR = ROOT / "data" / "processed"
MODELS_DIR = ROOT / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

TARGET = "load_kw"
LSTM_WINDOW = 24   # use past 24 hours to predict next hour

# Feature columns used by tree-based models
TREE_FEATURES = [
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "is_weekend", "month",
    "temperature", "solar_irradiance", "grid_price",
    "load_kw_lag1", "load_kw_lag24", "load_kw_lag168",
    "load_kw_roll3_mean", "load_kw_roll24_mean", "load_kw_roll24_std",
]

# Features used as input channels for LSTM (time-series)
LSTM_FEATURES = [
    "load_kw",
    "temperature", "solar_irradiance", "grid_price",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend",
]


# ──────────────────────────────────────────────────────────
# Metrics helpers
# ──────────────────────────────────────────────────────────

def mape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """MAPE — excludes near-zero actuals to avoid division explosion."""
    mask = np.abs(y_true) > 0.5   # exclude near-zero
    if mask.sum() == 0:
        return float("nan")
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def evaluate(name: str, y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    mae = mean_absolute_error(y_true, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    mape_val = mape(y_true, y_pred)
    print(f"  [{name}]  MAE={mae:.4f}  RMSE={rmse:.4f}  MAPE={mape_val:.2f}%")
    return {"model": name, "MAE": mae, "RMSE": rmse, "MAPE": mape_val}


# ──────────────────────────────────────────────────────────
# Data loading helpers
# ──────────────────────────────────────────────────────────

def load_splits() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train = pd.read_csv(PROC_DIR / "train.csv", index_col=0, parse_dates=True)
    val   = pd.read_csv(PROC_DIR / "val.csv",   index_col=0, parse_dates=True)
    test  = pd.read_csv(PROC_DIR / "test.csv",  index_col=0, parse_dates=True)
    return train, val, test


# ──────────────────────────────────────────────────────────
# Tree-based model helpers
# ──────────────────────────────────────────────────────────

def get_tree_xy(
    df: pd.DataFrame, scaler: StandardScaler | None = None, fit_scaler: bool = False
) -> tuple[np.ndarray, np.ndarray, StandardScaler]:
    X = df[TREE_FEATURES].values
    y = df[TARGET].values
    if fit_scaler:
        scaler = StandardScaler()
        X = scaler.fit_transform(X)
    else:
        X = scaler.transform(X)
    return X, y, scaler


# ──────────────────────────────────────────────────────────
# Model 1: Random Forest
# ──────────────────────────────────────────────────────────

def train_random_forest(X_train, y_train) -> RandomForestRegressor:
    print("\n[RF]    Training Random Forest ...")
    rf = RandomForestRegressor(
        n_estimators=300,
        max_depth=None,
        min_samples_leaf=3,
        n_jobs=-1,
        random_state=42,
    )
    rf.fit(X_train, y_train)
    return rf


# ──────────────────────────────────────────────────────────
# Model 2: XGBoost
# ──────────────────────────────────────────────────────────

def train_xgboost(X_train, y_train) -> xgb.XGBRegressor:
    print("[XGB]  Training XGBoost ...")
    model = xgb.XGBRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbosity=0,
    )
    model.fit(X_train, y_train)
    return model


# ──────────────────────────────────────────────────────────
# Model 3: LSTM
# ──────────────────────────────────────────────────────────

def build_sequences(
    data: np.ndarray, window: int = LSTM_WINDOW
) -> tuple[np.ndarray, np.ndarray]:
    """Create (X, y) sequences with a sliding window."""
    X, y = [], []
    for i in range(window, len(data)):
        X.append(data[i - window : i])   # shape (window, n_features)
        y.append(data[i, 0])             # first col is load_kw
    return np.array(X), np.array(y)


def get_lstm_data(
    train: pd.DataFrame,
    val: pd.DataFrame,
    test: pd.DataFrame,
) -> tuple:
    """Scale, sequence, and return LSTM-ready arrays."""
    feat_cols = [c for c in LSTM_FEATURES if c in train.columns]

    scaler_lstm = StandardScaler()
    train_vals = scaler_lstm.fit_transform(train[feat_cols].values)
    val_vals   = scaler_lstm.transform(val[feat_cols].values)
    test_vals  = scaler_lstm.transform(test[feat_cols].values)

    # We need the tail of train for the validation sequences
    train_val_vals = np.vstack([train_vals, val_vals])
    test_full_vals = np.vstack([train_vals[-LSTM_WINDOW:], val_vals, test_vals])

    X_train, y_train = build_sequences(train_vals, LSTM_WINDOW)
    X_val,   y_val   = build_sequences(np.vstack([train_vals[-LSTM_WINDOW:], val_vals]), LSTM_WINDOW)
    X_test,  y_test  = build_sequences(test_full_vals, LSTM_WINDOW)

    return X_train, y_train, X_val, y_val, X_test, y_test, scaler_lstm, feat_cols


def train_lstm(X_train, y_train, X_val, y_val, n_features: int) -> tf.keras.Model:
    print("[LSTM]  Training LSTM ...")
    tf.random.set_seed(42)
    model = Sequential(
        [
            LSTM(128, return_sequences=True, input_shape=(LSTM_WINDOW, n_features)),
            Dropout(0.2),
            LSTM(64, return_sequences=False),
            Dropout(0.2),
            Dense(32, activation="relu"),
            Dense(1),
        ]
    )
    model.compile(optimizer="adam", loss="mse")
    es = EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True)
    model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=100,
        batch_size=64,
        callbacks=[es],
        verbose=0,
    )
    return model


def lstm_predict_rescaled(
    model: tf.keras.Model,
    X: np.ndarray,
    scaler_lstm: StandardScaler,
    load_col_idx: int = 0,
) -> np.ndarray:
    """Predict and un-scale back to kWh."""
    y_scaled = model.predict(X, verbose=0).flatten()
    # Build a dummy array to inverse-transform only the load column
    dummy = np.zeros((len(y_scaled), scaler_lstm.n_features_in_))
    dummy[:, load_col_idx] = y_scaled
    return scaler_lstm.inverse_transform(dummy)[:, load_col_idx]


# ──────────────────────────────────────────────────────────
# Plot helper
# ──────────────────────────────────────────────────────────

def plot_predictions(y_true, preds_dict: dict, title: str, out_path: Path):
    plt.figure(figsize=(14, 4))
    plt.plot(y_true[:168], label="Actual", linewidth=1.5, alpha=0.8)
    for name, y_pred in preds_dict.items():
        plt.plot(y_pred[:168], label=name, linewidth=1, alpha=0.7)
    plt.title(title)
    plt.xlabel("Hours")
    plt.ylabel("Load (kW)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"   [METRICS] Plot saved -> {out_path}")


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  Load Forecasting — Model Training & Evaluation")
    print("=" * 55)

    train, val, test = load_splits()
    print(f"\n[DATA]  Data: train={len(train)}  val={len(val)}  test={len(test)}")

    # ── Tree-based features ──────────────────────────────
    X_train, y_train, scaler = get_tree_xy(train, fit_scaler=True)
    X_val,   y_val,   _      = get_tree_xy(val,   scaler=scaler)
    X_test,  y_test,  _      = get_tree_xy(test,  scaler=scaler)

    # ── Random Forest ────────────────────────────────────
    rf = train_random_forest(X_train, y_train)
    rf_pred_val  = rf.predict(X_val)
    rf_pred_test = rf.predict(X_test)
    rf_metrics   = evaluate("Random Forest (val)",  y_val,  rf_pred_val)
    rf_metrics_t = evaluate("Random Forest (test)", y_test, rf_pred_test)

    # ── XGBoost ──────────────────────────────────────────
    xgb_model = train_xgboost(X_train, y_train)
    xgb_pred_val  = xgb_model.predict(X_val)
    xgb_pred_test = xgb_model.predict(X_test)
    xgb_metrics   = evaluate("XGBoost (val)",  y_val,  xgb_pred_val)
    xgb_metrics_t = evaluate("XGBoost (test)", y_test, xgb_pred_test)

    # ── LSTM ─────────────────────────────────────────────
    X_tr_l, y_tr_l, X_vl_l, y_vl_l, X_ts_l, y_ts_l, scaler_lstm, feat_cols = \
        get_lstm_data(train, val, test)
    lstm_model = train_lstm(X_tr_l, y_tr_l, X_vl_l, y_vl_l, len(feat_cols))
    lstm_pred_val  = lstm_predict_rescaled(lstm_model, X_vl_l, scaler_lstm)
    lstm_pred_test = lstm_predict_rescaled(lstm_model, X_ts_l, scaler_lstm)
    lstm_metrics   = evaluate("LSTM (val)",  y_vl_l, lstm_pred_val)
    lstm_metrics_t = evaluate("LSTM (test)", y_ts_l, lstm_pred_test)

    # ── Metrics table ────────────────────────────────────
    metrics_df = pd.DataFrame([
        {**rf_metrics},
        {**xgb_metrics},
        {**lstm_metrics},
        {**rf_metrics_t,  "split": "test"},
        {**xgb_metrics_t, "split": "test"},
        {**lstm_metrics_t,"split": "test"},
    ])
    metrics_df.to_csv(MODELS_DIR / "metrics.csv", index=False)
    print(f"\n[PLOT]  Metrics saved -> {MODELS_DIR / 'metrics.csv'}")

    # ── Pick best model (lowest RMSE on val set) ─────────
    val_results = {
        "random_forest": rf_metrics["RMSE"],
        "xgboost":       xgb_metrics["RMSE"],
        "lstm":          lstm_metrics["RMSE"],
    }
    best_name = min(val_results, key=val_results.get)
    (MODELS_DIR / "best_model.txt").write_text(best_name)
    print(f"\n[BEST]  Best model: {best_name.upper()}  (val RMSE={val_results[best_name]:.4f})")

    # ── Save models ───────────────────────────────────────
    print("\n[SAVE]  Saving models ...")
    joblib.dump(rf,        MODELS_DIR / "rf_model.joblib")
    joblib.dump(xgb_model, MODELS_DIR / "xgb_model.joblib")
    joblib.dump(scaler,    MODELS_DIR / "scaler.joblib")
    lstm_model.save(MODELS_DIR / "lstm_model.keras")

    # Save LSTM scaler + feature list
    joblib.dump(scaler_lstm, MODELS_DIR / "lstm_scaler.joblib")
    (MODELS_DIR / "lstm_features.json").write_text(json.dumps(feat_cols))

    # ── Plots ────────────────────────────────────────────
    plot_predictions(
        y_test,
        {"Random Forest": rf_pred_test, "XGBoost": xgb_pred_test},
        "Predicted vs Actual Load — Test Set (first 168 h)",
        MODELS_DIR / "forecast_comparison.png",
    )

    print("\n[OK]  Forecasting module complete.")


if __name__ == "__main__":
    main()
