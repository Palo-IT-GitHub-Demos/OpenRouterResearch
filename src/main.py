"""LLMOps evaluation pipeline — entry point.

V2 adds :class:`AsyncPipeline` which runs all three evaluation stages
concurrently via ``asyncio.gather`` and integrates MLflow tracking.

Usage:
    python -m src.main
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from src.api.fake_client import FakeAsyncOpenRouterClient
from src.api.openrouter_client import (
    AsyncOpenRouterClient,
    OpenRouterClient,
    OpenRouterError,
)
from src.core.config import Settings, get_settings
from src.evaluators.cost_analyzer import (
    BUILTIN_WORKLOAD_PROFILES,
    AsyncCostAnalyzer,
    CostAnalyzer,
    call_costs_to_dataframe,
    summarize_actual_call_costs,
)
from src.evaluators.quality_judge import (
    AsyncQualityJudge,
    CollectResult,
    load_quality_prompts,
    quality_suite_id,
)
from src.evaluators.quality_metrics import summarize_quality_scores
from src.evaluators.security_scanner import AsyncSecurityScanner, SecurityScanner, probe_count
from src.observability.tracker import ExperimentTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_RESULTS_DIR = Path("results")
_INTERMEDIATE_DIR = Path("data/intermediate")
_QUALITY_PROMPTS = Path("data/prompts/quality_prompts.json")
_DRY_RUN_DIR = Path("data/dry_run")
_MIN_QUALITY_COVERAGE_FOR_CER = 0.8
_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
_MAX_INTERMEDIATE_FILE_BYTES = 100 * 1024 * 1024  # 100 MB — warn, do not block

# OpenRouter free-tier (":free" model) caps per account, not per key — verified
# 2026-08-21 against https://openrouter.ai/docs/api-reference/limits.
_FREE_TIER_RPD_NO_CREDITS = 50
_FREE_TIER_RPD_WITH_CREDITS = 1000


def _warn_on_empty_stage(name: str, df: pd.DataFrame) -> None:
    """Log a visible warning when a pipeline stage returned no data.

    Stages return an empty DataFrame on failure so the pipeline can continue;
    without this warning that fallback is silent and downstream merges show
    NaN/missing values with no indication of why.
    """
    if df.empty:
        logger.warning(
            "[%s] Stage returned no data — downstream results will have "
            "missing/NaN values for this axis. Check the error above.",
            name,
        )


def _unknown_target_models(models: list[str], pricing_df: pd.DataFrame) -> list[str]:
    """Return TARGET_MODELS entries absent from the live OpenRouter catalog.

    Every call against an unknown or deprecated model ID (e.g. a stale
    ``:free`` slug) fails, but that failure is otherwise indistinguishable
    from a transient transport error inside ``collection_errors``/probe
    errors. Surfacing it separately gives a precise, actionable diagnostic
    instead of a generic error-rate-exceeded message.
    """
    if pricing_df.empty or "model_id" not in pricing_df.columns:
        return []
    known = set(pricing_df["model_id"])
    return [m for m in models if m not in known]


def _estimate_free_tier_request_volume(
    models: list[str],
    *,
    quality_prompt_count: int,
    quality_repetitions: int,
    security_probe_count: int,
) -> int:
    """Return the planned request count against ``:free``-suffixed models.

    OpenRouter's daily rate-limit cap for free-tier accounts applies to calls
    made to ``:free`` model variants specifically (see
    ``_FREE_TIER_RPD_NO_CREDITS``), not to the account's overall call volume.
    """
    free_model_count = sum(1 for m in models if m.endswith(":free"))
    if free_model_count == 0:
        return 0
    return free_model_count * (quality_prompt_count * quality_repetitions + security_probe_count)


def _warn_on_free_tier_request_volume(estimated_requests: int) -> None:
    """Log a preflight warning when a run risks exceeding the free-tier cap."""
    if estimated_requests > _FREE_TIER_RPD_NO_CREDITS:
        logger.warning(
            "[preflight] This run is estimated to send %d requests to ':free' "
            "models — above OpenRouter's %d/day cap for accounts with <10 USD "
            "lifetime credits (https://openrouter.ai/docs/api-reference/limits). "
            "Buy >=10 USD credits to raise the cap to %d/day, or reduce "
            "TARGET_MODELS / QUALITY_REPETITIONS / the security probe set.",
            estimated_requests,
            _FREE_TIER_RPD_NO_CREDITS,
            _FREE_TIER_RPD_WITH_CREDITS,
        )


def _security_probe_count_for_estimate(probes_path: Path | None) -> int:
    """Return the probe count for the preflight estimate, or 0 if unreadable.

    The security stage itself raises a clear, dedicated error for a bad
    ``SECURITY_PROBES_PATH`` — this estimate must not duplicate or mask that.
    """
    try:
        return probe_count(probes_path)
    except (OSError, ValueError):
        return 0


# ── V1 synchronous pipeline (kept for backward compat) ────────────────────────


class Pipeline:
    """Synchronous pipeline — preserved for tests and offline use."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = OpenRouterClient(self._settings)

    def run(self) -> pd.DataFrame:
        models = self._settings.target_models_list
        logger.info("Starting benchmark for %d model(s): %s", len(models), models)

        with self._client:
            pricing_df = self._run_cost_stage(models)
            quality_df = self._run_quality_stage(models)
            security_df = self._run_security_stage(models, pricing_df)
            actual_call_costs = call_costs_to_dataframe(self._client.call_costs)

        result = _merge_results(
            models,
            pricing_df,
            quality_df,
            security_df,
            actual_call_costs=actual_call_costs,
        )
        _export(result, actual_call_costs)
        return result

    def _run_cost_stage(self, models: list[str]) -> pd.DataFrame:
        logger.info("[1/3] Fetching pricing data …")
        analyzer = CostAnalyzer(self._client)
        try:
            return analyzer.fetch_pricing()
        except OpenRouterError as exc:
            logger.error("Cost stage failed: %s", exc)
            return pd.DataFrame()

    def _run_quality_stage(self, models: list[str]) -> pd.DataFrame:
        # V1 sync pipeline — quality scoring via LLM judge removed.
        # Use CollectPipeline + a Copilot judge agent + MergePipeline instead.
        logger.info("[quality] Skipping — use Copilot judge agents " "(make collect / make judge / make merge).")
        return pd.DataFrame()

    def _run_security_stage(self, models: list[str], pricing_df: pd.DataFrame) -> pd.DataFrame:
        logger.info("[3/3] Running security scans …")
        scanner = SecurityScanner(self._client)
        try:
            return scanner.run_full_scan(models=models, pricing_df=pricing_df)
        except OpenRouterError as exc:
            logger.error("Security stage failed: %s", exc)
            return pd.DataFrame()


