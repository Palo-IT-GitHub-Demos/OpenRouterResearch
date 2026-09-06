"""Unit tests for dashboard/performance_viz.py."""

from __future__ import annotations

import pandas as pd

from dashboard.performance_viz import build_latency_bar


def test_returns_placeholder_when_no_latency_columns() -> None:
    figure = build_latency_bar(pd.DataFrame({"model": ["model-a"]}))

    assert "No latency data" in figure.layout.annotations[0].text


def test_returns_placeholder_when_all_latency_values_are_missing() -> None:
    df = pd.DataFrame(
        {
            "model": ["model-a"],
            "actual_latency_p50_ms": [None],
            "actual_latency_p95_ms": [None],
        }
    )

    figure = build_latency_bar(df)

    assert "No latency data" in figure.layout.annotations[0].text


def test_builds_grouped_p50_p95_bars_sorted_by_p50() -> None:
    df = pd.DataFrame(
        {
            "model": ["slow-model", "fast-model"],
            "actual_latency_p50_ms": [500.0, 100.0],
            "actual_latency_p95_ms": [900.0, 150.0],
        }
    )

    figure = build_latency_bar(df)

    assert len(figure.data) == 2
    assert figure.data[0].name == "p50 (median)"
    assert figure.data[1].name == "p95"
    # Sorted fastest (lowest p50) first.
    assert list(figure.data[0].y) == ["fast-model", "slow-model"]
    assert list(figure.data[0].x) == [100.0, 500.0]
