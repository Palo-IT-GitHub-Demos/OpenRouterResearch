"""Deterministic pre-evaluation layer for the generic LLM quality screen.

The screen deliberately measures only provider-neutral fundamentals: structured
output, factual sanity, elementary reasoning and instruction reliability. It is
not a substitute for domain-specific task evaluation.

Checks run in pure Python before any external judge is used. A check either
produces a definitive pass/fail score or returns ``None`` to route the response
to the blind Copilot judge panel.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a single deterministic evaluation."""

    passed: bool | None
    """True = definitive pass, False = definitive fail, None = undecidable (forward to LLM judge)."""

    score: int | None
    """Score on a 1–5 scale, or None when undecidable."""

    reason: str
    """Human-readable explanation of the result."""

    format_score: int | None = None
    """Output-format compliance on a 1–5 scale, or None when the prompt sets no strict contract.

    Scored separately from :attr:`score` so that a correct answer wrapped in
    markdown fences is reported as a formatting failure rather than as a
    content failure.
    """

    format_reason: str = ""
    """Human-readable explanation of :attr:`format_score`."""


@runtime_checkable
class DeterministicCheck(Protocol):
    """Protocol satisfied by all deterministic check classes."""

    category: str

    def run(
        self,
        prompt: str,
        response: str,
        evaluation: Mapping[str, Any] | None = None,
    ) -> CheckResult:
        """Evaluate *response* against *prompt* and optional metadata."""
        ...


# ── Concrete checks ────────────────────────────────────────────────────────────


class JsonValidityCheck:
    """Verify JSON syntax and, when configured, exact JSON content."""

    category = "json_output"

    def run(
        self,
        prompt: str,
        response: str,
        evaluation: Mapping[str, Any] | None = None,
    ) -> CheckResult:
        """Evaluate JSON content, reporting markdown fences as a formatting failure."""
        del prompt
        content = _strip_code_fences(response)
        fmt = _format_compliance(evaluation, response, content, "raw JSON")
        try:
            parsed = json.loads(content)
            expected_json = _get_context_value(evaluation, "expected_json")
            if expected_json is not None and parsed != expected_json:
                return CheckResult(
                    passed=False,
                    score=1,
                    reason="Response is valid JSON but does not match the required JSON value.",
                    **fmt,
                )
            return CheckResult(
                passed=True,
                score=5,
                reason=(
                    "Response is valid JSON and matches the required JSON value."
                    if expected_json is not None
                    else "Response is syntactically valid JSON."
                ),
                **fmt,
            )
        except json.JSONDecodeError as exc:
            return CheckResult(
                passed=False,
                score=1,
                reason=f"Invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno}).",
                **fmt,
            )


class PythonSyntaxCheck:
    """Verify Python syntax and an optional, non-executed function contract."""

    category = "code_generation"

    def run(
        self,
        prompt: str,
        response: str,
        evaluation: Mapping[str, Any] | None = None,
    ) -> CheckResult:
        """Check syntax and function shape without executing untrusted code."""
        del prompt
        code = _strip_code_fences(response)
        fmt = _format_compliance(evaluation, response, code, "raw Python")
        if not code:
            return CheckResult(
                passed=False,
                score=1,
                reason="Response is empty; expected Python source code.",
                **fmt,
            )
        try:
            tree = ast.parse(code, filename="<model-response>", mode="exec")
        except SyntaxError as exc:
            return CheckResult(
                passed=False,
                score=1,
                reason=f"Python SyntaxError: {exc.msg} (line {exc.lineno}).",
                **fmt,
            )

        required_function = _get_context_str(evaluation, "required_function")
        required_parameters = _get_context_strings(evaluation, "required_parameters")
        if required_function is None:
            return CheckResult(
                passed=True,
                score=5,
                reason="Response contains syntactically valid Python.",
                **fmt,
            )

        function = next(
            (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == required_function),
            None,
        )
        if function is None:
            return CheckResult(
                passed=False,
                score=1,
                reason=f"Required function '{required_function}' was not found.",
                **fmt,
            )

        actual_parameters = [arg.arg for arg in (*function.args.posonlyargs, *function.args.args)]
        if required_parameters and actual_parameters != required_parameters:
            return CheckResult(
                passed=False,
                score=1,
                reason=(
                    f"Function '{required_function}' parameters must be "
                    f"{required_parameters}, got {actual_parameters}."
                ),
                **fmt,
            )

        return CheckResult(
            passed=True,
            score=5,
            reason=f"Response satisfies the '{required_function}' Python function contract.",
            **fmt,
        )


