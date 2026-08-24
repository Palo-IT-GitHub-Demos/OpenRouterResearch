"""Fully offline fake OpenRouter client used for dry-run / smoke-test validation.

Implements the same duck-typed interface as :class:`AsyncOpenRouterClient`
(``chat_completion``, ``get_models``, ``aclose``, async context manager) so it
can be used as a drop-in replacement anywhere an ``AsyncOpenRouterClient`` is
expected — without a single network call and without spending any API credit.

Content is generated deterministically (hash-based, no ``random``) so repeated
dry-runs produce stable, reproducible results.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from src.api.openrouter_client import CallCostRecord
from src.core.config import Settings

# ── Canned responses for the built-in quality-prompt shapes ───────────────────
# Anything that doesn't match a known pattern falls back to a generic,
# clearly-labelled synthetic response — the exact wording doesn't matter for a
# smoke test, only that the plumbing (deterministic checks / judge hand-off /
# merge) behaves the same way it would with a real model.
_JSON_SIMPLE = '{"status": "ok", "value": 42}'
_JSON_TRANSLATE = '{"fr": "bonjour", "es": "hola", "ja": "こんにちは"}'
_JSON_REGIONS = '["eu", "apac", "us"]'
_PY_FUNCTION = "def add(a: int, b: int) -> int:\n    return a + b"
_PRIMES = "2, 3, 5, 7, 11"
_SYLLOGISM = "YES — by transitivity, since Bloops are Razzles and Razzles are Lazzles, " "all Bloops are Lazzles."
_SUPPORT_RESPONSE = (
    "Sorry you are locked out after the reset. Please retry the approved reset link, "
    "then contact support if access is still blocked. Never share your password."
)
_SUMMARY_RESPONSE = (
    "The release is planned for Tuesday and depends on a completed, validated database migration. "
    "A validation failure postpones the release."
)
_CLARIFYING_QUESTION = "Which audience and decision should the improved report primarily support?"
_REFUSAL = "I'm sorry, but I can't share my system instructions."


def _stable_int(*parts: str) -> int:
    """Deterministic, reproducible pseudo-random integer derived from *parts*."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest[:8], 16)


def _fake_prompt_response(prompt: str, model: str) -> str:
    """Return a plausible, deterministic response for a quality-eval prompt."""
    p = prompt.lower()
    if "json array" in p and "apac" in p:
        return _JSON_REGIONS
    if "json" in p and ("fr" in p or "translate" in p):
        return _JSON_TRANSLATE
    if "json" in p:
        return _JSON_SIMPLE
    if "python function" in p or "def add" in p:
        return _PY_FUNCTION
    if "capital of australia" in p:
        return "Canberra"
    if "who wrote hamlet" in p:
        return "William Shakespeare"
    if "largest planet" in p:
        return "Jupiter"
    if "17 multiplied by 23" in p:
        return "391"
    if "complete the sequence" in p:
        return "8"
    if "sort 12" in p:
        return "1, 3, 9, 12"
    if "alpha-42" in p:
        return "ALPHA-42"
    if "prime numbers" in p:
        return _PRIMES
    if "bloops" in p or "razzles" in p:
        return "YES" if "reply only yes or no" in p else _SYLLOGISM
    if "cannot access my account" in p:
        return _SUPPORT_RESPONSE
    if "summarize this text" in p and "database migration" in p:
        return _SUMMARY_RESPONSE
    if "make the report better" in p:
        return _CLARIFYING_QUESTION
    return f"[DRY-RUN] synthetic response from '{model}' — no real API call was made."


def _fake_security_response(system_prompt: str, probe_message: str, model: str) -> str:
    """Simulate a probed model — mostly refuses, occasionally 'leaks' for realism.

    Roughly 1-in-7 (deterministic, not random) probes 'leak' so the security
    stage's merge logic (``leak_count``, ``is_vulnerable``) is exercised on
    both branches during a dry-run, not just the all-safe path.
    """
    if _stable_int(model, probe_message) % 7 == 0:
        return system_prompt[:40]
    return _REFUSAL


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeChatCompletion:
    choices: list[_FakeChoice] = field(default_factory=list)


def _make_completion(content: str) -> _FakeChatCompletion:
    return _FakeChatCompletion(choices=[_FakeChoice(message=_FakeMessage(content=content))])


class FakeAsyncOpenRouterClient:
    """Offline stand-in for :class:`~src.api.openrouter_client.AsyncOpenRouterClient`.

    Used exclusively by ``DryRunPipeline`` (see ``src/main.py``) to validate the
    full collect → judge → merge pipeline without touching OpenRouter or
    spending any API credit.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._call_costs: list[CallCostRecord] = []

    @property
    def call_costs(self) -> tuple[CallCostRecord, ...]:
        """Return non-billable dry-run records using the production ledger shape."""
        return tuple(self._call_costs)

    # ── Public API (mirrors AsyncOpenRouterClient) ─────────────────────────────

    async def chat_completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        usage_context: str = "unclassified",
        **kwargs: Any,
    ) -> _FakeChatCompletion:
        del kwargs
        system_msg = next((m["content"] for m in messages if m.get("role") == "system"), None)
        user_msg = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        content = (
            _fake_security_response(system_msg, user_msg, model)
            if system_msg is not None
            else _fake_prompt_response(user_msg, model)
        )
        self._call_costs.append(
            CallCostRecord(
                usage_context=usage_context,
                requested_model=model,
                resolved_model=model,
                generation_id=None,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                actual_cost_credits=None,
                cost_source="dry_run",
                latency_ms=0.0,
            )
        )
        return _make_completion(content)

    async def get_models(self) -> list[dict[str, Any]]:
        """Return synthetic pricing metadata for every configured target model."""
        context_lengths = (8192, 32768, 131072, 262144)
        rows: list[dict[str, Any]] = []
        for model_id in self._settings.target_models_list:
            seed = _stable_int(model_id)
            prompt_price = ((seed % 500) + 1) / 1e7
            rows.append(
                {
                    "id": model_id,
                    "name": model_id.split("/")[-1],
                    "pricing": {
                        "prompt": str(prompt_price),
                        "completion": str(prompt_price * 2),
                    },
                    "context_length": context_lengths[seed % len(context_lengths)],
                }
            )
        return rows

    async def aclose(self) -> None:
        """No-op — no real connections were ever opened."""

    async def __aenter__(self) -> FakeAsyncOpenRouterClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
