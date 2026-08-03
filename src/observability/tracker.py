"""MLflow experiment tracker for the LLM benchmark pipeline.

Wraps MLflow to provide a clean, SEC-001 compliant API:
only token counts and model IDs are logged — never prompt content or API keys.

Usage:
    from src.observability.tracker import ExperimentTracker
    from src.core.config import get_settings

    settings = get_settings()
    tracker = ExperimentTracker(
        tracking_uri=settings.mlflow_tracking_uri,
    )
    tracker.start_run("benchmark-2026-07-10")
    tracker.log_quality_score("openai/gpt-4o-mini", prompt_id=0, score=4)
    tracker.log_dataframe("results", results_df)
    tracker.end_run()
"""

from __future__ import annotations

import logging
import os
import tempfile

import mlflow
import pandas as pd

logger = logging.getLogger(__name__)


class ExperimentTracker:
    """Thin MLflow wrapper for LLM benchmark observability.

    If MLflow fails to initialise (e.g. stale file-store, missing DB), the
    tracker silently becomes a no-op so the pipeline can still run.
    """

    def __init__(
        self,
        experiment_name: str = "llm-benchmark",
        tracking_uri: str = "sqlite:///mlruns.db",
    ) -> None:
        self._active = False
        self._enabled = False
        try:
            mlflow.set_tracking_uri(tracking_uri)
            mlflow.set_experiment(experiment_name)
            self._enabled = True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "MLflow init failed (%s) — tracking disabled. "
                "Set MLFLOW_TRACKING_URI=sqlite:///mlruns.db in .env to fix.",
                exc,
            )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start_run(self, run_name: str) -> None:
        """Open a new MLflow run.  Call :meth:`end_run` when finished."""
        if not self._enabled:
            return
        mlflow.start_run(run_name=run_name)
        self._active = True
        logger.info("MLflow run '%s' started.", run_name)

    def end_run(self) -> None:
        """Close the active MLflow run."""
        if self._active:
            mlflow.end_run()
            self._active = False

    # ── Logging helpers ────────────────────────────────────────────────────────

    def log_llm_call(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        cost_usd: float,
    ) -> None:
        if not self._enabled:
            return
        """Log per-call token usage and cost metrics.

        Args:
            model: OpenRouter model identifier — logged as-is (no secrets).
            prompt_tokens: Number of input tokens consumed.
            completion_tokens: Number of output tokens generated.
            latency_ms: Round-trip API latency in milliseconds.
            cost_usd: Estimated USD cost for this call.
        """
        key = _safe_metric_key(model)
        mlflow.log_metrics(
            {
                f"{key}.prompt_tokens": float(prompt_tokens),
                f"{key}.completion_tokens": float(completion_tokens),
                f"{key}.latency_ms": latency_ms,
                f"{key}.cost_usd": cost_usd,
            }
        )

    def log_quality_score(self, model: str, prompt_id: int, score: int) -> None:
        if not self._enabled:
            return
        """Log a quality score for one model/prompt pair.

        Args:
            model: Model identifier.
            prompt_id: Zero-based prompt index (used as the MLflow step).
            score: Quality score from 1 to 5.
        """
        mlflow.log_metric(
            f"{_safe_metric_key(model)}.quality_score",
            float(score),
            step=prompt_id,
        )

    def log_security_result(
        self, model: str, leak_count: int, is_vulnerable: bool
    ) -> None:
        if not self._enabled:
            return
        """Log security scan results for one model.

        Args:
            model: Model identifier.
            leak_count: Number of probes that caused a system-prompt leak.
            is_vulnerable: True if any probe succeeded.
        """
        key = _safe_metric_key(model)
        mlflow.log_metrics(
            {
                f"{key}.leak_count": float(leak_count),
                f"{key}.is_vulnerable": float(is_vulnerable),
            }
        )

    def log_dataframe(self, key: str, df: pd.DataFrame) -> None:
        if not self._enabled:
            return
        """Persist a DataFrame as a CSV artifact in the active run.

        Args:
            key: Artifact subdirectory name (e.g. ``"benchmark_results"``).
            df: DataFrame to serialise.
        """
        with tempfile.NamedTemporaryFile(
            suffix=".csv", delete=False, mode="w"
        ) as tmp:
            df.to_csv(tmp, index=False)
            tmp_path = tmp.name

        try:
            mlflow.log_artifact(tmp_path, artifact_path=key)
        finally:
            os.unlink(tmp_path)

    # ── Context manager ────────────────────────────────────────────────────────

    def __enter__(self) -> ExperimentTracker:
        return self

    def __exit__(self, *_: object) -> None:
        self.end_run()


# ── Helpers ────────────────────────────────────────────────────────────────────


def _safe_metric_key(model_id: str) -> str:
    """Convert a model ID to a valid MLflow metric key."""
    return model_id.replace("/", ".").replace("-", "_")
