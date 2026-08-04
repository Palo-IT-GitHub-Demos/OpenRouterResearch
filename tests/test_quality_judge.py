"""Unit tests for src/evaluators/quality_judge.py."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.evaluators.quality_judge import AsyncQualityJudge, QualityJudge, _alias


def _make_completion(content: str) -> MagicMock:
    """Build a mock ChatCompletion with the given message content."""
    completion = MagicMock()
    completion.choices[0].message.content = content
    return completion


def _make_async_completion(content: str) -> AsyncMock:
    """Build an async mock ChatCompletion."""
    completion = MagicMock()
    completion.choices[0].message.content = content
    mock = AsyncMock(return_value=completion)
    return mock


@pytest.fixture()
def mock_client() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def judge(mock_client: MagicMock) -> QualityJudge:
    return QualityJudge(mock_client, judge_model="openai/gpt-4o")


@pytest.fixture()
def async_mock_client() -> MagicMock:
    client = MagicMock()
    client.chat_completion = AsyncMock()
    return client


@pytest.fixture()
def async_judge(async_mock_client: MagicMock) -> AsyncQualityJudge:
    return AsyncQualityJudge(async_mock_client)


# ── Sync judge tests ───────────────────────────────────────────────────────────


class TestEvaluate:
    def test_returns_scores_for_all_models(
        self, judge: QualityJudge, mock_client: MagicMock
    ) -> None:
        responses = {
            "model-a": "Response from A",
            "model-b": "Response from B",
        }
        judge_json = json.dumps(
            {
                "scores": [
                    {"model_alias": "A", "score": 4, "reasoning": "Good."},
                    {"model_alias": "B", "score": 3, "reasoning": "Acceptable."},
                ]
            }
        )
        mock_client.chat_completion.return_value = _make_completion(judge_json)

        results = judge.evaluate(prompt="test prompt", responses=responses)

        assert len(results) == 2
        all_scores = {r.score for r in results.values()}
        assert all_scores.issubset({3, 4})

    def test_returns_empty_for_no_responses(self, judge: QualityJudge) -> None:
        assert judge.evaluate(prompt="test", responses={}) == {}

    def test_raises_on_malformed_json(
        self, judge: QualityJudge, mock_client: MagicMock
    ) -> None:
        mock_client.chat_completion.return_value = _make_completion("not json at all")
        with pytest.raises(ValueError, match="malformed JSON"):
            judge.evaluate(prompt="test", responses={"model-a": "answer"})

    def test_score_clamped_to_1_5(
        self, judge: QualityJudge, mock_client: MagicMock
    ) -> None:
        bad_json = json.dumps(
            {"scores": [{"model_alias": "A", "score": 99, "reasoning": "too high"}]}
        )
        mock_client.chat_completion.return_value = _make_completion(bad_json)
        with pytest.raises(ValueError):
            judge.evaluate(prompt="test", responses={"model-a": "answer"})


# ── Async judge tests ───────────────────────────────────────────────────────────


class TestAsyncEvaluate:
    async def test_returns_empty_for_undecidable_responses(
        self, async_judge: AsyncQualityJudge, async_mock_client: MagicMock
    ) -> None:
        """Undecidable responses (no category) are omitted — judged by
        Copilot agents."""
        results = await async_judge.evaluate(
            prompt="test",
            responses={"model-a": "great", "model-b": "ok"},
        )
        async_mock_client.chat_completion.assert_not_called()
        assert results == {}

    async def test_deterministic_check_skips_llm_for_json(
        self, async_judge: AsyncQualityJudge, async_mock_client: MagicMock
    ) -> None:
        """Valid JSON response should not invoke the LLM judge."""
        results = await async_judge.evaluate(
            prompt="return json",
            responses={"model-a": '{"key": "value"}'},
            category="json_output",
        )
        async_mock_client.chat_completion.assert_not_called()
        assert results["model-a"].score == 5

    async def test_deterministic_fail_score_is_1_for_bad_json(
        self, async_judge: AsyncQualityJudge, async_mock_client: MagicMock
    ) -> None:
        results = await async_judge.evaluate(
            prompt="return json",
            responses={"model-a": "not valid json!!!!"},
            category="json_output",
        )
        async_mock_client.chat_completion.assert_not_called()
        assert results["model-a"].score == 1

    async def test_empty_responses_returns_empty(
        self, async_judge: AsyncQualityJudge
    ) -> None:
        results = await async_judge.evaluate(prompt="test", responses={})
        assert results == {}

    async def test_undecidable_not_in_results(
        self, async_judge: AsyncQualityJudge, async_mock_client: MagicMock
    ) -> None:
        """Without a category, responses are undecidable — no LLM call,
        empty results."""
        results = await async_judge.evaluate(
            prompt="test",
            responses={"model-a": "some answer"},
        )
        async_mock_client.chat_completion.assert_not_called()
        assert results == {}


# ── Alias helper ───────────────────────────────────────────────────────────────────


class TestAlias:
    def test_first_alias_is_a(self) -> None:
        assert _alias(0) == "A"

    def test_sequential_aliases(self) -> None:
        assert [_alias(i) for i in range(3)] == ["A", "B", "C"]
