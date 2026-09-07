"""Unit tests for src/evaluators/quality_judge.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.evaluators.quality_judge import (
    FORMAT_COMPLIANCE_DIMENSION,
    AsyncQualityJudge,
    QualityJudge,
    _alias,
    _blind_alias_map,
    _scrub_self_identification,
    _validate_evaluation_contract,
    load_quality_prompts,
    quality_suite_id,
)


def _make_completion(content: str) -> MagicMock:
    """Build a mock ChatCompletion with the given message content."""
    completion = MagicMock()
    completion.id = "gen-test"
    completion.model = "resolved/model"
    completion.choices[0].message.content = content
    return completion


def _make_async_completion(content: str) -> AsyncMock:
    """Build an async mock ChatCompletion."""
    completion = MagicMock()
    completion.choices[0].message.content = content
    mock = AsyncMock(return_value=completion)
    return mock


def _write_prompt_fixture(tmp_path: Path, entries: list[dict[str, object]]) -> Path:
    """Write a minimal valid quality-screen fixture."""
    path = tmp_path / "quality_prompts.json"
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


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
    def test_returns_scores_for_all_models(self, judge: QualityJudge, mock_client: MagicMock) -> None:
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

    def test_raises_on_malformed_json(self, judge: QualityJudge, mock_client: MagicMock) -> None:
        mock_client.chat_completion.return_value = _make_completion("not json at all")
        with pytest.raises(ValueError, match="malformed JSON"):
            judge.evaluate(prompt="test", responses={"model-a": "answer"})

    def test_score_clamped_to_1_5(self, judge: QualityJudge, mock_client: MagicMock) -> None:
        bad_json = json.dumps({"scores": [{"model_alias": "A", "score": 99, "reasoning": "too high"}]})
        mock_client.chat_completion.return_value = _make_completion(bad_json)
        with pytest.raises(ValueError):
            judge.evaluate(prompt="test", responses={"model-a": "answer"})

    def test_includes_explicit_judge_context(self, judge: QualityJudge, mock_client: MagicMock) -> None:
        judge_json = json.dumps({"scores": [{"model_alias": "A", "score": 5, "reasoning": "Meets criteria."}]})
        mock_client.chat_completion.return_value = _make_completion(judge_json)

        judge.evaluate(
            prompt="Summarize this release note.",
            responses={"model-a": "A concise summary."},
            judge_criteria=["Mention the release date.", "Use one sentence."],
            reference_answer="The release is Tuesday.",
        )

        user_message = mock_client.chat_completion.call_args.kwargs["messages"][1]["content"]
        assert "Mention the release date." in user_message
        assert "The release is Tuesday." in user_message


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


class TestPromptSchema:
    def test_loads_current_generic_screen(self) -> None:
        prompts = load_quality_prompts(Path("data/prompts/quality_prompts.json"))
        assert len(prompts) == 16
        assert {prompt.quality_dimension for prompt in prompts} == {
            "structured_output",
            "code_correctness",
            "factual_sanity",
            "elementary_reasoning",
            "instruction_reliability",
            "concise_communication",
        }
        assert all(prompt.weight > 0 for prompt in prompts)

    def test_rejects_open_ended_prompt_without_criteria(self, tmp_path: Path) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "Write something useful.", "category": "unmapped_category"}],
        )
        with pytest.raises(ValueError, match="judge_criteria"):
            load_quality_prompts(path)

    def test_rejects_exact_category_without_answers(self, tmp_path: Path) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "What is 2 + 2?", "category": "exact_answer"}],
        )
        with pytest.raises(ValueError, match="accepted_answers"):
            load_quality_prompts(path)

    def test_rejects_prompt_with_messages(self, tmp_path: Path) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "One turn.",
                    "messages": [{"role": "user", "content": "Another turn."}],
                    "category": "generic_judgment",
                    "judge_criteria": ["Be useful."],
                }
            ],
        )
        with pytest.raises(ValueError, match="exactly one"):
            load_quality_prompts(path)

    async def test_collects_a_multiturn_scenario_in_one_api_call(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "messages": [
                        {"role": "user", "content": "Remember the word cobalt."},
                        {"role": "assistant", "content": "I will remember cobalt."},
                        {"role": "user", "content": "What word did I ask you to remember?"},
                    ],
                    "category": "generic_judgment",
                    "judge_criteria": ["Reply with cobalt."],
                }
            ],
        )
        async_mock_client.chat_completion.return_value = _make_completion("cobalt")

        result = await async_judge.run_collect(path, ["model-a"])

        assert async_mock_client.chat_completion.await_count == 1
        assert async_mock_client.chat_completion.call_args.kwargs["messages"] == [
            {"role": "user", "content": "Remember the word cobalt."},
            {"role": "assistant", "content": "I will remember cobalt."},
            {"role": "user", "content": "What word did I ask you to remember?"},
        ]
        assert result.pending_judgments[0]["prompt"] == (
            "user: Remember the word cobalt.\nassistant: I will remember cobalt.\n"
            "user: What word did I ask you to remember?"
        )


class TestValidateEvaluationContract:
    """Direct tests for the extracted business rule, without a full model."""

    def test_exact_category_requires_accepted_answers(self) -> None:
        with pytest.raises(ValueError, match="accepted_answers"):
            _validate_evaluation_contract("exact_answer", accepted_answers=[], judge_criteria=[])

    def test_unmapped_category_requires_judge_criteria(self) -> None:
        with pytest.raises(ValueError, match="judge_criteria"):
            _validate_evaluation_contract("unmapped_category", accepted_answers=[], judge_criteria=[])

    def test_deterministic_category_needs_no_judge_criteria(self) -> None:
        _validate_evaluation_contract("json_output", accepted_answers=[], judge_criteria=[])

    def test_exact_category_with_accepted_answers_passes(self) -> None:
        _validate_evaluation_contract("exact_answer", accepted_answers=["4"], judge_criteria=[])

    def test_suite_id_is_stable_and_content_addressed(self, tmp_path: Path) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "Answer 2 + 2.", "category": "exact_answer", "accepted_answers": ["4"]}],
        )
        first_id = quality_suite_id(path)
        assert first_id == quality_suite_id(path)

        path.write_text(
            json.dumps([{"prompt": "Answer 2 + 2.", "category": "exact_answer", "accepted_answers": ["four"]}]),
            encoding="utf-8",
        )
        assert first_id != quality_suite_id(path)


class TestScrubSelfIdentification:
    @pytest.mark.parametrize(
        ("text", "redacted_vendor"),
        [
            ("As an AI developed by Anthropic, I must decline.", "Anthropic"),
            ("I'm Claude, made by Anthropic.", "Claude"),
            ("As ChatGPT, I can help with that.", "ChatGPT"),
            ("I am a large language model created by Google.", "Google"),
            ("My name is Gemini and I was trained by Google.", "Gemini"),
        ],
    )
    def test_redacts_self_identifying_vendor_names(self, text: str, redacted_vendor: str) -> None:
        scrubbed = _scrub_self_identification(text)
        assert redacted_vendor not in scrubbed
        assert "[assistant]" in scrubbed

    @pytest.mark.parametrize(
        "text",
        [
            "The capital of Australia is Canberra.",
            "I am happy to help with your Python question.",
            "Meta released Llama 3 recently.",
        ],
    )
    def test_leaves_unrelated_content_untouched(self, text: str) -> None:
        assert _scrub_self_identification(text) == text


class TestAsyncCollect:
    async def test_collects_repeated_deterministic_and_judged_responses(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "Return the required JSON.",
                    "category": "json_output",
                    "quality_dimension": "structured_output",
                    "expected_json": {"ok": True},
                    "strict_output": True,
                },
                {
                    "prompt": "Write a concise support reply.",
                    "category": "generic_judgment",
                    "quality_dimension": "concise_communication",
                    "judge_criteria": ["Be helpful."],
                    "reference_answer": "Please contact support.",
                },
            ],
        )

        async def respond(**kwargs: object) -> MagicMock:
            messages = kwargs["messages"]
            assert isinstance(messages, list)
            prompt = messages[-1]["content"]
            content = '{"ok": true}' if "required JSON" in prompt else "Please contact support."
            return _make_completion(content)

        async_mock_client.chat_completion.side_effect = respond

        result = await async_judge.run_collect(path, ["model-a", "model-b"], repetitions=2)

        content_rows = [row for row in result.deterministic_rows if row["source"] == "deterministic"]
        format_rows = [row for row in result.deterministic_rows if row["source"] == "deterministic-format"]
        assert len(content_rows) == 4
        # The strict-output prompt also yields one format-compliance row per response.
        assert len(format_rows) == 4
        assert {row["quality_dimension"] for row in format_rows} == {FORMAT_COMPLIANCE_DIMENSION}
        assert len(result.pending_judgments) == 2
        assert result.prompt_count == 2
        assert result.dimension_count == 3
        assert result.repetitions == 2
        assert result.collection_errors == []
        assert {pending["attempt"] for pending in result.pending_judgments} == {0, 1}
        assert all(len(pending["responses"]) == 2 for pending in result.pending_judgments)
        assert async_mock_client.chat_completion.await_count == 8
        # Deterministic rows must retain the full prompt/response text, not just a preview,
        # so a drill-down view can show exactly what was sent and returned.
        assert content_rows[0]["prompt"] == "Return the required JSON."
        assert content_rows[0]["response"] == '{"ok": true}'

    async def test_judging_copy_is_scrubbed_but_evidence_copy_stays_raw(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "Write a concise support reply.",
                    "category": "generic_judgment",
                    "quality_dimension": "concise_communication",
                    "judge_criteria": ["Be helpful."],
                    "reference_answer": "Please contact support.",
                }
            ],
        )
        async_mock_client.chat_completion.return_value = _make_completion(
            "As an AI developed by Anthropic, here is how to reset your password."
        )

        result = await async_judge.run_collect(path, ["model-a"])

        pending = result.pending_judgments[0]
        alias = next(iter(pending["alias_map"]))
        # The raw text is what evidence/audit trails must show — never rewritten.
        assert "Anthropic" in pending["responses"][alias]
        # The judge-facing copy has the vendor name scrubbed.
        assert "Anthropic" not in pending["responses_for_judging"][alias]
        assert "[assistant]" in pending["responses_for_judging"][alias]

    async def test_collection_failure_is_not_scored_as_an_empty_response(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "Return JSON.",
                    "category": "json_output",
                    "expected_json": {"ok": True},
                }
            ],
        )
        async_mock_client.chat_completion.side_effect = RuntimeError("network unavailable")

        result = await async_judge.run_collect(path, ["model-a"])

        assert result.deterministic_rows == []
        assert result.pending_judgments == []
        assert len(result.collection_errors) == 1
        assert result.collection_errors[0]["error"] == "network unavailable"

    async def test_redaction_placeholder_remains_scored_with_optional_k1_recheck(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "What is the capital of Australia? Reply with the city name only.",
                    "category": "factual_sanity",
                    "accepted_answers": ["Canberra"],
                }
            ],
        )
        async_mock_client.chat_completion.return_value = _make_completion(
            'No actual address was provided; "[ADDRESS]" is a placeholder.'
        )

        result = await async_judge.run_collect(path, ["model-a"])

        assert len(result.deterministic_rows) == 1
        assert result.pending_judgments == []
        assert result.collection_errors == []
        row = result.deterministic_rows[0]
        assert row["score"] == 1
        assert row["verification_status"] == "optional_openrouter_recheck"
        assert row["generation_id"] == "gen-test"
        assert row["resolved_model"] == "resolved/model"
        assert len(str(row["request_sha256"])) == 64

    async def test_empty_model_response_receives_a_quality_failure(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [
                {
                    "prompt": "Return JSON.",
                    "category": "json_output",
                    "expected_json": {"ok": True},
                }
            ],
        )
        async_mock_client.chat_completion.return_value = _make_completion("")

        result = await async_judge.run_collect(path, ["model-a"])

        assert result.collection_errors == []
        assert result.deterministic_rows[0]["score"] == 1
        assert result.deterministic_rows[0]["source"] == "deterministic-empty-response"

    async def test_unknown_objective_failure_offers_k1_recheck_without_being_hidden(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "What is 2 + 2?", "category": "exact_answer", "accepted_answers": ["4"]}],
        )
        async_mock_client.chat_completion.return_value = _make_completion("5")

        result = await async_judge.run_collect(path, ["model-a"])

        assert result.collection_errors == []
        assert result.deterministic_rows[0]["score"] == 1
        assert result.deterministic_rows[0]["verification_status"] == "optional_openrouter_recheck"
        assert result.deterministic_rows[0]["expected_answers_json"] == '["4"]'

    async def test_objective_failure_with_repetitions_uses_run_evidence(
        self,
        async_judge: AsyncQualityJudge,
        async_mock_client: MagicMock,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "What is 2 + 2?", "category": "exact_answer", "accepted_answers": ["4"]}],
        )
        async_mock_client.chat_completion.return_value = _make_completion("5")

        result = await async_judge.run_collect(path, ["model-a"], repetitions=2)

        assert len(result.deterministic_rows) == 2
        assert {row["verification_status"] for row in result.deterministic_rows} == {"run_repetitions_available"}

    async def test_rejects_zero_repetitions(
        self,
        async_judge: AsyncQualityJudge,
        tmp_path: Path,
    ) -> None:
        path = _write_prompt_fixture(
            tmp_path,
            [{"prompt": "Answer 2 + 2.", "category": "exact_answer", "accepted_answers": ["4"]}],
        )
        with pytest.raises(ValueError, match="repetitions"):
            await async_judge.run_collect(path, ["model-a"], repetitions=0)

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

    async def test_empty_responses_returns_empty(self, async_judge: AsyncQualityJudge) -> None:
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

    def test_blind_aliases_are_reproducible_and_order_independent(self) -> None:
        first = _blind_alias_map(["model-b", "model-a", "model-c"], seed_material="quality-run")
        second = _blind_alias_map(["model-c", "model-b", "model-a"], seed_material="quality-run")
        assert first == second
        assert set(first.values()) == {"model-a", "model-b", "model-c"}

    def test_alias_round_trip_reconstructs_original_model_ids(self) -> None:
        """Scores keyed by alias must map back to the exact model that produced them.

        This mirrors the alias -> reverse_map -> model_id flow used by
        ``QualityJudge.evaluate`` and ``MergePipeline._rebuild_quality_df``:
        a wrong reverse mapping would silently attribute one model's score to
        another.
        """
        model_ids = ["openai/gpt-4o", "anthropic/claude-3.5", "google/gemini-1.5"]
        alias_map = _blind_alias_map(model_ids, seed_material="round-trip")
        reverse_map = {model_id: alias for alias, model_id in alias_map.items()}

        # Every model must have exactly one alias, and it must resolve back.
        assert set(reverse_map) == set(model_ids)
        for model_id in model_ids:
            alias = reverse_map[model_id]
            assert alias_map[alias] == model_id

        # Simulate a judge scoring by alias, then resolving back to model IDs.
        fake_scores_by_alias = {alias: idx + 1 for idx, alias in enumerate(sorted(alias_map))}
        scores_by_model = {alias_map[alias]: score for alias, score in fake_scores_by_alias.items()}
        for model_id in model_ids:
            expected_alias = reverse_map[model_id]
            assert scores_by_model[model_id] == fake_scores_by_alias[expected_alias]
