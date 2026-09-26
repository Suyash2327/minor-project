"""
data.py — Data generation, cleaning, and feature engineering
============================================================
Generates 180 days of synthetic hourly microgrid data with:
  - Electricity load: daily + weekly seasonality + temperature effect + noise
  - Solar generation: bell-curve profile scaled by irradiance
  - Grid price: time-of-use tariff (cheap at night, peak during daytime)
  - Battery initial state-of-charge (set at start)
  - Weather features: temperature and solar irradiance

Outputs:
  data/raw/microgrid_raw.csv
  data/processed/microgrid_features.csv
  data/processed/train.csv  /  val.csv  /  test.csv
"""

import os
import numpy as np
import pandas as pd
from pathlib import Path

# ──────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PROC_DIR = ROOT / "data" / "processed"
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROC_DIR.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────────────────
# Constants / parameters  (easy to tweak)
# ──────────────────────────────────────────────────────────
DAYS = 180           # simulation length
HOURS_PER_DAY = 24
N = DAYS * HOURS_PER_DAY   # total rows

SEED = 42
rng = np.random.default_rng(SEED)

# Load parameters (kWh per hour)
BASE_LOAD = 3.0          # base demand
MORNING_PEAK = 1.8       # extra demand 7-9 AM
EVENING_PEAK = 2.5       # extra demand 18-22 PM
WEEKEND_DIP = 0.7        # weekday multiplier (1.0 = normal)
TEMP_COEFF = 0.05        # kWh per degree above 20°C

# Solar parameters (kWh per hour, for a ~5 kW panel)
SOLAR_PEAK = 5.0         # peak power at midday

# Grid price  (£/kWh — time-of-use tariff)
PRICE_OFF_PEAK = 0.12    # 23:00-07:00
PRICE_MID = 0.20         # 07:00-16:00
PRICE_PEAK = 0.35        # 16:00-23:00

# Battery (kWh)
BATTERY_CAPACITY = 10.0
BATTERY_INIT_SOC = 0.5   # start at 50%


# ──────────────────────────────────────────────────────────
# Generate raw data
# ──────────────────────────────────────────────────────────

def generate_timestamps(start: str = "2024-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start=start, periods=N, freq="h")


def generate_temperature(timestamps: pd.DatetimeIndex) -> np.ndarray:
    """Realistic daily temperature with seasonal trend."""
    day_num = np.array([(ts - timestamps[0]).days for ts in timestamps])
    hour = timestamps.hour.values
    # Seasonal: warmer in summer, cooler in winter
    seasonal = 10 * np.sin(2 * np.pi * (day_num - 80) / 365)
    # Daily cycle: warmest at 14:00, coolest at 05:00
    daily = 5 * np.sin(2 * np.pi * (hour - 5) / 24)
    base_temp = 15 + seasonal + daily
    noise = rng.normal(0, 1.0, N)
    return base_temp + noise


def generate_solar_irradiance(timestamps: pd.DatetimeIndex) -> np.ndarray:
    """Solar irradiance in kW/m² (clear-sky model + cloudiness)."""
    hour = timestamps.hour.values
    day_num = np.array([(ts - timestamps[0]).days for ts in timestamps])
    # Seasonal day-length effect
    day_length = 10 + 4 * np.sin(2 * np.pi * (day_num - 80) / 365)
    sunrise = (24 - day_length) / 2
    sunset = sunrise + day_length
    # Bell curve between sunrise/sunset
    midday = (sunrise + sunset) / 2
    irradiance = np.where(
        (hour >= sunrise) & (hour <= sunset),
        np.exp(-0.5 * ((hour - midday) / (day_length / 4)) ** 2),
        0.0,
    )
    # Random cloudiness factor per hour (0.3 – 1.0)
    cloud = rng.uniform(0.3, 1.0, N)
    return irradiance * cloud


def generate_solar_power(irradiance: np.ndarray) -> np.ndarray:
    """Convert irradiance to kWh output."""
    return SOLAR_PEAK * irradiance


def generate_grid_price(timestamps: pd.DatetimeIndex) -> np.ndarray:
    """Time-of-use electricity tariff."""
    hour = timestamps.hour.values
    price = np.where(
        (hour >= 23) | (hour < 7),
        PRICE_OFF_PEAK,
        np.where(hour < 16, PRICE_MID, PRICE_PEAK),
    )
    # Add small random fluctuation ±2%
    return price * rng.uniform(0.98, 1.02, N)


def generate_load(
    timestamps: pd.DatetimeIndex, temperature: np.ndarray
) -> np.ndarray:
    """Realistic electricity demand with daily + weekly seasonality."""
    hour = timestamps.hour.values
    dow = timestamps.dayofweek.values  # 0=Mon … 6=Sun
    is_weekend = (dow >= 5).astype(float)

    # Daily profile
    load = np.full(N, BASE_LOAD)
    load += MORNING_PEAK * np.exp(-0.5 * ((hour - 8) / 1.5) ** 2)
    load += EVENING_PEAK * np.exp(-0.5 * ((hour - 19) / 2.0) ** 2)
    # Night dip
    night = (hour <= 5) | (hour >= 23)
    load[night] *= 0.55

    # Weekend is slightly lower on average
    load *= (1 - 0.15 * is_weekend)

    # Temperature sensitivity (cooling load when hot)
    temp_effect = TEMP_COEFF * np.clip(temperature - 20, 0, None)
    load += temp_effect

    # Random noise ±8%
    noise = rng.normal(1.0, 0.08, N)
    load *= noise

    return np.clip(load, 0.5, None)


def build_raw_dataframe() -> pd.DataFrame:
    timestamps = generate_timestamps()
    temperature = generate_temperature(timestamps)
    irradiance = generate_solar_irradiance(timestamps)
    solar_power = generate_solar_power(irradiance)
    grid_price = generate_grid_price(timestamps)
    load = generate_load(timestamps, temperature)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "load_kw": load,
            "solar_kw": solar_power,
            "grid_price": grid_price,
            "temperature": temperature,
            "solar_irradiance": irradiance,
        }
    )
    df.set_index("timestamp", inplace=True)
    return df


