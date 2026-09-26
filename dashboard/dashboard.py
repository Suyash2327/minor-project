"""
dashboard.py — Streamlit dashboard for Microgrid Optimization
=============================================================
Panels:
  A) Predicted vs. Actual Load (line chart)
  B) Optimized Source Mix per Hour (stacked bar chart)
  C) Cost Comparison — Optimized vs. Baseline (bar + metric cards)
  D) Forecast Accuracy Metrics (MAE / RMSE / MAPE)
  E) Battery State-of-Charge over the dispatch horizon

Run with:
    streamlit run dashboard/dashboard.py
"""

import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st

# ──────────────────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Microgrid Optimizer",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────
# Custom CSS (dark glass-morphism theme)
# ──────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* ── Global background ── */
    .stApp {
        background: linear-gradient(135deg, #0d1117 0%, #161b22 50%, #0d1117 100%);
        color: #e6edf3;
    }
    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {
        background: rgba(22, 27, 34, 0.9);
        backdrop-filter: blur(12px);
        border-right: 1px solid rgba(48, 54, 61, 0.8);
    }
    /* ── Metric cards ── */
    [data-testid="stMetric"] {
        background: rgba(30, 36, 45, 0.85);
        border: 1px solid rgba(48, 54, 61, 0.8);
        border-radius: 12px;
        padding: 16px 20px;
        backdrop-filter: blur(8px);
    }
    [data-testid="stMetricLabel"] { color: #8b949e !important; font-size: 0.82rem; }
    [data-testid="stMetricValue"] { color: #58a6ff !important; font-size: 1.5rem; font-weight: 700; }
    [data-testid="stMetricDelta"] { font-size: 0.82rem; }
    /* ── Section headers ── */
    h1 { color: #58a6ff !important; }
    h2 { color: #79c0ff !important; font-size: 1.1rem !important; font-weight: 600 !important; }
    h3 { color: #a5d6ff !important; }
    /* ── Divider ── */
    hr { border-color: rgba(48, 54, 61, 0.6) !important; }
    /* ── Plotly chart container ── */
    .js-plotly-plot { border-radius: 12px; }
    /* ── Status badge ── */
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        background: rgba(35, 134, 54, 0.25);
        border: 1px solid rgba(35, 134, 54, 0.6);
        color: #3fb950;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────
# Colour palette
# ──────────────────────────────────────────────────────────
COLORS = {
    "solar":    "#FFD700",
    "battery":  "#00D4AA",
    "grid":     "#58A6FF",
    "diesel":   "#FF7B7B",
    "actual":   "#E6EDF3",
    "forecast": "#79C0FF",
    "optimized":"#3FB950",
    "baseline": "#FF7B7B",
    "soc":      "#00D4AA",
}

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#8b949e", family="Inter, sans-serif"),
    margin=dict(l=10, r=10, t=40, b=40),
    xaxis=dict(gridcolor="rgba(48,54,61,0.5)", zerolinecolor="rgba(48,54,61,0.5)"),
    yaxis=dict(gridcolor="rgba(48,54,61,0.5)", zerolinecolor="rgba(48,54,61,0.5)"),
    legend=dict(bgcolor="rgba(0,0,0,0)", bordercolor="rgba(48,54,61,0.5)", borderwidth=1),
)


# ──────────────────────────────────────────────────────────
# Data loading (with caching)
# ──────────────────────────────────────────────────────────

@st.cache_data(ttl=3600, show_spinner=False)
def load_pipeline_results(horizon: int, init_soc: float, period: str) -> dict:
    """Cache pipeline results to avoid recomputing on every interaction."""
    from src.pipeline import run_pipeline
    return run_pipeline(horizon=horizon, init_soc=init_soc, use_period=period)


@st.cache_data(show_spinner=False)
def load_metrics_table() -> pd.DataFrame | None:
    path = Path(__file__).resolve().parent.parent / "models" / "metrics.csv"
    if path.exists():
        return pd.read_csv(path)
    return None


@st.cache_data(show_spinner=False)
def load_raw_data() -> pd.DataFrame | None:
    path = Path(__file__).resolve().parent.parent / "data" / "raw" / "microgrid_raw.csv"
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    return None


# ──────────────────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚡ Microgrid Settings")
    st.markdown("---")

    period = st.selectbox(
        "Data period",
        options=["test", "val"],
        help="Which dataset split to run the pipeline on.",
    )
    horizon = st.slider(
        "Forecast horizon (hours)", min_value=6, max_value=48, value=24, step=6
    )
    init_soc = st.slider(
        "Initial battery SoC (%)", min_value=20, max_value=90, value=50, step=5
    ) / 100.0

    st.markdown("---")
    run_btn = st.button("🔄  Run Pipeline", use_container_width=True, type="primary")
    st.markdown("---")
    st.markdown("### Microgrid Specs")
    st.markdown("""
    | Parameter | Value |
    |-----------|-------|
    | Solar capacity | 5 kW |
    | Battery capacity | 10 kWh |
    | SoC limits | 20 – 90% |
    | Grid tariff | TOU (3-band) |
    | Diesel price | £0.40/kWh |
    """)


# ──────────────────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────────────────

st.markdown(
    """
    <h1 style="font-size:2rem; margin-bottom:0">
        ⚡ AI-Based Load Forecasting &amp; Microgrid Optimization
    </h1>
    <p style="color:#8b949e; margin-top:4px; font-size:0.92rem">
        ML-powered demand forecasting + linear programming dispatch — real-time dashboard
    </p>
    """,
    unsafe_allow_html=True,
)
st.markdown("---")


# ──────────────────────────────────────────────────────────
# Run pipeline
# ──────────────────────────────────────────────────────────

models_dir = Path(__file__).resolve().parent.parent / "models"
if not (models_dir / "best_model.txt").exists():
    st.error(
        "⚠️  No trained models found. Please run:\n"
        "```\npython src/data.py\npython src/forecast.py\n```"
    )
    st.stop()

with st.spinner("🔄 Running pipeline … (first run may take a few seconds)"):
    try:
        results = load_pipeline_results(horizon, init_soc, period)
    except Exception as e:
        st.error(f"Pipeline error: {e}")
        st.stop()

optimized = results["optimized"]
baseline  = results["baseline"]
timestamps = results["timestamps"]
actual_load    = np.array(results["actual_load"])
forecast_load  = np.array(results["forecast_load"])
solar_available= np.array(results["solar_available"])
metrics        = results["metrics"]
model_name     = results["model_name"]
hours = list(range(len(timestamps)))


# ──────────────────────────────────────────────────────────
# KPI cards
# ──────────────────────────────────────────────────────────

opt_cost  = optimized["cost"].sum()
base_cost = baseline["cost"].sum()
saving_pct = (base_cost - opt_cost) / base_cost * 100 if base_cost > 0 else 0
solar_pct  = optimized["solar_kw"].sum() / (optimized["load_kw"].sum() + 1e-9) * 100

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("🏆 Best Model", model_name.replace("_", " ").title())
with c2:
    st.metric("📐 Forecast MAE", f"{metrics['MAE']:.3f} kW")
with c3:
    st.metric("💰 Optimized Cost", f"£{opt_cost:.2f}", delta=f"-£{base_cost - opt_cost:.2f} vs baseline")
with c4:
    st.metric("📉 Cost Saving", f"{saving_pct:.1f}%", delta="vs reactive baseline")
with c5:
    st.metric("☀️ Solar Coverage", f"{solar_pct:.1f}%")

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Panel A — Predicted vs Actual Load
# ──────────────────────────────────────────────────────────

st.markdown("## 📈 A) Load Forecast: Predicted vs. Actual")

fig_load = go.Figure()
fig_load.add_trace(go.Scatter(
    x=hours, y=actual_load[:len(hours)],
    name="Actual Load",
    line=dict(color=COLORS["actual"], width=2),
    mode="lines",
))
fig_load.add_trace(go.Scatter(
    x=hours, y=forecast_load[:len(hours)],
    name=f"Forecast ({model_name.replace('_',' ').title()})",
    line=dict(color=COLORS["forecast"], width=2, dash="dash"),
    mode="lines",
))
fig_load.add_trace(go.Scatter(
    x=hours, y=solar_available[:len(hours)],
    name="Solar Available",
    line=dict(color=COLORS["solar"], width=1.5, dash="dot"),
    mode="lines",
    opacity=0.7,
))
fig_load.update_layout(
    **PLOTLY_LAYOUT,
    height=320,
    title=dict(text="kW", font=dict(size=12)),
    xaxis_title="Hour",
    yaxis_title="Power (kW)",
)
st.plotly_chart(fig_load, use_container_width=True)

# Accuracy sub-metrics
a1, a2, a3 = st.columns(3)
a1.metric("MAE",  f"{metrics['MAE']:.4f} kW")
a2.metric("RMSE", f"{metrics['RMSE']:.4f} kW")
a3.metric("MAPE", f"{metrics['MAPE']:.2f} %")

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Panel B — Optimized Source Mix
# ──────────────────────────────────────────────────────────

st.markdown("## ⚡ B) Optimized Dispatch — Source Mix per Hour")

fig_mix = go.Figure()
fig_mix.add_trace(go.Bar(
    x=hours, y=optimized["solar_kw"].values,
    name="Solar", marker_color=COLORS["solar"],
))
fig_mix.add_trace(go.Bar(
    x=hours, y=optimized["battery_discharge"].values,
    name="Battery Discharge", marker_color=COLORS["battery"],
))
fig_mix.add_trace(go.Bar(
    x=hours, y=optimized["grid_kw"].values,
    name="Grid", marker_color=COLORS["grid"],
))
fig_mix.add_trace(go.Bar(
    x=hours, y=optimized["diesel_kw"].values,
    name="Diesel", marker_color=COLORS["diesel"],
))
fig_mix.add_trace(go.Scatter(
    x=hours, y=optimized["load_kw"].values,
    name="Forecasted Load",
    line=dict(color=COLORS["actual"], width=2, dash="dot"),
    mode="lines",
))
fig_mix.update_layout(
    **PLOTLY_LAYOUT,
    barmode="stack",
    height=340,
    xaxis_title="Hour",
    yaxis_title="Power (kW)",
)
st.plotly_chart(fig_mix, use_container_width=True)

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Panel C — Cost Comparison
# ──────────────────────────────────────────────────────────

st.markdown("## 💰 C) Cost Comparison: Optimized vs. Reactive Baseline")

col_chart, col_detail = st.columns([3, 2])

with col_chart:
    fig_cost = go.Figure()
    fig_cost.add_trace(go.Bar(
        x=hours, y=optimized["cost"].values,
        name="Optimized", marker_color=COLORS["optimized"], opacity=0.85,
    ))
    fig_cost.add_trace(go.Bar(
        x=hours, y=baseline["cost"].values,
        name="Baseline", marker_color=COLORS["baseline"], opacity=0.85,
    ))
    fig_cost.update_layout(
        **PLOTLY_LAYOUT,
        barmode="group",
        height=300,
        xaxis_title="Hour",
        yaxis_title="Cost (£)",
    )
    st.plotly_chart(fig_cost, use_container_width=True)

with col_detail:
    st.markdown(f"""
    <br/>
    <div style="background:rgba(30,36,45,0.85); border:1px solid rgba(48,54,61,0.8);
                border-radius:12px; padding:20px; margin-top:10px;">
      <div style="font-size:0.82rem; color:#8b949e;">Total Cost — Optimized</div>
      <div style="font-size:1.8rem; font-weight:700; color:#3fb950;">£{opt_cost:.2f}</div>
      <hr style="margin:12px 0"/>
      <div style="font-size:0.82rem; color:#8b949e;">Total Cost — Baseline</div>
      <div style="font-size:1.8rem; font-weight:700; color:#ff7b7b;">£{base_cost:.2f}</div>
      <hr style="margin:12px 0"/>
      <div style="font-size:0.82rem; color:#8b949e;">Saving</div>
      <div style="font-size:1.5rem; font-weight:700; color:#79c0ff;">
          £{base_cost - opt_cost:.2f} ({saving_pct:.1f}%)
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Energy mix breakdown
    total_energy = optimized["load_kw"].sum() + 1e-9
    st.markdown(f"""
    <br/>
    <div style="background:rgba(30,36,45,0.85); border:1px solid rgba(48,54,61,0.8);
                border-radius:12px; padding:20px;">
      <div style="font-size:0.85rem; color:#8b949e; margin-bottom:8px;">Energy Mix (Optimized)</div>
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span style="color:#FFD700;">☀️ Solar</span>
        <span>{optimized['solar_kw'].sum()/total_energy*100:.1f}%</span>
      </div>
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span style="color:#00D4AA;">🔋 Battery</span>
        <span>{optimized['battery_discharge'].sum()/total_energy*100:.1f}%</span>
      </div>
      <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
        <span style="color:#58A6FF;">🔌 Grid</span>
        <span>{optimized['grid_kw'].sum()/total_energy*100:.1f}%</span>
      </div>
      <div style="display:flex; justify-content:space-between;">
        <span style="color:#FF7B7B;">⛽ Diesel</span>
        <span>{optimized['diesel_kw'].sum()/total_energy*100:.1f}%</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Panel D — Battery SoC
# ──────────────────────────────────────────────────────────

st.markdown("## 🔋 D) Battery State of Charge")

fig_soc = go.Figure()
fig_soc.add_trace(go.Scatter(
    x=hours, y=optimized["soc"].values * 100,
    name="Optimized SoC", fill="tozeroy",
    line=dict(color=COLORS["soc"], width=2),
    fillcolor="rgba(0, 212, 170, 0.15)",
))
fig_soc.add_trace(go.Scatter(
    x=hours, y=baseline["soc"].values * 100,
    name="Baseline SoC",
    line=dict(color=COLORS["baseline"], width=1.5, dash="dash"),
))
fig_soc.add_hline(y=20, line_dash="dot", line_color="rgba(255,123,123,0.5)",
                  annotation_text="Min SoC (20%)", annotation_position="bottom right")
fig_soc.add_hline(y=90, line_dash="dot", line_color="rgba(255,215,0,0.5)",
                  annotation_text="Max SoC (90%)", annotation_position="top right")
fig_soc.update_layout(
    **PLOTLY_LAYOUT,
    height=280,
    xaxis_title="Hour",
    yaxis_title="SoC (%)",
)
fig_soc.update_yaxes(range=[0, 105])
st.plotly_chart(fig_soc, use_container_width=True)

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Panel E — Model comparison metrics table
# ──────────────────────────────────────────────────────────

st.markdown("## 📊 E) Forecasting Model Comparison")

metrics_df = load_metrics_table()
if metrics_df is not None:
    # Show only val metrics
    val_df = metrics_df[metrics_df["model"].str.contains("val", case=False, na=False)].copy()
    val_df["model"] = val_df["model"].str.replace(r"\s*\(val\)", "", regex=True).str.strip()
    val_df = val_df.rename(columns={"model": "Model", "MAE": "MAE (kW)", "RMSE": "RMSE (kW)", "MAPE": "MAPE (%)"})

    def highlight_best(s):
        # Lower is better for all metrics
        is_best = s == s.min()
        return ["background-color: rgba(35,134,54,0.2); color: #3fb950; font-weight:bold"
                if v else "" for v in is_best]

    styled = (
        val_df[["Model", "MAE (kW)", "RMSE (kW)", "MAPE (%)"]].reset_index(drop=True)
        .style.apply(highlight_best, subset=["MAE (kW)", "RMSE (kW)", "MAPE (%)"])
        .format({"MAE (kW)": "{:.4f}", "RMSE (kW)": "{:.4f}", "MAPE (%)": "{:.2f}"})
    )
    st.dataframe(styled, use_container_width=True, height=140)
else:
    st.info("Run `python src/forecast.py` to populate the metrics table.")

st.markdown("---")


# ──────────────────────────────────────────────────────────
# Raw data overview (collapsible)
# ──────────────────────────────────────────────────────────

with st.expander("📂 Raw Dataset Overview", expanded=False):
    raw = load_raw_data()
    if raw is not None:
        st.markdown(f"**{len(raw):,} hourly records** · {raw.index.min().date()} → {raw.index.max().date()}")
        # 7-day sample chart
        sample = raw.iloc[:7*24]
        fig_raw = go.Figure()
        fig_raw.add_trace(go.Scatter(x=sample.index, y=sample["load_kw"], name="Load (kW)",
                                     line=dict(color=COLORS["actual"])))
        fig_raw.add_trace(go.Scatter(x=sample.index, y=sample["solar_kw"], name="Solar (kW)",
                                     line=dict(color=COLORS["solar"])))
        fig_raw.update_layout(**PLOTLY_LAYOUT, height=250, title="First 7 Days")
        st.plotly_chart(fig_raw, use_container_width=True)
        st.dataframe(raw.describe().round(3), use_container_width=True)


# ──────────────────────────────────────────────────────────
# Footer
# ──────────────────────────────────────────────────────────

st.markdown(
    """
    <div style="text-align:center; color:#484f58; font-size:0.78rem; margin-top:24px;">
        AI-Based Load Forecasting for Microgrid Optimization •
        Minor Project • Python · Scikit-learn · XGBoost · TensorFlow · PuLP · Streamlit
    </div>
    """,
    unsafe_allow_html=True,
)