# ── V2 asynchronous pipeline ───────────────────────────────────────────────────


class AsyncPipeline:
    """Async pipeline — runs cost, quality, and security stages concurrently.

    Not wired to the CLI (`main()` only dispatches `CollectPipeline` /
    `MergePipeline` / `DryRunPipeline`) — the 3-phase split superseded this
    single-call pipeline once quality judging moved to blind Copilot agents.
    Kept for programmatic/notebook use where an OpenRouter-only judge is
    acceptable; has no dedicated test coverage.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tracker = ExperimentTracker(
            tracking_uri=self._settings.mlflow_tracking_uri,
        )

    async def run(self) -> pd.DataFrame:
        """Execute all stages concurrently and return the merged results DataFrame."""
        models = self._settings.target_models_list
        timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
        logger.info("Starting async benchmark for %d model(s): %s", len(models), models)

        self._tracker.start_run(f"benchmark-{timestamp}")
        try:
            async with AsyncOpenRouterClient(self._settings) as client:
                pricing_df, quality_df, security_df = await asyncio.gather(
                    self._run_cost_stage(client),
                    self._run_quality_stage(client, models),
                    self._run_security_stage(client, models),
                )
                actual_call_costs = call_costs_to_dataframe(client.call_costs)

            _warn_on_empty_stage("cost", pricing_df)
            _warn_on_empty_stage("quality", quality_df)
            _warn_on_empty_stage("security", security_df)

            prompt_count, dimension_count, suite_id = _quality_screen_metadata(_QUALITY_PROMPTS)
            result = _merge_results(
                models,
                pricing_df,
                quality_df,
                security_df,
                self._settings.workload_profile,
                quality_prompt_count=prompt_count,
                quality_dimension_count=dimension_count,
                quality_repetitions=self._settings.quality_repetitions,
                quality_suite_id=suite_id,
                actual_call_costs=actual_call_costs,
            )
            self._log_results(result, quality_df, security_df)
            self._tracker.log_dataframe("benchmark_results", result)
            if not actual_call_costs.empty:
                self._tracker.log_dataframe("actual_call_costs", actual_call_costs)
            _export(result, actual_call_costs)
            return result
        finally:
            self._tracker.end_run()

    # ── Private stages ─────────────────────────────────────────────────────────

    async def _run_cost_stage(self, client: AsyncOpenRouterClient) -> pd.DataFrame:
        logger.info("[cost] Fetching pricing data …")
        analyzer = AsyncCostAnalyzer(client)
        try:
            df = await analyzer.fetch_pricing()
            logger.info("[cost] Pricing fetched for %d models.", len(df))
            return df
        except OpenRouterError as exc:
            logger.error("[cost] Stage failed: %s", exc)
            return pd.DataFrame()

    async def _run_quality_stage(self, client: AsyncOpenRouterClient, models: list[str]) -> pd.DataFrame:
        logger.info("[quality] Running deterministic evaluation …")
        if not _QUALITY_PROMPTS.exists():
            logger.warning("[quality] No prompts file found at '%s'; skipping.", _QUALITY_PROMPTS)
            return pd.DataFrame()
        judge = AsyncQualityJudge(client)
        try:
            df = await judge.run_dataset(
                _QUALITY_PROMPTS,
                models,
                repetitions=self._settings.quality_repetitions,
            )
            logger.info(
                "[quality] Evaluation complete — %d deterministic scores recorded.",
                len(df),
            )
            return df
        except (OpenRouterError, ValueError) as exc:
            logger.error("[quality] Stage failed: %s", exc)
            return pd.DataFrame()

    async def _run_security_stage(self, client: AsyncOpenRouterClient, models: list[str]) -> pd.DataFrame:
        logger.info("[security] Running security scans …")
        probes_path = Path(self._settings.security_probes_path) if self._settings.security_probes_path else None
        scanner = AsyncSecurityScanner(client, probes_path=probes_path)
        try:
            df = await scanner.run_full_scan(models=models)
            logger.info("[security] Scan complete — %d models scanned.", len(df))
            return df
        except OpenRouterError as exc:
            logger.error("[security] Stage failed: %s", exc)
            return pd.DataFrame()

    # ── MLflow logging ─────────────────────────────────────────────────────────

    def _log_results(
        self,
        result: pd.DataFrame,
        quality_df: pd.DataFrame,
        security_df: pd.DataFrame,
    ) -> None:
        if not quality_df.empty and "model" in quality_df.columns:
            for _, row in quality_df.iterrows():
                self._tracker.log_quality_score(
                    str(row["model"]),
                    int(row.get("prompt_id", 0)),
                    float(row["score"]),
                )

        if not security_df.empty:
            for _, row in security_df.iterrows():
                self._tracker.log_security_result(
                    str(row["model"]),
                    int(row.get("leak_count", 0)),
                    bool(row.get("is_vulnerable", False)),
                )


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _merge_results(
    models: list[str],
    pricing_df: pd.DataFrame,
    quality_df: pd.DataFrame,
    security_df: pd.DataFrame,
    workload_profile_name: str = "enterprise_qa",
    quality_prompt_count: int | None = None,
    quality_dimension_count: int | None = None,
    quality_repetitions: int = 1,
    quality_collection_errors: pd.DataFrame | None = None,
    quality_suite_id: str | None = None,
    actual_call_costs: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Merge quality, security and pricing outputs into a decision matrix.

    Quality is macro-averaged across generic screen dimensions. The resulting
    cost-efficiency ratio is only eligible when at least 80% of the configured
    screen prompts were scored, avoiding false precision from partial runs.
    """
    base = pd.DataFrame({"model": models})

    if not quality_df.empty and "score" in quality_df.columns:
        quality_summary = summarize_quality_scores(
            quality_df,
            expected_prompt_count=quality_prompt_count,
        )
        base = base.merge(quality_summary, on="model", how="left")

    if quality_collection_errors is not None and not quality_collection_errors.empty:
        error_summary = (
            quality_collection_errors.groupby("model", as_index=False)
            .size()
            .rename(columns={"size": "quality_collection_error_count"})
        )
        base = base.merge(error_summary, on="model", how="left")

    base["quality_collection_error_count"] = base.get("quality_collection_error_count", 0)
    base["quality_collection_error_count"] = base["quality_collection_error_count"].fillna(0).astype("int32")
    if quality_prompt_count is not None and quality_prompt_count > 0:
        expected_attempts = quality_prompt_count * quality_repetitions
        base["quality_collection_success_rate"] = (
            1.0 - base["quality_collection_error_count"] / expected_attempts
        ).clip(lower=0.0, upper=1.0)

    if quality_dimension_count is not None and quality_dimension_count > 0:
        observed_dimension_count = (
            base["quality_dimension_count"]
            if "quality_dimension_count" in base.columns
            else pd.Series(0.0, index=base.index)
        )
        base["quality_dimension_coverage_rate"] = (observed_dimension_count / quality_dimension_count).clip(
            lower=0.0, upper=1.0
        )

    if quality_suite_id:
        base["quality_suite_id"] = quality_suite_id

    if actual_call_costs is not None and not actual_call_costs.empty:
        base = base.merge(summarize_actual_call_costs(actual_call_costs), on="model", how="left")

    if not security_df.empty:
        _wanted = ["model", "leak_count", "is_vulnerable", "zero_data_retention", "rsi", "probe_details"]
        sec_cols = [c for c in _wanted if c in security_df.columns]
        base = base.merge(security_df[sec_cols], on="model", how="left")

    if not pricing_df.empty and "model_id" in pricing_df.columns:
        target_pricing = pricing_df[pricing_df["model_id"].isin(models)][
            [
                "model_id",
                "prompt_price_per_token",
                "completion_price_per_token",
                "context_length",
            ]
        ].rename(columns={"model_id": "model"})
        base = base.merge(target_pricing, on="model", how="left")

    # ── TCO & CER ─────────────────────────────────────────────────────────────
    profile = BUILTIN_WORKLOAD_PROFILES.get(workload_profile_name)
    if profile is not None and not pricing_df.empty and "model_id" in pricing_df.columns:
        input_price = pd.to_numeric(base["prompt_price_per_token"], errors="coerce")
        completion_price = pd.to_numeric(base["completion_price_per_token"], errors="coerce")
        has_pricing = input_price.notna() & completion_price.notna()
        base["tco_usd"] = (
            input_price * profile.monthly_prompt_tokens + completion_price * profile.monthly_completion_tokens
        ).where(has_pricing, float("inf"))

        quality_col = "avg_quality_score"
        if quality_col in base.columns:
            coverage = (
                pd.to_numeric(base["quality_coverage_rate"], errors="coerce").fillna(1.0)
                if "quality_coverage_rate" in base.columns
                else pd.Series(1.0, index=base.index)
            )
            dimension_coverage = (
                pd.to_numeric(base["quality_dimension_coverage_rate"], errors="coerce").fillna(1.0)
                if "quality_dimension_coverage_rate" in base.columns
                else pd.Series(1.0, index=base.index)
            )
            base["quality_cer_eligible"] = (
                base[quality_col].notna() & (coverage >= _MIN_QUALITY_COVERAGE_FOR_CER) & (dimension_coverage >= 1.0)
            )
            raw_cer = (
                (base[quality_col].where(base["quality_cer_eligible"], 0.0).fillna(0.0) / base["tco_usd"])
                .replace([float("inf"), -float("inf")], 0.0)
                .fillna(0.0)
            )
            max_cer = raw_cer.max()
            base["cer"] = (raw_cer / max_cer).round(4) if max_cer > 0 else raw_cer

        base["workload_profile"] = workload_profile_name

    return base