# ──────────────────────────────────────────────────────────
# Cleaning
# ──────────────────────────────────────────────────────────

def clean(df: pd.DataFrame) -> pd.DataFrame:
    """Fill any gaps, ensure consistent hourly frequency."""
    df = df.asfreq("h")
    df = df.interpolate(method="time")
    df = df.ffill().bfill()
    # Clip physically impossible values
    df["load_kw"] = df["load_kw"].clip(lower=0)
    df["solar_kw"] = df["solar_kw"].clip(lower=0, upper=SOLAR_PEAK)
    df["grid_price"] = df["grid_price"].clip(lower=0.01)
    return df


# ──────────────────────────────────────────────────────────
# Feature Engineering
# ──────────────────────────────────────────────────────────

def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df["hour"] = df.index.hour
    df["day_of_week"] = df.index.dayofweek
    df["is_weekend"] = (df.index.dayofweek >= 5).astype(int)
    df["month"] = df.index.month
    df["day_of_year"] = df.index.dayofyear
    # Cyclical encoding avoids ordinal interpretation
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["day_of_week"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["day_of_week"] / 7)
    return df


def add_lag_features(df: pd.DataFrame, target: str = "load_kw") -> pd.DataFrame:
    df[f"{target}_lag1"] = df[target].shift(1)
    df[f"{target}_lag24"] = df[target].shift(24)
    df[f"{target}_lag168"] = df[target].shift(168)   # 1 week
    return df


def add_rolling_features(df: pd.DataFrame, target: str = "load_kw") -> pd.DataFrame:
    df[f"{target}_roll3_mean"] = df[target].shift(1).rolling(3).mean()
    df[f"{target}_roll24_mean"] = df[target].shift(1).rolling(24).mean()
    df[f"{target}_roll24_std"] = df[target].shift(1).rolling(24).std()
    return df


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = add_time_features(df)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    df.dropna(inplace=True)   # remove rows with NaN from lags
    return df


# ──────────────────────────────────────────────────────────
# Train / Validation / Test split  (chronological — NEVER shuffle)
# ──────────────────────────────────────────────────────────

def chronological_split(
    df: pd.DataFrame,
    train_frac: float = 0.70,
    val_frac: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df)
    train_end = int(n * train_frac)
    val_end = int(n * (train_frac + val_frac))
    train = df.iloc[:train_end]
    val = df.iloc[train_end:val_end]
    test = df.iloc[val_end:]
    return train, val, test


# ──────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────

def main():
    print("[*] Generating synthetic microgrid data...")
    raw = build_raw_dataframe()
    raw = clean(raw)
    raw.to_csv(RAW_DIR / "microgrid_raw.csv")
    print(f"    Raw data saved  -> {RAW_DIR / 'microgrid_raw.csv'}  ({len(raw)} rows)")

    print("[*] Engineering features...")
    feat = engineer_features(raw.copy())
    feat.to_csv(PROC_DIR / "microgrid_features.csv")
    print(f"    Features saved  -> {PROC_DIR / 'microgrid_features.csv'}  ({len(feat)} rows, {len(feat.columns)} cols)")

    print("[*] Splitting into train / val / test...")
    train, val, test = chronological_split(feat)
    train.to_csv(PROC_DIR / "train.csv")
    val.to_csv(PROC_DIR / "val.csv")
    test.to_csv(PROC_DIR / "test.csv")
    print(f"    Train: {len(train)}  Val: {len(val)}  Test: {len(test)}")
    print("\n[DONE] Data pipeline complete.")


if __name__ == "__main__":
    main()
