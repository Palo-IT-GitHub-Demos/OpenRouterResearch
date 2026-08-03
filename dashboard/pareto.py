"""Pareto frontier computation for the benchmark dashboard."""

from __future__ import annotations

import pandas as pd


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

    sorted_df = df.sort_values(
        [cost_col, quality_col], ascending=[True, False]
    ).reset_index(drop=True)
    pareto_mask: list[bool] = []
    max_quality_seen = float("-inf")

    for quality in sorted_df[quality_col]:
        if quality >= max_quality_seen:
            pareto_mask.append(True)
            max_quality_seen = float(quality)
        else:
            pareto_mask.append(False)

    return sorted_df[pareto_mask].reset_index(drop=True)