def _export(df: pd.DataFrame, actual_call_costs: pd.DataFrame | None = None) -> None:
    """Export summary results and, when available, the per-call cost ledger."""
    _RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    stem = _RESULTS_DIR / f"benchmark_{timestamp}"
    df.to_csv(f"{stem}.csv", index=False)
    df.to_json(f"{stem}.json", orient="records", indent=2)
    logger.info("Results exported to '%s.{csv,json}'", stem)
    if actual_call_costs is not None and not actual_call_costs.empty:
        call_costs_dir = _RESULTS_DIR / "call_costs"
        call_costs_dir.mkdir(exist_ok=True)
        call_costs_stem = call_costs_dir / f"benchmark_{timestamp}_call_costs"
        actual_call_costs.to_csv(f"{call_costs_stem}.csv", index=False)
        actual_call_costs.to_json(f"{call_costs_stem}.json", orient="records", indent=2)
        logger.info("Actual call-cost ledger exported to '%s.{csv,json}'", call_costs_stem)


def _quality_screen_metadata(prompts_path: Path) -> tuple[int | None, int | None, str | None]:
    """Return prompt/dimension counts and a suite ID when the fixture is valid."""
    if not prompts_path.exists():
        return None, None, None
    try:
        prompts = load_quality_prompts(prompts_path)
        dimension_count = len({prompt.quality_dimension for prompt in prompts})
        return len(prompts), dimension_count, quality_suite_id(prompts_path)
    except ValueError as exc:
        logger.warning("Could not read quality screen metadata: %s", exc)
        return None, None, None


def _enforce_collect_error_budget(
    collect_result: CollectResult,
    security_df: pd.DataFrame,
    *,
    model_count: int,
    max_quality_collection_error_rate: float,
    max_security_probe_error_rate: float,
) -> None:
    """Stop a run when transport/probe failures exceed configured thresholds."""
    if collect_result.prompt_count > 0 and model_count > 0 and collect_result.repetitions > 0:
        expected_quality_attempts = collect_result.prompt_count * model_count * collect_result.repetitions
    else:
        expected_quality_attempts = 0

    if expected_quality_attempts > 0:
        quality_error_rate = len(collect_result.collection_errors) / expected_quality_attempts
        if quality_error_rate > max_quality_collection_error_rate:
            raise ValueError(
                "[quality] Collection error budget exceeded: "
                f"{quality_error_rate:.2%} > {max_quality_collection_error_rate:.2%}. "
                "Fix upstream transport/provider instability before continuing."
            )

    if security_df.empty:
        raise ValueError("[security] Stage produced no rows; refusing to continue with an unvalidated security axis.")

    if "probe_count" in security_df.columns and "probe_error_count" in security_df.columns:
        probe_count = int(pd.to_numeric(security_df["probe_count"], errors="coerce").fillna(0).sum())
        probe_error_count = int(pd.to_numeric(security_df["probe_error_count"], errors="coerce").fillna(0).sum())
        if probe_count > 0:
            security_probe_error_rate = probe_error_count / probe_count
            if security_probe_error_rate > max_security_probe_error_rate:
                raise ValueError(
                    "[security] Probe error budget exceeded: "
                    f"{security_probe_error_rate:.2%} > {max_security_probe_error_rate:.2%}. "
                    "Fix probe/model transport failures before continuing."
                )


