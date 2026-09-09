"""Deterministic Model Compass recommendation calculations.

The recommendation report is deliberately separate from the one-row-per-model
benchmark summary. It preserves every model for every generic use case and
records why a model is recommended, eligible, below threshold, or lacks enough
evidence for a decision.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Final

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_USE_CASE_CATALOG_PATH: Final[Path] = Path("data/catalog/model_compass_use_cases.json")
_QUALITY_MINIMUM: Final[float] = 1.0
_QUALITY_MAXIMUM: Final[float] = 5.0
_REQUIRED_COMPONENTS: Final[tuple[str, ...]] = ("quality", "security", "cost", "performance")


class RecommendationWeights(BaseModel):
    """Configurable weights used for the recommendation score."""

    model_config = ConfigDict(extra="forbid")

    quality: float = Field(gt=0.0)
    security: float = Field(gt=0.0)
    cost: float = Field(gt=0.0)
    performance: float = Field(gt=0.0)

    @model_validator(mode="after")
    def validate_sum(self) -> RecommendationWeights:
        """Require a normalized weight vector."""
        if not math.isclose(sum(self.model_dump().values()), 1.0, abs_tol=1e-9):
            raise ValueError("Recommendation weights must sum to 1.0.")
        return self


class UseCaseDefinition(BaseModel):
    """Versioned generic use-case definition."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    prompt_ids: list[int] = Field(min_length=1)
    minimum_quality_score: float = Field(ge=_QUALITY_MINIMUM, le=_QUALITY_MAXIMUM)


