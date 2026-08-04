"""LLMOps evaluation pipeline — entry point.

V2 adds :class:`AsyncPipeline` which runs all three evaluation stages
concurrently via ``asyncio.gather`` and integrates MLflow tracking.

Usage:
    python -m src.main
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.api.openrouter_client import (
    AsyncOpenRouterClient,
    OpenRouterClient,
    OpenRouterError,
)
from src.core.config import Settings, get_settings
from src.evaluators.cost_analyzer import AsyncCostAnalyzer, CostAnalyzer
from src.evaluators.quality_judge import AsyncQualityJudge, CollectResult
from src.evaluators.security_scanner import AsyncSecurityScanner, SecurityScanner
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

        result = _merge_results(models, pricing_df, quality_df, security_df)
        _export(result)
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
        logger.info(
            "[quality] Skipping — use Copilot judge agents "
            "(make collect / make judge / make merge)."
        )
        return pd.DataFrame()

    def _run_security_stage(
        self, models: list[str], pricing_df: pd.DataFrame
    ) -> pd.DataFrame:
        logger.info("[3/3] Running security scans …")
        scanner = SecurityScanner(self._client)
        try:
            return scanner.run_full_scan(models=models, pricing_df=pricing_df)
        except OpenRouterError as exc:
            logger.error("Security stage failed: %s", exc)
            return pd.DataFrame()


# ── V2 asynchronous pipeline ───────────────────────────────────────────────────


class AsyncPipeline:
    """Async pipeline — runs cost, quality, and security stages concurrently."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._tracker = ExperimentTracker(
            tracking_uri=self._settings.mlflow_tracking_uri,
        )

    async def run(self) -> pd.DataFrame:
        """Execute all stages concurrently and return the merged results DataFrame."""
        models = self._settings.target_models_list
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        logger.info("Starting async benchmark for %d model(s): %s", len(models), models)

        self._tracker.start_run(f"benchmark-{timestamp}")
        try:
            async with AsyncOpenRouterClient(self._settings) as client:
                pricing_df, quality_df, security_df = await asyncio.gather(
                    self._run_cost_stage(client),
                    self._run_quality_stage(client, models),
                    self._run_security_stage(client, models),
                )

            result = _merge_results(models, pricing_df, quality_df, security_df)
            self._log_results(result, quality_df, security_df)
            self._tracker.log_dataframe("benchmark_results", result)
            _export(result)
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

    async def _run_quality_stage(
        self, client: AsyncOpenRouterClient, models: list[str]
    ) -> pd.DataFrame:
        logger.info("[quality] Running deterministic evaluation …")
        if not _QUALITY_PROMPTS.exists():
            logger.warning(
                "[quality] No prompts file found at '%s'; skipping.", _QUALITY_PROMPTS
            )
            return pd.DataFrame()
        judge = AsyncQualityJudge(client)
        try:
            df = await judge.run_dataset(_QUALITY_PROMPTS, models)
            logger.info(
                "[quality] Evaluation complete — %d deterministic scores recorded.",
                len(df),
            )
            return df
        except (OpenRouterError, ValueError) as exc:
            logger.error("[quality] Stage failed: %s", exc)
            return pd.DataFrame()

    async def _run_security_stage(
        self, client: AsyncOpenRouterClient, models: list[str]
    ) -> pd.DataFrame:
        logger.info("[security] Running security scans …")
        probes_path = (
            Path(self._settings.security_probes_path)
            if self._settings.security_probes_path
            else None
        )
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
                    int(row["score"]),
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
) -> pd.DataFrame:
    base = pd.DataFrame({"model": models})

    if not quality_df.empty and "score" in quality_df.columns:
        avg_quality = (
            quality_df.groupby("model", as_index=False)["score"]
            .mean()
            .rename(columns={"score": "avg_quality_score"})
        )
        base = base.merge(avg_quality, on="model", how="left")

    if not security_df.empty:
        base = base.merge(
            security_df[
                ["model", "leak_count", "is_vulnerable", "zero_data_retention"]
            ],
            on="model",
            how="left",
        )

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

    return base


