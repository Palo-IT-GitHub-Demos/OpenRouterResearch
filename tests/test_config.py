"""Unit tests for src/core/config.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.config import Settings, get_settings
from src.core.model_presets import MODEL_PRESETS


class TestSettingsValidation:
    def test_parses_comma_separated_target_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TARGET_MODELS", raising=False)
        s = Settings(
            openrouter_api_key="sk-test",  # type: ignore[arg-type]
            target_models="model-a,model-b, model-c",
        )
        assert s.target_models_list == ["model-a", "model-b", "model-c"]

    def test_accepts_json_array_target_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TARGET_MODELS", raising=False)
        s = Settings(
            openrouter_api_key="sk-test",  # type: ignore[arg-type]
            target_models='["model-x","model-y"]',
        )
        assert s.target_models_list == ["model-x", "model-y"]

    def test_target_models_accepts_a_bare_preset_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TARGET_MODELS", raising=False)
        s = Settings(
            openrouter_api_key="sk-test",  # type: ignore[arg-type]
            target_models="paid_flagship",
        )
        assert s.target_models_list == list(MODEL_PRESETS["paid_flagship"].models)

    def test_default_target_models_are_free(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # _env_file=None isolates from the repo's real .env, but pydantic-settings
        # still reads the process environment — this test targets the Settings
        # field default, not whatever the operator has exported or configured.
        monkeypatch.delenv("TARGET_MODELS", raising=False)
        s = Settings(openrouter_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]
        assert all(":free" in m for m in s.target_models_list)

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(ValidationError):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_quality_repetitions_must_stay_within_supported_range(self) -> None:
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", quality_repetitions=0)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", quality_repetitions=6)  # type: ignore[arg-type]

    def test_quality_repetitions_accepts_shortlist_stability_runs(self) -> None:
        settings = Settings(openrouter_api_key="sk-test", quality_repetitions=3)  # type: ignore[arg-type]
        assert settings.quality_repetitions == 3

    def test_max_quality_collection_error_rate_must_stay_between_zero_and_one(self) -> None:
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", max_quality_collection_error_rate=-0.1)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", max_quality_collection_error_rate=1.1)  # type: ignore[arg-type]

    def test_max_security_probe_error_rate_must_stay_between_zero_and_one(self) -> None:
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", max_security_probe_error_rate=-0.1)  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            Settings(openrouter_api_key="sk-test", max_security_probe_error_rate=1.1)  # type: ignore[arg-type]

    def test_security_mode_defaults_to_basic(self) -> None:
        s = Settings(openrouter_api_key="sk-test", _env_file=None)  # type: ignore[call-arg]
        assert s.security_mode == "basic"


class TestGetSettings:
    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-cached-test")
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()
