"""Unit tests for src/main.py — split-pipeline merge helpers.

Focus: MergePipeline._rebuild_quality_df must attribute each Copilot judge
score to the correct model via alias_map, never to a sibling model.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.core.config import Settings
from src.core.model_presets import MODEL_PRESETS
from src.core.run_manifest import build_run_manifest, inspect_run_manifest
from src.evaluators.quality_judge import CollectResult
from src.main import (
    _FREE_TIER_RPD_NO_CREDITS,
    CollectPipeline,
    MergePipeline,
    VerifyPipeline,
    _build_arg_parser,
    _enforce_collect_error_budget,
    _estimate_free_tier_request_volume,
    _resolve_security_probes_path,
    _select_models_command,
    _unknown_target_models,
    _validate_pending_payload,
    _warn_on_free_tier_request_volume,
    main,
)


def _pending_with_two_models() -> dict[str, object]:
    """Build a minimal pending payload for one prompt scored across two models."""
    alias_map = {"A": "openai/gpt-4o", "B": "anthropic/claude-3.5"}
    return {
        "timestamp": "20260101_000000",
        "models": list(alias_map.values()),
        "pending_judgments": [
            {
                "prompt_id": 1,
                "attempt": 0,
                "prompt": "Explain recursion.",
                "prompt_preview": "Explain recursion.",
                "category": "open_ended",
                "quality_dimension": "reasoning",
                "weight": 1.0,
                "alias_map": alias_map,
                # Keyed by alias, matching the real schema produced by
                # AsyncQualityJudge.run_collect (never by model_id directly).
                "responses": {
                    "A": "Recursion is when a function calls itself.",
                    "B": "Recursion means self-reference in a function.",
                },
            }
        ],
        "deterministic_scores": [],
        "quality_collection_errors": [],
    }


def _write_scores_file(tmp_path: Path, judge_name: str, judgments: list[dict[str, object]]) -> Path:
    path = tmp_path / f"scores_20260101_000000_{judge_name}.json"
    payload = {
        "judge": judge_name,
        "timestamp": "20260101_000000",
        "scores": [
            {
                "prompt_id": 1,
                "attempt": 0,
                "judgments": judgments,
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestRebuildQualityDf:
    def test_score_is_attributed_to_the_correct_model_via_alias(self, tmp_path: Path) -> None:
        pending = _pending_with_two_models()
        scores_path = _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 5, "reasoning": "Correct and clear."},
                {"alias": "B", "score": 2, "reasoning": "Vague."},
            ],
        )

        result = MergePipeline._rebuild_quality_df(pending, scores_path)

        by_model = {row["model"]: row["score"] for row in result.to_dict(orient="records")}
        assert by_model["openai/gpt-4o"] == 5
        assert by_model["anthropic/claude-3.5"] == 2

    def test_scores_from_multiple_judges_are_averaged_per_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = _pending_with_two_models()
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 4, "reasoning": "Good."},
                {"alias": "B", "score": 2, "reasoning": "Weak."},
            ],
        )
        gpt_scores = tmp_path / "scores_20260101_000000_gpt.json"
        gpt_scores.write_text(
            json.dumps(
                {
                    "judge": "gpt",
                    "timestamp": "20260101_000000",
                    "scores": [
                        {
                            "prompt_id": 1,
                            "attempt": 0,
                            "judgments": [
                                {"alias": "A", "score": 2, "reasoning": "Overstated."},
                                {"alias": "B", "score": 4, "reasoning": "Solid."},
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        # No explicit scores_path -> loads every scores_*.json matching the timestamp.
        result = MergePipeline._rebuild_quality_df(pending, None)

        by_model = {row["model"]: row["score"] for row in result.to_dict(orient="records")}
        assert by_model["openai/gpt-4o"] == 3.0  # avg(4, 2)
        assert by_model["anthropic/claude-3.5"] == 3.0  # avg(2, 4)
        assert json.loads(result.loc[result["model"] == "openai/gpt-4o", "judge_verdicts"].iloc[0]) == [
            {"judge_id": "claude", "score": 4, "reasoning": "Good."},
            {"judge_id": "gpt", "score": 2, "reasoning": "Overstated."},
        ]

    def test_unknown_alias_causes_a_coverage_gap_error(self, tmp_path: Path) -> None:
        # A judge that misspells/invents an alias never actually scored the
        # real one — this is indistinguishable from silently dropping that
        # model's response, which must fail fast rather than merge partial data.
        pending = _pending_with_two_models()
        scores_path = _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 5, "reasoning": "Correct."},
                {"alias": "Z", "score": 1, "reasoning": "Unknown alias, must not attach to any model."},
            ],
        )

        with pytest.raises(ValueError, match=r"scored 1/2 expected"):
            MergePipeline._rebuild_quality_df(pending, scores_path)

    def test_prompt_and_response_are_carried_through(self, tmp_path: Path) -> None:
        pending = _pending_with_two_models()
        scores_path = _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 5, "reasoning": "Correct."},
                {"alias": "B", "score": 4, "reasoning": "Also fine."},
            ],
        )

        result = MergePipeline._rebuild_quality_df(pending, scores_path)

        by_model = {row["model"]: row for row in result.to_dict(orient="records")}
        assert by_model["openai/gpt-4o"]["prompt"] == "Explain recursion."
        assert by_model["openai/gpt-4o"]["response"] == "Recursion is when a function calls itself."
        assert by_model["anthropic/claude-3.5"]["response"] == "Recursion means self-reference in a function."

    def test_judge_disagreement_is_the_range_across_judges(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = _pending_with_two_models()
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 5, "reasoning": "Meets all criteria."},
                {"alias": "B", "score": 5, "reasoning": "Meets all criteria."},
            ],
        )
        gpt_scores = tmp_path / "scores_20260101_000000_gpt.json"
        gpt_scores.write_text(
            json.dumps(
                {
                    "judge": "gpt",
                    "timestamp": "20260101_000000",
                    "scores": [
                        {
                            "prompt_id": 1,
                            "attempt": 0,
                            "judgments": [
                                {"alias": "A", "score": 3, "reasoning": "Lacks concrete success criteria."},
                                {"alias": "B", "score": 5, "reasoning": "Meets all criteria."},
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = MergePipeline._rebuild_quality_df(pending, None)

        by_model = {row["model"]: row["judge_disagreement"] for row in result.to_dict(orient="records")}
        assert by_model["openai/gpt-4o"] == 2  # scores 5, 3
        assert by_model["anthropic/claude-3.5"] == 0  # scores 5, 5

    def test_missing_alias_in_one_judge_file_raises_a_coverage_error(self, tmp_path: Path) -> None:
        pending = _pending_with_two_models()
        scores_path = _write_scores_file(
            tmp_path,
            "claude",
            # Alias B is never scored at all — a silent partial-coverage drop.
            judgments=[{"alias": "A", "score": 5, "reasoning": "Correct."}],
        )

        with pytest.raises(ValueError, match=r"Judge 'claude' scored 1/2 expected"):
            MergePipeline._rebuild_quality_df(pending, scores_path)

    def test_full_coverage_by_every_judge_does_not_raise(self, tmp_path: Path) -> None:
        pending = _pending_with_two_models()
        scores_path = _write_scores_file(
            tmp_path,
            "claude",
            judgments=[
                {"alias": "A", "score": 5, "reasoning": "Correct."},
                {"alias": "B", "score": 4, "reasoning": "Also fine."},
            ],
        )

        result = MergePipeline._rebuild_quality_df(pending, scores_path)

        assert len(result) == 2


class TestMergePipelineFailFast:
    def test_run_fails_when_pending_judgments_are_not_scored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pending_path = tmp_path / "pending_20260101_000000.json"
        pending_path.write_text(
            json.dumps(_pending_with_two_models()),
            encoding="utf-8",
        )
        # Hermetic: without this, the legacy-fallback glob in _rebuild_quality_df
        # reads the real data/intermediate/ directory and can pick up an unrelated
        # leftover scores_*.json file from a real run.
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        monkeypatch.setattr("src.main._RESULTS_DIR", tmp_path / "results")

        with pytest.raises(ValueError, match="Missing Copilot judge scores"):
            MergePipeline().run(pending_path=pending_path)


class TestPendingPayloadContract:
    def test_accepts_pending_payload_with_matching_aliases(self) -> None:
        _validate_pending_payload(_pending_with_two_models())

    def test_rejects_pending_payload_with_mismatched_response_aliases(self) -> None:
        pending = _pending_with_two_models()
        pending["pending_judgments"][0]["responses"] = {"A": "only one response"}  # type: ignore[index]

        with pytest.raises(ValueError, match="responses do not match alias_map"):
            _validate_pending_payload(pending)

    def test_rejects_pending_payload_with_invalid_phase_field(self) -> None:
        pending = _pending_with_two_models()
        pending["security"] = {"model": "openai/gpt-4o"}

        with pytest.raises(ValueError, match="'security' must be a list"):
            _validate_pending_payload(pending)


class TestRunManifest:
    def test_manifest_detects_modified_artifact(self, tmp_path: Path) -> None:
        artifact = tmp_path / "benchmark.csv"
        artifact.write_text("model,score\na,5\n", encoding="utf-8")
        manifest = tmp_path / "run.manifest.json"
        manifest.write_text(
            json.dumps(build_run_manifest(run_id="run-1", metadata={}, artifacts=[artifact], root=tmp_path)),
            encoding="utf-8",
        )
        artifact.write_text("model,score\na,1\n", encoding="utf-8")

        assert inspect_run_manifest(manifest, tmp_path) == ["Checksum mismatch: benchmark.csv"]

    def test_manifest_reports_missing_artifact(self, tmp_path: Path) -> None:
        artifact = tmp_path / "benchmark.csv"
        artifact.write_text("model,score\na,5\n", encoding="utf-8")
        payload = build_run_manifest(run_id="run-1", metadata={}, artifacts=[artifact], root=tmp_path)
        artifact.unlink()
        manifest = tmp_path / "run.manifest.json"
        manifest.write_text(json.dumps(payload), encoding="utf-8")

        assert inspect_run_manifest(manifest, tmp_path) == ["Missing artifact: benchmark.csv"]


class TestCollectErrorBudget:
    def test_raises_when_quality_collection_error_budget_is_exceeded(self) -> None:
        from src.evaluators.quality_judge import CollectResult

        collect_result = CollectResult(
            deterministic_rows=[],
            pending_judgments=[],
            collection_errors=[{"error": "timeout"}, {"error": "timeout"}],
            prompt_count=2,
            repetitions=1,
        )
        security_df = pd.DataFrame([{"model": "test_model", "leak_count": 0}])

        with pytest.raises(ValueError, match="Collection error budget exceeded"):
            _enforce_collect_error_budget(
                collect_result,
                security_df,
                model_count=2,
                max_quality_collection_error_rate=0.2,
                max_security_probe_error_rate=0.5,
            )

    def test_passes_when_quality_collection_error_rate_within_budget(self) -> None:
        from src.evaluators.quality_judge import CollectResult

        collect_result = CollectResult(
            deterministic_rows=[{"score": 5}],
            pending_judgments=[],
            collection_errors=[{"error": "timeout"}],
            prompt_count=2,
            repetitions=1,
        )
        security_df = pd.DataFrame([{"model": "test_model", "leak_count": 0}])

        # Should not raise: 1 error / 2 attempts = 50%, budget is 50%
        _enforce_collect_error_budget(
            collect_result,
            security_df,
            model_count=1,
            max_quality_collection_error_rate=0.5,
            max_security_probe_error_rate=0.5,
        )


class TestDryRunFakeCompletion:
    async def test_fake_completion_carries_the_provenance_fields_the_collector_reads(self) -> None:
        from src.api.fake_client import FakeAsyncOpenRouterClient

        client = FakeAsyncOpenRouterClient(Settings(openrouter_api_key="test-key"))
        completion = await client.chat_completion(
            model="vendor/model-x",
            messages=[{"role": "user", "content": "What is the capital of Australia?"}],
        )

        # Missing id/model made every dry-run response look like a transport
        # failure, silently emptying the quality axis of the pre-flight check.
        assert completion.id
        assert completion.model == "vendor/model-x"
        assert completion.choices[0].message.content == "Canberra"


class TestUnknownTargetModels:
    def test_flags_models_absent_from_the_live_catalog(self) -> None:
        pricing_df = pd.DataFrame([{"model_id": "openai/gpt-4o-mini"}, {"model_id": "google/gemma-4-31b-it:free"}])

        unknown = _unknown_target_models(
            ["openai/gpt-4o-mini", "meta-llama/llama-3.3-70b-instruct:free"],
            pricing_df,
        )

        assert unknown == ["meta-llama/llama-3.3-70b-instruct:free"]

    def test_returns_empty_when_all_models_are_known(self) -> None:
        pricing_df = pd.DataFrame([{"model_id": "openai/gpt-4o-mini"}, {"model_id": "google/gemma-4-31b-it:free"}])

        assert _unknown_target_models(["openai/gpt-4o-mini"], pricing_df) == []

    def test_returns_empty_when_pricing_is_unavailable(self) -> None:
        # An empty/failed cost stage must never be misreported as "unknown models".
        assert _unknown_target_models(["openai/gpt-4o-mini"], pd.DataFrame()) == []


class TestEstimateFreeTierRequestVolume:
    def test_counts_only_free_suffixed_models(self) -> None:
        models = ["openai/gpt-4o-mini", "google/gemma-4-31b-it:free"]

        total = _estimate_free_tier_request_volume(
            models,
            quality_prompt_count=16,
            quality_repetitions=1,
            security_probe_count=5,
        )

        # Only the single ":free" model counts: 1 * (16 * 1 + 5) = 21
        assert total == 21

    def test_zero_when_no_free_models(self) -> None:
        total = _estimate_free_tier_request_volume(
            ["openai/gpt-4o-mini"],
            quality_prompt_count=16,
            quality_repetitions=2,
            security_probe_count=30,
        )

        assert total == 0

    def test_matches_documented_default_run_math(self) -> None:
        # 3 default free models, 16 prompts, 1 repetition, 5 built-in probes -> 63
        models = ["a:free", "b:free", "c:free"]

        total = _estimate_free_tier_request_volume(
            models,
            quality_prompt_count=16,
            quality_repetitions=1,
            security_probe_count=5,
        )

        assert total == 63
        assert total > _FREE_TIER_RPD_NO_CREDITS


class TestWarnOnFreeTierRequestVolume:
    def test_logs_warning_when_over_the_cap(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            _warn_on_free_tier_request_volume(_FREE_TIER_RPD_NO_CREDITS + 1)

        assert any("preflight" in record.message for record in caplog.records)

    def test_no_warning_when_within_the_cap(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level("WARNING"):
            _warn_on_free_tier_request_volume(_FREE_TIER_RPD_NO_CREDITS)

        assert not caplog.records


def _patch_async_client_context_manager(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch AsyncOpenRouterClient so `async with AsyncOpenRouterClient(...)` needs no real HTTP."""
    mock_client = MagicMock()
    mock_client.call_costs = ()
    mock_cm = AsyncMock()
    mock_cm.__aenter__.return_value = mock_client
    mock_cm.__aexit__.return_value = None
    monkeypatch.setattr("src.main.AsyncOpenRouterClient", MagicMock(return_value=mock_cm))
    return mock_client


