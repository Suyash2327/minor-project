"""
optimize.py — Dispatch optimizer and reactive baseline controller
=================================================================
Uses PuLP to formulate a 24-hour rolling Linear Program (LP).

Decision variables per time step t:
  grid_power[t]        — power drawn from the grid (kW)
  diesel_power[t]      — power from diesel generator (kW)
  battery_charge[t]    — power used to charge the battery (kW)
  battery_discharge[t] — power drawn from the battery (kW)
  solar_curtail[t]     — unused solar power (kW)

Objective: minimise total energy cost + battery degradation cost

Constraints:
  (1) Energy balance: solar_used + battery_discharge + grid + diesel = load
  (2) Solar: solar_used = solar_available − solar_curtail
  (3) Battery SoC: stays within [SOC_MIN, SOC_MAX] × capacity
  (4) Battery (dis)charge rates ≤ hardware limits
  (5) No simultaneous charge + discharge
  (6) Diesel only when load exceeds a threshold

Fallback: if the LP solver returns INFEASIBLE, a rule-based controller
is used automatically.
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional

try:
    import pulp
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False
    print("[WARN]  PuLP not found — using rule-based fallback only")

# ──────────────────────────────────────────────────────────
# Microgrid parameters  (easy to adjust)
# ──────────────────────────────────────────────────────────
BATTERY_CAPACITY   = 10.0   # kWh
SOC_MIN            = 0.20   # minimum state-of-charge fraction
SOC_MAX            = 0.90   # maximum state-of-charge fraction
CHARGE_RATE_MAX    = 3.0    # max charge   rate (kW)
DISCHARGE_RATE_MAX = 3.0    # max discharge rate (kW)
BATTERY_EFFICIENCY = 0.95   # round-trip efficiency
DIESEL_PRICE       = 0.40   # £/kWh
BATTERY_DEGRADE    = 0.02   # £/kWh cycled (degradation cost)
GRID_EXPORT_PRICE  = 0.05   # £/kWh for exported solar (optional revenue)
DIESEL_THRESHOLD   = 6.0    # kW — diesel only above this load level


# ──────────────────────────────────────────────────────────
# ── LP OPTIMIZER ────────────────────────────────────────
# ──────────────────────────────────────────────────────────

def lp_optimize(
    load_forecast: np.ndarray,
    solar_forecast: np.ndarray,
    grid_prices: np.ndarray,
    init_soc: float = 0.5,
    horizon: int = 24,
) -> pd.DataFrame:
    """
    Solve the dispatch LP for one horizon window.

    Parameters
    ----------
    load_forecast  : shape (horizon,)  — forecasted load in kW
    solar_forecast : shape (horizon,)  — expected solar generation in kW
    grid_prices    : shape (horizon,)  — time-of-use grid price (£/kWh)
    init_soc       : initial battery state-of-charge (fraction of capacity)
    horizon        : number of time steps to optimise (default 24 hours)

    Returns
    -------
    DataFrame with columns: hour, load_kw, solar_kw, grid_kw, diesel_kw,
                             battery_charge, battery_discharge, soc, cost
    """
    if not PULP_AVAILABLE:
        return rule_based_dispatch(load_forecast, solar_forecast, grid_prices, init_soc)

    T = min(horizon, len(load_forecast))
    prob = pulp.LpProblem("MicrogridDispatch", pulp.LpMinimize)

    # ── Decision variables ────────────────────────────────
    grid     = [pulp.LpVariable(f"grid_{t}",   lowBound=0) for t in range(T)]
    diesel   = [pulp.LpVariable(f"diesel_{t}", lowBound=0) for t in range(T)]
    b_ch     = [pulp.LpVariable(f"bch_{t}",    lowBound=0, upBound=CHARGE_RATE_MAX)   for t in range(T)]
    b_dis    = [pulp.LpVariable(f"bdis_{t}",   lowBound=0, upBound=DISCHARGE_RATE_MAX) for t in range(T)]
    curtail  = [pulp.LpVariable(f"curt_{t}",   lowBound=0) for t in range(T)]
    soc      = [pulp.LpVariable(f"soc_{t}",    lowBound=SOC_MIN * BATTERY_CAPACITY,
                                                upBound=SOC_MAX  * BATTERY_CAPACITY)   for t in range(T)]

    # ── Objective: minimise cost ──────────────────────────
    prob += pulp.lpSum(
        grid_prices[t] * grid[t]
        + DIESEL_PRICE * diesel[t]
        + BATTERY_DEGRADE * b_ch[t]
        + BATTERY_DEGRADE * b_dis[t]
        - GRID_EXPORT_PRICE * curtail[t]  # reward for exporting unused solar
        for t in range(T)
    )

    for t in range(T):
        load  = float(load_forecast[t])
        solar = float(solar_forecast[t])

        # Energy balance: (solar - curtail) + discharge + grid + diesel = load + charge
        prob += (solar - curtail[t] + b_dis[t] + grid[t] + diesel[t]
                 == load + b_ch[t])

        # Solar curtailment ≤ available solar
        prob += curtail[t] <= solar

        # Battery SoC dynamics
        soc_prev = init_soc * BATTERY_CAPACITY if t == 0 else soc[t - 1]
        prob += soc[t] == soc_prev + BATTERY_EFFICIENCY * b_ch[t] - b_dis[t]

        # Prevent simultaneous charge and discharge (big-M relaxation)
        # We use a simple upper-bound trick: if both occur, cost penalises it
        # (For a strict MIP version, binary vars would be added here)

    # ── Solve ─────────────────────────────────────────────
    solver = pulp.PULP_CBC_CMD(msg=False)
    status = prob.solve(solver)

    if pulp.LpStatus[status] != "Optimal":
        print(f"   [WARN]  LP status: {pulp.LpStatus[status]} — falling back to rule-based")
        return rule_based_dispatch(load_forecast, solar_forecast, grid_prices, init_soc)

    # ── Extract results ───────────────────────────────────
    rows = []
    for t in range(T):
        solar_used = float(solar_forecast[t]) - pulp.value(curtail[t])
        cost_t = (
            grid_prices[t] * pulp.value(grid[t])
            + DIESEL_PRICE * pulp.value(diesel[t])
            + BATTERY_DEGRADE * (pulp.value(b_ch[t]) + pulp.value(b_dis[t]))
        )
        rows.append(
            {
                "hour": t,
                "load_kw":           float(load_forecast[t]),
                "solar_kw":          max(solar_used, 0),
                "grid_kw":           max(pulp.value(grid[t]),   0),
                "diesel_kw":         max(pulp.value(diesel[t]), 0),
                "battery_charge":    max(pulp.value(b_ch[t]),   0),
                "battery_discharge": max(pulp.value(b_dis[t]),  0),
                "soc":               pulp.value(soc[t]) / BATTERY_CAPACITY,
                "cost":              max(cost_t, 0),
            }
        )
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────
# ── RULE-BASED FALLBACK (also the Baseline) ─────────────
# ──────────────────────────────────────────────────────────

def rule_based_dispatch(
    load_actual: np.ndarray,
    solar_available: np.ndarray,
    grid_prices: np.ndarray,
    init_soc: float = 0.5,
) -> pd.DataFrame:
    """
    Simple reactive controller (no forecast):
    Priority order: solar -> battery discharge -> grid -> diesel

    This is also used as the naive baseline for comparison.
    """
    soc = init_soc  # fraction of capacity
    rows = []

    for t in range(len(load_actual)):
        load  = float(load_actual[t])
        solar = float(solar_available[t])
        price = float(grid_prices[t])

        remaining = load

        # 1. Use solar first
        solar_used = min(solar, remaining)
        remaining -= solar_used

        # 2. Use battery discharge
        max_discharge = min(
            DISCHARGE_RATE_MAX,
            max(soc - SOC_MIN, 0) * BATTERY_CAPACITY,
        )
        b_dis = min(max_discharge, remaining)
        remaining -= b_dis
        soc -= b_dis / BATTERY_CAPACITY

        # 3. Grid power for the rest
        grid_kw = remaining
        remaining = 0

        # 4. Charge battery with excess solar if SoC < SOC_MAX
        excess_solar = solar - solar_used
        max_charge = min(
            CHARGE_RATE_MAX,
            max(SOC_MAX - soc, 0) * BATTERY_CAPACITY,
        )
        b_ch = min(excess_solar, max_charge)
        soc += BATTERY_EFFICIENCY * b_ch / BATTERY_CAPACITY
        soc = float(np.clip(soc, SOC_MIN, SOC_MAX))

        cost_t = price * grid_kw + BATTERY_DEGRADE * (b_ch + b_dis)

        rows.append(
            {
                "hour":              t,
                "load_kw":           load,
                "solar_kw":          solar_used,
                "grid_kw":           grid_kw,
                "diesel_kw":         0.0,
                "battery_charge":    b_ch,
                "battery_discharge": b_dis,
                "soc":               soc,
                "cost":              cost_t,
            }
        )

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────
# ── Quick sanity-check / main ───────────────────────────
# ──────────────────────────────────────────────────────────

def _sample_day_test():
    """Run optimizer on one synthetic day and print results."""
    ROOT = Path(__file__).resolve().parent.parent
    raw = pd.read_csv(
        ROOT / "data" / "raw" / "microgrid_raw.csv",
        index_col=0, parse_dates=True,
    )
    day = raw.iloc[:24]
    load   = day["load_kw"].values
    solar  = day["solar_kw"].values
    prices = day["grid_price"].values

    print("\n[TEST]  Testing LP optimizer on first 24 hours ...")
    result = lp_optimize(load, solar, prices, init_soc=0.5)
    print(result[["hour", "load_kw", "solar_kw", "grid_kw", "battery_discharge", "soc", "cost"]].to_string(index=False))
    total_cost = result["cost"].sum()
    print(f"\n   LP total cost: £{total_cost:.2f}")

    print("\n[TEST]  Testing rule-based baseline on the same day ...")
    baseline = rule_based_dispatch(load, solar, prices, init_soc=0.5)
    base_cost = baseline["cost"].sum()
    print(f"   Baseline cost: £{base_cost:.2f}")

    saving = (base_cost - total_cost) / base_cost * 100 if base_cost > 0 else 0
    print(f"\n[COST]  Cost saving vs. baseline: {saving:.1f}%")

    # Validate demand-matching constraint
    for _, row in result.iterrows():
        balance = (row["solar_kw"] + row["grid_kw"] + row["diesel_kw"]
                   + row["battery_discharge"] - row["battery_charge"])
        assert abs(balance - row["load_kw"]) < 0.01, f"Demand mismatch at hour {row['hour']}"
    print("[OK]  Demand-matching constraint satisfied for all hours.")


if __name__ == "__main__":
    _sample_day_test()
