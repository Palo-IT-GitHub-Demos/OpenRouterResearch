"""Curated, coherent OpenRouter model-set presets for benchmark runs.

Picking models by hand means typing exact, easy-to-typo OpenRouter slugs into
``TARGET_MODELS`` and hoping the mix makes sense for a comparison. A preset is
a named, pre-vetted set built for one specific comparison purpose (e.g. "is a
free model good enough versus paying?") instead of an arbitrary list.

Slugs below are the ones already verified live against ``GET /models`` (see
``.env.example``) — OpenRouter's catalog churns (models get renamed or
discontinued), so always re-check with::

    make verify MODELS=<preset name>

before a real (paid) ``make collect``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.model_selector import load_selection


@dataclass(frozen=True)
class ModelPreset:
    """A named, coherent set of OpenRouter model IDs for one comparison purpose."""

    description: str
    models: tuple[str, ...]


MODEL_PRESETS: dict[str, ModelPreset] = {
    "free_general": ModelPreset(
        description=(
            "Two-model free-tier comparison (Google and Cohere) kept small enough "
            "for the default basic probe set on a 50-request daily quota."
        ),
        models=(
            "google/gemma-4-31b-it:free",
            "cohere/north-mini-code:free",
        ),
    ),
    "paid_flagship": ModelPreset(
        description=(
            "Cross-provider flagship paid trio (Anthropic, Meta, OpenAI) for a " "production-grade benchmark."
        ),
        models=(
            "anthropic/claude-sonnet-5",
            "meta-llama/llama-3.3-70b-instruct",
            "openai/gpt-4o-mini",
        ),
    ),
    "budget_paid": ModelPreset(
        description=(
            "Low-cost paid alternatives for comparing economical production models "
            "without using free-tier request quotas."
        ),
        models=(
            "mistralai/mistral-small-3.1-24b-instruct",
            "openai/gpt-4o-mini",
        ),
    ),
    "mixed_value": ModelPreset(
        description=(
            "Two free models plus one budget-paid model, to check whether a "
            "free-tier model is already good enough before paying."
        ),
        models=(
            "google/gemma-4-31b-it:free",
            "cohere/north-mini-code:free",
            "openai/gpt-4o-mini",
        ),
    ),
}


def resolve_models_arg(value: str, *, strict: bool = False) -> list[str]:
    """Resolve a ``TARGET_MODELS``/``--models`` value to explicit model IDs.

    *value* is either a preset name (see :data:`MODEL_PRESETS`), the saved
    ``selection`` name, or a comma-separated list of explicit OpenRouter model IDs. A bare token is
    treated as a preset name when it has no ``,`` and no ``/`` — every real
    OpenRouter model ID contains a ``/`` (``vendor/model-name``), so this
    never misclassifies an actual model list.

    Args:
        value: Raw config value from ``.env``/CLI.
        strict: When True, an unrecognised preset-looking name raises
            ``ValueError`` instead of silently passing through as a single
            (bogus) model ID. Used by the CLI, where a typo should fail fast
            with a helpful message instead of surfacing later as an opaque
            "unknown model" error from the live catalog check.

    Returns:
        A list of explicit OpenRouter model IDs.
    """
    cleaned = value.strip()
    if cleaned == "selection":
        return load_selection()
    looks_like_preset = bool(cleaned) and "," not in cleaned and "/" not in cleaned
    if looks_like_preset:
        preset = MODEL_PRESETS.get(cleaned)
        if preset is not None:
            return list(preset.models)
        if strict:
            available = ", ".join(sorted(MODEL_PRESETS))
            raise ValueError(f"Unknown model preset '{cleaned}'. Available presets: {available}.")
    return [m.strip() for m in cleaned.split(",") if m.strip()]


def format_model_presets() -> str:
    """Render all presets as human-readable text for the ``models`` CLI subcommand."""
    lines = ["Available model-set presets (TARGET_MODELS=<name>, --models <name>, or MODELS=<name>):", ""]
    for name, preset in MODEL_PRESETS.items():
        lines.append(f"  {name}")
        lines.append(f"    {preset.description}")
        for model in preset.models:
            lines.append(f"      - {model}")
        lines.append("")
    lines.append("Re-verify before a paid run: make verify MODELS=<name>")
    return "\n".join(lines).rstrip()
