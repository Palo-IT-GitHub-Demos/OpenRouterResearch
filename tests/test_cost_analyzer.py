"""Unit tests for src/evaluators/cost_analyzer.py."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.api.openrouter_client import CallCostRecord
from src.evaluators.cost_analyzer import (
    BUILTIN_WORKLOAD_PROFILES,
    CostAnalyzer,
    UsageRecord,
    WorkloadProfile,
    call_costs_to_dataframe,
    compute_cer,
    compute_tco,
    summarize_actual_call_costs,
)


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
    def test_returns_dataframe_with_expected_columns(self, analyzer: CostAnalyzer) -> None:
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

    def test_aggregates_multiple_calls_for_same_model(self, analyzer: CostAnalyzer) -> None:
        pricing_df = analyzer.fetch_pricing()
        usage = [
            UsageRecord("openai/gpt-4o-mini", 100, 50),
            UsageRecord("openai/gpt-4o-mini", 200, 100),
        ]
        result = analyzer.compute_cost_matrix(usage, pricing_df)
        row = result[result["model"] == "openai/gpt-4o-mini"].iloc[0]
        assert row["prompt_tokens"] == 300
        assert row["requests"] == 2


# ── WorkloadProfile ────────────────────────────────────────────────────────────


_PROFILE = WorkloadProfile("test", daily_requests=100, avg_prompt_tokens=500, avg_completion_tokens=250)


class TestWorkloadProfile:
    def test_monthly_prompt_tokens(self) -> None:
        # 100 req/day × 500 tokens × 22 days = 1_100_000
        assert _PROFILE.monthly_prompt_tokens == 100 * 500 * 22

    def test_monthly_completion_tokens(self) -> None:
        assert _PROFILE.monthly_completion_tokens == 100 * 250 * 22

    def test_builtin_profiles_exist(self) -> None:
        assert "enterprise_qa" in BUILTIN_WORKLOAD_PROFILES
        assert "code_assistant" in BUILTIN_WORKLOAD_PROFILES
        assert "document_analysis" in BUILTIN_WORKLOAD_PROFILES
        assert "chatbot_high_volume" in BUILTIN_WORKLOAD_PROFILES


# ── compute_tco ────────────────────────────────────────────────────────────────


def _make_pricing_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_id": "openai/gpt-4o-mini",
                "prompt_price_per_token": 0.000001,
                "completion_price_per_token": 0.000002,
                "context_length": 128000,
            }
        ]
    )


class TestComputeTco:
    def test_known_price_returns_correct_tco(self) -> None:
        pricing = _make_pricing_df()
        profile = WorkloadProfile("t", 100, 500, 250, 22)
        tco = compute_tco("openai/gpt-4o-mini", pricing, profile)
        expected = profile.monthly_prompt_tokens * 0.000001 + profile.monthly_completion_tokens * 0.000002
        assert tco == pytest.approx(expected)

    def test_missing_model_returns_inf(self) -> None:
        pricing = _make_pricing_df()
        tco = compute_tco("unknown/model", pricing, _PROFILE)
        assert math.isinf(tco)

    def test_empty_pricing_returns_inf(self) -> None:
        tco = compute_tco("any/model", pd.DataFrame(), _PROFILE)
        assert math.isinf(tco)


# ── compute_cer ────────────────────────────────────────────────────────────────


class TestComputeCer:
    def test_zero_tco_returns_zero(self) -> None:
        assert compute_cer(4.5, 0.0) == 0.0

    def test_inf_tco_returns_zero(self) -> None:
        assert compute_cer(4.5, float("inf")) == 0.0

    def test_valid_cer_ranking(self) -> None:
        # Model A: score=4, tco=10 → CER = 0.4
        # Model B: score=3, tco=15 → CER = 0.2
        cer_a = compute_cer(4.0, 10.0)
        cer_b = compute_cer(3.0, 15.0)
        assert cer_a > cer_b

    def test_positive_score_positive_tco(self) -> None:
        cer = compute_cer(3.5, 100.0)
        assert cer > 0.0


class TestActualCallCostSummary:
    def test_distinguishes_real_zero_cost_from_missing_cost(self) -> None:
        records = (
            CallCostRecord(
                usage_context="quality_screen",
                requested_model="free-model",
                resolved_model="free-model",
                generation_id="gen-free",
                prompt_tokens=10,
                completion_tokens=4,
                total_tokens=14,
                actual_cost_credits=0.0,
                cost_source="openrouter_usage",
                latency_ms=120.0,
                network_latency_ms=120.0,
            ),
            CallCostRecord(
                usage_context="security_scan",
                requested_model="unknown-cost-model",
                resolved_model="unknown-cost-model",
                generation_id="gen-unknown",
                prompt_tokens=20,
                completion_tokens=8,
                total_tokens=28,
                actual_cost_credits=None,
                cost_source="unavailable",
                latency_ms=140.0,
                network_latency_ms=140.0,
            ),
        )

        summary = summarize_actual_call_costs(call_costs_to_dataframe(records))
        free_row = summary.loc[summary["model"] == "free-model"].iloc[0]
        unknown_row = summary.loc[summary["model"] == "unknown-cost-model"].iloc[0]

        assert free_row["actual_cost_credits"] == 0.0
        assert free_row["actual_cost_coverage_rate"] == 1.0
        assert free_row["actual_cost_missing_call_count"] == 0
        assert unknown_row["actual_cost_credits"] == 0.0
        assert unknown_row["actual_cost_coverage_rate"] == 0.0
        assert unknown_row["actual_cost_missing_call_count"] == 1

    def test_aggregates_call_usage_and_detects_routing_mismatch(self) -> None:
        records = (
            CallCostRecord(
                usage_context="quality_screen",
                requested_model="requested-model",
                resolved_model="resolved-model",
                generation_id="gen-1",
                prompt_tokens=100,
                completion_tokens=50,
                total_tokens=150,
                actual_cost_credits=0.001,
                cost_source="openrouter_usage",
                latency_ms=200.0,
                network_latency_ms=150.0,
            ),
            CallCostRecord(
                usage_context="security_scan",
                requested_model="requested-model",
                resolved_model="requested-model",
                generation_id="gen-2",
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                actual_cost_credits=0.0002,
                cost_source="openrouter_usage",
                latency_ms=50.0,
                network_latency_ms=50.0,
            ),
        )

        row = summarize_actual_call_costs(call_costs_to_dataframe(records)).iloc[0]

        assert row["actual_cost_credits"] == pytest.approx(0.0012)
        assert row["actual_cost_call_count"] == 2
        assert row["actual_cost_reported_call_count"] == 2
        assert row["actual_prompt_tokens"] == 120
        assert row["actual_completion_tokens"] == 60
        assert row["actual_latency_ms"] == pytest.approx(250.0)
        assert row["actual_model_mismatch_call_count"] == 1

    def test_latency_percentiles_and_throughput_use_network_latency_not_wall_clock(self) -> None:
        # latency_ms includes queueing/retry time; network_latency_ms is the
        # actual request/response duration once the call was in flight.
        records = (
            CallCostRecord(
                usage_context="quality_screen",
                requested_model="model-a",
                resolved_model="model-a",
                generation_id="gen-1",
                prompt_tokens=10,
                completion_tokens=40,
                total_tokens=50,
                actual_cost_credits=0.001,
                cost_source="openrouter_usage",
                latency_ms=5_000.0,  # e.g. queued for 4.85s behind other calls
                network_latency_ms=150.0,
            ),
            CallCostRecord(
                usage_context="quality_screen",
                requested_model="model-a",
                resolved_model="model-a",
                generation_id="gen-2",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                actual_cost_credits=0.001,
                cost_source="openrouter_usage",
                latency_ms=50.0,
                network_latency_ms=50.0,
            ),
        )

        row = summarize_actual_call_costs(call_costs_to_dataframe(records)).iloc[0]

        # Percentiles reflect the fast/slow network calls (50, 150), never the
        # 5-second wall-clock figure that included queueing.
        assert row["actual_latency_p50_ms"] == pytest.approx(100.0)
        assert row["actual_latency_p95_ms"] == pytest.approx(145.0)
        # 60 completion tokens over 0.2s of network time = 300 tokens/second.
        assert row["actual_tokens_per_second"] == pytest.approx(300.0)

    def test_legacy_ledger_without_network_latency_falls_back_to_wall_clock(self) -> None:
        legacy_df = pd.DataFrame(
            [
                {
                    "requested_model": "model-a",
                    "resolved_model": "model-a",
                    "actual_cost_credits": 0.001,
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                    "latency_ms": 100.0,
                    # No network_latency_ms column at all — pre-Phase-D ledger.
                }
            ]
        )

        row = summarize_actual_call_costs(legacy_df).iloc[0]

        assert row["actual_latency_p50_ms"] == pytest.approx(100.0)
        assert row["actual_latency_p95_ms"] == pytest.approx(100.0)
