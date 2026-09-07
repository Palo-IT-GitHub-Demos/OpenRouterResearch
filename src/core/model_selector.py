"""Pure model filtering and run-estimation helpers for interactive selection."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SELECTION_PATH = Path("data/intermediate/model_selection.json")


@dataclass(frozen=True)
class ModelCatalogEntry:
    """Relevant, non-secret model catalog data used by the selector."""

    model_id: str
    input_price_per_token: float
    output_price_per_token: float
    context_length: int

    @property
    def is_free(self) -> bool:
        """Return whether this catalog entry has no input or output price."""
        return self.model_id.endswith(":free") or (
            self.input_price_per_token == 0.0 and self.output_price_per_token == 0.0
        )


def catalog_entries(catalog: list[dict[str, Any]]) -> list[ModelCatalogEntry]:
    """Convert OpenRouter catalog rows, ignoring rows without usable pricing."""
    entries: list[ModelCatalogEntry] = []
    for row in catalog:
        model_id = row.get("id")
        pricing = row.get("pricing")
        if not isinstance(model_id, str) or not model_id or not isinstance(pricing, dict):
            continue
        try:
            input_price = float(pricing.get("prompt", 0.0))
            output_price = float(pricing.get("completion", 0.0))
            context_length = int(row.get("context_length", 0))
        except (TypeError, ValueError):
            continue
        if input_price < 0 or output_price < 0 or context_length < 0:
            continue
        entries.append(ModelCatalogEntry(model_id, input_price, output_price, context_length))
    return entries


def select_models(
    entries: list[ModelCatalogEntry],
    *,
    paid_only: bool = False,
    free_only: bool = False,
    max_input_price_per_million: float | None = None,
    max_output_price_per_million: float | None = None,
    min_context_length: int | None = None,
    limit: int = 6,
) -> list[ModelCatalogEntry]:
    """Filter and rank catalog entries by estimated per-request cost."""
    if paid_only and free_only:
        raise ValueError("paid_only and free_only cannot both be enabled")
    if limit < 1:
        raise ValueError("limit must be at least 1")

    def matches(entry: ModelCatalogEntry) -> bool:
        input_price = entry.input_price_per_token * 1_000_000
        output_price = entry.output_price_per_token * 1_000_000
        return (
            (not paid_only or not entry.is_free)
            and (not free_only or entry.is_free)
            and (max_input_price_per_million is None or input_price <= max_input_price_per_million)
            and (max_output_price_per_million is None or output_price <= max_output_price_per_million)
            and (min_context_length is None or entry.context_length >= min_context_length)
        )

    return sorted(
        (entry for entry in entries if matches(entry)),
        key=lambda entry: (entry.input_price_per_token + entry.output_price_per_token, entry.model_id),
    )[:limit]


def estimate_requests(
    model_count: int, quality_prompt_count: int, security_probe_count: int, repetitions: int = 1
) -> int:
    """Estimate completion requests for a selected model set."""
    if min(model_count, quality_prompt_count, security_probe_count, repetitions) < 0:
        raise ValueError("request-count inputs cannot be negative")
    return model_count * (quality_prompt_count * repetitions + security_probe_count)


def estimate_cost_usd(
    entries: list[ModelCatalogEntry],
    *,
    daily_requests: int = 500,
    avg_prompt_tokens: int = 512,
    avg_completion_tokens: int = 256,
    working_days: int = 22,
) -> float:
    """Estimate monthly input/output cost for the selected models."""
    if min(daily_requests, avg_prompt_tokens, avg_completion_tokens, working_days) < 0:
        raise ValueError("workload inputs cannot be negative")
    monthly_input = daily_requests * avg_prompt_tokens * working_days
    monthly_output = daily_requests * avg_completion_tokens * working_days
    return sum(
        entry.input_price_per_token * monthly_input + entry.output_price_per_token * monthly_output for entry in entries
    )


def save_selection(models: list[str], path: Path = SELECTION_PATH) -> Path:
    """Persist the selected model IDs for subsequent pipeline commands."""
    if not models or any(not model for model in models):
        raise ValueError("models must contain at least one non-empty model ID")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": models}, indent=2) + "\n", encoding="utf-8")
    return path


def load_selection(path: Path = SELECTION_PATH) -> list[str]:
    """Load model IDs saved by the interactive selector."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("No saved model selection found. Run 'make select' first.") from exc
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not models or not all(isinstance(model, str) and model for model in models):
        raise ValueError("Saved model selection is invalid. Run 'make select' again.")
    return models
