"""Cost analyser — fetches live pricing from OpenRouter and computes cost matrices.

Both a synchronous (``CostAnalyzer``) and an asynchronous (``AsyncCostAnalyzer``)
variant are provided.  ``compute_cost_matrix`` is a shared module-level function
(pure pandas, no I/O) used by both.

V3 additions
------------
- :class:`WorkloadProfile` — parameterized client workload for TCO modeling.
- :func:`compute_tco` — monthly Total Cost of Ownership for a model + profile.
- :func:`compute_cer` — Cost-Efficiency Ratio (quality / TCO).
- :data:`BUILTIN_WORKLOAD_PROFILES` — four enterprise-representative profiles.

V4 additions
------------
- :func:`call_costs_to_dataframe` — one audit row for every OpenRouter call.
- :func:`summarize_actual_call_costs` — actual charged-cost aggregation based
    on OpenRouter's ``response.usage.cost``, never on a price estimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from src.api.openrouter_client import AsyncOpenRouterClient, CallCostRecord, OpenRouterClient

_ACTUAL_COST_SUMMARY_COLUMNS = [
    "model",
    "actual_cost_credits",
    "actual_cost_call_count",
    "actual_cost_reported_call_count",
    "actual_cost_missing_call_count",
    "actual_cost_coverage_rate",
    "actual_prompt_tokens",
    "actual_completion_tokens",
    "actual_total_tokens",
    "actual_latency_ms",
    "actual_model_mismatch_call_count",
]


def call_costs_to_dataframe(records: tuple[CallCostRecord, ...]) -> pd.DataFrame:
    """Convert an immutable OpenRouter call ledger into a DataFrame.

    Rows contain model IDs, generation IDs, token counts, actual charged
    credits and latency. They intentionally exclude prompt and response text.
    """
    columns = list(CallCostRecord.__dataclass_fields__)
    if not records:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([record.as_dict() for record in records], columns=columns)


def summarize_actual_call_costs(call_costs_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate authoritative OpenRouter call costs by requested model.

    ``actual_cost_coverage_rate`` distinguishes a real zero-cost response from
    an absent usage cost. A free model therefore has zero credits *and* 100%
    coverage, while missing provider cost metadata stays explicitly unknown.
    """
    if call_costs_df.empty or "requested_model" not in call_costs_df.columns:
        return pd.DataFrame(columns=_ACTUAL_COST_SUMMARY_COLUMNS)

    work_df = call_costs_df.copy()
    raw_costs = (
        work_df["actual_cost_credits"]
        if "actual_cost_credits" in work_df.columns
        else pd.Series(pd.NA, index=work_df.index)
    )
    cost_series = pd.to_numeric(raw_costs, errors="coerce")
    work_df["actual_cost_reported"] = cost_series.notna().astype("int32")
    work_df["actual_cost_credits_safe"] = cost_series.fillna(0.0)

    for column in ("prompt_tokens", "completion_tokens", "total_tokens", "latency_ms"):
        raw_values = work_df[column] if column in work_df.columns else pd.Series(pd.NA, index=work_df.index)
        work_df[column] = pd.to_numeric(raw_values, errors="coerce").fillna(0.0)

    if "resolved_model" in work_df.columns:
        work_df["model_mismatch"] = (
            work_df["resolved_model"].fillna(work_df["requested_model"]) != work_df["requested_model"]
        ).astype("int32")
    else:
        work_df["model_mismatch"] = 0

    summary_df = (
        work_df.groupby("requested_model", as_index=False)
        .agg(
            actual_cost_credits=("actual_cost_credits_safe", "sum"),
            actual_cost_call_count=("requested_model", "size"),
            actual_cost_reported_call_count=("actual_cost_reported", "sum"),
            actual_prompt_tokens=("prompt_tokens", "sum"),
            actual_completion_tokens=("completion_tokens", "sum"),
            actual_total_tokens=("total_tokens", "sum"),
            actual_latency_ms=("latency_ms", "sum"),
            actual_model_mismatch_call_count=("model_mismatch", "sum"),
        )
        .rename(columns={"requested_model": "model"})
    )
    summary_df["actual_cost_missing_call_count"] = (
        summary_df["actual_cost_call_count"] - summary_df["actual_cost_reported_call_count"]
    )
    summary_df["actual_cost_coverage_rate"] = (
        summary_df["actual_cost_reported_call_count"] / summary_df["actual_cost_call_count"]
    )
    return summary_df[_ACTUAL_COST_SUMMARY_COLUMNS].sort_values("model").reset_index(drop=True)


@dataclass(frozen=True)
class WorkloadProfile:
    """Parameterized client workload for monthly TCO computation."""

    name: str
    daily_requests: int
    avg_prompt_tokens: int
    avg_completion_tokens: int
    working_days_per_month: int = 22

    @property
    def monthly_prompt_tokens(self) -> int:
        return self.daily_requests * self.avg_prompt_tokens * self.working_days_per_month

    @property
    def monthly_completion_tokens(self) -> int:
        return self.daily_requests * self.avg_completion_tokens * self.working_days_per_month


BUILTIN_WORKLOAD_PROFILES: dict[str, WorkloadProfile] = {
    "enterprise_qa": WorkloadProfile("enterprise_qa", 500, 512, 256),
    "code_assistant": WorkloadProfile("code_assistant", 200, 1024, 512),
    "document_analysis": WorkloadProfile("document_analysis", 100, 4096, 512),
    "chatbot_high_volume": WorkloadProfile("chatbot_high_volume", 5000, 256, 128),
}