class TestVerifyPipeline:
    """Unit tests for VerifyPipeline.run() — the real-but-zero-cost preflight.

    ``_run_cost_stage`` is reused from ``CollectPipeline`` via composition, so
    it's patched at the class level exactly like ``TestCollectPipelineRun`` does.
    """

    @staticmethod
    def _settings(**overrides: object) -> Settings:
        defaults: dict[str, object] = {"openrouter_api_key": "sk-test", "target_models": "openai/gpt-4o-mini"}
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    async def test_happy_path_logs_success_and_does_not_raise(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_client = _patch_async_client_context_manager(monkeypatch)
        mock_client.get_key_info = AsyncMock(return_value={"label": "my-key", "usage": 0.1, "limit": None})
        pricing_df = pd.DataFrame([{"model_id": "openai/gpt-4o-mini", "prompt_price_per_token": 1e-7}])
        monkeypatch.setattr(CollectPipeline, "_run_cost_stage", AsyncMock(return_value=pricing_df))

        with caplog.at_level("INFO"):
            await VerifyPipeline(self._settings()).run()

        assert any("Ready for a real run" in record.message for record in caplog.records)

    async def test_raises_when_key_check_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.api.openrouter_client import OpenRouterError

        mock_client = _patch_async_client_context_manager(monkeypatch)
        mock_client.get_key_info = AsyncMock(side_effect=OpenRouterError("401 Unauthorized"))
        monkeypatch.setattr(CollectPipeline, "_run_cost_stage", AsyncMock(return_value=pd.DataFrame()))

        with pytest.raises(ValueError, match="API key check failed"):
            await VerifyPipeline(self._settings()).run()

    async def test_raises_when_catalog_fetch_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_client = _patch_async_client_context_manager(monkeypatch)
        mock_client.get_key_info = AsyncMock(return_value={"label": "my-key"})
        monkeypatch.setattr(CollectPipeline, "_run_cost_stage", AsyncMock(return_value=pd.DataFrame()))

        with pytest.raises(ValueError, match="live model catalog"):
            await VerifyPipeline(self._settings()).run()

    async def test_raises_when_target_model_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_client = _patch_async_client_context_manager(monkeypatch)
        mock_client.get_key_info = AsyncMock(return_value={"label": "my-key"})
        pricing_df = pd.DataFrame([{"model_id": "some/other-model"}])
        monkeypatch.setattr(CollectPipeline, "_run_cost_stage", AsyncMock(return_value=pricing_df))

        with pytest.raises(ValueError, match="not in the"):
            await VerifyPipeline(self._settings(target_models="openai/gpt-4o-mini")).run()


class TestCollectPipelineRun:
    """Integration tests for CollectPipeline.run() — mocks the OpenRouter client
    and the three stage methods so only the orchestration logic (preflight,
    gather, error budget, pending-file persistence) is exercised.
    """

    @staticmethod
    def _patch_stages(
        monkeypatch: pytest.MonkeyPatch,
        *,
        pricing_df: pd.DataFrame,
        security_df: pd.DataFrame,
        collect_result: CollectResult,
    ) -> None:
        monkeypatch.setattr(CollectPipeline, "_run_cost_stage", AsyncMock(return_value=pricing_df))
        monkeypatch.setattr(CollectPipeline, "_run_security_stage", AsyncMock(return_value=security_df))
        monkeypatch.setattr(CollectPipeline, "_run_quality_collect", AsyncMock(return_value=collect_result))

    async def test_happy_path_writes_pending_file_and_returns_its_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _patch_async_client_context_manager(monkeypatch)
        pricing_df = pd.DataFrame(
            [
                {
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_price_per_token": 1e-7,
                    "completion_price_per_token": 3e-7,
                    "context_length": 128000,
                }
            ]
        )
        security_df = pd.DataFrame(
            [
                {
                    "model": "openai/gpt-4o-mini",
                    "leak_count": 0,
                    "is_vulnerable": False,
                    "probe_count": 5,
                    "probe_error_count": 0,
                }
            ]
        )
        collect_result = CollectResult(
            deterministic_rows=[{"model": "openai/gpt-4o-mini", "prompt_id": 1, "attempt": 0, "score": 5}],
            pending_judgments=[],
            collection_errors=[],
            prompt_count=1,
            repetitions=1,
        )
        self._patch_stages(monkeypatch, pricing_df=pricing_df, security_df=security_df, collect_result=collect_result)
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]

        pending_path = await CollectPipeline(settings).run()

        assert pending_path.exists()
        payload = json.loads(pending_path.read_text())
        assert payload["models"] == ["openai/gpt-4o-mini"]
        assert len(payload["deterministic_scores"]) == 1
        assert payload["pricing"][0]["model_id"] == "openai/gpt-4o-mini"

    async def test_judging_file_uses_scrubbed_responses_pending_file_stays_raw(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _patch_async_client_context_manager(monkeypatch)
        pricing_df = pd.DataFrame(
            [
                {
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_price_per_token": 1e-7,
                    "completion_price_per_token": 3e-7,
                    "context_length": 128000,
                }
            ]
        )
        security_df = pd.DataFrame(
            [
                {
                    "model": "openai/gpt-4o-mini",
                    "leak_count": 0,
                    "is_vulnerable": False,
                    "probe_count": 5,
                    "probe_error_count": 0,
                }
            ]
        )
        collect_result = CollectResult(
            deterministic_rows=[],
            pending_judgments=[
                {
                    "prompt_id": 1,
                    "attempt": 0,
                    "prompt": "Write a concise reply.",
                    "prompt_preview": "Write a concise reply.",
                    "category": "generic_judgment",
                    "quality_dimension": "concise_communication",
                    "weight": 1.0,
                    "judge_criteria": ["Be helpful."],
                    "reference_answer": None,
                    "alias_map": {"A": "openai/gpt-4o-mini"},
                    "responses": {"A": "As an AI developed by OpenAI, here you go."},
                    "responses_for_judging": {"A": "As an AI developed by [assistant], here you go."},
                }
            ],
            collection_errors=[],
            prompt_count=1,
            repetitions=1,
        )
        self._patch_stages(monkeypatch, pricing_df=pricing_df, security_df=security_df, collect_result=collect_result)
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]

        pending_path = await CollectPipeline(settings).run()

        pending_payload = json.loads(pending_path.read_text())
        raw_response = pending_payload["pending_judgments"][0]["responses"]["A"]
        assert "OpenAI" in raw_response

        judging_path = pending_path.parent / pending_path.name.replace("pending_", "judging_")
        judging_payload = json.loads(judging_path.read_text())
        judged_response = judging_payload["pending_judgments"][0]["responses"]["A"]
        assert "OpenAI" not in judged_response
        assert "alias_map" not in judging_payload["pending_judgments"][0]

    async def test_logs_error_for_unknown_target_models(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _patch_async_client_context_manager(monkeypatch)
        # Pricing only knows about one of the two configured models.
        pricing_df = pd.DataFrame([{"model_id": "openai/gpt-4o-mini", "prompt_price_per_token": 1e-7}])
        security_df = pd.DataFrame([{"model": "openai/gpt-4o-mini", "probe_count": 5, "probe_error_count": 0}])
        collect_result = CollectResult(prompt_count=0, repetitions=1)
        self._patch_stages(monkeypatch, pricing_df=pricing_df, security_df=security_df, collect_result=collect_result)
        settings = Settings(  # type: ignore[arg-type]
            openrouter_api_key="sk-test",
            target_models="openai/gpt-4o-mini,some/stale-model:free",
        )

        with caplog.at_level("ERROR"):
            await CollectPipeline(settings).run()

        assert any("stale-model" in record.message for record in caplog.records)

    async def test_raises_when_security_stage_returns_no_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)
        _patch_async_client_context_manager(monkeypatch)
        collect_result = CollectResult(prompt_count=0, repetitions=1)
        self._patch_stages(
            monkeypatch,
            pricing_df=pd.DataFrame(),
            security_df=pd.DataFrame(),  # empty -> must abort, unvalidated security axis
            collect_result=collect_result,
        )
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]

        with pytest.raises(ValueError, match="unvalidated security axis"):
            await CollectPipeline(settings).run()