def _export(df: pd.DataFrame) -> None:
    _RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = _RESULTS_DIR / f"benchmark_{timestamp}"
    df.to_csv(f"{stem}.csv", index=False)
    df.to_json(f"{stem}.json", orient="records", indent=2)
    logger.info("Results exported to '%s.{csv,json}'", stem)


# ── Split pipeline helpers ─────────────────────────────────────────────────────


def _save_pending(
    models: list[str],
    pricing_df: pd.DataFrame,
    security_df: pd.DataFrame,
    collect_result: CollectResult,
) -> Path:
    """Persist intermediate data to ``data/intermediate/pending_{ts}.json``.

    Also writes a **blind** ``judging_{ts}.json`` without ``alias_map`` so
    Copilot judge agents cannot identify which company made each response.
    """
    _INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _INTERMEDIATE_DIR / f"pending_{timestamp}.json"

    payload = {
        "timestamp": timestamp,
        "models": models,
        "pricing": pricing_df.to_dict(orient="records") if not pricing_df.empty else [],
        "security": security_df.to_dict(orient="records")
        if not security_df.empty
        else [],
        "deterministic_scores": collect_result.deterministic_rows,
        "pending_judgments": collect_result.pending_judgments,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Intermediate file saved → '%s'", path)

    # ── Blind judging file (no alias_map) ──────────────────────────────────────
    judging_path = _INTERMEDIATE_DIR / f"judging_{timestamp}.json"
    judging_payload = {
        "timestamp": timestamp,
        "pending_judgments": [
            {
                "prompt_id": pj["prompt_id"],
                "prompt": pj["prompt"],
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
    files = sorted(
        directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
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

        async with AsyncOpenRouterClient(self._settings) as client:
            pricing_df, security_df, collect_result = await asyncio.gather(
                self._run_cost_stage(client),
                self._run_security_stage(client, models),
                self._run_quality_collect(client, models),
            )

        pending_path = _save_pending(
            models=models,
            pricing_df=pricing_df,
            security_df=security_df,
            collect_result=collect_result,
        )

        n_det = len(collect_result.deterministic_rows)
        n_pend = len(collect_result.pending_judgments)
        logger.info("Deterministic scores: %d  |  Pending judgments: %d", n_det, n_pend)

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

    async def _run_security_stage(
        self, client: AsyncOpenRouterClient, models: list[str]
    ) -> pd.DataFrame:
        logger.info("[security] Scanning %d models …", len(models))
        probes_path = (
            Path(self._settings.security_probes_path)
            if self._settings.security_probes_path
            else None
        )
        try:
            df = await AsyncSecurityScanner(
                client, probes_path=probes_path
            ).run_full_scan(models)
            logger.info("[security] Scan complete — %d models scanned.", len(df))
            return df
        except OpenRouterError as exc:
            logger.error("[security] Failed: %s", exc)
            return pd.DataFrame()

    async def _run_quality_collect(
        self, client: AsyncOpenRouterClient, models: list[str]
    ) -> CollectResult:
        logger.info("[quality] Collecting responses (no LLM judge) …")
        if not _QUALITY_PROMPTS.exists():
            logger.warning(
                "[quality] No prompts file at '%s'; skipping.", _QUALITY_PROMPTS
            )
            return CollectResult()
        judge = AsyncQualityJudge(client)
        try:
            result = await judge.run_collect(_QUALITY_PROMPTS, models)
            logger.info(
                "[quality] Collected: %d deterministic, %d pending judgment(s).",
                len(result.deterministic_rows),
                len(result.pending_judgments),
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
            raise FileNotFoundError(
                "No pending_*.json found in data/intermediate/. "
                "Run 'make collect' first."
            )

        logger.info("Phase 3 — loading intermediate data from '%s'", pending_path)
        pending = json.loads(pending_path.read_text())

        models: list[str] = pending["models"]
        pricing_df = pd.DataFrame(pending.get("pricing", []))
        security_df = pd.DataFrame(pending.get("security", []))
        timestamp: str = pending["timestamp"]

        quality_df = self._rebuild_quality_df(pending, scores_path)

        result = _merge_results(models, pricing_df, quality_df, security_df)

        self._tracker.start_run(f"benchmark-{timestamp}")
        try:
            self._log_results(result, quality_df, security_df)
            self._tracker.log_dataframe("benchmark_results", result)
        finally:
            self._tracker.end_run()

        _export(result)
        return result

    def _rebuild_quality_df(
        self, pending: dict[str, object], scores_path: Path | None
    ) -> pd.DataFrame:
        """Combine deterministic rows + Copilot judge scores into a quality DataFrame.

        Loads ALL ``scores_*_{judge}.json`` files whose internal ``timestamp``
        matches the pending file.  Scores from different judges are averaged per
        ``(prompt_id, model)``; recused models (absent from a judge's file) are
        simply excluded from that judge's contribution to the average.
        """
        rows: list[dict[str, object]] = list(pending.get("deterministic_scores", []))  # type: ignore[arg-type]
        pending_judgments: list[dict[str, object]] = pending.get(
            "pending_judgments", []
        )  # type: ignore[assignment]
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

                # Accumulate scores per (prompt_id, model_id) across all judges.
                # Recused models are simply absent from a judge's file.
                score_pool: dict[tuple[int, str], list[int]] = {}
                reasoning_pool: dict[tuple[int, str], list[str]] = {}
                source_pool: dict[tuple[int, str], list[str]] = {}
                prompt_preview_map: dict[int, str] = {
                    int(str(pj["prompt_id"])): str(pj.get("prompt_preview", ""))
                    for pj in pending_judgments
                }
                alias_maps: dict[int, dict[str, str]] = {
                    int(str(pj["prompt_id"])): pj["alias_map"]  # type: ignore[misc]
                    for pj in pending_judgments
                }

                for sf in scores_files:
                    scores_data = json.loads(sf.read_text())
                    judge_name: str = str(scores_data.get("judge", sf.stem))
                    for item in scores_data.get("scores", []):
                        pid = int(item["prompt_id"])
                        alias_map = alias_maps.get(pid, {})
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
                            key = (pid, model_id)
                            score_pool.setdefault(key, []).append(int(str(j["score"])))
                            reasoning_pool.setdefault(key, []).append(
                                str(j.get("reasoning", ""))
                            )
                            source_pool.setdefault(key, []).append(judge_name)

                # Build averaged rows.
                for (pid, model_id), scores in score_pool.items():
                    avg = round(sum(scores) / len(scores), 2)
                    sources = source_pool[(pid, model_id)]
                    reasonings = reasoning_pool[(pid, model_id)]
                    rows.append(
                        {
                            "prompt_id": pid,
                            "prompt_preview": prompt_preview_map.get(pid, ""),
                            "model": model_id,
                            "score": avg,
                            "reasoning": " | ".join(
                                f"[{s}] {r[:120]}"
                                for s, r in zip(sources, reasonings, strict=False)
                            ),
                            "source": f"copilot-avg({len(scores)})",
                        }
                    )

        df = pd.DataFrame(rows)
        return (
            df.sort_values(["prompt_id", "score"], ascending=[True, False]).reset_index(
                drop=True
            )
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
                    int(row["score"]),
                )
        if not security_df.empty:
            for _, row in security_df.iterrows():
                self._tracker.log_security_result(
                    str(row["model"]),
                    int(row.get("leak_count", 0)),
                    bool(row.get("is_vulnerable", False)),
                )


def main() -> None:
    try:
        subcommand = sys.argv[1] if len(sys.argv) > 1 else "collect"
        if subcommand in ("run", "collect"):
            pending = asyncio.run(CollectPipeline().run())
            logger.info("Pending file: %s", pending)
        elif subcommand == "merge":
            result = MergePipeline().run()
            print(result.to_string(index=False))
        else:
            logger.error(
                "Unknown subcommand '%s'. Usage: python -m src.main [collect|merge]",
                subcommand,
            )
            sys.exit(1)
    except Exception as exc:
        logger.critical("Pipeline failed: %s", exc, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