def compute_tco(
    model_id: str,
    pricing_df: pd.DataFrame,
    profile: WorkloadProfile,
) -> float:
    """Return the monthly Total Cost of Ownership (USD) for *model_id* under *profile*.

    Prices in *pricing_df* are per-token (as returned by OpenRouter's
    ``/api/v1/models`` endpoint).  The function converts them to per-million-token
    rates for the multiplication.

    Returns ``float("inf")`` when the model is absent from *pricing_df*.
    """
    if pricing_df.empty or "model_id" not in pricing_df.columns:
        return float("inf")
    row = pricing_df.loc[pricing_df["model_id"] == model_id]
    if row.empty:
        return float("inf")
    prompt_price: float = float(row["prompt_price_per_token"].iloc[0])
    completion_price: float = float(row["completion_price_per_token"].iloc[0])
    tco = profile.monthly_prompt_tokens * prompt_price + profile.monthly_completion_tokens * completion_price
    return round(tco, 6)


def compute_cer(quality_score: float, tco_usd: float) -> float:
    """Return the Cost-Efficiency Ratio (quality_score / tco_usd).

    Returns 0.0 when *tco_usd* is zero, infinite, or NaN to avoid division
    errors.  Callers should normalize across models by dividing by
    ``max(CER)`` of the benchmark run.
    """
    if tco_usd <= 0.0 or not math.isfinite(tco_usd):
        return 0.0
    return round(quality_score / tco_usd, 8)


@dataclass(frozen=True)
class UsageRecord:
    """Token-usage record for a single API call."""

    model: str
    prompt_tokens: int
    completion_tokens: int


def compute_cost_matrix(
    usage_log: list[UsageRecord],
    pricing_df: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate per-model aggregate costs from a list of usage records.

    Args:
        usage_log: Token usage data collected during benchmarking.
        pricing_df: Pricing table returned by :meth:`CostAnalyzer.fetch_pricing`
            or :meth:`AsyncCostAnalyzer.fetch_pricing`.

    Returns:
        DataFrame with columns: ``model``, ``prompt_tokens``,
        ``completion_tokens``, ``input_cost_usd``, ``output_cost_usd``,
        ``total_cost_usd``, ``requests``.
    """
    empty_cols = [
        "model",
        "prompt_tokens",
        "completion_tokens",
        "input_cost_usd",
        "output_cost_usd",
        "total_cost_usd",
        "requests",
    ]
    if not usage_log:
        return pd.DataFrame(columns=empty_cols)

    usage_df = pd.DataFrame(
        [
            {
                "model": r.model,
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
            }
            for r in usage_log
        ]
    )

    merged = usage_df.merge(
        pricing_df[["model_id", "prompt_price_per_token", "completion_price_per_token"]],
        left_on="model",
        right_on="model_id",
        how="left",
    ).fillna(0)

    merged["input_cost_usd"] = merged["prompt_tokens"] * merged["prompt_price_per_token"]
    merged["output_cost_usd"] = merged["completion_tokens"] * merged["completion_price_per_token"]
    merged["total_cost_usd"] = merged["input_cost_usd"] + merged["output_cost_usd"]

    return (
        merged.groupby("model", as_index=False)
        .agg(
            prompt_tokens=("prompt_tokens", "sum"),
            completion_tokens=("completion_tokens", "sum"),
            input_cost_usd=("input_cost_usd", "sum"),
            output_cost_usd=("output_cost_usd", "sum"),
            total_cost_usd=("total_cost_usd", "sum"),
            requests=("model", "count"),
        )
        .sort_values("total_cost_usd")
        .reset_index(drop=True)
    )


def _parse_pricing_rows(models: list[dict[str, object]]) -> list[dict[str, object]]:
    """Shared parsing logic for the /models endpoint response."""
    rows: list[dict[str, object]] = []
    for m in models:
        raw_pricing = m.get("pricing")
        pricing = raw_pricing if isinstance(raw_pricing, dict) else {}
        prompt_raw = pricing.get("prompt")
        completion_raw = pricing.get("completion")
        try:
            prompt_price = float(prompt_raw or 0)
            completion_price = float(completion_raw or 0)
        except (TypeError, ValueError):
            prompt_price = 0.0
            completion_price = 0.0

        context_length_raw = m.get("context_length")
        context_length = int(context_length_raw) if isinstance(context_length_raw, int | str) else 0

        rows.append(
            {
                "model_id": m.get("id", ""),
                "name": m.get("name", ""),
                "prompt_price_per_token": prompt_price,
                "completion_price_per_token": completion_price,
                "context_length": context_length,
            }
        )
    return rows


# ── Synchronous client ─────────────────────────────────────────────────────────


class CostAnalyzer:
    """Compute token cost matrices from live OpenRouter pricing data."""

    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    def fetch_pricing(self) -> pd.DataFrame:
        """Retrieve model pricing from OpenRouter's ``/api/v1/models`` endpoint."""
        models = self._client.get_models()
        return pd.DataFrame(_parse_pricing_rows(models))

    def compute_cost_matrix(
        self,
        usage_log: list[UsageRecord],
        pricing_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Delegate to the module-level :func:`compute_cost_matrix`."""
        return compute_cost_matrix(usage_log, pricing_df)


# ── Asynchronous client ────────────────────────────────────────────────────────


class AsyncCostAnalyzer:
    """Async variant of :class:`CostAnalyzer`."""

    def __init__(self, client: AsyncOpenRouterClient) -> None:
        self._client = client

    async def fetch_pricing(self) -> pd.DataFrame:
        """Async fetch of model pricing from ``/api/v1/models``."""
        models = await self._client.get_models()
        return pd.DataFrame(_parse_pricing_rows(models))

    def compute_cost_matrix(
        self,
        usage_log: list[UsageRecord],
        pricing_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Delegate to the module-level :func:`compute_cost_matrix`."""
        return compute_cost_matrix(usage_log, pricing_df)
