"""
tests/test_optimizer.py — Unit tests for the dispatch optimizer
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import pytest

from src.optimize import (
    lp_optimize,
    rule_based_dispatch,
    BATTERY_CAPACITY,
    SOC_MIN,
    SOC_MAX,
)

# ── Fixtures ──────────────────────────────────────────────

@pytest.fixture
def sample_24h():
    """Realistic 24-hour synthetic inputs."""
    hours = np.arange(24)
    load  = 3.0 + 1.5 * np.exp(-0.5 * ((hours - 8) / 2) ** 2) \
                + 2.0 * np.exp(-0.5 * ((hours - 19) / 2.5) ** 2)
    solar = 5.0 * np.exp(-0.5 * ((hours - 12) / 3.5) ** 2)
    price = np.where((hours >= 23) | (hours < 7), 0.12,
            np.where(hours < 16, 0.20, 0.35))
    return load, solar, price


# ── LP optimizer tests ────────────────────────────────────

class TestLpOptimizer:
    def test_output_shape(self, sample_24h):
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price, init_soc=0.5)
        assert len(result) == 24

    def test_required_columns(self, sample_24h):
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price)
        for col in ["hour", "load_kw", "solar_kw", "grid_kw", "diesel_kw",
                    "battery_charge", "battery_discharge", "soc", "cost"]:
            assert col in result.columns, f"Missing column: {col}"

    def test_demand_matching(self, sample_24h):
        """Supply = load for every time step (energy balance)."""
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price, init_soc=0.5)
        for _, row in result.iterrows():
            supply = (row["solar_kw"] + row["grid_kw"] + row["diesel_kw"]
                      + row["battery_discharge"] - row["battery_charge"])
            assert abs(supply - row["load_kw"]) < 0.05, \
                f"Demand mismatch at hour {row['hour']}: supply={supply:.3f} vs load={row['load_kw']:.3f}"

    def test_soc_within_bounds(self, sample_24h):
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price, init_soc=0.5)
        assert (result["soc"] >= SOC_MIN - 0.01).all(), "SoC below minimum"
        assert (result["soc"] <= SOC_MAX + 0.01).all(), "SoC above maximum"

    def test_non_negative_outputs(self, sample_24h):
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price, init_soc=0.5)
        for col in ["solar_kw", "grid_kw", "diesel_kw", "battery_charge",
                    "battery_discharge", "cost"]:
            assert (result[col] >= -0.01).all(), f"{col} has negative values"

    def test_total_cost_positive(self, sample_24h):
        load, solar, price = sample_24h
        result = lp_optimize(load, solar, price, init_soc=0.5)
        assert result["cost"].sum() >= 0


# ── Rule-based baseline tests ─────────────────────────────

class TestRuleBasedDispatch:
    def test_output_shape(self, sample_24h):
        load, solar, price = sample_24h
        result = rule_based_dispatch(load, solar, price)
        assert len(result) == 24

    def test_soc_within_bounds(self, sample_24h):
        load, solar, price = sample_24h
        result = rule_based_dispatch(load, solar, price, init_soc=0.5)
        assert (result["soc"] >= SOC_MIN - 0.01).all()
        assert (result["soc"] <= SOC_MAX + 0.01).all()

    def test_non_negative_outputs(self, sample_24h):
        load, solar, price = sample_24h
        result = rule_based_dispatch(load, solar, price)
        for col in ["solar_kw", "grid_kw", "battery_charge",
                    "battery_discharge", "cost"]:
            assert (result[col] >= -0.01).all(), f"{col} has negative values"

    def test_zero_diesel_in_baseline(self, sample_24h):
        """Rule-based controller doesn't use diesel (simple version)."""
        load, solar, price = sample_24h
        result = rule_based_dispatch(load, solar, price)
        assert (result["diesel_kw"] == 0).all()


# ── Cost comparison test ──────────────────────────────────

class TestCostSavings:
    def test_optimizer_not_worse_than_baseline(self, sample_24h):
        """LP optimizer cost should be ≤ rule-based cost (or very close)."""
        load, solar, price = sample_24h
        opt      = lp_optimize(load, solar, price, init_soc=0.5)
        baseline = rule_based_dispatch(load, solar, price, init_soc=0.5)
        # Allow 5% tolerance (rounding, fallback to rule-based, etc.)
        assert opt["cost"].sum() <= baseline["cost"].sum() * 1.05, \
            "Optimizer is significantly more expensive than the baseline!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
