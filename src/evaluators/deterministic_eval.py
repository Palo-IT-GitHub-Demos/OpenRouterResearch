"""Deterministic pre-evaluation layer for the LLM benchmark.

Runs zero-cost, code-based checks before invoking the LLM-Judge.
If a check can definitively pass or fail a response, the LLM call is skipped —
saving API cost and latency.

Each concrete class implements the :class:`DeterministicCheck` protocol.
The module-level ``CHECKS`` registry maps prompt categories to the appropriate
check instance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single deterministic evaluation."""

    passed: bool | None
    """True = definitive pass, False = definitive fail, None = undecidable (forward to LLM judge)."""

    score: int | None
    """Score on a 1–5 scale, or None when undecidable."""

    reason: str
    """Human-readable explanation of the result."""


@runtime_checkable
class DeterministicCheck(Protocol):
    """Protocol satisfied by all deterministic check classes."""

    category: str

    def run(self, prompt: str, response: str) -> CheckResult:
        """Evaluate *response* against *prompt* deterministically."""
        ...


# ── Concrete checks ────────────────────────────────────────────────────────────


class JsonValidityCheck:
    """Verify that the model's response is syntactically valid JSON."""

    category = "json_output"

    def run(self, prompt: str, response: str) -> CheckResult:
        content = _strip_code_fences(response)
        try:
            json.loads(content)
            return CheckResult(
                passed=True,
                score=5,
                reason="Response is syntactically valid JSON.",
            )
        except json.JSONDecodeError as exc:
            return CheckResult(
                passed=False,
                score=1,
                reason=f"Invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno}).",
            )


class PythonSyntaxCheck:
    """Verify that the model's response is syntactically valid Python."""

    category = "code_generation"

    def run(self, prompt: str, response: str) -> CheckResult:
        code = _strip_code_fences(response)
        try:
            compile(code, "<model-response>", "exec")
            return CheckResult(
                passed=True,
                score=5,
                reason="Response contains syntactically valid Python.",
            )
        except SyntaxError as exc:
            return CheckResult(
                passed=False,
                score=1,
                reason=f"Python SyntaxError: {exc.msg} (line {exc.lineno}).",
            )


class ExactFormatCheck:
    """Placeholder for instruction-following checks.

    Generic instruction prompts require LLM judgement — this check always
    returns undecidable so the LLM-Judge is invoked.
    """

    category = "instruction_following"

    def run(self, prompt: str, response: str) -> CheckResult:
        return CheckResult(
            passed=None,
            score=None,
            reason="Instruction-following format requires LLM judgement.",
        )


# ── Registry ───────────────────────────────────────────────────────────────────

CHECKS: dict[str, DeterministicCheck] = {
    "json_output": JsonValidityCheck(),
    "code_generation": PythonSyntaxCheck(),
    "instruction_following": ExactFormatCheck(),
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences (e.g. ```json ... ```) if present."""
    lines = text.strip().splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()
