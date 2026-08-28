"""Centralised, type-safe configuration loaded from environment variables.

Usage:
    from src.core.config import get_settings

    settings = get_settings()
    api_key = settings.openrouter_api_key.get_secret_value()
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.core.model_presets import resolve_models_arg


class Settings(BaseSettings):
    """Application settings resolved from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_ignore_empty=True,
        populate_by_name=True,
        extra="ignore",  # Silently drop unknown env vars (e.g. PORT, APP_ENV).
    )

    # ── OpenRouter ─────────────────────────────────────────────────────────────
    openrouter_api_key: SecretStr
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Evaluation ─────────────────────────────────────────────────────────────
    # Note: le juge LLM est désormais un agent Copilot (@judge-anthropic,
    # @judge-openai, @judge-google). JUDGE_MODEL n'est plus utilisé.

    # Stored as a comma-separated string so pydantic-settings never attempts to
    # JSON-decode it.  Exposed as ``list[str]`` via the computed field below.
    # ⚠️  Si TARGET_MODELS est défini dans .env, il écrase ce défaut.
    #     Pour tester avec exactement ces 3 modèles, ne pas définir
    #     TARGET_MODELS dans .env.
    target_models: str = Field(
        default=("nvidia/nemotron-3-ultra-550b-a55b:free," "google/gemma-4-31b-it:free," "openai/gpt-oss-20b:free")
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_models_list(self) -> list[str]:
        """Parse ``TARGET_MODELS`` into a list, expanding a bare preset name.

        Accepts a JSON array, a comma-separated model list, or (new) a single
        named preset (see ``src.core.model_presets.MODEL_PRESETS``) such as
        ``TARGET_MODELS=paid_flagship`` — resolved via ``resolve_models_arg``.
        """
        raw = self.target_models.strip()
        if raw.startswith("["):
            import json  # noqa: PLC0415

            try:
                decoded: Any = json.loads(raw)
                if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
                    return decoded
            except Exception:  # noqa: BLE001
                pass
        return resolve_models_arg(raw)

    # ── HTTP client ────────────────────────────────────────────────────────────
    request_timeout: float = 60.0
    max_retries: int = 3
    max_concurrent_requests: int = 3  # Conservative default for free-tier rate limits

    # ── Observability ──────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "sqlite:///mlruns.db"

    # ── Security ───────────────────────────────────────────────────────────────
    # Named probe set for this run: "basic" (5 built-in probes, default),
    # "owasp" (data/prompts/owasp_probes.json — 30 probes, OWASP GenAI LLM Top
    # 10 2026, required for the dashboard's RSI/heatmap), or "extended"
    # (data/prompts/extended_probes.json — 15 advanced jailbreak/obfuscation
    # probes). Resolved by ``main._resolve_security_probes_path``. Ignored
    # when security_probes_path below is set (that always wins).
    security_mode: str = "basic"

    # Optional path to a JSON file containing custom security probes —
    # overrides security_mode above.
    security_probes_path: str | None = None

    # ── Quality screen ─────────────────────────────────────────────────────────
    # Repeat a generic screen prompt to measure score stability. Keep the broad
    # OpenRouter pre-screen at one run; use 2–5 only for a shortlisted cohort.
    quality_repetitions: int = Field(default=1, ge=1, le=5)

    # Abort a run when collection transport failures exceed this ratio.
    max_quality_collection_error_rate: float = Field(default=0.15, ge=0.0, le=1.0)

    # Abort a run when security probe transport failures exceed this ratio.
    max_security_probe_error_rate: float = Field(default=0.15, ge=0.0, le=1.0)

    # ── Cost modeling ──────────────────────────────────────────────────────────
    # Workload profile used for TCO/CER calculations.
    # Accepted values: "enterprise_qa" | "code_assistant" | "document_analysis"
    #                  | "chatbot_high_volume"
    workload_profile: str = "enterprise_qa"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()  # type: ignore[call-arg]
