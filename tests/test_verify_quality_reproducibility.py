"""Tests for optional k=1 OpenRouter reproducibility checks."""

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.verify_quality_reproducibility import (
    RecheckResult,
    _selected_evidence,
    classify_verification,
)


def _result(passed: bool, error: str | None = None) -> RecheckResult:
    return RecheckResult("response", passed, "gen-1", "model", error=error)


@pytest.mark.parametrize(
    ("rechecks", "expected"),
    [
        ([_result(False), _result(False)], "confirmed_failure"),
        ([_result(True), _result(True)], "not_reproduced"),
        ([_result(True), _result(False)], "unstable"),
        ([_result(False, "timeout"), _result(False)], "inconclusive"),
        ([_result(False)], "inconclusive"),
    ],
)
def test_classifies_openrouter_reproducibility(
    rechecks: list[RecheckResult], expected: str
) -> None:
    assert classify_verification(rechecks) == expected


def test_rejects_extra_rechecks_when_run_already_has_k_greater_than_one(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmark_test.csv"
    benchmark.write_text("model\nmodel-a\n", encoding="utf-8")
    details_dir = tmp_path / "quality_details"
    details_dir.mkdir()
    pd.DataFrame(
        {
            "model": ["model-a", "model-a"],
            "prompt_id": [4, 4],
            "attempt": [0, 1],
            "prompt": ["What is the capital of Australia?"] * 2,
            "response": ["Canberra", "Sydney"],
            "score": [5, 1],
            "quality_dimension": ["factual_sanity"] * 2,
            "expected_answers_json": [json.dumps(["Canberra"])] * 2,
            "verification_status": ["run_repetitions_available"] * 2,
        }
    ).to_csv(details_dir / "benchmark_test_quality_details.csv", index=False)

    with pytest.raises(ValueError, match="already has k=2 attempts"):
        _selected_evidence(benchmark, "model-a", 4)


def test_rejects_correct_or_otherwise_ineligible_k1_evidence(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmark_test.csv"
    benchmark.write_text("model\nmodel-a\n", encoding="utf-8")
    details_dir = tmp_path / "quality_details"
    details_dir.mkdir()
    pd.DataFrame(
        {
            "model": ["model-a"],
            "prompt_id": [4],
            "attempt": [0],
            "prompt": ["What is the capital of Australia?"],
            "response": ["Canberra"],
            "score": [5],
            "quality_dimension": ["factual_sanity"],
            "expected_answers_json": [json.dumps(["Canberra"])],
            "verification_status": ["not_required"],
        }
    ).to_csv(details_dir / "benchmark_test_quality_details.csv", index=False)

    with pytest.raises(ValueError, match="not eligible"):
        _selected_evidence(benchmark, "model-a", 4)