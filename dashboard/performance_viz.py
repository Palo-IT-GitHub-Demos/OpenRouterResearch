"""Performance visualisation helpers for the Streamlit dashboard.

Pure functions — no I/O, no Streamlit calls — so they can be unit-tested
independently and reused by the static HTML export.

Expected columns
----------------
For :func:`build_latency_bar`:
    ``model``, ``actual_latency_p50_ms``, ``actual_latency_p95_ms``
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def build_latency_bar(performance_df: pd.DataFrame) -> go.Figure:
    """Return a grouped bar chart of p50/p95 response latency per model.

    Both percentiles are computed from the network-only latency of each
    call (excludes time spent queueing behind ``MAX_CONCURRENT_REQUESTS`` and
    retry back-off waits) — see ``src/api/openrouter_client.py``.

    Args:
        performance_df: DataFrame with ``model``, ``actual_latency_p50_ms``
            and ``actual_latency_p95_ms`` columns, one row per model.

    Returns:
        Plotly Figure — lower bars are faster/better.
    """
    required = {"model", "actual_latency_p50_ms", "actual_latency_p95_ms"}
    if performance_df.empty or not required.issubset(performance_df.columns):
        fig = go.Figure()
        fig.add_annotation(text="No latency data available for this run", showarrow=False)
        return fig

    df = performance_df[["model", "actual_latency_p50_ms", "actual_latency_p95_ms"]].drop_duplicates("model")
    df = df.dropna(subset=["actual_latency_p50_ms", "actual_latency_p95_ms"], how="all")
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No latency data available for this run", showarrow=False)
        return fig

    df = df.sort_values("actual_latency_p50_ms", na_position="last")

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="p50 (median)",
            x=df["actual_latency_p50_ms"],
            y=df["model"],
            orientation="h",
            marker_color="#3498db",
            hovertemplate="Model: %{y}<br>p50: %{x:.0f} ms<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            name="p95",
            x=df["actual_latency_p95_ms"],
            y=df["model"],
            orientation="h",
            marker_color="#e67e22",
            hovertemplate="Model: %{y}<br>p95: %{x:.0f} ms<extra></extra>",
        )
    )
    fig.update_layout(
        title="Response latency per model (network time only, excludes queueing)",
        xaxis_title="Latency (ms) — lower is faster",
        yaxis_title="Model",
        barmode="group",
        height=max(300, 70 * len(df)),
    )
    return fig
