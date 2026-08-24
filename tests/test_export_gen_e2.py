"""Unit tests for scripts/export_gen_e2_registry.py."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.export_gen_e2_registry import _build_registry, _load_results, main

# ── Fixtures ──────────────────────────────────────────────────────────────────

_SAMPLE_RECORDS = [
    {
        "model": "openai/gpt-4o-mini",
        "avg_quality_score": 4.2,
        "prompt_price_per_token": 0.000001,
        "completion_price_per_token": 0.000002,
        "zero_data_retention": True,
        "leak_count": 0,
        "is_vulnerable": False,
    },
    {
        "model": "anthropic/claude-3.5-sonnet",
        "avg_quality_score": 4.7,
        "prompt_price_per_token": 0.000003,
        "completion_price_per_token": 0.000015,
        "zero_data_retention": False,
        "leak_count": 1,
        "is_vulnerable": True,
    },
]


def _write_sample_json(tmp_path: Path) -> Path:
    p = tmp_path / "benchmark_test.json"
    p.write_text(json.dumps(_SAMPLE_RECORDS), encoding="utf-8")
    return p


# ── _load_results ─────────────────────────────────────────────────────────────


class TestLoadResults:
    def test_returns_list_of_records(self, tmp_path: Path) -> None:
        p = _write_sample_json(tmp_path)
        records = _load_results(p)
        assert isinstance(records, list)
        assert len(records) == 2

    def test_raises_on_non_array_json(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.json"
        p.write_text('{"key": "value"}')
        with pytest.raises(ValueError):
            _load_results(p)


# ── _build_registry ───────────────────────────────────────────────────────────


class TestBuildRegistry:
    def test_schema_version_present(self) -> None:
        reg = _build_registry(_SAMPLE_RECORDS, "enterprise_qa")
        assert reg["schema_version"] == 1

    def test_all_models_present(self) -> None:
        reg = _build_registry(_SAMPLE_RECORDS, "enterprise_qa")
        model_ids = [m["id"] for m in reg["models"]]  # type: ignore[index]
        assert "openai/gpt-4o-mini" in model_ids
        assert "anthropic/claude-3.5-sonnet" in model_ids

    def test_owasp_scores_normalized(self) -> None:
        records_with_probes = [
            {
                **_SAMPLE_RECORDS[0],
                "probe_details": json.dumps(
                    [
                        {"category_id": "LLM01", "leaked": True},
                        {"category_id": "LLM01", "leaked": False},
                        {"category_id": "LLM07", "leaked": False},
                    ]
                ),
            }
        ]
        reg = _build_registry(records_with_probes, "enterprise_qa")
        model = reg["models"][0]  # type: ignore[index]
        if "owasp_scores" in model:
            for cat_id, score in model["owasp_scores"].items():  # type: ignore[union-attr]
                assert 0.0 <= score <= 1.0, f"{cat_id} score out of bounds: {score}"

    def test_unknown_profile_raises(self) -> None:
        with pytest.raises(ValueError):
            _build_registry(_SAMPLE_RECORDS, "nonexistent_profile")

    def test_tco_is_non_negative_or_none(self) -> None:
        reg = _build_registry(_SAMPLE_RECORDS, "enterprise_qa")
        for model in reg["models"]:  # type: ignore[union-attr]
            tco = model.get("tco_usd_monthly")
            if tco is not None:
                assert tco >= 0.0


# ── main() CLI ────────────────────────────────────────────────────────────────


class TestMainCli:
    def test_dry_run_does_not_write_file(self, tmp_path: Path) -> None:
        results = _write_sample_json(tmp_path)
        output = tmp_path / "out.yaml"
        ret = main(["--results", str(results), "--output", str(output), "--dry-run"])
        assert ret == 0
        assert not output.exists()

    def test_writes_valid_yaml(self, tmp_path: Path) -> None:
        results = _write_sample_json(tmp_path)
        output = tmp_path / "registry.yaml"
        ret = main(["--results", str(results), "--output", str(output), "--profile", "enterprise_qa"])
        assert ret == 0
        assert output.exists()
        parsed = yaml.safe_load(output.read_text())
        assert isinstance(parsed, dict)
        assert "models" in parsed
        assert len(parsed["models"]) == 2

    def test_missing_results_returns_error(self, tmp_path: Path) -> None:
        ret = main(["--results", str(tmp_path / "nope.json"), "--output", str(tmp_path / "out.yaml")])
        assert ret == 1
