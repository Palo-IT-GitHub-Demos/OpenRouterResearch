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
    "avg_quality_score_deterministic",
    "avg_quality_score_judged",
    "quality_pass_rate",
    "quality_prompt_count",
    "quality_dimension_count",
    "quality_coverage_rate",
    "quality_score_stddev",
    "quality_stability_score",
    "quality_repetitions_observed",
    "quality_deterministic_prompt_count",
    "quality_judged_prompt_count",
    "quality_excluded_prompt_count",
    "quality_judge_disagreement_rate",
]

INPUT_CORRUPTION_STATUS = "suspected_input_corruption"
"""``verification_status`` marking a prompt every model missed against a known answer."""

_MIN_MODELS_FOR_CORRUPTION_SIGNAL = 2
_PASSING_SCORE = 4.0
_CONTENT_SOURCE = "deterministic"
_JUDGED_SOURCE_PREFIX = "copilot"
_DISAGREEMENT_THRESHOLD = 2
"""Judge-score range (max - min) at or above which a response is flagged as disputed.

With a 1-5 scale and 3 judges, a range of 2 already means the panel disagreed on
whether the response landed in the same tier (e.g. 3 vs 5), not just a rounding
wobble (e.g. 4 vs 5). See docs/quality-methodology.md "Judge disagreement".
"""

_DIMENSION_COLUMNS = ["model", "quality_dimension", "dimension_score", "quality_prompt_count"]

_DETAIL_COLUMNS = [
    "model",
    "prompt_id",
    "attempt",
    "category",
    "quality_dimension",
    "prompt",
    "response",
    "score",
    "judge_disagreement",
    "reasoning",
    "judge_verdicts",
    "source",
    "generation_id",
    "resolved_model",
    "request_sha256",
    "expected_answers_json",
    "verification_status",
]


def _has_reference_answer(series: pd.Series) -> pd.Series:
    """Return whether each row carries a non-empty accepted-answer list."""
    text = series.fillna("").astype(str).str.strip()
    return ~text.isin({"", "[]", "nan", "NaN", "null"})


def flag_suspected_input_corruption(
    quality_df: pd.DataFrame,
    *,
    min_models: int = _MIN_MODELS_FOR_CORRUPTION_SIGNAL,
) -> pd.Series:
    """Flag reference-answer prompts that every model in the run got wrong.

    When unrelated models from different providers all miss a prompt whose
    correct answer is known and fixed, the shared cause is far more likely to
    be the request that actually reached the provider (proxy redaction,
    template substitution, truncation) than a simultaneous failure of every
    model. Treating that as a model-quality failure silently penalises the
    whole field on the same prompt.

    The check is deliberately narrow to keep false positives out: it only
    considers content rows from reference-answer prompts, so a prompt that is
    merely hard, or that every model formats badly, is never flagged.

    Raw scores and responses are never rewritten. The flag only removes the
    prompt from the aggregate denominators and is surfaced as
    ``verification_status=suspected_input_corruption`` in the evidence files.

    Args:
        quality_df: Long-format scores including ``expected_answers_json``
            and ``source``.
        min_models: Minimum number of distinct models that must have attempted
            the prompt before an all-fail pattern counts as a signal.

    Returns:
        Boolean mask aligned to *quality_df*'s index. All-``False`` when the
        required metadata columns are missing (legacy artifacts).
    """
    no_flag = pd.Series(False, index=quality_df.index, dtype=bool)
    required = {"model", "prompt_id", "score", "expected_answers_json", "source"}
    if quality_df.empty or not required.issubset(quality_df.columns):
        return no_flag

    candidates = _has_reference_answer(quality_df["expected_answers_json"]) & (
        quality_df["source"].fillna("").astype(str) == _CONTENT_SOURCE
    )
    work_df = quality_df.loc[candidates, ["model", "prompt_id", "score"]].copy()
    work_df["score"] = pd.to_numeric(work_df["score"], errors="coerce")
    work_df = work_df.dropna()
    if work_df.empty:
        return no_flag

    per_model_df = work_df.groupby(["prompt_id", "model"], as_index=False).agg(score=("score", "mean"))
    per_model_df["failed"] = per_model_df["score"] < _PASSING_SCORE
    per_prompt_df = per_model_df.groupby("prompt_id").agg(
        model_count=("model", "nunique"), failed_count=("failed", "sum")
    )
    corrupted = per_prompt_df.index[
        (per_prompt_df["model_count"] >= min_models) & (per_prompt_df["failed_count"] == per_prompt_df["model_count"])
    ]
    if corrupted.empty:
        return no_flag
    return candidates & quality_df["prompt_id"].isin(corrupted)


