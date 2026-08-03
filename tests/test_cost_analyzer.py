"""Unit tests for src/evaluators/cost_analyzer.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.evaluators.cost_analyzer import CostAnalyzer, UsageRecord


@pytest.fixture()
def mock_client() -> MagicMock:
    client = MagicMock()
    client.get_models.return_value = [
        {
            "id": "openai/gpt-4o-mini",
            "name": "GPT-4o mini",
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "context_length": 128000,
        },
        {
            "id": "anthropic/claude-3.5-sonnet",
            "name": "Claude 3.5 Sonnet",
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "context_length": 200000,
        },
    ]
    return client


@pytest.fixture()
def analyzer(mock_client: MagicMock) -> CostAnalyzer:
    return CostAnalyzer(mock_client)


class TestFetchPricing:
    def test_returns_dataframe_with_expected_columns(
        self, analyzer: CostAnalyzer
    ) -> None:
        df = analyzer.fetch_pricing()
        assert set(df.columns) >= {
            "model_id",
            "prompt_price_per_token",
            "completion_price_per_token",
        }

    def test_parses_prices_as_float(self, analyzer: CostAnalyzer) -> None:
        df = analyzer.fetch_pricing()
        row = df[df["model_id"] == "openai/gpt-4o-mini"].iloc[0]
        assert row["prompt_price_per_token"] == pytest.approx(0.000001)
        assert row["completion_price_per_token"] == pytest.approx(0.000002)

    def test_handles_missing_pricing(self, mock_client: MagicMock) -> None:
        mock_client.get_models.return_value = [{"id": "mystery/model", "name": "Mystery"}]
        analyzer = CostAnalyzer(mock_client)
        df = analyzer.fetch_pricing()
        assert df.iloc[0]["prompt_price_per_token"] == 0.0


class TestComputeCostMatrix:
    def test_calculates_costs_correctly(self, analyzer: CostAnalyzer) -> None:
        pricing_df = analyzer.fetch_pricing()
        usage = [
            UsageRecord("openai/gpt-4o-mini", prompt_tokens=1000, completion_tokens=500),
        ]
        result = analyzer.compute_cost_matrix(usage, pricing_df)

        row = result[result["model"] == "openai/gpt-4o-mini"].iloc[0]
        assert row["input_cost_usd"] == pytest.approx(1000 * 0.000001)
        assert row["output_cost_usd"] == pytest.approx(500 * 0.000002)
        assert row["total_cost_usd"] == pytest.approx(row["input_cost_usd"] + row["output_cost_usd"])

    def test_empty_usage_returns_empty_dataframe(self, analyzer: CostAnalyzer) -> None:
        pricing_df = analyzer.fetch_pricing()
        result = analyzer.compute_cost_matrix([], pricing_df)
        assert result.empty

    def test_aggregates_multiple_calls_for_same_model(
        self, analyzer: CostAnalyzer
    ) -> None:
        pricing_df = analyzer.fetch_pricing()
        usage = [
            UsageRecord("openai/gpt-4o-mini", 100, 50),
            UsageRecord("openai/gpt-4o-mini", 200, 100),
        ]
        result = analyzer.compute_cost_matrix(usage, pricing_df)
        row = result[result["model"] == "openai/gpt-4o-mini"].iloc[0]
        assert row["prompt_tokens"] == 300
        assert row["requests"] == 2
