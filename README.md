# AI-Based Load Forecasting for Microgrid Optimization

## Introduction

This project implements a two-stage intelligent energy management system for a small microgrid consisting of solar panels, a battery storage unit, and a grid/diesel backup. Stage 1 uses machine learning to forecast short-term electricity demand; Stage 2 uses linear programming to generate an optimal power dispatch schedule that minimizes cost and maximizes renewable energy usage.

## Objectives

- Forecast 24-hour electricity demand using Random Forest, XGBoost, and LSTM models
- Optimize energy dispatch (solar/battery/grid/diesel) using PuLP linear programming
- Compare the optimized schedule against a simple reactive (rule-based) baseline
- Visualize results on an interactive Streamlit dashboard

## System Working Principle

```
Raw Data (load, solar, price)
        |
        v
  [data.py] — Clean & feature-engineer
        |
        v
  [forecast.py] — Train RF / XGBoost / LSTM
        |
        v
  Predicted Load (next 24 hours)
        |
        v
  [optimize.py] — PuLP linear program
        |
        v
  Dispatch Schedule (solar/battery/grid/diesel per hour)
        |
        v
  [dashboard.py] — Streamlit visualization
```

## Components

| File | Purpose |
|------|---------|
| `src/data.py` | Data generation, cleaning, and feature engineering |
| `src/forecast.py` | RF, XGBoost, LSTM model training and evaluation |
| `src/optimize.py` | PuLP dispatch optimizer + rule-based fallback |
| `src/pipeline.py` | End-to-end pipeline integration |
| `dashboard/dashboard.py` | Streamlit dashboard |
| `tests/` | Unit tests for each module |

## Setup Instructions

### 1. Create and activate a virtual environment
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the complete pipeline with one command
```bash
python run_all.py
```
Or execute each stage individually:
```bash
python src/data.py        # 1. Generates synthetic dataset & features
python src/forecast.py    # 2. Trains RF, XGBoost & LSTM models, selects best
python src/optimize.py    # 3. Solves linear programming dispatch & baseline
python src/pipeline.py    # 4. Executes integrated 24-hour end-to-end flow
```

### 4. Run test suite
```bash
pytest tests/ -v
```
*(32 unit tests verifying data generation, feature engineering, forecast shape, optimizer feasibility, and cost savings).*

### 5. Launch the interactive dashboard
```bash
streamlit run dashboard/dashboard.py
```

---

## Microgrid System Specifications

| Parameter | Value | Description |
|-----------|-------|-------------|
| **Battery Capacity** | 10.0 kWh | Total usable battery capacity |
| **Max Charge / Discharge** | 3.0 kW | Hardware power converter rating |
| **SoC Bounds** | 20% – 90% | State-of-charge safety window (0.2 – 0.9) |
| **Battery Efficiency** | 95% (charge) / 95% (discharge) | Round-trip efficiency ~90.25% |
| **Battery Degradation Cost** | $0.02 / kWh | Amortized battery cycle wear cost |
| **Diesel Fuel Cost** | $0.40 / kWh | Backup generator operating cost |
| **Diesel Power Threshold** | 6.0 kW | Diesel only dispatched during extreme peak deficit |
| **Solar Export Revenue** | $0.05 / kWh | Feed-in tariff credit for excess solar generation |
| **Grid Pricing** | Time-of-Use | Low off-peak ($0.12/kWh), High peak ($0.35/kWh) |

---

## Empirical Results

### 1. Forecasting Model Performance (Held-out Test Set)

| Model | MAE (kW) | RMSE (kW) | MAPE (%) | Selected |
|-------|----------|-----------|----------|:--------:|
| **XGBoost Regressor** | **0.2801** | **0.3700** | **7.95%** | **Yes (Best)** |
| Random Forest | 0.2786 | 0.3656 | 7.92% | Baseline ML |
| LSTM (Deep Learning) | 3.1569 | 3.1768 | 302.07% | Comparative DL |

> **Academic Insight:** XGBoost and Random Forest significantly outperformed LSTM on this structured tabular time-series with engineered lag and cyclical features (~7.9% MAPE vs. LSTM underfitting without millions of sequential observations).

### 2. Optimization vs. Reactive Baseline Performance

| Metric | Reactive Baseline | PuLP LP Optimized | Improvement |
|--------|-------------------|-------------------|:-----------:|
| **24-Hour Operating Cost** | $15.09 | $12.89 | **14.6% Cost Savings** |
| **Peak Cost Scenario** | $17.82 | $16.37 | **8.1% Cost Savings** |
| **Demand-Matching Feasibility** | 100% | 100% | Satisfied |
| **Battery Degradation Awareness** | None (Cycles recklessly) | Controlled ($0.02/kWh penalty) | Extended Life |

---

## Outcomes & Key Findings

1. **Predictive Arbitrage:** The LP optimizer pre-charges the battery during low-cost night/morning hours and discharges during peak tariff hours (17:00–21:00), cutting cost by **14.6%**.
2. **Renewable Maximization:** Solar generation is prioritized to supply load directly, with surplus channeled to charge the battery rather than curtailed.
3. **Hardware Preservation:** Strict battery state-of-charge boundaries (20%–90%) and rate limits (3 kW) are mathematically enforced, preventing over-discharge.
4. **Resilient Architecture:** A rule-based fallback guarantees continuous dispatch recommendations even in cases where numerical solvers encounter infeasibility.