def _drop_suspected_input_corruption(quality_df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Return *quality_df* without flagged prompts, plus the excluded prompt count."""
    mask = flag_suspected_input_corruption(quality_df)
    if not bool(mask.any()):
        return quality_df, 0
    excluded = int(quality_df.loc[mask, "prompt_id"].nunique())
    return quality_df.loc[~quality_df["prompt_id"].isin(quality_df.loc[mask, "prompt_id"])], excluded


def _normalize_quality_df(quality_df: pd.DataFrame) -> pd.DataFrame:
    """Coerce optional metadata columns to safe defaults for legacy artifacts."""
    work_df = quality_df.copy()
    work_df["score"] = pd.to_numeric(work_df["score"], errors="coerce")
    work_df = work_df.dropna(subset=["model", "prompt_id", "score"])
    if work_df.empty:
        return work_df

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
    return work_df


def _prompt_and_dimension_frames(work_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Group normalized scores per (model, prompt, dimension) then per (model, dimension).

    Extracted so :func:`summarize_quality_scores` and
    :func:`summarize_quality_dimensions` can never disagree on how
    ``dimension_score`` (the weighted macro-average per dimension) is derived.
    """
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

    return prompt_df, dimension_df


def summarize_quality_dimensions(quality_df: pd.DataFrame) -> pd.DataFrame:
    """Return a long-format per-model, per-dimension quality breakdown.

    ``avg_quality_score`` in :func:`summarize_quality_scores` is the mean of
    the same ``dimension_score`` values returned here across dimensions — this
    is the detail that gets averaged away in the main summary.

    Args:
        quality_df: Long-format scores with at least ``model``, ``prompt_id``
            and ``score`` (see :func:`summarize_quality_scores`).

    Returns:
        One row per (model, quality_dimension) with ``dimension_score``
        (1-5) and ``quality_prompt_count`` (distinct prompts observed for
        that dimension). Empty (with the expected columns) if *quality_df*
        has no usable rows.
    """
    if quality_df.empty or not {"model", "prompt_id", "score"}.issubset(quality_df.columns):
        return pd.DataFrame(columns=_DIMENSION_COLUMNS)

    scored_df, _ = _drop_suspected_input_corruption(quality_df)
    work_df = _normalize_quality_df(scored_df)
    if work_df.empty:
        return pd.DataFrame(columns=_DIMENSION_COLUMNS)

    prompt_df, dimension_df = _prompt_and_dimension_frames(work_df)
    prompt_counts_df = prompt_df.groupby(["model", "quality_dimension"], as_index=False).agg(
        quality_prompt_count=("prompt_id", "nunique")
    )
    result_df = dimension_df.merge(prompt_counts_df, on=["model", "quality_dimension"], how="left")
    return result_df[_DIMENSION_COLUMNS].sort_values(["model", "quality_dimension"]).reset_index(drop=True)


def build_quality_details(quality_df: pd.DataFrame) -> pd.DataFrame:
    """Return the long-format prompt/response transcript for audit and drill-down.

    One row per (model, prompt_id, attempt) actually scored — the exact
    prompt text sent to the model and the response it returned, alongside the
    score/reasoning/dimension that fed the aggregated metrics. Missing
    metadata (legacy artifacts predating this field) defaults to an empty
    string rather than raising.

    Args:
        quality_df: Long-format scores, ideally including ``prompt`` and
            ``response`` (see :func:`~src.evaluators.quality_judge.AsyncQualityJudge.run_collect`).

    Returns:
        One row per scored (model, prompt_id, attempt), sorted for readability.
    """
    if quality_df.empty:
        return pd.DataFrame(columns=_DETAIL_COLUMNS)

    details_df = quality_df.copy()
    for column in _DETAIL_COLUMNS:
        if column in details_df.columns:
            continue
        string_columns = {
            "prompt",
            "response",
            "reasoning",
            "judge_verdicts",
            "category",
            "generation_id",
            "resolved_model",
            "request_sha256",
            "expected_answers_json",
            "verification_status",
        }
        details_df[column] = "" if column in string_columns else pd.NA
    corrupted = flag_suspected_input_corruption(details_df)
    if bool(corrupted.any()):
        flagged_prompts = details_df.loc[corrupted, "prompt_id"]
        details_df.loc[details_df["prompt_id"].isin(flagged_prompts), "verification_status"] = INPUT_CORRUPTION_STATUS
    return details_df[_DETAIL_COLUMNS].sort_values(["model", "prompt_id", "attempt"]).reset_index(drop=True)


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

    scored_df, excluded_prompt_count = _drop_suspected_input_corruption(quality_df)
    work_df = _normalize_quality_df(scored_df)
    if work_df.empty:
        return pd.DataFrame(columns=_SUMMARY_COLUMNS)

    prompt_df, dimension_df = _prompt_and_dimension_frames(work_df)

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

    # Deterministic checks are pass/fail rendered as 1 or 5; judge scores are a
    # graded 1-5. Averaging them into a single figure hides which scale drives
    # a model's rank, so both are published alongside the blended score.
    for label, source_prefix in (("deterministic", "deterministic"), ("judged", "copilot")):
        column = f"avg_quality_score_{label}"
        subset_df = work_df.loc[work_df["source"].str.startswith(source_prefix)]
        if subset_df.empty:
            summary_df[column] = pd.NA
            continue
        _, subset_dimension_df = _prompt_and_dimension_frames(subset_df)
        subset_summary_df = subset_dimension_df.groupby("model", as_index=False).agg(
            **{column: ("dimension_score", "mean")}
        )
        summary_df = summary_df.merge(subset_summary_df, on="model", how="left")

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
        # Excluded prompts leave the denominator too, so a suspected input
        # corruption is not also reported as a collection gap.
        scorable_prompt_count = max(expected_prompt_count - excluded_prompt_count, 1)
        summary_df["quality_coverage_rate"] = (summary_df["quality_prompt_count"] / scorable_prompt_count).clip(
            lower=0.0, upper=1.0
        )
    else:
        summary_df["quality_coverage_rate"] = pd.NA

    summary_df["quality_excluded_prompt_count"] = excluded_prompt_count

    if "judge_disagreement" in work_df.columns:
        disagreement_df = work_df.assign(
            disagreement=pd.to_numeric(work_df["judge_disagreement"], errors="coerce")
        ).dropna(subset=["disagreement"])
    else:
        disagreement_df = work_df.iloc[0:0]
    if disagreement_df.empty:
        summary_df["quality_judge_disagreement_rate"] = pd.NA
    else:
        disagreement_summary_df = (
            disagreement_df.assign(disputed=(disagreement_df["disagreement"] >= _DISAGREEMENT_THRESHOLD))
            .groupby("model", as_index=False)
            .agg(quality_judge_disagreement_rate=("disputed", "mean"))
        )
        summary_df = summary_df.merge(disagreement_summary_df, on="model", how="left")

    return summary_df[_SUMMARY_COLUMNS].sort_values("model").reset_index(drop=True)
