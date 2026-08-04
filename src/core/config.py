"""Centralised, type-safe configuration loaded from environment variables.

Usage:
    from src.core.config import get_settings

    settings = get_settings()
    api_key = settings.openrouter_api_key.get_secret_value()
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default free models (no cost, no account required beyond OpenRouter key).
_DEFAULT_MODELS = (
    "google/gemma-4-31b-it:free,"
    "qwen/qwen3-coder:free,"
    "nvidia/nemotron-3-super-120b-a12b:free"
)


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
        default=(
            "nvidia/nemotron-3-ultra-550b-a55b:free,"
            "google/gemma-4-31b-it:free,"
            "meta-llama/llama-3.3-70b-instruct:free"
        )
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def target_models_list(self) -> list[str]:
        """Parse the comma-separated ``TARGET_MODELS`` env var into a list."""
        raw = self.target_models.strip()
        if raw.startswith("["):
            import json  # noqa: PLC0415

            try:
                return json.loads(raw)
            except Exception:  # noqa: BLE001
                pass
        return [m.strip() for m in raw.split(",") if m.strip()]

    # ── HTTP client ────────────────────────────────────────────────────────────
    request_timeout: float = 60.0
    max_retries: int = 3
    max_concurrent_requests: int = 3  # Conservative default for free-tier rate limits

    # ── Observability ──────────────────────────────────────────────────────────
    mlflow_tracking_uri: str = "sqlite:///mlruns.db"

    # ── Security ───────────────────────────────────────────────────────────────
    # Optional path to a JSON file containing custom security probes.
    security_probes_path: str | None = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached singleton Settings instance."""
    return Settings()
