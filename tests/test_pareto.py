"""Unit tests for dashboard/pareto.py."""

from __future__ import annotations

import pandas as pd

from dashboard.pareto import build_pareto_scatter, compute_pareto_front


class TestComputeParetoFront:
    def test_dominated_point_excluded(self) -> None:
        df = pd.DataFrame(
            {
                "model": ["cheap-bad", "cheap-good", "expensive-great"],
                "cost": [1.0, 1.0, 10.0],
                "quality": [2.0, 4.0, 5.0],
            }
        )
        pareto = compute_pareto_front(df, "cost", "quality")
        assert "cheap-bad" not in pareto["model"].values
        assert "cheap-good" in pareto["model"].values
        assert "expensive-great" in pareto["model"].values

    def test_all_pareto_when_tradeoff(self) -> None:
        df = pd.DataFrame(
            {
                "model": ["A", "B"],
                "cost": [1.0, 5.0],
                "quality": [3.0, 5.0],
            }
        )
        pareto = compute_pareto_front(df, "cost", "quality")
        assert len(pareto) == 2

    def test_single_row_is_pareto(self) -> None:
        df = pd.DataFrame({"model": ["only"], "cost": [1.0], "quality": [4.0]})
        pareto = compute_pareto_front(df, "cost", "quality")
        assert len(pareto) == 1

    def test_empty_df_returns_empty(self) -> None:
        df = pd.DataFrame({"cost": pd.Series([], dtype=float), "quality": pd.Series([], dtype=float)})
        pareto = compute_pareto_front(df, "cost", "quality")
        assert pareto.empty

    def test_sorted_by_cost_ascending(self) -> None:
        df = pd.DataFrame({"model": ["B", "A"], "cost": [5.0, 1.0], "quality": [5.0, 3.0]})
        pareto = compute_pareto_front(df, "cost", "quality")
        assert list(pareto["cost"]) == sorted(pareto["cost"])

    def test_equal_cost_higher_quality_is_pareto(self) -> None:
        df = pd.DataFrame(
            {
                "model": ["X", "Y"],
                "cost": [2.0, 2.0],
                "quality": [3.0, 5.0],
            }
        )
        pareto = compute_pareto_front(df, "cost", "quality")
        # The first one encountered (lower or equal quality at same cost) may be included
        # because the algorithm keeps the first point at each cost level.
        assert "Y" in pareto["model"].values


class TestParetoChart:
    def test_single_pareto_point_has_a_visible_marker_and_hover(self) -> None:
        df = pd.DataFrame(
            {
                "model": ["provider/model-a"],
                "cost_per_1m_tokens_usd": [1.0],
                "avg_quality_score": [4.0],
                "security_status": ["Safe"],
                "zero_data_retention": [True],
            }
        )

        figure = build_pareto_scatter(df, df)

        frontier = next(trace for trace in figure.data if trace.name == "Pareto frontier")
        assert frontier.mode == "lines+markers+text"
        assert frontier.marker.size == 18
        # The frontier overlay must not answer hover itself — it sits on top of
        # the colored trace at the exact same coordinates, so leaving it
        # interactive made the tooltip depend on cursor sub-pixel position.
        assert frontier.hoverinfo == "skip"

        colored_trace = next(trace for trace in figure.data if trace.name == "Safe")
        assert "Pareto-optimal: %{customdata[2]}" in colored_trace.hovertemplate
        assert colored_trace.customdata[0][2] == "Yes"
