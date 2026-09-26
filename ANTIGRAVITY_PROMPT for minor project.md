# Antigravity Prompt — AI-Based Load Forecasting for Microgrid Optimization

Copy everything below into Antigravity as your starting prompt.

---

## Prompt

Build a complete, working project called **"AI-Based Load Forecasting for Microgrid Optimization."**

**What the project does:**
A two-stage system for a small microgrid (solar + battery + grid/diesel backup).
Stage 1 forecasts short-term electricity demand using machine learning.
Stage 2 takes that forecast and runs an optimization model that decides, for each
time period, how much power should come from solar, battery, or grid/diesel — to
minimize cost and maximize renewable usage. The output is a recommended dispatch
schedule shown on a simple dashboard, compared against a naive "reactive" baseline
so the cost/efficiency improvement is visible.

**Tech stack to use:**
- Python 3.x
- Pandas, NumPy for data handling
- Scikit-learn (Random Forest, XGBoost) and TensorFlow/PyTorch (LSTM) for forecasting
- PuLP or Pyomo for the optimization / linear programming layer
- Streamlit for the dashboard
- Matplotlib/Plotly for charts

**Data:**
Use a public household/microgrid load dataset (or generate realistic synthetic
15-minute/hourly load data with daily + weekly seasonality if no dataset is
available) plus simulated solar generation (based on time of day) and a simple
time-of-use grid price. Include a synthetic weather feature (temperature/solar
irradiance) that influences both load and solar output.

**Build the project in this order, and don't skip steps:**
1. Project scaffold: folder structure, virtual environment, requirements.txt, README.
2. Data layer: load/generate dataset, clean it, engineer time-based features
   (hour, day-of-week, lag values, rolling averages).
3. Forecasting module: train and evaluate Random Forest, XGBoost, and an LSTM
   model on a chronological train/test split. Report MAE, RMSE, MAPE for each
   and pick the best one as default.
4. Optimization module: formulate the dispatch problem as a linear program using
   PuLP (decision variables for grid/battery/diesel/solar usage per time step,
   an objective that minimizes cost, and constraints for demand-matching and
   battery state-of-charge limits). Include a simple rule-based fallback in case
   the solver is infeasible.
5. Baseline comparison: implement a simple reactive/rule-based controller (no
   forecasting) to compare against the optimized schedule.
6. Integration: connect forecast → optimizer → schedule output as one pipeline
   function that takes raw recent data and returns the next 24-hour dispatch plan.
7. Dashboard: build a Streamlit app that shows (a) predicted vs. actual load,
   (b) the recommended source mix per hour as a stacked chart, (c) cost
   comparison between optimized and baseline schedules, (d) forecast accuracy
   metrics.
8. Tests: add basic unit tests for the data pipeline, forecasting output shape,
   and optimizer feasibility.
9. Documentation: generate a clear README explaining setup, how to run, and
   how each module works, matching the structure of my project synopsis
   (Introduction, Objectives, System Working Principle, Components, Outcomes).

**Constraints / preferences:**
- Keep code modular — separate files for `data.py`, `forecast.py`, `optimize.py`,
  `dashboard.py`, not one giant script.
- Prioritize a working end-to-end pipeline first (even with the simplest models),
  then improve accuracy/optimization complexity incrementally.
- Explain your reasoning and any assumptions you make about the data or
  constraints as you go, since I'll need to understand this well enough to
  present and defend it academically.
- Ask me before making major architecture decisions I haven't specified
  (e.g., which dataset to use if none is provided, or how many days of data
  to simulate).

Please start with step 1 (project scaffold) and confirm the folder structure
with me before generating the rest of the code.
