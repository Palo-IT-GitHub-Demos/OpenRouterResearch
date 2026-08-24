"""Unit tests for generic quality-screen metric aggregation."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.evaluators.quality_metrics import summarize_quality_scores


def _rows() -> list[dict[str, object]]:
    """Return a small, multi-dimension quality result fixture."""
    return [
        {
            "model": "model-a",
            "prompt_id": 0,
            "attempt": 0,
            "score": 5,
            "quality_dimension": "structured_output",
            "weight": 1.0,
            "source": "deterministic",
        },
        {
            "model": "model-a",
            "prompt_id": 1,
            "attempt": 0,
            "score": 5,
            "quality_dimension": "structured_output",
            "weight": 1.0,
            "source": "deterministic",
        },
        {
            "model": "model-a",
            "prompt_id": 2,
            "attempt": 0,
            "score": 1,
            "quality_dimension": "factual_sanity",
            "weight": 1.0,
            "source": "deterministic",
        },
        {
            "model": "model-b",
            "prompt_id": 0,
            "attempt": 0,
            "score": 4,
            "quality_dimension": "structured_output",
            "weight": 1.0,
            "source": "deterministic",
        },
        {
            "model": "model-b",
            "prompt_id": 0,
            "attempt": 1,
            "score": 2,
            "quality_dimension": "structured_output",
            "weight": 1.0,
            "source": "deterministic",
        },
        {
            "model": "model-b",
            "prompt_id": 1,
            "attempt": 0,
            "score": 3,
            "quality_dimension": "concise_communication",
            "weight": 1.0,
            "source": "copilot-avg(3)",
        },
    ]


class TestSummarizeQualityScores:
    def test_macro_averages_dimensions_not_prompt_count(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows()), expected_prompt_count=4)
        row = summary.loc[summary["model"] == "model-a"].iloc[0]

        # structured_output = (5 + 5) / 2 = 5; factual_sanity = 1;
        # macro average = (5 + 1) / 2 = 3, not the flat mean 11 / 3.
        assert row["avg_quality_score"] == pytest.approx(3.0)
        assert row["quality_prompt_count"] == 3
        assert row["quality_dimension_count"] == 2
        assert row["quality_coverage_rate"] == pytest.approx(0.75)
        assert row["quality_pass_rate"] == pytest.approx(2 / 3)

    def test_reports_stability_only_for_repeated_prompts(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows()), expected_prompt_count=2)
        row = summary.loc[summary["model"] == "model-b"].iloc[0]

        # Population standard deviation for scores 4 and 2 is 1.0.
        assert row["quality_score_stddev"] == pytest.approx(1.0)
        assert row["quality_stability_score"] == pytest.approx(0.5)
        assert row["quality_repetitions_observed"] == pytest.approx(2.0)

    def test_reports_deterministic_and_judged_provenance(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows()), expected_prompt_count=2)
        row = summary.loc[summary["model"] == "model-b"].iloc[0]

        assert row["quality_deterministic_prompt_count"] == 1
        assert row["quality_judged_prompt_count"] == 1

    def test_single_attempt_has_no_stability_claim(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows()), expected_prompt_count=4)
        row = summary.loc[summary["model"] == "model-a"].iloc[0]

        assert math.isnan(row["quality_score_stddev"])
        assert math.isnan(row["quality_stability_score"])

    def test_handles_legacy_records_without_metadata(self) -> None:
        quality_df = pd.DataFrame(
            [
                {"model": "legacy-model", "prompt_id": 0, "score": 4},
                {"model": "legacy-model", "prompt_id": 1, "score": 2},
            ]
        )

        summary = summarize_quality_scores(quality_df)
        row = summary.iloc[0]
        assert row["avg_quality_score"] == pytest.approx(3.0)
        assert row["quality_dimension_count"] == 1
        assert pd.isna(row["quality_coverage_rate"])

    def test_empty_or_invalid_input_returns_empty_summary(self) -> None:
        assert summarize_quality_scores(pd.DataFrame()).empty
        assert summarize_quality_scores(pd.DataFrame({"model": ["a"]})).empty
