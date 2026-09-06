"""Quality-dimension visualisation helpers for the Streamlit dashboard.

Pure functions — no I/O, no Streamlit calls — so they can be unit-tested
independently and reused by the static HTML export.

Expected columns
----------------
For :func:`build_quality_dimension_heatmap`:
    ``model``, ``quality_dimension``, ``dimension_score``
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go


def build_quality_dimension_heatmap(dimension_df: pd.DataFrame) -> go.Figure:
    """Return a heatmap of dimension_score per model x quality dimension.

    Args:
        dimension_df: Long-format DataFrame with columns
            ``model``, ``quality_dimension``, ``dimension_score`` (1-5).

    Returns:
        Plotly Figure — red (1) to green (5) colour scale.
    """
    required = {"model", "quality_dimension", "dimension_score"}
    if dimension_df.empty or not required.issubset(dimension_df.columns):
        fig = go.Figure()
        fig.add_annotation(text="No per-dimension quality data available", showarrow=False)
        return fig

    pivot = dimension_df.pivot_table(
        index="model",
        columns="quality_dimension",
        values="dimension_score",
        aggfunc="mean",
    )
    pivot = pivot.reindex(sorted(pivot.columns), axis=1)

    fig = go.Figure(
        go.Heatmap(
            z=pivot.values.tolist(),
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale=[[0, "#e74c3c"], [0.5, "#f39c12"], [1, "#2ecc71"]],
            zmin=1.0,
            zmax=5.0,
            text=[[f"{v:.2f}" if pd.notna(v) else "—" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            colorbar=dict(title="Score (1–5)"),
            hovertemplate="Model: %{y}<br>Dimension: %{x}<br>Score: %{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="Quality score by dimension",
        xaxis_title="Quality dimension",
        yaxis_title="Model",
        height=max(300, 60 * len(pivot)),
    )
    return fig
