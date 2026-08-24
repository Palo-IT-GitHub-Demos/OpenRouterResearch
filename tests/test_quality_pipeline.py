"""Integration-oriented tests for quality score merging and decision metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.main import MergePipeline, _export, _merge_results


def _pricing() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_id": "model-a",
                "prompt_price_per_token": 0.000001,
                "completion_price_per_token": 0.000002,
                "context_length": 128000,
            },
            {
                "model_id": "model-b",
                "prompt_price_per_token": 0.000001,
                "completion_price_per_token": 0.000002,
                "context_length": 128000,
            },
        ]
    )


def _quality_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model": "model-a",
                "prompt_id": 0,
                "attempt": 0,
                "score": 5.0,
                "quality_dimension": "structured_output",
                "weight": 1.0,
                "source": "deterministic",
            },
            {
                "model": "model-a",
                "prompt_id": 1,
                "attempt": 0,
                "score": 4.0,
                "quality_dimension": "factual_sanity",
                "weight": 1.0,
                "source": "deterministic",
            },
            {
                "model": "model-b",
                "prompt_id": 0,
                "attempt": 0,
                "score": 5.0,
                "quality_dimension": "structured_output",
                "weight": 1.0,
                "source": "deterministic",
            },
        ]
    )


class TestMergeResults:
    def test_quality_metrics_gate_cer_when_the_screen_is_incomplete(self) -> None:
        result = _merge_results(
            ["model-a", "model-b"],
            _pricing(),
            _quality_rows(),
            pd.DataFrame(),
            quality_prompt_count=2,
            quality_dimension_count=2,
            quality_repetitions=1,
            quality_collection_errors=pd.DataFrame(),
            quality_suite_id="generic-screen-v1-test",
        )

        model_a = result.loc[result["model"] == "model-a"].iloc[0]
        model_b = result.loc[result["model"] == "model-b"].iloc[0]

        assert model_a["avg_quality_score"] == pytest.approx(4.5)
        assert model_a["quality_coverage_rate"] == pytest.approx(1.0)
        assert model_a["quality_dimension_coverage_rate"] == pytest.approx(1.0)
        assert bool(model_a["quality_cer_eligible"])
        assert model_a["cer"] > 0.0

        assert model_b["quality_coverage_rate"] == pytest.approx(0.5)
        assert model_b["quality_dimension_coverage_rate"] == pytest.approx(0.5)
        assert not bool(model_b["quality_cer_eligible"])
        assert model_b["cer"] == 0.0
        assert model_b["quality_collection_error_count"] == 0
        assert model_b["quality_suite_id"] == "generic-screen-v1-test"

    def test_collection_errors_reduce_success_rate_without_changing_quality_score(self) -> None:
        errors = pd.DataFrame(
            [
                {
                    "model": "model-a",
                    "prompt_id": 1,
                    "attempt": 0,
                    "error": "timeout",
                }
            ]
        )
        result = _merge_results(
            ["model-a", "model-b"],
            _pricing(),
            _quality_rows(),
            pd.DataFrame(),
            quality_prompt_count=2,
            quality_dimension_count=2,
            quality_collection_errors=errors,
        )

        model_a = result.loc[result["model"] == "model-a"].iloc[0]
        model_b = result.loc[result["model"] == "model-b"].iloc[0]
        assert model_a["quality_collection_error_count"] == 1
        assert model_a["quality_collection_success_rate"] == pytest.approx(0.5)
        assert model_b["quality_collection_error_count"] == 0
        assert model_b["quality_collection_success_rate"] == pytest.approx(1.0)

    def test_merges_actual_call_costs_separately_from_tco_projection(self) -> None:
        actual_call_costs = pd.DataFrame(
            [
                {
                    "usage_context": "quality_screen",
                    "requested_model": "model-a",
                    "resolved_model": "model-a",
                    "generation_id": "gen-a",
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                    "actual_cost_credits": 0.00042,
                    "cost_source": "openrouter_usage",
                    "latency_ms": 150.0,
                },
                {
                    "usage_context": "security_scan",
                    "requested_model": "model-a",
                    "resolved_model": "model-a",
                    "generation_id": "gen-b",
                    "prompt_tokens": 50,
                    "completion_tokens": 10,
                    "total_tokens": 60,
                    "actual_cost_credits": 0.0,
                    "cost_source": "openrouter_usage",
                    "latency_ms": 80.0,
                },
            ]
        )

        result = _merge_results(
            ["model-a", "model-b"],
            _pricing(),
            _quality_rows(),
            pd.DataFrame(),
            actual_call_costs=actual_call_costs,
        )
        model_a = result.loc[result["model"] == "model-a"].iloc[0]
        model_b = result.loc[result["model"] == "model-b"].iloc[0]

        assert model_a["actual_cost_credits"] == pytest.approx(0.00042)
        assert model_a["actual_cost_call_count"] == 2
        assert model_a["actual_cost_coverage_rate"] == 1.0
        assert pd.isna(model_b["actual_cost_credits"])
        assert model_a["tco_usd"] > model_a["actual_cost_credits"]


class TestRebuildQualityDataframe:
    def test_keeps_attempts_separate_when_merging_judges(self, tmp_path: Path) -> None:
        pending: dict[str, object] = {
            "timestamp": "20260814_120000",
            "deterministic_scores": [],
            "pending_judgments": [
                {
                    "prompt_id": 5,
                    "attempt": 0,
                    "prompt_preview": "Support prompt",
                    "category": "generic_judgment",
                    "quality_dimension": "concise_communication",
                    "weight": 1.0,
                    "alias_map": {"A": "model-a"},
                },
                {
                    "prompt_id": 5,
                    "attempt": 1,
                    "prompt_preview": "Support prompt",
                    "category": "generic_judgment",
                    "quality_dimension": "concise_communication",
                    "weight": 1.0,
                    "alias_map": {"A": "model-a"},
                },
            ],
        }
        scores_path = tmp_path / "scores.json"
        scores_path.write_text(
            json.dumps(
                {
                    "timestamp": "20260814_120000",
                    "judge": "test-judge",
                    "scores": [
                        {
                            "prompt_id": 5,
                            "attempt": 0,
                            "judgments": [{"alias": "A", "score": 5, "reasoning": "Complete."}],
                        },
                        {
                            "prompt_id": 5,
                            "attempt": 1,
                            "judgments": [{"alias": "A", "score": 3, "reasoning": "Partial."}],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        quality_df = MergePipeline._rebuild_quality_df(pending, scores_path)

        assert list(quality_df["attempt"]) == [0, 1]
        assert list(quality_df["score"]) == [5.0, 3.0]
        assert set(quality_df["quality_dimension"]) == {"concise_communication"}
        assert set(quality_df["source"]) == {"copilot-avg(1)"}

    def test_legacy_deterministic_rows_default_to_attempt_zero(self) -> None:
        pending: dict[str, object] = {
            "timestamp": "20260814_120000",
            "deterministic_scores": [{"model": "model-a", "prompt_id": 0, "score": 5}],
            "pending_judgments": [],
        }

        quality_df = MergePipeline._rebuild_quality_df(pending, None)

        assert quality_df.iloc[0]["attempt"] == 0


class TestExportCallCostLedger:
    def test_exports_summary_and_per_call_ledger(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("src.main._RESULTS_DIR", tmp_path)
        summary = pd.DataFrame({"model": ["model-a"], "actual_cost_credits": [0.00042]})
        ledger = pd.DataFrame(
            [
                {
                    "usage_context": "quality_screen",
                    "requested_model": "model-a",
                    "actual_cost_credits": 0.00042,
                }
            ]
        )

        _export(summary, ledger)

        summary_files = list(tmp_path.glob("benchmark_*.json"))
        ledger_files = list((tmp_path / "call_costs").glob("benchmark_*_call_costs.json"))
        assert len(summary_files) == 1
        assert len(ledger_files) == 1
        assert json.loads(ledger_files[0].read_text())[0]["actual_cost_credits"] == pytest.approx(0.00042)
