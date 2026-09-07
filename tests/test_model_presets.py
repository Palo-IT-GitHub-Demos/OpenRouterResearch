"""Unit tests for src/core/model_presets.py."""

from __future__ import annotations

import pytest

from src.core.model_presets import MODEL_PRESETS, format_model_presets, resolve_models_arg


class TestModelPresets:
    def test_every_preset_compares_at_least_two_models(self) -> None:
        for name, preset in MODEL_PRESETS.items():
            assert len(preset.models) >= 2, f"preset '{name}' should compare at least 2 models"

    def test_free_general_stays_within_basic_free_request_quota(self) -> None:
        assert len(MODEL_PRESETS["free_general"].models) == 2

    def test_every_model_id_contains_a_vendor_separator(self) -> None:
        # Every real OpenRouter model ID is "vendor/model-name[:variant]" — this
        # is also the heuristic resolve_models_arg relies on to detect a preset
        # name, so a preset accidentally containing a bare token would break it.
        for preset in MODEL_PRESETS.values():
            for model in preset.models:
                assert "/" in model

    def test_every_preset_has_a_non_empty_description(self) -> None:
        for preset in MODEL_PRESETS.values():
            assert preset.description.strip()

    def test_budget_paid_preset_contains_no_free_tier_models(self) -> None:
        budget_models = MODEL_PRESETS["budget_paid"].models

        assert budget_models
        assert all(not model.endswith(":free") for model in budget_models)
        assert "mistralai/mistral-small-3.1-24b-instruct" in budget_models


class TestResolveModelsArg:
    def test_resolves_a_known_preset_name_to_its_models(self) -> None:
        assert resolve_models_arg("paid_flagship") == list(MODEL_PRESETS["paid_flagship"].models)

    def test_passes_through_a_comma_separated_list_unchanged(self) -> None:
        assert resolve_models_arg("a/b,c/d") == ["a/b", "c/d"]

    def test_strips_whitespace_around_entries(self) -> None:
        assert resolve_models_arg(" a/b , c/d ") == ["a/b", "c/d"]

    def test_a_real_model_id_is_never_misclassified_as_a_preset(self) -> None:
        # Single model, no comma, but contains '/' — must not be looked up as a preset.
        assert resolve_models_arg("openai/gpt-4o-mini") == ["openai/gpt-4o-mini"]

    def test_unknown_bare_token_passes_through_as_a_single_model_when_not_strict(self) -> None:
        assert resolve_models_arg("typo_preset") == ["typo_preset"]

    def test_unknown_bare_token_raises_when_strict(self) -> None:
        with pytest.raises(ValueError, match="Unknown model preset 'typo_preset'"):
            resolve_models_arg("typo_preset", strict=True)

    def test_known_preset_name_never_raises_even_when_strict(self) -> None:
        assert resolve_models_arg("free_general", strict=True) == list(MODEL_PRESETS["free_general"].models)


class TestFormatModelPresets:
    def test_includes_every_preset_name_and_model(self) -> None:
        rendered = format_model_presets()
        for name, preset in MODEL_PRESETS.items():
            assert name in rendered
            for model in preset.models:
                assert model in rendered
