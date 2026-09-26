# Build Steps — AI-Based Load Forecasting for Microgrid Optimization

A detailed technical checklist for building this project, whether you're guiding
Antigravity through it or building it yourself. Follow the order — each step
depends on the one before it.

---

## Step 1: Project Setup

- [x] Create project folder with subfolders: `data/`, `models/`, `src/`, `notebooks/`, `dashboard/`, `tests/`
- [x] Set up a Python virtual environment
- [x] Create `requirements.txt` with: `pandas`, `numpy`, `scikit-learn`, `xgboost`, `tensorflow` (or `torch`), `pulp`, `streamlit`, `matplotlib`, `plotly`
- [x] Initialize a `README.md` and (optionally) a git repo

## Step 2: Get / Generate Data

- [x] Find a public dataset (e.g., UCI "Individual Household Electric Power Consumption", Kaggle microgrid/smart-meter datasets) **or**
- [x] Generate synthetic data if no real dataset fits:
  - Simulate hourly/15-min load with a daily pattern (low at night, peaks morning + evening) plus weekly pattern (weekday vs weekend) plus random noise
  - Simulate solar generation as a function of hour of day (zero at night, peak at midday), scaled by a random "cloudiness" factor
  - Simulate a simple time-of-use grid price (cheap at night, expensive during peak hours)
- [x] Save raw data to `data/raw/`

## Step 3: Data Cleaning & Feature Engineering

- [x] Handle missing timestamps/values (interpolate or forward-fill)
- [x] Resample to a consistent interval (e.g., hourly)
- [x] Create time features: `hour`, `day_of_week`, `is_weekend`, `month`
- [x] Create lag features: load 1 hour ago, 24 hours ago, 168 hours ago (1 week)
- [x] Create rolling features: rolling mean/std of load over past 3/24 hours
- [x] Split data **chronologically** into train/validation/test (never shuffle randomly — this is a common mistake)
- [x] Save processed data to `data/processed/`

## Step 4: Forecasting Models

- [x] Build baseline model: Random Forest Regressor
- [x] Build second model: XGBoost Regressor
- [x] Build deep learning model: LSTM (using a sliding window of past N hours as input)
- [x] Evaluate all three on the test set using MAE, RMSE, and MAPE
- [x] Plot predicted vs. actual load for each model to visually sanity-check
- [x] Select the best-performing model as the default forecaster
- [x] Save trained model(s) to `models/`

**Common pitfalls to watch for:**
- LSTM underperforming simpler models due to insufficient data or poor tuning — don't assume deep learning is automatically better
- MAPE blowing up when actual load is near zero (e.g., at night) — consider excluding near-zero periods from MAPE or using MAE/RMSE as primary metrics

## Step 5: Optimization Module

- [x] Define decision variables per time step: `grid_power`, `battery_charge`, `battery_discharge`, `diesel_power`
- [x] Define the objective function: minimize `(grid_power × grid_price) + (diesel_power × diesel_price) + (battery_usage × degradation_cost)`
- [x] Define constraints:
  - [x] `solar_used + battery_discharge + grid_power + diesel_power = forecasted_load` for every time step
  - [x] Battery state-of-charge stays within safe bounds (e.g., 20%–90%)
  - [x] Battery charge/discharge rate does not exceed hardware limits
  - [x] (Optional) Diesel usage only allowed above a certain load threshold
- [x] Implement using PuLP or Pyomo, solving either one time step at a time or as a rolling 24-hour horizon
- [x] Add a fallback rule-based method for when the solver returns "infeasible" (e.g., default to grid power)
- [x] Test the optimizer on a few sample days to confirm outputs make physical sense (e.g., battery isn't charging and discharging simultaneously)

## Step 6: Baseline (Reactive) Controller

- [x] Implement a simple non-predictive controller: use solar first, battery second, grid/diesel only when both are insufficient — based on *current* load only, no forecast
- [x] This becomes the point of comparison to show the value of forecasting + optimization

## Step 7: Pipeline Integration

- [x] Write one function that takes recent raw data as input and returns:
  - Forecasted load for the next N hours
  - Optimized dispatch schedule for the next N hours
  - Reactive baseline schedule for the same period (for comparison)
- [x] Confirm the pipeline runs end-to-end without manual intervention

## Step 8: Dashboard

- [x] Build a Streamlit app with:
  - [x] Chart: predicted vs. actual load over time
  - [x] Stacked area/bar chart: source mix (solar/battery/grid/diesel) per hour from the optimizer
  - [x] Side-by-side comparison: total cost (optimized vs. reactive baseline)
  - [x] Table or metric cards: forecast accuracy (MAE/RMSE/MAPE)
- [x] Keep it simple and readable — this is what you'll demo to your professor

## Step 9: Testing & Validation

- [x] Unit test: data pipeline produces expected columns/shape
- [x] Unit test: forecasting model outputs the correct number of predictions
- [x] Unit test: optimizer output always satisfies the demand-matching constraint
- [x] Run the full pipeline on a held-out test period and confirm the optimized schedule beats the baseline on cost

## Step 10: Documentation & Report

- [x] Write/update `README.md`: setup instructions, how to run the dashboard, explanation of each module
- [x] Summarize results: forecast accuracy achieved, % cost savings vs. baseline, % renewable usage improvement
- [x] Prepare a short results section for your synopsis/report with charts exported from the dashboard

---

## Suggested Order of Difficulty (if short on time)

1. Data + Random Forest forecasting → gets you a working demo fastest
2. Rule-based optimization (skip LP initially) → still satisfies "optimization" objective
3. Add XGBoost/LSTM comparison → strengthens the ML component
4. Add real PuLP/Pyomo linear programming → strengthens the optimization component
5. Polish dashboard last → highest visual impact for lowest technical risk
