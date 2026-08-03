"""Cost analyser — fetches live pricing from OpenRouter and computes cost matrices.

Both a synchronous (``CostAnalyzer``) and an asynchronous (``AsyncCostAnalyzer``)
variant are provided.  ``compute_cost_matrix`` is a shared module-level function
(pure pandas, no I/O) used by both.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.api.openrouter_client import AsyncOpenRouterClient, OpenRouterClient


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
    _EMPTY_COLS = [
        "model",
        "prompt_tokens",
        "completion_tokens",
        "input_cost_usd",
        "output_cost_usd",
        "total_cost_usd",
        "requests",
    ]
    if not usage_log:
        return pd.DataFrame(columns=_EMPTY_COLS)

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
        pricing_df[
            ["model_id", "prompt_price_per_token", "completion_price_per_token"]
        ],
        left_on="model",
        right_on="model_id",
        how="left",
    ).fillna(0)

    merged["input_cost_usd"] = (
        merged["prompt_tokens"] * merged["prompt_price_per_token"]
    )
    merged["output_cost_usd"] = (
        merged["completion_tokens"] * merged["completion_price_per_token"]
    )
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
        pricing = m.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt") or 0)  # type: ignore[union-attr]
            completion_price = float(pricing.get("completion") or 0)  # type: ignore[union-attr]
        except (TypeError, ValueError):
            prompt_price = 0.0
            completion_price = 0.0

        rows.append(
            {
                "model_id": m.get("id", ""),
                "name": m.get("name", ""),
                "prompt_price_per_token": prompt_price,
                "completion_price_per_token": completion_price,
                "context_length": int(m.get("context_length") or 0),
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



@dataclass(frozen=True)
class UsageRecord:
    """Token-usage record for a single API call."""

    model: str
    prompt_tokens: int
    completion_tokens: int


class CostAnalyzer:
    """Compute token cost matrices from live OpenRouter pricing data."""

    def __init__(self, client: OpenRouterClient) -> None:
        self._client = client

    def fetch_pricing(self) -> pd.DataFrame:
        """Retrieve model pricing from OpenRouter's ``/api/v1/models`` endpoint.

        Returns:
            DataFrame with columns:
            - ``model_id`` (str)
            - ``name`` (str)
            - ``prompt_price_per_token`` (float, USD)
            - ``completion_price_per_token`` (float, USD)
            - ``context_length`` (int)
        """
        models = self._client.get_models()
        rows: list[dict[str, object]] = []

        for m in models:
            pricing = m.get("pricing") or {}
            try:
                prompt_price = float(pricing.get("prompt") or 0)
                completion_price = float(pricing.get("completion") or 0)
            except (TypeError, ValueError):
                prompt_price = 0.0
                completion_price = 0.0

            rows.append(
                {
                    "model_id": m.get("id", ""),
                    "name": m.get("name", ""),
                    "prompt_price_per_token": prompt_price,
                    "completion_price_per_token": completion_price,
                    "context_length": int(m.get("context_length") or 0),
                }
            )

        return pd.DataFrame(rows)

    def compute_cost_matrix(
        self,
        usage_log: list[UsageRecord],
        pricing_df: pd.DataFrame,
    ) -> pd.DataFrame:
        """Calculate per-request and aggregate costs for a list of usage records.

        Args:
            usage_log: Token usage data collected during benchmarking.
            pricing_df: Pricing table returned by :meth:`fetch_pricing`.

        Returns:
            DataFrame with columns:
            - ``model`` — model identifier
            - ``prompt_tokens`` — total input tokens
            - ``completion_tokens`` — total output tokens
            - ``input_cost_usd`` — total input cost in USD
            - ``output_cost_usd`` — total output cost in USD
            - ``total_cost_usd`` — combined cost in USD
            - ``requests`` — number of API calls
        """
        if not usage_log:
            return pd.DataFrame(
                columns=[
                    "model",
                    "prompt_tokens",
                    "completion_tokens",
                    "input_cost_usd",
                    "output_cost_usd",
                    "total_cost_usd",
                    "requests",
                ]
            )

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

        # Join pricing; models not found in pricing get zero cost.
        merged = usage_df.merge(
            pricing_df[
                ["model_id", "prompt_price_per_token", "completion_price_per_token"]
            ],
            left_on="model",
            right_on="model_id",
            how="left",
        ).fillna(0)

        merged["input_cost_usd"] = (
            merged["prompt_tokens"] * merged["prompt_price_per_token"]
        )
        merged["output_cost_usd"] = (
            merged["completion_tokens"] * merged["completion_price_per_token"]
        )
        merged["total_cost_usd"] = merged["input_cost_usd"] + merged["output_cost_usd"]

        result = (
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

        return result
