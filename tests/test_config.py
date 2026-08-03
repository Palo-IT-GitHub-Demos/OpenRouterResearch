"""Unit tests for src/core/config.py."""

from __future__ import annotations

import pytest

from src.core.config import Settings, get_settings


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

    def test_default_target_models_are_free(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("TARGET_MODELS", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        get_settings.cache_clear()
        s = get_settings()
        assert all(":free" in m for m in s.target_models_list)
        get_settings.cache_clear()

    def test_default_judge_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("JUDGE_MODEL", raising=False)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
        get_settings.cache_clear()
        s = get_settings()
        assert s.judge_model == "nvidia/nemotron-3-ultra-550b-a55b:free"
        get_settings.cache_clear()

    def test_missing_api_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        with pytest.raises(Exception):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestGetSettings:
    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-cached-test")
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()
