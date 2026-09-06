"""Security visualisation helpers for the Streamlit dashboard.

All functions take a pre-built DataFrame and return a Plotly Figure —
no I/O, no Streamlit calls — so they can be unit-tested independently.

Expected columns
----------------
For :func:`build_owasp_heatmap` and :func:`build_rsi_bar`:
    ``model``, ``category_id``, ``category_name``, ``vulnerability_rate``

For :func:`build_cost_security_quadrant`:
    ``model``, ``rsi``, ``tco_usd``, ``avg_quality_score`` (optional)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.evaluators.security_scanner import RSI_ROBUST_THRESHOLD, RSI_VULNERABLE_THRESHOLD


def build_owasp_heatmap(security_df: pd.DataFrame) -> go.Figure:
    """Return a heatmap of vulnerability_rate per model × OWASP category.

    Args:
        security_df: Long-format DataFrame with columns
            ``model``, ``category_id``, ``vulnerability_rate``.

    Returns:
        Plotly Figure — green (0.0) to red (1.0) colour scale.
    """
    if security_df.empty or not {"model", "category_id", "vulnerability_rate"}.issubset(security_df.columns):
        fig = go.Figure()
        fig.add_annotation(text="No security data available", showarrow=False)
        return fig

    pivot = security_df.pivot_table(
        index="model",
        columns="category_id",
        values="vulnerability_rate",
        aggfunc="mean",
    )
    pivot = pivot.reindex(
        index=sorted(security_df["model"].unique()),
        columns=sorted(security_df["category_id"].unique()),
    )

    # Sort columns by OWASP ID
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)

    not_scored: set[str] = set()
    if "scored" in security_df.columns:
        not_scored = set(security_df.loc[~security_df["scored"].astype(bool), "category_id"].unique())
    labels = [f"{c}*" if c in not_scored else str(c) for c in pivot.columns]

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values.tolist(),
            x=labels,
            y=list(pivot.index),
            colorscale=[[0, "#2ecc71"], [0.5, "#f39c12"], [1, "#e74c3c"]],
            zmin=0.0,
            zmax=1.0,
            text=[[f"{v:.0%}" if pd.notna(v) else "N/A" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            colorbar=dict(title="Vulnerability rate", tickformat=".0%"),
            hovertemplate="Model: %{y}<br>Category: %{x}<br>Vulnerability rate: %{z:.0%}<extra></extra>",
            hoverongaps=False,
        )
    )
    fig.update_layout(
        title="OWASP LLM Top 10 — vulnerability rate by model",
        xaxis_title=(
            "OWASP category — * = reported but excluded from the RSI (not exercisable by a single-turn probe)"
            if not_scored
            else "OWASP category"
        ),
        yaxis_title="Model",
        height=max(300, 60 * len(pivot)),
    )
    return fig


def build_rsi_bar(security_df: pd.DataFrame) -> go.Figure:
    """Return a horizontal bar chart ranking models by Robustness Safety Index.

    Args:
        security_df: DataFrame with at least ``model`` and ``rsi`` columns.
            RSI values are expected in [0, 100].

    Returns:
        Plotly Figure — bars coloured from red (low RSI) to green (high RSI).
    """
    if security_df.empty or not {"model", "rsi"}.issubset(security_df.columns):
        fig = go.Figure()
        fig.add_annotation(text="No RSI data available", showarrow=False)
        return fig

    columns = ["model", "rsi"] + [c for c in ("leak_count",) if c in security_df.columns]
    df = security_df[columns].drop_duplicates("model").sort_values("rsi")
    leaked = (
        pd.to_numeric(df["leak_count"], errors="coerce").fillna(0) > 0
        if "leak_count" in df.columns
        else pd.Series(False, index=df.index)
    )

    colors = [
        "#e74c3c" if rsi < RSI_VULNERABLE_THRESHOLD else "#f39c12" if rsi < RSI_ROBUST_THRESHOLD else "#2ecc71"
        for rsi in df["rsi"]
    ]

    fig = go.Figure(
        go.Bar(
            x=df["rsi"],
            y=df["model"],
            orientation="h",
            marker_color=colors,
            text=[
                f"{v:.1f}" + (" \u26a0 confirmed leak" if lk else "")
                for v, lk in zip(df["rsi"], leaked, strict=True)
            ],
            textposition="outside",
            hovertemplate="Model: %{y}<br>RSI: %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Robustness Safety Index (RSI) \u2014 higher is safer",
        xaxis=dict(title="RSI (0\u2013100)", range=[0, 130]),
        yaxis_title="Model",
        height=max(300, 55 * len(df)),
    )
    fig.add_vline(
        x=RSI_VULNERABLE_THRESHOLD,
        line_dash="dot",
        line_color="#e74c3c",
        annotation_text=f"< {RSI_VULNERABLE_THRESHOLD:.0f} vulnerable",
    )
    fig.add_vline(
        x=RSI_ROBUST_THRESHOLD,
        line_dash="dot",
        line_color="#2ecc71",
        annotation_text=f"\u2265 {RSI_ROBUST_THRESHOLD:.0f} robust",
    )
    return fig


def build_cost_security_quadrant(results_df: pd.DataFrame) -> go.Figure:
    """Return a scatter plot: RSI (X) vs TCO monthly (Y), sized by quality.

    The ideal model is in the top-right quadrant: high RSI *and* low TCO.
    Y-axis is inverted so "cheap" models appear at the top.

    Args:
        results_df: DataFrame with columns ``model``, ``rsi``, ``tco_usd``.
            ``avg_quality_score`` is used for marker size when present.

    Returns:
        Plotly Figure.
    """
    required = {"model", "rsi", "tco_usd"}
    if results_df.empty or not required.issubset(results_df.columns):
        fig = go.Figure()
        fig.add_annotation(text="No data available for quadrant", showarrow=False)
        return fig

    df = results_df[list(required | {"avg_quality_score"} & set(results_df.columns))].copy()
    df = df[df["tco_usd"].apply(lambda v: isinstance(v, float | int) and v < float("inf"))]

    if df.empty:
        fig = go.Figure()
        fig.add_annotation(text="No finite TCO data to plot", showarrow=False)
        return fig

    size_col = "avg_quality_score" if "avg_quality_score" in df.columns else None
    sizes = (df[size_col].fillna(1.0) * 10).tolist() if size_col else [20] * len(df)

    fig = go.Figure(
        go.Scatter(
            x=df["rsi"],
            y=df["tco_usd"],
            mode="markers+text",
            text=df["model"].apply(lambda m: m.split("/")[-1]),
            textposition="top center",
            marker=dict(
                size=sizes,
                color=df["rsi"],
                colorscale=[[0, "#e74c3c"], [0.5, "#f39c12"], [1, "#2ecc71"]],
                showscale=True,
                colorbar=dict(title="RSI"),
            ),
            hovertemplate=("<b>%{text}</b><br>" "RSI: %{x:.1f}<br>" "TCO/month: $%{y:.2f}<extra></extra>"),
        )
    )
    fig.update_layout(
        title="Cost vs Security Quadrant — ideal: high RSI, low TCO",
        xaxis=dict(title="RSI (0–100, higher = safer)", range=[0, 105]),
        yaxis=dict(title="Monthly TCO (USD)", autorange="reversed"),
        height=500,
    )
    return fig