# ── Split pipeline helpers ─────────────────────────────────────────────────────


def _save_pending(
    models: list[str],
    pricing_df: pd.DataFrame,
    security_df: pd.DataFrame,
    collect_result: CollectResult,
    actual_call_costs: pd.DataFrame,
) -> Path:
    """Persist intermediate data to ``data/intermediate/pending_{ts}.json``.

    Also writes a **blind** ``judging_{ts}.json`` without ``alias_map`` so
    Copilot judge agents cannot identify which company made each response.
    """
    _INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)
    path = _INTERMEDIATE_DIR / f"pending_{timestamp}.json"

    payload = {
        "timestamp": timestamp,
        "models": models,
        "pricing": pricing_df.to_dict(orient="records") if not pricing_df.empty else [],
        "security": security_df.to_dict(orient="records") if not security_df.empty else [],
        "actual_call_costs": actual_call_costs.to_dict(orient="records") if not actual_call_costs.empty else [],
        "deterministic_scores": collect_result.deterministic_rows,
        "quality_collection_errors": collect_result.collection_errors,
        "quality_metadata": {
            "prompt_count": collect_result.prompt_count,
            "dimension_count": collect_result.dimension_count,
            "repetitions": collect_result.repetitions,
            "suite_id": collect_result.quality_suite_id,
        },
        "pending_judgments": collect_result.pending_judgments,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    size_bytes = path.stat().st_size
    if size_bytes > _MAX_INTERMEDIATE_FILE_BYTES:
        logger.warning(
            "Intermediate file '%s' is %.1f MB (> %.0f MB) — consider reducing "
            "TARGET_MODELS, quality prompt count, or QUALITY_REPETITIONS to avoid disk pressure.",
            path,
            size_bytes / (1024 * 1024),
            _MAX_INTERMEDIATE_FILE_BYTES / (1024 * 1024),
        )
    logger.info("Intermediate file saved → '%s'", path)

    # ── Blind judging file (no alias_map) ──────────────────────────────────────
    judging_path = _INTERMEDIATE_DIR / f"judging_{timestamp}.json"
    judging_payload = {
        "timestamp": timestamp,
        "pending_judgments": [
            {
                "prompt_id": pj["prompt_id"],
                "prompt": pj["prompt"],
                "attempt": pj.get("attempt", 0),
                "quality_dimension": pj.get("quality_dimension", "legacy"),
                "weight": pj.get("weight", 1.0),
                "judge_criteria": pj.get("judge_criteria", []),
                "reference_answer": pj.get("reference_answer"),
                "prompt_preview": pj.get("prompt_preview", ""),
                "category": pj.get("category"),
                "responses": pj["responses"],
                # alias_map intentionally omitted — blind evaluation
            }
            for pj in collect_result.pending_judgments
        ],
    }
    judging_path.write_text(json.dumps(judging_payload, indent=2, ensure_ascii=False))
    logger.info("Blind judging file saved → '%s'", judging_path)

    return path


def _latest_file(directory: Path, pattern: str) -> Path | None:
    """Return the most recently modified file matching *pattern* in *directory*."""
    files = sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ── Phase 1: CollectPipeline ───────────────────────────────────────────────────


class CollectPipeline:
    """Phase 1 — collect responses + deterministic eval + security + pricing.

    No LLM judge calls.  Saves ``data/intermediate/pending_{ts}.json`` for
    Phase 2 (Copilot judge) and Phase 3 (merge).
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def run(self) -> Path:
        models = self._settings.target_models_list
        logger.info("Phase 1 — collecting from %d model(s): %s", len(models), models)

        prompt_count, _dimension_count, _suite_id = _quality_screen_metadata(_QUALITY_PROMPTS)
        probes_path = Path(self._settings.security_probes_path) if self._settings.security_probes_path else None
        estimated_free_tier_requests = _estimate_free_tier_request_volume(
            models,
            quality_prompt_count=prompt_count or 0,
            quality_repetitions=self._settings.quality_repetitions,
            security_probe_count=_security_probe_count_for_estimate(probes_path),
        )
        _warn_on_free_tier_request_volume(estimated_free_tier_requests)

        async with AsyncOpenRouterClient(self._settings) as client:
            pricing_df, security_df, collect_result = await asyncio.gather(
                self._run_cost_stage(client),
                self._run_security_stage(client, models),
                self._run_quality_collect(client, models),
            )
            actual_call_costs = call_costs_to_dataframe(client.call_costs)

        _warn_on_empty_stage("cost", pricing_df)
        _warn_on_empty_stage("security", security_df)

        unknown_models = _unknown_target_models(models, pricing_df)
        if unknown_models:
            logger.error(
                "[cost] %d model ID(s) in TARGET_MODELS were not found in the live "
                "OpenRouter catalog — every call to them will fail: %s. Check "
                "https://openrouter.ai/models for the current slug; free-tier "
                "variants are sometimes renamed or discontinued.",
                len(unknown_models),
                unknown_models,
            )

        if not collect_result.deterministic_rows and not collect_result.pending_judgments:
            logger.warning(
                "[quality] No deterministic scores or pending judgments collected — "
                "check TARGET_MODELS and data/prompts/quality_prompts.json."
            )

        _enforce_collect_error_budget(
            collect_result,
            security_df,
            model_count=len(models),
            max_quality_collection_error_rate=self._settings.max_quality_collection_error_rate,
            max_security_probe_error_rate=self._settings.max_security_probe_error_rate,
        )

        pending_path = _save_pending(
            models=models,
            pricing_df=pricing_df,
            security_df=security_df,
            collect_result=collect_result,
            actual_call_costs=actual_call_costs,
        )

        n_det = len(collect_result.deterministic_rows)
        n_pend = len(collect_result.pending_judgments)
        n_errs = len(collect_result.collection_errors)
        logger.info(
            "Deterministic scores: %d  |  Pending judgments: %d  |  Collection errors: %d  |  Cost records: %d",
            n_det,
            n_pend,
            n_errs,
            len(actual_call_costs),
        )

        # ── Fail-fast gate: collection error budget ────────────────────────────────────────
        total_quality_attempts = len(collect_result.deterministic_rows) + n_pend + n_errs
        if total_quality_attempts > 0:
            error_rate = n_errs / total_quality_attempts
            max_allowed = self._settings.max_quality_collection_error_rate
            if error_rate > max_allowed:
                raise ValueError(
                    f"[quality] ABORT: error rate {error_rate:.1%} exceeds threshold {max_allowed:.1%} "
                    f"({n_errs} errors in {total_quality_attempts} attempts). "
                    f"Run is too degraded for reliable evaluation."
                )
            logger.info(f"[quality] Error rate {error_rate:.1%} within budget (max {max_allowed:.1%})")

        if n_pend > 0:
            logger.info("Next: run judge-benchmark prompt in Copilot, then: make merge")
        else:
            logger.info("All scores are deterministic — run: make merge")

        return pending_path

    async def _run_cost_stage(self, client: AsyncOpenRouterClient) -> pd.DataFrame:
        logger.info("[cost] Fetching pricing data …")
        try:
            df = await AsyncCostAnalyzer(client).fetch_pricing()
            logger.info("[cost] Pricing fetched for %d models.", len(df))
            return df
        except OpenRouterError as exc:
            logger.error("[cost] Failed: %s", exc)
            return pd.DataFrame()

    async def _run_security_stage(self, client: AsyncOpenRouterClient, models: list[str]) -> pd.DataFrame:
        logger.info("[security] Scanning %d models …", len(models))
        probes_path = Path(self._settings.security_probes_path) if self._settings.security_probes_path else None
        try:
            df = await AsyncSecurityScanner(client, probes_path=probes_path).run_full_scan(models)
            logger.info("[security] Scan complete — %d models scanned.", len(df))
            return df
        except OpenRouterError as exc:
            logger.error("[security] Failed: %s", exc)
            return pd.DataFrame()

    async def _run_quality_collect(self, client: AsyncOpenRouterClient, models: list[str]) -> CollectResult:
        logger.info("[quality] Collecting responses (no LLM judge) …")
        if not _QUALITY_PROMPTS.exists():
            logger.warning("[quality] No prompts file at '%s'; skipping.", _QUALITY_PROMPTS)
            return CollectResult()
        judge = AsyncQualityJudge(client)
        try:
            result = await judge.run_collect(
                _QUALITY_PROMPTS,
                models,
                repetitions=self._settings.quality_repetitions,
            )
            logger.info(
                "[quality] Collected: %d deterministic, %d pending judgment(s), %d collection error(s).",
                len(result.deterministic_rows),
                len(result.pending_judgments),
                len(result.collection_errors),
            )
            return result
        except OpenRouterError as exc:
            logger.error("[quality] Collection failed: %s", exc)
            return CollectResult()


# ── Phase 3: MergePipeline ─────────────────────────────────────────────────────


class MergePipeline:
    """Phase 3 — merge Copilot scores + deterministic scores + security + pricing.

    Reads ``data/intermediate/pending_{ts}.json`` (written by Phase 1) and
    ``data/intermediate/scores_{ts}.json`` (written by Copilot Phase 2), then
    produces the final benchmark DataFrame and exports it to ``results/``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tracker = ExperimentTracker(
            tracking_uri=self._settings.mlflow_tracking_uri,
        )

    def run(
        self,
        pending_path: Path | None = None,
        scores_path: Path | None = None,
    ) -> pd.DataFrame:
        pending_path = pending_path or _latest_file(_INTERMEDIATE_DIR, "pending_*.json")
        if pending_path is None:
            raise FileNotFoundError("No pending_*.json found in data/intermediate/. " "Run 'make collect' first.")

        logger.info("Phase 3 — loading intermediate data from '%s'", pending_path)
        pending = json.loads(pending_path.read_text())

        models: list[str] = pending["models"]
        pricing_df = pd.DataFrame(pending.get("pricing", []))
        security_df = pd.DataFrame(pending.get("security", []))
        actual_call_costs = pd.DataFrame(pending.get("actual_call_costs", []))
        timestamp: str = pending["timestamp"]

        quality_df = self._rebuild_quality_df(pending, scores_path)
        pending_judgments = cast(list[dict[str, object]], pending.get("pending_judgments", []))
        if pending_judgments and quality_df.empty:
            logger.error(
                "[quality] %d pending judgment(s) were never scored — no scores_*.json "
                "matched timestamp '%s'. Quality metrics will be missing for this run. "
                "Run a Copilot judge agent (@judge-anthropic / @judge-openai / @judge-google "
                "or @judge-coordinator), then re-run 'make merge'.",
                len(pending_judgments),
                timestamp,
            )
            raise ValueError(
                "Missing Copilot judge scores for pending judgments. "
                "Run @judge-coordinator (or all three judge agents) before merge."
            )

        if pending_judgments:
            expected_pending_keys = {
                (int(str(item["prompt_id"])), int(str(item.get("attempt", 0)))) for item in pending_judgments
            }
            scored_pending_keys = {
                (int(row["prompt_id"]), int(row["attempt"]))
                for _, row in quality_df.iterrows()
                if (
                    int(row.get("prompt_id", -1)),
                    int(row.get("attempt", 0)),
                )
                in expected_pending_keys
            }
            missing_pending_keys = expected_pending_keys - scored_pending_keys
            if missing_pending_keys:
                raise ValueError(
                    "Missing Copilot judge scores for some pending prompts/attempts: "
                    f"{sorted(missing_pending_keys)}."
                )

        quality_metadata = cast(dict[str, object], pending.get("quality_metadata", {}))
        prompt_count_raw = quality_metadata.get("prompt_count")
        prompt_count = prompt_count_raw if isinstance(prompt_count_raw, int) else None
        dimension_count_raw = quality_metadata.get("dimension_count")
        dimension_count = dimension_count_raw if isinstance(dimension_count_raw, int) else None
        repetitions_raw = quality_metadata.get("repetitions", 1)
        repetitions = repetitions_raw if isinstance(repetitions_raw, int) else 1
        suite_id_raw = quality_metadata.get("suite_id")
        suite_id = suite_id_raw if isinstance(suite_id_raw, str) else None
        collection_errors = pd.DataFrame(pending.get("quality_collection_errors", []))

        result = _merge_results(
            models,
            pricing_df,
            quality_df,
            security_df,
            self._settings.workload_profile,
            quality_prompt_count=prompt_count,
            quality_dimension_count=dimension_count,
            quality_repetitions=repetitions,
            quality_collection_errors=collection_errors,
            quality_suite_id=suite_id,
            actual_call_costs=actual_call_costs,
        )

        self._tracker.start_run(f"benchmark-{timestamp}")
        try:
            self._log_results(result, quality_df, security_df)
            self._tracker.log_dataframe("benchmark_results", result)
            if not actual_call_costs.empty:
                self._tracker.log_dataframe("actual_call_costs", actual_call_costs)
        finally:
            self._tracker.end_run()

        _export(result, actual_call_costs)
        return result

    @staticmethod
    def _rebuild_quality_df(pending: dict[str, object], scores_path: Path | None) -> pd.DataFrame:
        """Combine deterministic rows + Copilot judge scores into a quality DataFrame.

        Loads ALL ``scores_*_{judge}.json`` files whose internal ``timestamp``
        matches the pending file. Scores from different judges are averaged per
        ``(prompt_id, attempt, model)``; recused models (absent from a judge's
        file) are simply excluded from that judge's contribution to the average.
        """
        rows = list(cast(list[dict[str, object]], pending.get("deterministic_scores", [])))
        pending_judgments = cast(
            list[dict[str, object]],
            pending.get("pending_judgments", []),
        )
        timestamp: str = str(pending.get("timestamp", ""))

        if pending_judgments:
            # Collect all scores files for this run (multi-judge support).
            # Priority order: explicit path > all files matching the run timestamp.
            scores_files: list[Path] = []
            if scores_path is not None:
                scores_files = [scores_path]
            else:
                # Load every scores_*.json whose internal timestamp matches.
                for sf in sorted(_INTERMEDIATE_DIR.glob("scores_*.json")):
                    try:
                        data = json.loads(sf.read_text())
                        if data.get("timestamp") == timestamp:
                            scores_files.append(sf)
                    except Exception:  # noqa: BLE001
                        pass
                # Backward compat: also check the legacy single-file pattern.
                if not scores_files:
                    legacy = _latest_file(_INTERMEDIATE_DIR, "scores_*.json")
                    if legacy:
                        scores_files = [legacy]

            if not scores_files:
                logger.warning(
                    "No scores files found for timestamp '%s' — pending "
                    "judgments skipped. Run a Copilot judge agent "
                    "(@judge-anthropic / @judge-openai / @judge-google).",
                    timestamp,
                )
            else:
                logger.info(
                    "Loading scores from %d file(s): %s",
                    len(scores_files),
                    [sf.name for sf in scores_files],
                )

                # Accumulate scores per (prompt_id, attempt, model_id) across judges.
                # Recused models are simply absent from a judge's file.
                score_pool: dict[tuple[int, int, str], list[int]] = {}
                reasoning_pool: dict[tuple[int, int, str], list[str]] = {}
                source_pool: dict[tuple[int, int, str], list[str]] = {}
                pending_metadata: dict[tuple[int, int], dict[str, object]] = {
                    (int(str(pj["prompt_id"])), int(str(pj.get("attempt", 0)))): {
                        "prompt_preview": str(pj.get("prompt_preview", "")),
                        "category": str(pj.get("category", "legacy")),
                        "quality_dimension": str(pj.get("quality_dimension", "legacy")),
                        "weight": pj.get("weight", 1.0),
                    }
                    for pj in pending_judgments
                }
                alias_maps: dict[tuple[int, int], dict[str, str]] = {
                    (int(str(pj["prompt_id"])), int(str(pj.get("attempt", 0)))): cast(dict[str, str], pj["alias_map"])
                    for pj in pending_judgments
                }

                for sf in scores_files:
                    scores_data = json.loads(sf.read_text())
                    judge_name: str = str(scores_data.get("judge", sf.stem))
                    for item in scores_data.get("scores", []):
                        pid = int(item["prompt_id"])
                        attempt = int(item.get("attempt", 0))
                        alias_map = alias_maps.get((pid, attempt), {})
                        for j in item.get("judgments", []):
                            alias: str = j["alias"]
                            model_id = alias_map.get(alias)
                            if model_id is None:
                                logger.warning(
                                    "Unknown alias '%s' in '%s'; skipping.",
                                    alias,
                                    sf.name,
                                )
                                continue
                            try:
                                score = int(str(j["score"]))
                            except (KeyError, TypeError, ValueError):
                                logger.warning("Malformed judge score in '%s'; skipping.", sf.name)
                                continue
                            if not 1 <= score <= 5:
                                logger.warning("Invalid judge score %d in '%s'; skipping.", score, sf.name)
                                continue
                            key = (pid, attempt, model_id)
                            score_pool.setdefault(key, []).append(score)
                            reasoning_pool.setdefault(key, []).append(str(j.get("reasoning", "")))
                            source_pool.setdefault(key, []).append(judge_name)

                # Build averaged rows.
                for (pid, attempt, model_id), scores in score_pool.items():
                    avg = round(sum(scores) / len(scores), 2)
                    reasonings = reasoning_pool[(pid, attempt, model_id)]
                    sources = source_pool[(pid, attempt, model_id)]
                    metadata = pending_metadata.get((pid, attempt), {})
                    rows.append(
                        {
                            "prompt_id": pid,
                            "attempt": attempt,
                            "prompt_preview": metadata.get("prompt_preview", ""),
                            "model": model_id,
                            "score": avg,
                            "reasoning": " | ".join(
                                f"[{s}] {r[:120]}" for s, r in zip(sources, reasonings, strict=False)
                            ),
                            "source": f"copilot-avg({len(scores)})",
                            "category": metadata.get("category", "legacy"),
                            "quality_dimension": metadata.get("quality_dimension", "legacy"),
                            "weight": metadata.get("weight", 1.0),
                        }
                    )

        df = pd.DataFrame(rows)
        if not df.empty and "attempt" not in df.columns:
            df["attempt"] = 0
        return (
            df.sort_values(["prompt_id", "attempt", "score"], ascending=[True, True, False]).reset_index(drop=True)
            if not df.empty
            else df
        )

    def _log_results(
        self,
        result: pd.DataFrame,
        quality_df: pd.DataFrame,
        security_df: pd.DataFrame,
    ) -> None:
        if not quality_df.empty and "model" in quality_df.columns:
            for _, row in quality_df.iterrows():
                self._tracker.log_quality_score(
                    str(row["model"]),
                    int(row.get("prompt_id", 0)),
                    float(row["score"]),
                )
        if not security_df.empty:
            for _, row in security_df.iterrows():
                self._tracker.log_security_result(
                    str(row["model"]),
                    int(row.get("leak_count", 0)),
                    bool(row.get("is_vulnerable", False)),
                )


# ── Dry-run: offline smoke test (no API, no judge agents) ─────────────────────


def _run_preflight_checks(settings: Settings) -> None:
    """Fast, fully offline validation to catch config/data mistakes *before*
    spending real API budget or crashing mid-way through a paid run.

    Raises:
        ValueError: If a fatal misconfiguration is found (listed all at once).
    """
    problems: list[str] = []

    models = settings.target_models_list
    if not models:
        problems.append("TARGET_MODELS est vide — aucun modèle à évaluer.")
    duplicates = sorted({m for m in models if models.count(m) > 1})
    if duplicates:
        problems.append(f"Modèles en double dans TARGET_MODELS : {duplicates}")

    if not _QUALITY_PROMPTS.exists():
        problems.append(f"Fichier de prompts introuvable : '{_QUALITY_PROMPTS}'.")
    else:
        try:
            load_quality_prompts(_QUALITY_PROMPTS)
        except ValueError as exc:
            problems.append(str(exc))

    if settings.security_probes_path:
        probes_path = Path(settings.security_probes_path)
        if not probes_path.exists():
            problems.append(f"SECURITY_PROBES_PATH pointe vers un fichier inexistant : " f"'{probes_path}'.")
        else:
            try:
                probes = json.loads(probes_path.read_text())
                if not isinstance(probes, list) or not probes:
                    problems.append(f"'{probes_path}' doit contenir une liste JSON non vide.")
                else:
                    for i, probe in enumerate(probes):
                        if not isinstance(probe, dict) or not probe.get("message"):
                            problems.append(
                                f"Probe #{i} de '{probes_path}' invalide " "— clé 'message' manquante ou vide."
                            )
            except json.JSONDecodeError as exc:
                problems.append(f"'{probes_path}' contient du JSON invalide : {exc}")

    if problems:
        formatted = "\n  - ".join(problems)
        raise ValueError(
            "[DRY-RUN] Configuration invalide — corrige avant de lancer un run " f"réel :\n  - {formatted}"
        )

    logger.info("[DRY-RUN] Pré-vérifications OK — config, prompts et probes valides.")


def _write_fake_scores(pending_judgments: list[dict[str, object]], timestamp: str, path: Path) -> None:
    """Write a synthetic ``scores_*.json`` standing in for a Copilot judge agent.

    Scores are deterministic (hash-based) placeholders, clearly labelled as
    such in ``reasoning`` — they only exist to exercise the Phase-3 merge
    logic, never to reflect real quality judgments.
    """
    scores: list[dict[str, object]] = []
    for pj in pending_judgments:
        alias_map: dict[str, str] = pj["alias_map"]  # type: ignore[assignment]
        judgments = []
        for alias in alias_map:
            seed_source = f"{timestamp}|{pj['prompt_id']}|{pj.get('attempt', 0)}|{alias}"
            seed = int(
                hashlib.sha256(seed_source.encode()).hexdigest()[:8],
                16,
            )
            judgments.append(
                {
                    "alias": alias,
                    "reasoning": ("[DRY-RUN] synthetic placeholder score — not a real " "quality evaluation."),
                    "score": (seed % 5) + 1,
                }
            )
        scores.append(
            {
                "prompt_id": pj["prompt_id"],
                "attempt": pj.get("attempt", 0),
                "judgments": judgments,
            }
        )

    payload = {"timestamp": timestamp, "judge": "dry-run-synthetic", "scores": scores}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _report_dry_run_summary(
    result: pd.DataFrame,
    collect_result: CollectResult,
    security_df: pd.DataFrame,
    pricing_df: pd.DataFrame,
    models: list[str],
) -> None:
    n_det = len(collect_result.deterministic_rows)
    n_pend = len(collect_result.pending_judgments)
    n_errors = len(collect_result.collection_errors)
    n_missing_pricing = (
        int(result["prompt_price_per_token"].isna().sum())
        if "prompt_price_per_token" in result.columns
        else len(models)
    )

    logger.info("=" * 70)
    logger.info("[DRY-RUN] ✅ Pipeline validé de bout en bout — AUCUN coût API réel.")
    logger.info("[DRY-RUN]   Modèles testés         : %d", len(models))
    logger.info("[DRY-RUN]   Scores déterministes   : %d", n_det)
    logger.info(
        "[DRY-RUN]   Jugements simulés      : %d (scores factices — pas un " "vrai jugement qualité)",
        n_pend,
    )
    logger.info("[DRY-RUN]   Erreurs de collecte   : %d", n_errors)
    logger.info("[DRY-RUN]   Scans sécurité         : %d modèle(s)", len(security_df))
    logger.info("[DRY-RUN]   Lignes pricing (fake)  : %d", len(pricing_df))
    if n_missing_pricing:
        logger.warning(
            "[DRY-RUN]   ⚠ %d modèle(s) sans pricing — vérifie TARGET_MODELS.",
            n_missing_pricing,
        )
    logger.info("=" * 70)
    logger.info("[DRY-RUN] Si tout est vert ci-dessus, tu peux lancer en confiance :")
    logger.info("[DRY-RUN]   make collect   (Phase 1 réelle — appelle OpenRouter)")


class DryRunPipeline(CollectPipeline):
    """Fully offline smoke test — no OpenRouter calls, no Copilot judge agents.

    Reuses :class:`CollectPipeline`'s stage methods with a
    :class:`~src.api.fake_client.FakeAsyncOpenRouterClient` instead of the real
    HTTP client, then substitutes a synthetic judge for the pending
    judgments so the *entire* collect → judge → merge flow can be validated
    before spending real API budget.

    All artefacts are written under ``data/dry_run/`` — fully isolated from
    ``data/intermediate/`` and ``results/`` so a dry-run can never be mistaken
    for (or accidentally consumed by) a real ``make merge``.
    """

    async def run(self) -> pd.DataFrame:
        settings = self._settings
        models = settings.target_models_list

        _run_preflight_checks(settings)

        logger.info(
            "[DRY-RUN] Simulation offline pour %d modèle(s) — aucun appel API, " "aucun agent juge : %s",
            len(models),
            models,
        )
        _DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)

        async with FakeAsyncOpenRouterClient(settings) as client:
            pricing_df, security_df, collect_result = await asyncio.gather(
                self._run_cost_stage(cast(AsyncOpenRouterClient, client)),
                self._run_security_stage(cast(AsyncOpenRouterClient, client), models),
                self._run_quality_collect(cast(AsyncOpenRouterClient, client), models),
            )
            actual_call_costs = call_costs_to_dataframe(client.call_costs)

        timestamp = datetime.now().strftime(_TIMESTAMP_FORMAT)

        pending = {
            "timestamp": timestamp,
            "models": models,
            "pricing": pricing_df.to_dict(orient="records") if not pricing_df.empty else [],
            "security": security_df.to_dict(orient="records") if not security_df.empty else [],
            "actual_call_costs": actual_call_costs.to_dict(orient="records") if not actual_call_costs.empty else [],
            "deterministic_scores": collect_result.deterministic_rows,
            "pending_judgments": collect_result.pending_judgments,
            "quality_collection_errors": collect_result.collection_errors,
            "quality_metadata": {
                "prompt_count": collect_result.prompt_count,
                "dimension_count": collect_result.dimension_count,
                "repetitions": collect_result.repetitions,
                "suite_id": collect_result.quality_suite_id,
            },
        }
        pending_path = _DRY_RUN_DIR / f"pending_{timestamp}.json"
        pending_path.write_text(json.dumps(pending, indent=2, ensure_ascii=False))

        scores_path = _DRY_RUN_DIR / f"scores_{timestamp}.json"
        _write_fake_scores(collect_result.pending_judgments, timestamp, scores_path)

        quality_df = MergePipeline._rebuild_quality_df(pending, scores_path)
        result = _merge_results(
            models,
            pricing_df,
            quality_df,
            security_df,
            settings.workload_profile,
            quality_prompt_count=collect_result.prompt_count,
            quality_dimension_count=collect_result.dimension_count,
            quality_repetitions=collect_result.repetitions,
            quality_collection_errors=pd.DataFrame(collect_result.collection_errors),
            quality_suite_id=collect_result.quality_suite_id,
            actual_call_costs=actual_call_costs,
        )

        preview_stem = _DRY_RUN_DIR / f"benchmark_preview_{timestamp}"
        result.to_csv(f"{preview_stem}.csv", index=False)
        result.to_json(f"{preview_stem}.json", orient="records", indent=2)
        call_costs_stem = _DRY_RUN_DIR / f"call_costs_{timestamp}"
        actual_call_costs.to_csv(f"{call_costs_stem}.csv", index=False)
        actual_call_costs.to_json(f"{call_costs_stem}.json", orient="records", indent=2)
        logger.info("[DRY-RUN] Aperçu du résultat fusionné → '%s.{csv,json}'", preview_stem)

        _report_dry_run_summary(result, collect_result, security_df, pricing_df, models)
        return result


