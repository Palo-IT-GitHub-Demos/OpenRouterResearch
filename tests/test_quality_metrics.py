"""Unit tests for generic quality-screen metric aggregation."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from src.evaluators.quality_metrics import (
    INPUT_CORRUPTION_STATUS,
    build_quality_details,
    flag_suspected_input_corruption,
    summarize_quality_dimensions,
    summarize_quality_scores,
)


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


class TestSummarizeQualityDimensions:
    def test_one_row_per_model_and_dimension(self) -> None:
        breakdown = summarize_quality_dimensions(pd.DataFrame(_rows()))

        model_a = breakdown.loc[breakdown["model"] == "model-a"].set_index("quality_dimension")
        assert model_a.loc["structured_output", "dimension_score"] == pytest.approx(5.0)
        assert model_a.loc["factual_sanity", "dimension_score"] == pytest.approx(1.0)

    def test_matches_the_dimension_average_baked_into_avg_quality_score(self) -> None:
        # avg_quality_score is the mean of exactly these per-dimension scores (see
        # TestSummarizeQualityScores.test_macro_averages_dimensions_not_prompt_count).
        breakdown = summarize_quality_dimensions(pd.DataFrame(_rows()))
        model_a_scores = breakdown.loc[breakdown["model"] == "model-a", "dimension_score"]
        assert model_a_scores.mean() == pytest.approx(3.0)

    def test_prompt_count_reflects_distinct_prompts_per_dimension(self) -> None:
        breakdown = summarize_quality_dimensions(pd.DataFrame(_rows()))
        model_a = breakdown.loc[breakdown["model"] == "model-a"].set_index("quality_dimension")
        assert model_a.loc["structured_output", "quality_prompt_count"] == 2
        assert model_a.loc["factual_sanity", "quality_prompt_count"] == 1

    def test_empty_or_invalid_input_returns_empty_breakdown(self) -> None:
        assert summarize_quality_dimensions(pd.DataFrame()).empty
        assert summarize_quality_dimensions(pd.DataFrame({"model": ["a"]})).empty


class TestBuildQualityDetails:
    def test_keeps_one_row_per_scored_attempt(self) -> None:
        details = build_quality_details(pd.DataFrame(_rows()))
        assert len(details) == len(_rows())

    def test_defaults_missing_prompt_and_response_to_empty_string(self) -> None:
        # _rows() fixture predates the prompt/response fields — legacy artifacts
        # must not crash, and should render as blank rather than NaN.
        details = build_quality_details(pd.DataFrame(_rows()))
        assert (details["prompt"] == "").all()
        assert (details["response"] == "").all()

    def test_defaults_missing_judge_disagreement_to_na(self) -> None:
        # _rows() fixture predates judge_disagreement — must default to "not
        # applicable" (NA), never to 0 (which would falsely read as unanimous).
        details = build_quality_details(pd.DataFrame(_rows()))
        assert details["judge_disagreement"].isna().all()

    def test_preserves_real_prompt_and_response_text(self) -> None:
        rows = [
            {
                "model": "model-a",
                "prompt_id": 0,
                "attempt": 0,
                "prompt": "Say hello.",
                "response": "Hello!",
                "score": 5,
                "reasoning": "Correct greeting.",
                "quality_dimension": "structured_output",
                "category": "generic",
                "source": "deterministic",
            }
        ]
        details = build_quality_details(pd.DataFrame(rows))
        assert details.loc[0, "prompt"] == "Say hello."
        assert details.loc[0, "response"] == "Hello!"

    def test_empty_input_returns_empty_details(self) -> None:
        assert build_quality_details(pd.DataFrame()).empty


def _reference_answer_rows(scores: dict[str, float], *, prompt_id: int = 0) -> list[dict[str, object]]:
    return [
        {
            "model": model,
            "prompt_id": prompt_id,
            "attempt": 0,
            "score": score,
            "quality_dimension": "factual_sanity",
            "source": "deterministic",
            "expected_answers_json": '["Canberra"]',
        }
        for model, score in scores.items()
    ]


class TestFlagSuspectedInputCorruption:
    def test_flags_reference_prompt_every_model_missed(self) -> None:
        df = pd.DataFrame(_reference_answer_rows({"model-a": 1.0, "model-b": 1.0, "model-c": 1.0}))
        assert flag_suspected_input_corruption(df).all()

    def test_ignores_prompt_that_at_least_one_model_answered(self) -> None:
        df = pd.DataFrame(_reference_answer_rows({"model-a": 1.0, "model-b": 5.0}))
        assert not flag_suspected_input_corruption(df).any()

    def test_ignores_single_model_runs(self) -> None:
        df = pd.DataFrame(_reference_answer_rows({"model-a": 1.0}))
        assert not flag_suspected_input_corruption(df).any()

    def test_ignores_prompts_without_a_reference_answer(self) -> None:
        rows = _reference_answer_rows({"model-a": 1.0, "model-b": 1.0})
        for row in rows:
            row["expected_answers_json"] = "[]"
        assert not flag_suspected_input_corruption(pd.DataFrame(rows)).any()

    def test_ignores_format_compliance_rows(self) -> None:
        rows = _reference_answer_rows({"model-a": 1.0, "model-b": 1.0})
        for row in rows:
            row["source"] = "deterministic-format"
        assert not flag_suspected_input_corruption(pd.DataFrame(rows)).any()

    def test_legacy_frame_without_metadata_is_never_flagged(self) -> None:
        df = pd.DataFrame(_rows())
        assert not flag_suspected_input_corruption(df).any()

    def test_flagged_prompt_is_excluded_from_the_summary(self) -> None:
        rows = _reference_answer_rows({"model-a": 1.0, "model-b": 1.0}, prompt_id=0)
        rows += _reference_answer_rows({"model-a": 5.0, "model-b": 5.0}, prompt_id=1)
        summary = summarize_quality_scores(pd.DataFrame(rows), expected_prompt_count=2)
        assert (summary["avg_quality_score"] == 5.0).all()
        assert (summary["quality_excluded_prompt_count"] == 1).all()
        # The excluded prompt leaves the denominator too, so it is not also
        # reported as a collection gap.
        assert (summary["quality_coverage_rate"] == 1.0).all()

    def test_evidence_keeps_raw_score_and_records_the_status(self) -> None:
        rows = _reference_answer_rows({"model-a": 1.0, "model-b": 1.0})
        details = build_quality_details(pd.DataFrame(rows))
        assert (details["score"] == 1.0).all()
        assert (details["verification_status"] == INPUT_CORRUPTION_STATUS).all()


class TestQualityScoreSourceSplit:
    def test_deterministic_and_judged_averages_are_reported_separately(self) -> None:
        rows = [
            {
                "model": "model-a",
                "prompt_id": 0,
                "attempt": 0,
                "score": 5,
                "quality_dimension": "structured_output",
                "source": "deterministic",
            },
            {
                "model": "model-a",
                "prompt_id": 1,
                "attempt": 0,
                "score": 3,
                "quality_dimension": "concise_communication",
                "source": "copilot-avg(3)",
            },
        ]
        summary = summarize_quality_scores(pd.DataFrame(rows))
        assert summary.loc[0, "avg_quality_score_deterministic"] == 5.0
        assert summary.loc[0, "avg_quality_score_judged"] == 3.0
        assert summary.loc[0, "avg_quality_score"] == 4.0

    def test_judged_average_is_null_for_a_model_without_judge_rows(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows())).set_index("model")
        assert pd.isna(summary.loc["model-a", "avg_quality_score_judged"])
        assert summary.loc["model-b", "avg_quality_score_judged"] == 3.0


class TestJudgeDisagreementRate:
    def test_disagreement_rate_counts_disputed_prompts(self) -> None:
        rows = [
            {
                "model": "model-a",
                "prompt_id": 0,
                "attempt": 0,
                "score": 4.0,
                "quality_dimension": "concise_communication",
                "source": "copilot-avg(3)",
                "judge_disagreement": 2,  # disputed: range >= 2
            },
            {
                "model": "model-a",
                "prompt_id": 1,
                "attempt": 0,
                "score": 5.0,
                "quality_dimension": "concise_communication",
                "source": "copilot-avg(3)",
                "judge_disagreement": 0,  # unanimous
            },
        ]
        summary = summarize_quality_scores(pd.DataFrame(rows))
        assert summary.loc[0, "quality_judge_disagreement_rate"] == 0.5

    def test_disagreement_rate_is_null_without_any_judged_prompt(self) -> None:
        summary = summarize_quality_scores(pd.DataFrame(_rows()))
        assert summary["quality_judge_disagreement_rate"].isna().all()

    def test_deterministic_rows_do_not_count_as_disagreement_evidence(self) -> None:
        rows = [
            {
                "model": "model-a",
                "prompt_id": 0,
                "attempt": 0,
                "score": 5.0,
                "quality_dimension": "structured_output",
                "source": "deterministic",
                # No judge_disagreement column at all on a legacy/deterministic row.
            }
        ]
        summary = summarize_quality_scores(pd.DataFrame(rows))
        assert summary["quality_judge_disagreement_rate"].isna().all()
