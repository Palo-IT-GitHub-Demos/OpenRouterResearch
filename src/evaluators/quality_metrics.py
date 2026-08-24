"""Vectorized quality-screen metric aggregation.

The generic quality screen is intentionally a pre-selection signal, not a
domain benchmark. This module makes that limitation explicit by reporting
coverage, stability and dimension-balanced scores alongside the legacy
``avg_quality_score`` field.
"""

from __future__ import annotations

import pandas as pd

_SUMMARY_COLUMNS = [
    "model",
    "avg_quality_score",
    "quality_pass_rate",
    "quality_prompt_count",
    "quality_dimension_count",
    "quality_coverage_rate",
    "quality_score_stddev",
    "quality_stability_score",
    "quality_repetitions_observed",
    "quality_deterministic_prompt_count",
    "quality_judged_prompt_count",
]


def summarize_quality_scores(
    quality_df: pd.DataFrame,
    *,
    expected_prompt_count: int | None = None,
) -> pd.DataFrame:
    """Summarize per-response quality scores into transparent model metrics.

    Scores are first averaged across repeated attempts per prompt, then across
    quality dimensions. This macro-average prevents a dimension with many
    simple prompts from dominating the overall score.

    Args:
        quality_df: Long-format scores with at least ``model``, ``prompt_id``
            and ``score``. Optional metadata fields are handled safely for
            legacy intermediate artifacts.
        expected_prompt_count: Number of distinct screen prompts configured for
            the run. When supplied, coverage is reported in ``[0, 1]``.

    Returns:
        One row per model with quality, coverage, provenance and stability
        metrics. ``quality_stability_score`` is null unless a prompt was run at
        least twice.
    """
    if quality_df.empty or not {"model", "prompt_id", "score"}.issubset(quality_df.columns):
        return pd.DataFrame(columns=_SUMMARY_COLUMNS)

    work_df = quality_df.copy()
    work_df["score"] = pd.to_numeric(work_df["score"], errors="coerce")
    work_df = work_df.dropna(subset=["model", "prompt_id", "score"])
    if work_df.empty:
        return pd.DataFrame(columns=_SUMMARY_COLUMNS)

    if "quality_dimension" in work_df.columns:
        work_df["quality_dimension"] = work_df["quality_dimension"].fillna("legacy")
    else:
        work_df["quality_dimension"] = "legacy"
    if "weight" in work_df.columns:
        work_df["weight"] = pd.to_numeric(work_df["weight"], errors="coerce").fillna(1.0)
    else:
        work_df["weight"] = 1.0
    if "attempt" in work_df.columns:
        work_df["attempt"] = pd.to_numeric(work_df["attempt"], errors="coerce").fillna(0).astype("int32")
    else:
        work_df["attempt"] = 0
    if "source" in work_df.columns:
        work_df["source"] = work_df["source"].fillna("legacy")
    else:
        work_df["source"] = "legacy"

    prompt_df = work_df.groupby(["model", "prompt_id", "quality_dimension"], as_index=False).agg(
        score=("score", "mean"),
        weight=("weight", "first"),
        source=("source", "first"),
    )
    prompt_df["weighted_score"] = prompt_df["score"] * prompt_df["weight"]

    dimension_df = prompt_df.groupby(["model", "quality_dimension"], as_index=False).agg(
        weighted_score=("weighted_score", "sum"), total_weight=("weight", "sum")
    )
    dimension_df["dimension_score"] = dimension_df["weighted_score"] / dimension_df["total_weight"]

    summary_df = dimension_df.groupby("model", as_index=False).agg(
        avg_quality_score=("dimension_score", "mean"),
        quality_dimension_count=("quality_dimension", "nunique"),
    )
    prompt_summary_df = (
        prompt_df.assign(passed=(prompt_df["score"] >= 4.0).astype("float32"))
        .groupby("model", as_index=False)
        .agg(
            quality_pass_rate=("passed", "mean"),
            quality_prompt_count=("prompt_id", "nunique"),
        )
    )
    summary_df = summary_df.merge(prompt_summary_df, on="model", how="left")

    source_flags_df = prompt_df.assign(
        deterministic=prompt_df["source"].str.startswith("deterministic").astype("int32"),
        judged=prompt_df["source"].str.startswith("copilot").astype("int32"),
    )
    source_summary_df = source_flags_df.groupby("model", as_index=False).agg(
        quality_deterministic_prompt_count=("deterministic", "sum"),
        quality_judged_prompt_count=("judged", "sum"),
    )
    summary_df = summary_df.merge(source_summary_df, on="model", how="left")

    attempt_moments_df = (
        work_df.assign(score_squared=work_df["score"] ** 2)
        .groupby(["model", "prompt_id"], as_index=False)
        .agg(
            score_mean=("score", "mean"),
            score_squared_mean=("score_squared", "mean"),
            attempt_count=("attempt", "nunique"),
        )
    )
    attempt_moments_df["score_stddev"] = (
        attempt_moments_df["score_squared_mean"] - attempt_moments_df["score_mean"] ** 2
    ).clip(lower=0.0) ** 0.5
    repeated_df = attempt_moments_df.loc[attempt_moments_df["attempt_count"] >= 2].copy()
    if not repeated_df.empty:
        repeated_df["stability"] = (1.0 - repeated_df["score_stddev"] / 2.0).clip(lower=0.0, upper=1.0)
        stability_df = repeated_df.groupby("model", as_index=False).agg(
            quality_score_stddev=("score_stddev", "mean"),
            quality_stability_score=("stability", "mean"),
            quality_repetitions_observed=("attempt_count", "mean"),
        )
        summary_df = summary_df.merge(stability_df, on="model", how="left")
    else:
        summary_df["quality_score_stddev"] = pd.NA
        summary_df["quality_stability_score"] = pd.NA
        summary_df["quality_repetitions_observed"] = pd.NA

    if expected_prompt_count is not None and expected_prompt_count > 0:
        summary_df["quality_coverage_rate"] = (summary_df["quality_prompt_count"] / expected_prompt_count).clip(
            lower=0.0, upper=1.0
        )
    else:
        summary_df["quality_coverage_rate"] = pd.NA

    return summary_df[_SUMMARY_COLUMNS].sort_values("model").reset_index(drop=True)
