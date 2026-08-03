"""Unit tests for src/evaluators/deterministic_eval.py."""

from __future__ import annotations

import pytest

from src.evaluators.deterministic_eval import (
    CHECKS,
    ExactFormatCheck,
    JsonValidityCheck,
    PythonSyntaxCheck,
    _strip_code_fences,
)


class TestJsonValidityCheck:
    def test_valid_json_passes(self) -> None:
        check = JsonValidityCheck()
        result = check.run("", '{"key": "value"}')
        assert result.passed is True
        assert result.score == 5

    def test_invalid_json_fails(self) -> None:
        check = JsonValidityCheck()
        result = check.run("", "not json at all")
        assert result.passed is False
        assert result.score == 1

    def test_markdown_fenced_json_passes(self) -> None:
        check = JsonValidityCheck()
        result = check.run("", '```json\n{"key": "value"}\n```')
        assert result.passed is True
        assert result.score == 5

    def test_empty_object_passes(self) -> None:
        check = JsonValidityCheck()
        result = check.run("", "{}")
        assert result.passed is True

    def test_reason_is_non_empty(self) -> None:
        check = JsonValidityCheck()
        result = check.run("", "bad")
        assert len(result.reason) > 0


class TestPythonSyntaxCheck:
    def test_valid_function_passes(self) -> None:
        check = PythonSyntaxCheck()
        code = "def add(a: int, b: int) -> int:\n    return a + b"
        result = check.run("", code)
        assert result.passed is True
        assert result.score == 5

    def test_syntax_error_fails(self) -> None:
        check = PythonSyntaxCheck()
        result = check.run("", "def broken(:\n    pass")
        assert result.passed is False
        assert result.score == 1
        assert "SyntaxError" in result.reason

    def test_fenced_code_block_passes(self) -> None:
        check = PythonSyntaxCheck()
        result = check.run("", "```python\nx = 1 + 1\n```")
        assert result.passed is True

    def test_empty_string_passes(self) -> None:
        check = PythonSyntaxCheck()
        result = check.run("", "")
        assert result.passed is True


class TestExactFormatCheck:
    def test_always_undecidable(self) -> None:
        check = ExactFormatCheck()
        result = check.run("any prompt", "any response")
        assert result.passed is None
        assert result.score is None

    def test_reason_is_non_empty(self) -> None:
        check = ExactFormatCheck()
        result = check.run("", "")
        assert len(result.reason) > 0


class TestChecksRegistry:
    def test_json_output_registered(self) -> None:
        assert "json_output" in CHECKS
        assert isinstance(CHECKS["json_output"], JsonValidityCheck)

    def test_code_generation_registered(self) -> None:
        assert "code_generation" in CHECKS
        assert isinstance(CHECKS["code_generation"], PythonSyntaxCheck)

    def test_instruction_following_registered(self) -> None:
        assert "instruction_following" in CHECKS


class TestStripCodeFences:
    def test_strips_fenced_block(self) -> None:
        raw = "```json\n{}\n```"
        assert _strip_code_fences(raw) == "{}"

    def test_no_fences_unchanged(self) -> None:
        raw = '{"key": 1}'
        assert _strip_code_fences(raw) == raw