class ExactFormatCheck:
    """Evaluate exact output when accepted answers are supplied.

    Without reference answers, the response remains undecidable and is sent to
    the blind judge panel. This preserves support for open-ended prompts.
    """

    category = "instruction_following"

    def run(
        self,
        prompt: str,
        response: str,
        evaluation: Mapping[str, Any] | None = None,
    ) -> CheckResult:
        """Compare a response to normalized accepted answers when available."""
        del prompt
        accepted_answers = _get_context_strings(evaluation, "accepted_answers")
        if accepted_answers:
            normalized_response = _normalize_exact_text(response)
            normalized_answers = {_normalize_exact_text(answer) for answer in accepted_answers}
            matches = normalized_response in normalized_answers
            fmt: dict[str, Any] = {}
            if _is_strict_output(evaluation):
                literal = response.strip() in {answer.strip() for answer in accepted_answers}
                fmt = {
                    "format_score": 5 if literal else 1,
                    "format_reason": (
                        "Response is exactly the accepted answer, with no extra text."
                        if literal
                        else "Response was asked for the bare answer only, but adds casing, punctuation or extra text."
                    ),
                }
            if matches:
                return CheckResult(
                    passed=True,
                    score=5,
                    reason="Response matches an accepted answer.",
                    **fmt,
                )
            return CheckResult(
                passed=False,
                score=1,
                reason="Response does not match any accepted answer exactly.",
                **fmt,
            )
        return CheckResult(
            passed=None,
            score=None,
            reason="Instruction-following format requires LLM judgement.",
        )


class ExactAnswerCheck(ExactFormatCheck):
    """Exact-answer check for factual-sanity and elementary-reasoning probes."""

    category = "exact_answer"


# ── Registry ───────────────────────────────────────────────────────────────────

CHECKS: dict[str, DeterministicCheck] = {
    "json_output": JsonValidityCheck(),
    "code_generation": PythonSyntaxCheck(),
    "instruction_following": ExactFormatCheck(),
    "exact_answer": ExactAnswerCheck(),
    "factual_sanity": ExactAnswerCheck(),
    "logical_reasoning": ExactAnswerCheck(),
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


def _get_context_value(evaluation: Mapping[str, Any] | None, key: str) -> Any | None:
    """Return a metadata value when *evaluation* is available."""
    return evaluation.get(key) if evaluation is not None else None


def _get_context_str(evaluation: Mapping[str, Any] | None, key: str) -> str | None:
    """Return a string metadata value, otherwise ``None``."""
    value = _get_context_value(evaluation, key)
    return value if isinstance(value, str) else None


def _get_context_strings(evaluation: Mapping[str, Any] | None, key: str) -> list[str]:
    """Return a validated list of string metadata values."""
    value = _get_context_value(evaluation, key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return value


def _is_strict_output(evaluation: Mapping[str, Any] | None) -> bool:
    """Return whether the response must not include markdown or extra text."""
    return _get_context_value(evaluation, "strict_output") is True


def _format_compliance(
    evaluation: Mapping[str, Any] | None,
    response: str,
    content: str,
    expected_form: str,
) -> dict[str, Any]:
    """Return the ``CheckResult`` format fields for a strict-output prompt.

    Empty when the prompt sets no strict contract, so non-strict prompts keep
    reporting content only.
    """
    if not _is_strict_output(evaluation):
        return {}
    compliant = content == response.strip()
    return {
        "format_score": 5 if compliant else 1,
        "format_reason": (
            f"Response contains {expected_form} only, as instructed."
            if compliant
            else f"Response must contain {expected_form} only, without markdown fences or extra text."
        ),
    }


def _normalize_exact_text(value: str) -> str:
    """Normalize whitespace and casing while preserving meaningful punctuation."""
    return re.sub(r"\s+", " ", value.strip()).casefold()