class TestMergePipelineRun:
    def test_happy_path_exports_results_from_deterministic_scores_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = {
            "timestamp": "20260101_000000",
            "models": ["openai/gpt-4o-mini"],
            "pricing": [
                {
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_price_per_token": 1e-7,
                    "completion_price_per_token": 3e-7,
                    "context_length": 128000,
                }
            ],
            "security": [{"model": "openai/gpt-4o-mini", "leak_count": 0, "is_vulnerable": False}],
            "actual_call_costs": [],
            "deterministic_scores": [
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt_id": 1,
                    "attempt": 0,
                    "score": 5,
                    "category": "open_ended",
                    "quality_dimension": "reasoning",
                    "weight": 1.0,
                }
            ],
            "pending_judgments": [],
            "quality_collection_errors": [],
            "quality_metadata": {"prompt_count": 1, "dimension_count": 1, "repetitions": 1, "suite_id": "abc123"},
        }
        pending_path = tmp_path / "pending_20260101_000000.json"
        pending_path.write_text(json.dumps(pending), encoding="utf-8")
        results_dir = tmp_path / "results"
        monkeypatch.setattr("src.main._RESULTS_DIR", results_dir)

        result = MergePipeline().run(pending_path=pending_path)

        assert not result.empty
        assert result.loc[0, "model"] == "openai/gpt-4o-mini"
        assert list(results_dir.glob("benchmark_*.csv"))
        assert list(results_dir.glob("benchmark_*.json"))

    def test_exports_quality_collection_diagnostics(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        pending = {
            "timestamp": "20260101_000000",
            "models": ["model-a"],
            "pricing": [],
            "security": [],
            "actual_call_costs": [],
            "deterministic_scores": [],
            "pending_judgments": [],
            "quality_collection_errors": [
                {
                    "model": "model-a",
                    "prompt_id": 4,
                    "attempt": 0,
                    "prompt": "What is the capital of Australia?",
                    "response": "",
                    "quality_dimension": "factual_sanity",
                    "error": "OpenRouter API error 503",
                    "generation_id": None,
                    "request_sha256": "abc123",
                }
            ],
            "quality_metadata": {"prompt_count": 1, "dimension_count": 1, "repetitions": 1},
        }
        pending_path = tmp_path / "pending_20260101_000000.json"
        pending_path.write_text(json.dumps(pending), encoding="utf-8")
        results_dir = tmp_path / "results"
        monkeypatch.setattr("src.main._RESULTS_DIR", results_dir)

        MergePipeline().run(pending_path=pending_path)

        diagnostics = list((results_dir / "quality_diagnostics").glob("*_quality_diagnostics.csv"))
        assert len(diagnostics) == 1
        diagnostics_df = pd.read_csv(diagnostics[0])
        assert diagnostics_df.loc[0, "error"] == "OpenRouter API error 503"

    def test_exports_per_dimension_columns_and_quality_details(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pending = {
            "timestamp": "20260101_000000",
            "models": ["openai/gpt-4o-mini"],
            "pricing": [
                {
                    "model_id": "openai/gpt-4o-mini",
                    "prompt_price_per_token": 1e-7,
                    "completion_price_per_token": 3e-7,
                    "context_length": 128000,
                }
            ],
            "security": [{"model": "openai/gpt-4o-mini", "leak_count": 0, "is_vulnerable": False}],
            "actual_call_costs": [],
            "deterministic_scores": [
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt_id": 1,
                    "attempt": 0,
                    "prompt": 'Return {"status": "ok"} as JSON.',
                    "response": '{"status": "ok"}',
                    "score": 5,
                    "reasoning": "Valid JSON.",
                    "category": "json_output",
                    "quality_dimension": "structured_output",
                    "weight": 1.0,
                    "source": "deterministic",
                },
                {
                    "model": "openai/gpt-4o-mini",
                    "prompt_id": 2,
                    "attempt": 0,
                    "prompt": "What is 2+2?",
                    "response": "4",
                    "score": 3,
                    "reasoning": "Correct but terse.",
                    "category": "exact_answer",
                    "quality_dimension": "elementary_reasoning",
                    "weight": 1.0,
                    "source": "deterministic",
                },
            ],
            "pending_judgments": [],
            "quality_collection_errors": [],
            "quality_metadata": {"prompt_count": 2, "dimension_count": 2, "repetitions": 1, "suite_id": "abc123"},
        }
        pending_path = tmp_path / "pending_20260101_000000.json"
        pending_path.write_text(json.dumps(pending), encoding="utf-8")
        results_dir = tmp_path / "results"
        monkeypatch.setattr("src.main._RESULTS_DIR", results_dir)

        result = MergePipeline().run(pending_path=pending_path)

        assert result.loc[0, "quality_dim_structured_output"] == 5.0
        assert result.loc[0, "quality_dim_elementary_reasoning"] == 3.0

        details_files = list((results_dir / "quality_details").glob("*_quality_details.csv"))
        assert len(details_files) == 1
        details_df = pd.read_csv(details_files[0])
        assert set(details_df["prompt"]) == {'Return {"status": "ok"} as JSON.', "What is 2+2?"}
        assert set(details_df["response"]) == {'{"status": "ok"}', "4"}

    def test_raises_file_not_found_when_no_pending_file_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("src.main._INTERMEDIATE_DIR", tmp_path)

        with pytest.raises(FileNotFoundError, match="make collect"):
            MergePipeline().run()


class TestResolveSecurityProbesPath:
    """SECURITY_MODE resolution — the single source of truth for all 5 former
    duplicated call sites (CollectPipeline.run/_run_security_stage,
    VerifyPipeline.run, the dead-code AsyncPipeline, and _run_preflight_checks).
    """

    def _settings(self, **overrides: object) -> Settings:
        defaults: dict[str, object] = {"openrouter_api_key": "sk-test"}
        defaults.update(overrides)
        return Settings(_env_file=None, **defaults)  # type: ignore[arg-type, call-arg]

    def test_basic_mode_uses_the_built_in_probes(self) -> None:
        assert _resolve_security_probes_path(self._settings(security_mode="basic")) is None

    def test_owasp_mode_resolves_to_the_owasp_probe_file(self) -> None:
        result = _resolve_security_probes_path(self._settings(security_mode="owasp"))
        assert result == Path("data/prompts/owasp_probes.json")

    def test_extended_mode_resolves_to_the_extended_probe_file(self) -> None:
        result = _resolve_security_probes_path(self._settings(security_mode="extended"))
        assert result == Path("data/prompts/extended_probes.json")

    def test_explicit_probes_path_wins_over_security_mode(self) -> None:
        settings = self._settings(security_mode="owasp", security_probes_path="custom/probes.json")
        assert _resolve_security_probes_path(settings) == Path("custom/probes.json")

    def test_unknown_security_mode_raises_a_clear_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown SECURITY_MODE 'bogus'"):
            _resolve_security_probes_path(self._settings(security_mode="bogus"))


class TestMainDispatch:
    """Integration tests for main()'s CLI subcommand dispatch."""

    def test_collect_subcommand_invokes_collect_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "collect"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=Path("data/intermediate/pending_x.json"))
        mock_cls = MagicMock(return_value=mock_instance)
        monkeypatch.setattr("src.main.CollectPipeline", mock_cls)

        main()

        mock_cls.assert_called_once_with()
        mock_instance.run.assert_awaited_once()

    def test_default_subcommand_is_collect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=Path("data/intermediate/pending_x.json"))
        monkeypatch.setattr("src.main.CollectPipeline", MagicMock(return_value=mock_instance))

        main()

        mock_instance.run.assert_awaited_once()

    def test_merge_subcommand_invokes_merge_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "merge"])
        mock_instance = MagicMock()
        mock_instance.run = MagicMock(return_value=pd.DataFrame({"model": ["m"]}))
        monkeypatch.setattr("src.main.MergePipeline", MagicMock(return_value=mock_instance))

        main()

        mock_instance.run.assert_called_once_with()

    def test_dry_run_subcommand_invokes_dry_run_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "dry-run"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=pd.DataFrame({"model": ["m"]}))
        monkeypatch.setattr("src.main.DryRunPipeline", MagicMock(return_value=mock_instance))

        main()

        mock_instance.run.assert_awaited_once()

    def test_verify_subcommand_invokes_verify_pipeline(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "verify"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=None)
        monkeypatch.setattr("src.main.VerifyPipeline", MagicMock(return_value=mock_instance))

        main()

        mock_instance.run.assert_awaited_once()

    def test_verify_subcommand_exits_with_error_on_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "verify"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=ValueError("[VERIFY] boom"))
        monkeypatch.setattr("src.main.VerifyPipeline", MagicMock(return_value=mock_instance))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_unknown_subcommand_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "bogus"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_pipeline_exception_is_caught_and_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "collect"])
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(side_effect=RuntimeError("boom"))
        monkeypatch.setattr("src.main.CollectPipeline", MagicMock(return_value=mock_instance))

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1

    def test_models_subcommand_prints_presets_and_never_touches_settings(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "models"])
        monkeypatch.setattr("src.main.get_settings", MagicMock(side_effect=AssertionError("should not be called")))

        main()

        out = capsys.readouterr().out
        assert "free_general" in out
        assert "paid_flagship" in out

    def test_select_subcommand_prints_dynamic_selection(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "select", "--paid-only", "--limit", "1"])
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]
        monkeypatch.setattr("src.main.get_settings", MagicMock(return_value=settings))
        client = MagicMock()
        client.get_models = AsyncMock(
            return_value=[
                {"id": "vendor/free:free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 8192},
                {
                    "id": "vendor/cheap",
                    "pricing": {"prompt": "0.0000002", "completion": "0.0000006"},
                    "context_length": 32768,
                },
            ]
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        context.__aexit__.return_value = None
        monkeypatch.setattr("src.main.AsyncOpenRouterClient", MagicMock(return_value=context))

        main()

        output = capsys.readouterr().out
        assert "vendor/cheap" in output
        assert "Recommended models" in output

    async def test_select_interactive_accepts_model_numbers(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]
        monkeypatch.setattr("src.main.get_settings", MagicMock(return_value=settings))
        client = MagicMock()
        client.get_models = AsyncMock(
            return_value=[
                {
                    "id": "vendor/cheap-a",
                    "pricing": {"prompt": "0.0000002", "completion": "0.0000006"},
                    "context_length": 32768,
                },
                {
                    "id": "vendor/cheap-b",
                    "pricing": {"prompt": "0.0000003", "completion": "0.0000008"},
                    "context_length": 32768,
                },
            ]
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        context.__aexit__.return_value = None
        monkeypatch.setattr("src.main.AsyncOpenRouterClient", MagicMock(return_value=context))
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=MagicMock(return_value=True)))
        monkeypatch.setattr(
            "builtins.input",
            MagicMock(return_value="2", side_effect=["skip", "skip", "skip", "skip", "skip", "2"]),
        )

        await _select_models_command(_build_arg_parser().parse_args(["select", "--paid-only", "--limit", "2"]))

        output = capsys.readouterr().out
        assert "Selection saved as 'selection'" in output
        assert 'make verify MODELS="selection"' in output

    async def test_select_interactive_can_choose_model_outside_recommendation(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        settings = Settings(openrouter_api_key="sk-test", target_models="openai/gpt-4o-mini")  # type: ignore[arg-type]
        monkeypatch.setattr("src.main.get_settings", MagicMock(return_value=settings))
        client = MagicMock()
        client.get_models = AsyncMock(
            return_value=[
                {
                    "id": "vendor/recommended",
                    "pricing": {"prompt": "0.0000002", "completion": "0.0000006"},
                    "context_length": 32768,
                },
                {
                    "id": "vendor/other",
                    "pricing": {"prompt": "0.0000003", "completion": "0.0000008"},
                    "context_length": 32768,
                },
            ]
        )
        context = AsyncMock()
        context.__aenter__.return_value = client
        context.__aexit__.return_value = None
        monkeypatch.setattr("src.main.AsyncOpenRouterClient", MagicMock(return_value=context))
        monkeypatch.setattr("sys.stdin", MagicMock(isatty=MagicMock(return_value=True)))
        monkeypatch.setattr("builtins.input", MagicMock(side_effect=["skip", "skip", "skip", "skip", "1", "2"]))
        selection_path = Path("data/intermediate/test_model_selection.json")
        monkeypatch.setattr("src.main.save_selection", lambda models: selection_path)

        await _select_models_command(_build_arg_parser().parse_args(["select", "--paid-only", "--limit", "1"]))

        output = capsys.readouterr().out
        assert "Other models matching your filters" in output
        assert 'make verify MODELS="selection"' in output

    def test_collect_with_models_flag_overrides_target_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "collect", "--models", "paid_flagship"])
        base_settings = Settings(openrouter_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]
        monkeypatch.setattr("src.main.get_settings", MagicMock(return_value=base_settings))
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=Path("data/intermediate/pending_x.json"))
        mock_cls = MagicMock(return_value=mock_instance)
        monkeypatch.setattr("src.main.CollectPipeline", mock_cls)

        main()

        mock_cls.assert_called_once()
        (settings_arg,) = mock_cls.call_args.args
        assert settings_arg.target_models_list == list(MODEL_PRESETS["paid_flagship"].models)

    def test_collect_with_security_flag_overrides_security_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "collect", "--security", "owasp"])
        base_settings = Settings(openrouter_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]
        monkeypatch.setattr("src.main.get_settings", MagicMock(return_value=base_settings))
        mock_instance = MagicMock()
        mock_instance.run = AsyncMock(return_value=Path("data/intermediate/pending_x.json"))
        mock_cls = MagicMock(return_value=mock_instance)
        monkeypatch.setattr("src.main.CollectPipeline", mock_cls)

        main()

        (settings_arg,) = mock_cls.call_args.args
        assert settings_arg.security_mode == "owasp"

    def test_invalid_models_flag_exits_with_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog", "collect", "--models", "not_a_real_preset"])

        with pytest.raises(SystemExit) as exc_info:
            main()

        assert exc_info.value.code == 1