# ── Verify: real, zero-cost preflight (auth + live model catalog) ─────────────


def _format_credit_summary(key_info: dict[str, Any]) -> str:
    """Render OpenRouter's ``GET /key`` payload as a human-readable one-liner."""
    label = key_info.get("label") or "(unlabelled key)"
    usage = key_info.get("usage")
    limit = key_info.get("limit")
    limit_remaining = key_info.get("limit_remaining")
    is_free_tier = key_info.get("is_free_tier")

    parts = [f"key='{label}'"]
    if isinstance(usage, int | float):
        parts.append(f"lifetime usage={usage:.4f} credits")
    if limit is None:
        parts.append("no per-key spend limit")
    elif isinstance(limit_remaining, int | float):
        parts.append(f"limit_remaining={limit_remaining:.4f}/{limit:.4f} credits")
    if is_free_tier is not None:
        parts.append(f"is_free_tier={is_free_tier}")
    return ", ".join(parts)


class VerifyPipeline:
    """Real but zero-cost preflight — validates the API key and TARGET_MODELS
    against the live OpenRouter catalog without a single chat completion.

    Sits between :class:`DryRunPipeline` (fully offline, fake data) and
    :class:`CollectPipeline` (real, full-cost run). Both ``GET /key`` and
    ``GET /models`` are metadata-only endpoints that OpenRouter does not bill,
    so this can be re-run as often as needed right before a costly
    ``make collect``. Unlike ``CollectPipeline``, failures here raise
    immediately instead of degrading gracefully — the whole point is to stop
    *before* spending budget, not to salvage a partial run.

    Uses a :class:`CollectPipeline` instance purely to reuse its
    ``_run_cost_stage`` (real pricing fetch); composition rather than
    inheritance keeps ``run()``'s return type independent of
    ``CollectPipeline.run()``'s.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._collector = CollectPipeline(self._settings)

    async def run(self) -> None:
        settings = self._settings
        models = settings.target_models_list

        _run_preflight_checks(settings)

        async with AsyncOpenRouterClient(settings) as client:
            try:
                key_info = await client.get_key_info()
            except OpenRouterError as exc:
                raise ValueError(f"[VERIFY] \u274c API key check failed: {exc}") from exc

            pricing_df = await self._collector._run_cost_stage(client)

        logger.info("[VERIFY] \u2705 API key accepted \u2014 %s", _format_credit_summary(key_info))

        if pricing_df.empty:
            raise ValueError(
                "[VERIFY] \u274c Could not fetch the live model catalog (GET /models) — "
                "check network connectivity and try again."
            )

        unknown_models = _unknown_target_models(models, pricing_df)
        if unknown_models:
            raise ValueError(
                f"[VERIFY] \u274c {len(unknown_models)} model ID(s) in TARGET_MODELS are not in "
                f"the live OpenRouter catalog: {unknown_models}. Check https://openrouter.ai/models "
                "for the current slug — every call to them would fail during 'make collect'."
            )
        logger.info("[VERIFY] \u2705 All %d TARGET_MODELS entries resolve in the live catalog.", len(models))

        prompt_count, _dim_count, _suite_id = _quality_screen_metadata(_QUALITY_PROMPTS)
        probes_path = Path(settings.security_probes_path) if settings.security_probes_path else None
        estimated_requests = _estimate_free_tier_request_volume(
            models,
            quality_prompt_count=prompt_count or 0,
            quality_repetitions=settings.quality_repetitions,
            security_probe_count=_security_probe_count_for_estimate(probes_path),
        )
        _warn_on_free_tier_request_volume(estimated_requests)

        logger.info("=" * 70)
        logger.info("[VERIFY] \u2705 Ready for a real run — key valid, models known, $0 spent so far.")
        logger.info("[VERIFY]   make collect   (Phase 1 — real OpenRouter calls)")
        logger.info("=" * 70)


def main() -> None:
    try:
        subcommand = sys.argv[1] if len(sys.argv) > 1 else "collect"
        if subcommand in ("run", "collect"):
            pending = asyncio.run(CollectPipeline().run())
            logger.info("Pending file: %s", pending)
        elif subcommand == "merge":
            result = MergePipeline().run()
            print(result.to_string(index=False))
        elif subcommand in ("dry-run", "dryrun"):
            result = asyncio.run(DryRunPipeline().run())
            print(result.to_string(index=False))
        elif subcommand == "verify":
            asyncio.run(VerifyPipeline().run())
        else:
            logger.error(
                "Unknown subcommand '%s'. Usage: python -m src.main " "[collect|merge|dry-run|verify]",
                subcommand,
            )
            sys.exit(1)
    except Exception as exc:
        logger.critical("Pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