class UseCaseCatalog(BaseModel):
    """Validated Model Compass use-case catalog."""

    model_config = ConfigDict(extra="forbid")

    catalog_version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    weights: RecommendationWeights
    use_cases: list[UseCaseDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_use_cases(self) -> UseCaseCatalog:
        """Reject duplicate IDs and overlapping prompt ownership."""
        ids = [use_case.id for use_case in self.use_cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Use-case IDs must be unique.")
        prompt_owners: dict[int, str] = {}
        for use_case in self.use_cases:
            for prompt_id in use_case.prompt_ids:
                previous_owner = prompt_owners.get(prompt_id)
                if previous_owner is not None:
                    raise ValueError(f"Prompt ID {prompt_id} belongs to both '{previous_owner}' and '{use_case.id}'.")
                prompt_owners[prompt_id] = use_case.id
        return self


def load_use_case_catalog(path: Path = DEFAULT_USE_CASE_CATALOG_PATH) -> UseCaseCatalog:
    """Load and validate a Model Compass use-case catalog."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return UseCaseCatalog.model_validate(payload)
    except FileNotFoundError as exc:
        raise ValueError(f"Use-case catalog not found: '{path}'.") from exc
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid use-case catalog '{path}': {exc}") from exc


def parse_recommendation_weights(raw: str | None) -> RecommendationWeights | None:
    """Parse an optional JSON weight override from ``MODEL_COMPASS_WEIGHTS``."""
    if raw is None or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
        return RecommendationWeights.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid MODEL_COMPASS_WEIGHTS: provide JSON with positive quality, security, cost, "
            f"and performance weights summing to 1.0 ({exc})."
        ) from exc


def _normalize_quality_score(series: pd.Series) -> pd.Series:
    """Map the quality scale 1-5 to the common 0-100 component scale."""
    return ((pd.to_numeric(series, errors="coerce") - _QUALITY_MINIMUM) / 4.0 * 100.0).clip(0.0, 100.0)


def _normalize_higher_is_better(series: pd.Series) -> pd.Series:
    """Normalize a higher-is-better metric to 0-100, preserving missing values."""
    values = pd.to_numeric(series, errors="coerce")
    finite = values.where(values.map(math.isfinite))
    if finite.notna().sum() == 0:
        return pd.Series(float("nan"), index=series.index, dtype="float64")
    minimum = float(finite.min())
    maximum = float(finite.max())
    if math.isclose(minimum, maximum):
        return finite.notna().astype(float) * 100.0
    return ((finite - minimum) / (maximum - minimum) * 100.0).clip(0.0, 100.0)


def _normalize_lower_is_better(series: pd.Series) -> pd.Series:
    """Normalize a lower-is-better metric to 0-100, preserving missing values."""
    values = pd.to_numeric(series, errors="coerce")
    finite = values.where(values.map(math.isfinite))
    if finite.notna().sum() == 0:
        return pd.Series(float("nan"), index=series.index, dtype="float64")
    minimum = float(finite.min())
    maximum = float(finite.max())
    if math.isclose(minimum, maximum):
        return finite.notna().astype(float) * 100.0
    return ((maximum - finite) / (maximum - minimum) * 100.0).clip(0.0, 100.0)


def _quality_by_use_case(
    quality_df: pd.DataFrame,
    models: list[str],
    use_case: UseCaseDefinition,
) -> pd.DataFrame:
    """Calculate per-model quality and coverage for one use case."""
    columns = ["model", "quality_score", "quality_coverage_rate", "quality_prompt_count"]
    if quality_df.empty or not {"model", "prompt_id", "score"}.issubset(quality_df.columns):
        return pd.DataFrame(
            {
                "model": models,
                "quality_score": float("nan"),
                "quality_coverage_rate": 0.0,
                "quality_prompt_count": 0,
            },
            columns=columns,
        )

    work = quality_df.loc[:, ["model", "prompt_id", "score"]].copy()
    work["prompt_id"] = pd.to_numeric(work["prompt_id"], errors="coerce")
    work = work.loc[work["prompt_id"].isin(use_case.prompt_ids)]
    if work.empty:
        return pd.DataFrame(
            {
                "model": models,
                "quality_score": float("nan"),
                "quality_coverage_rate": 0.0,
                "quality_prompt_count": 0,
            },
            columns=columns,
        )

    work["score"] = pd.to_numeric(work["score"], errors="coerce")
    work = work.dropna(subset=["model", "prompt_id", "score"])
    prompt_scores = work.groupby(["model", "prompt_id"], as_index=False)["score"].mean()
    summary = prompt_scores.groupby("model", as_index=False).agg(
        quality_score=("score", "mean"),
        quality_prompt_count=("prompt_id", "nunique"),
    )
    summary["quality_coverage_rate"] = summary["quality_prompt_count"] / len(use_case.prompt_ids)
    model_frame = pd.DataFrame({"model": models})
    merged = model_frame.merge(summary, on="model", how="left")
    merged["quality_prompt_count"] = (
        pd.to_numeric(merged["quality_prompt_count"], errors="coerce").fillna(0).astype("int32")
    )
    merged["quality_coverage_rate"] = pd.to_numeric(merged["quality_coverage_rate"], errors="coerce").fillna(0.0)
    return merged[columns]


def _numeric_column(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric frame column or a same-index missing series."""
    if column not in frame.columns:
        return pd.Series(float("nan"), index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _performance_component(frame: pd.DataFrame) -> tuple[pd.Series, str]:
    """Return the normalized performance component and the metric used."""
    latency = _numeric_column(frame, "actual_latency_p95_ms")
    if latency.notna().any():
        return _normalize_lower_is_better(latency), "actual_latency_p95_ms"
    throughput = _numeric_column(frame, "actual_tokens_per_second")
    if throughput.notna().any():
        return _normalize_higher_is_better(throughput), "actual_tokens_per_second"
    return pd.Series(float("nan"), index=frame.index, dtype="float64"), "unavailable"


def _missing_components(row: pd.Series) -> str:
    """Render missing decision dimensions in a stable, human-readable order."""
    return ", ".join(component for component in _REQUIRED_COMPONENTS if pd.isna(row[f"{component}_score"]))


def build_recommendation_report(
    benchmark_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    catalog_path: Path = DEFAULT_USE_CASE_CATALOG_PATH,
    weights: RecommendationWeights | None = None,
) -> pd.DataFrame:
    """Build one recommendation row for every use-case/model pair.

    Quality eligibility is evaluated before the weighted score. A model that
    misses the use-case threshold is never marked recommended because of a low
    cost or fast response. A complete decision score requires all four default
    components; incomplete runs remain visible with an evidence status rather
    than receiving a misleading partial recommendation.
    """
    catalog = load_use_case_catalog(catalog_path)
    if weights is not None:
        catalog = catalog.model_copy(update={"weights": weights})
    if benchmark_df.empty or "model" not in benchmark_df.columns:
        return pd.DataFrame()

    model_frame = benchmark_df[["model"]].drop_duplicates().reset_index(drop=True)
    security_score = _numeric_column(benchmark_df, "rsi").groupby(benchmark_df["model"]).first()
    cost_score = _normalize_lower_is_better(_numeric_column(benchmark_df, "tco_usd"))
    performance_score, performance_basis = _performance_component(benchmark_df)
    metric_frame = benchmark_df[["model"]].copy()
    metric_frame["security_score"] = metric_frame["model"].map(security_score)
    metric_frame["cost_score"] = cost_score.to_numpy()
    metric_frame["performance_score"] = performance_score.to_numpy()
    metric_frame = metric_frame.drop_duplicates("model")

    weight_values = catalog.weights.model_dump()
    weight_json = json.dumps(weight_values, sort_keys=True)
    reports: list[pd.DataFrame] = []
    for use_case in catalog.use_cases:
        quality_frame = _quality_by_use_case(quality_df, model_frame["model"].tolist(), use_case)
        report = model_frame.merge(quality_frame, on="model", how="left")
        report = report.merge(metric_frame, on="model", how="left")
        report["use_case_id"] = use_case.id
        report["use_case_name"] = use_case.name
        report["use_case_description"] = use_case.description
        report["catalog_version"] = catalog.catalog_version
        report["prompt_ids"] = json.dumps(use_case.prompt_ids)
        report["quality_threshold"] = use_case.minimum_quality_score
        report["quality_score_100"] = _normalize_quality_score(report["quality_score"])
        report["quality_eligible"] = (
            report["quality_score"].ge(use_case.minimum_quality_score) & report["quality_coverage_rate"].ge(1.0)
        ).fillna(False)

        component_columns = [f"{component}_score" for component in _REQUIRED_COMPONENTS]
        available = report[component_columns].notna()
        available_weight = sum(
            available[f"{component}_score"].astype(float) * weight_values[component]
            for component in _REQUIRED_COMPONENTS
        )
        weighted_total = sum(
            pd.to_numeric(report[f"{component}_score"], errors="coerce").fillna(0.0) * weight_values[component]
            for component in _REQUIRED_COMPONENTS
        )
        report["recommendation_score_coverage"] = available_weight.round(4)
        report["recommendation_score"] = (weighted_total / available_weight.replace(0.0, float("nan"))).round(4)
        report["recommendation_weights"] = weight_json
        report["performance_basis"] = performance_basis
        report["decision_evidence_complete"] = available.all(axis=1)
        report["evidence_missing"] = report.apply(_missing_components, axis=1)

        ranked_scores = report["recommendation_score"].where(
            report["quality_eligible"] & report["decision_evidence_complete"]
        )
        report["recommendation_rank"] = ranked_scores.rank(method="dense", ascending=False, na_option="keep")
        report["recommendation_rank"] = report["recommendation_rank"].round().astype("Int64")
        status = pd.Series("insufficient_quality_evidence", index=report.index, dtype="string")
        quality_complete = report["quality_coverage_rate"].ge(1.0) & report["quality_score"].notna()
        status.loc[quality_complete & report["quality_score"].lt(use_case.minimum_quality_score)] = (
            "below_quality_threshold"
        )
        status.loc[report["quality_eligible"] & ~report["decision_evidence_complete"]] = (
            "insufficient_decision_evidence"
        )
        status.loc[report["recommendation_rank"].notna() & report["recommendation_rank"].gt(1)] = "eligible"
        status.loc[report["recommendation_rank"].eq(1)] = "recommended"
        report["recommendation_status"] = status
        reports.append(report)

    columns = [
        "use_case_id",
        "use_case_name",
        "use_case_description",
        "catalog_version",
        "prompt_ids",
        "model",
        "quality_score",
        "quality_score_100",
        "quality_coverage_rate",
        "quality_prompt_count",
        "quality_threshold",
        "quality_eligible",
        "security_score",
        "cost_score",
        "performance_score",
        "performance_basis",
        "recommendation_score",
        "recommendation_score_coverage",
        "recommendation_weights",
        "decision_evidence_complete",
        "evidence_missing",
        "recommendation_rank",
        "recommendation_status",
    ]
    records = [record for report in reports for record in report[columns].to_dict(orient="records")]
    return pd.DataFrame.from_records(records, columns=columns)
