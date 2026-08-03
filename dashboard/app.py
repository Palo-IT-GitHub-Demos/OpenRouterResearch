"""Streamlit dashboard — Quality vs Cost benchmark visualisation.

Run with:
    streamlit run dashboard/app.py

Reads the latest benchmark CSV from ``results/`` (or a user-selected file) and
renders a Plotly scatter plot with a Pareto frontier overlay.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.pareto import compute_pareto_front

_RESULTS_DIR = Path("results")

st.set_page_config(
    page_title="LLM Benchmark Dashboard",
    page_icon="🤖",
    layout="wide",
)
st.title("LLM Benchmark — Quality vs Cost")

# ── Sidebar: file selection ────────────────────────────────────────────────────

csv_files = sorted(_RESULTS_DIR.glob("*.csv"), reverse=True)
if not csv_files:
    st.warning(
        "No benchmark results found in `results/`.  "
        "Run `python -m src.main` first."
    )
    st.stop()

selected_file: Path = st.sidebar.selectbox(  # type: ignore[assignment]
    "Benchmark run",
    options=csv_files,
    format_func=lambda p: p.stem,
)
df = pd.read_csv(selected_file)

# ── Column checks ──────────────────────────────────────────────────────────────

required = {"model", "avg_quality_score", "prompt_price_per_token"}
missing = required - set(df.columns)
if missing:
    st.error(f"Missing columns in result file: {missing}")
    st.stop()

# ── Derived columns ────────────────────────────────────────────────────────────

df["cost_per_1m_tokens_usd"] = df["prompt_price_per_token"].fillna(0) * 1_000_000

if "is_vulnerable" not in df.columns:
    df["is_vulnerable"] = False
if "leak_count" not in df.columns:
    df["leak_count"] = 0
if "zero_data_retention" not in df.columns:
    df["zero_data_retention"] = False


def _security_label(row: pd.Series) -> str:  # type: ignore[type-arg]
    if row["is_vulnerable"]:
        return "Vulnerable"
    if row["leak_count"] > 0:
        return "Partial Risk"
    return "Safe"


df["security_status"] = df.apply(_security_label, axis=1)

_COLOR_MAP = {"Safe": "#2ecc71", "Partial Risk": "#f39c12", "Vulnerable": "#e74c3c"}

# ── Pareto frontier ────────────────────────────────────────────────────────────

plot_df = df.dropna(subset=["cost_per_1m_tokens_usd", "avg_quality_score"])
pareto_df = compute_pareto_front(
    plot_df, cost_col="cost_per_1m_tokens_usd", quality_col="avg_quality_score"
)

# ── Plotly figure ──────────────────────────────────────────────────────────────

fig = go.Figure()

for label, colour in _COLOR_MAP.items():
    subset = plot_df[plot_df["security_status"] == label]
    if subset.empty:
        continue
    hover_parts = [
        "<b>%{customdata[0]}</b>",
        "Cost / 1M tokens: $%{x:.4f}",
        "Avg quality score: %{y:.2f}",
        "ZDR: %{customdata[1]}",
    ]
    fig.add_trace(
        go.Scatter(
            x=subset["cost_per_1m_tokens_usd"],
            y=subset["avg_quality_score"],
            mode="markers+text",
            name=label,
            marker=dict(color=colour, size=14, line=dict(width=1, color="#333")),
            text=subset["model"].str.split("/").str[-1],
            textposition="top center",
            customdata=subset[["model", "zero_data_retention"]].values,
            hovertemplate="<br>".join(hover_parts) + "<extra></extra>",
        )
    )

if not pareto_df.empty:
    fig.add_trace(
        go.Scatter(
            x=pareto_df["cost_per_1m_tokens_usd"],
            y=pareto_df["avg_quality_score"],
            mode="lines",
            name="Pareto frontier",
            line=dict(color="#3498db", dash="dot", width=2),
            hoverinfo="skip",
        )
    )

fig.update_layout(
    xaxis_title="Cost per 1M input tokens (USD)",
    yaxis_title="Avg quality score (1–5)",
    legend_title="Security",
    height=560,
    hovermode="closest",
    font=dict(size=13),
)

st.plotly_chart(fig, use_container_width=True)

# ── Pareto summary ─────────────────────────────────────────────────────────────

if not pareto_df.empty:
    with st.expander("Pareto-optimal models (best quality/cost trade-off)", expanded=True):
        st.dataframe(
            pareto_df[
                ["model", "avg_quality_score", "cost_per_1m_tokens_usd", "security_status"]
            ],
            use_container_width=True,
            hide_index=True,
        )

# ── Full results table ─────────────────────────────────────────────────────────

st.subheader("Full benchmark results")
st.dataframe(df, use_container_width=True, hide_index=True)
