"""Pareto frontier computation and chart for the benchmark dashboard."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

_SECURITY_COLORS = {"Safe": "#2ecc71", "Partial risk": "#f39c12", "Vulnerable": "#e74c3c"}


def compute_pareto_front(
    df: pd.DataFrame,
    cost_col: str,
    quality_col: str,
) -> pd.DataFrame:
    """Return the Pareto-optimal subset of *df* (min cost, max quality).

    A model is Pareto-optimal when no other model simultaneously offers a
    lower cost **and** a higher quality score.

    Algorithm: sort by cost ascending; track the maximum quality seen so far;
    a point is Pareto-optimal if its quality meets or exceeds that maximum.
    This runs in O(n log n) time.

    Args:
        df: DataFrame containing at least *cost_col* and *quality_col*.
        cost_col: Column name for the cost axis (lower is better).
        quality_col: Column name for the quality axis (higher is better).

    Returns:
        Filtered DataFrame containing only Pareto-optimal rows, sorted by
        *cost_col* ascending.
    """
    if df.empty:
        return df.copy()

    sorted_df = df.sort_values([cost_col, quality_col], ascending=[True, False]).reset_index(drop=True)
    pareto_mask: list[bool] = []
    max_quality_seen = float("-inf")

    for quality in sorted_df[quality_col]:
        if quality >= max_quality_seen:
            pareto_mask.append(True)
            max_quality_seen = float(quality)
        else:
            pareto_mask.append(False)

    return sorted_df[pareto_mask].reset_index(drop=True)


def build_pareto_scatter(plot_df: pd.DataFrame, pareto_df: pd.DataFrame) -> go.Figure:
    """Return the quality-vs-cost scatter, colour-coded by security status.

    Args:
        plot_df: DataFrame with ``model``, ``cost_per_1m_tokens_usd``,
            ``avg_quality_score``, ``security_status`` and
            ``zero_data_retention`` columns — one point per model.
        pareto_df: Pareto-optimal subset of *plot_df* (see
            :func:`compute_pareto_front`), drawn as a dotted frontier line.

    Returns:
        Plotly Figure.
    """
    pareto_models = set(pareto_df["model"]) if not pareto_df.empty else set()

    figure = go.Figure()
    for label, color in _SECURITY_COLORS.items():
        subset = plot_df.loc[plot_df["security_status"] == label]
        if subset.empty:
            continue
        is_pareto = subset["model"].isin(pareto_models).map({True: "Yes", False: "No"})
        figure.add_trace(
            go.Scatter(
                x=subset["cost_per_1m_tokens_usd"],
                y=subset["avg_quality_score"],
                mode="markers+text",
                name=label,
                marker=dict(color=color, size=14, line=dict(width=1, color="#333")),
                text=subset["model"].str.split("/").str[-1],
                textposition="top center",
                customdata=subset[["model", "zero_data_retention"]].assign(is_pareto=is_pareto).values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Cost / 1M input tokens: $%{x:.4f}<br>"
                    "Quality screen score: %{y:.2f}<br>"
                    "Zero data retention: %{customdata[1]}<br>"
                    "Pareto-optimal: %{customdata[2]}<extra></extra>"
                ),
            )
        )

    if not pareto_df.empty:
        # No hovertemplate here: this trace only draws the dotted frontier line
        # and diamond markers on top of the colored points above, at the exact
        # same coordinates — leaving it interactive made the tooltip content
        # depend on sub-pixel cursor position (edge vs. center of the diamond).
        figure.add_trace(
            go.Scatter(
                x=pareto_df["cost_per_1m_tokens_usd"],
                y=pareto_df["avg_quality_score"],
                mode="lines+markers+text",
                name="Pareto frontier",
                line=dict(color="#1d4ed8", dash="dot", width=3),
                marker=dict(color="#ffffff", size=18, line=dict(color="#1d4ed8", width=3), symbol="diamond"),
                text=pareto_df["model"].str.split("/").str[-1],
                textposition="bottom center",
                hoverinfo="skip",
            )
        )

    figure.update_layout(
        xaxis_title="Cost per 1M input tokens (USD)",
        yaxis_title="Generic quality screen score (1–5)",
        legend_title="Security",
        height=560,
        hovermode="closest",
    )
    return figure
