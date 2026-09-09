"""Tests for deterministic Model Compass recommendation calculations."""

from __future__ import annotations

import pandas as pd
import pytest

from src.evaluators.recommendation import (
    DEFAULT_USE_CASE_CATALOG_PATH,
    build_recommendation_report,
    load_use_case_catalog,
    parse_recommendation_weights,
)


def _benchmark(*, complete: bool = True) -> pd.DataFrame:
    rows = [
        {
            "model": "model-a",
            "tco_usd": 1.0,
            "rsi": 90.0,
            "actual_latency_p95_ms": 100.0,
        },
        {
            "model": "model-b",
            "tco_usd": 2.0,
            "rsi": 80.0,
            "actual_latency_p95_ms": 200.0,
        },
        {
            "model": "model-c",
            "tco_usd": 3.0,
            "rsi": 70.0,
            "actual_latency_p95_ms": 300.0,
        },
    ]
    if not complete:
        rows[0].pop("rsi")
    return pd.DataFrame(rows)


def _quality() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    scores = {"model-a": 5.0, "model-b": 4.0, "model-c": 3.0}
    for model, score in scores.items():
        for prompt_id in (0, 1, 2):
            rows.append(
                {
                    "model": model,
                    "prompt_id": prompt_id,
                    "score": score,
                }
            )
    return pd.DataFrame(rows)


class TestModelCompassCatalog:
    def test_catalog_is_versioned_and_has_normalized_weights(self) -> None:
        catalog = load_use_case_catalog(DEFAULT_USE_CASE_CATALOG_PATH)

        assert catalog.catalog_version == "model-compass-use-cases-v1"
        assert len(catalog.use_cases) == 6
        assert sum(catalog.weights.model_dump().values()) == pytest.approx(1.0)

    def test_accepts_a_valid_weight_override(self) -> None:
        weights = parse_recommendation_weights('{"quality":0.6,"security":0.2,"cost":0.15,"performance":0.05}')

        assert weights is not None
        assert weights.quality == pytest.approx(0.6)

    def test_rejects_weights_that_do_not_sum_to_one(self) -> None:
        with pytest.raises(ValueError, match="MODEL_COMPASS_WEIGHTS"):
            parse_recommendation_weights('{"quality":1,"security":1,"cost":1,"performance":1}')


class TestModelCompassRecommendations:
    def test_applies_use_case_threshold_before_ranking(self) -> None:
        report = build_recommendation_report(_benchmark(), _quality())
        structured = report.loc[report["use_case_id"] == "structured_extraction"].set_index("model")

        assert structured.loc["model-a", "quality_score"] == pytest.approx(5.0)
        assert structured.loc["model-a", "recommendation_status"] == "recommended"
        assert structured.loc["model-a", "recommendation_rank"] == 1
        assert structured.loc["model-b", "recommendation_status"] == "eligible"
        assert structured.loc["model-b", "recommendation_rank"] == 2
        assert structured.loc["model-c", "recommendation_status"] == "below_quality_threshold"
        assert pd.isna(structured.loc["model-c", "recommendation_rank"])

    def test_preserves_dense_ties_without_a_tiebreak_rule(self) -> None:
        benchmark = _benchmark()
        benchmark.loc[benchmark["model"] == "model-b", ["tco_usd", "rsi", "actual_latency_p95_ms"]] = [
            1.0,
            90.0,
            100.0,
        ]
        quality = _quality()
        quality.loc[quality["model"] == "model-b", "score"] = 5.0

        report = build_recommendation_report(benchmark, quality)
        structured = report.loc[report["use_case_id"] == "structured_extraction"].set_index("model")

        assert structured.loc["model-a", "recommendation_rank"] == 1
        assert structured.loc["model-b", "recommendation_rank"] == 1
        assert structured.loc["model-a", "recommendation_status"] == "recommended"
        assert structured.loc["model-b", "recommendation_status"] == "recommended"

    def test_does_not_recommend_when_decision_evidence_is_incomplete(self) -> None:
        report = build_recommendation_report(_benchmark(complete=False), _quality())
        structured = report.loc[report["use_case_id"] == "structured_extraction"].set_index("model")

        assert structured.loc["model-a", "quality_eligible"]
        assert not structured.loc["model-a", "decision_evidence_complete"]
        assert structured.loc["model-a", "recommendation_status"] == "insufficient_decision_evidence"
        assert "security" in structured.loc["model-a", "evidence_missing"]
        assert pd.isna(structured.loc["model-a", "recommendation_rank"])

    def test_emits_one_row_for_each_model_and_use_case(self) -> None:
        report = build_recommendation_report(_benchmark(), _quality())

        assert len(report) == 18
        assert report[["use_case_id", "model"]].drop_duplicates().shape == (18, 2)

    def test_records_custom_weights_in_the_report(self) -> None:
        weights = parse_recommendation_weights('{"quality":0.6,"security":0.2,"cost":0.15,"performance":0.05}')
        report = build_recommendation_report(_benchmark(), _quality(), weights=weights)

        assert report["recommendation_weights"].nunique() == 1
        assert '"quality": 0.6' in report["recommendation_weights"].iloc[0]
