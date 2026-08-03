"""Unit tests for src/observability/tracker.py."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pandas as pd
import pytest

from src.observability.tracker import ExperimentTracker, _safe_metric_key


@pytest.fixture()
def tracker() -> ExperimentTracker:
    with (
        patch("mlflow.set_tracking_uri"),
        patch("mlflow.set_experiment"),
    ):
        t = ExperimentTracker(experiment_name="test", tracking_uri="sqlite:///test.db")
        # Ensure enabled flag is set despite the mocked MLflow calls.
        t._enabled = True
        return t


class TestExperimentTracker:
    def test_start_and_end_run(self, tracker: ExperimentTracker) -> None:
        with patch("mlflow.start_run") as mock_start, patch("mlflow.end_run") as mock_end:
            tracker.start_run("my-run")
            assert tracker._active is True
            mock_start.assert_called_once_with(run_name="my-run")

            tracker.end_run()
            assert tracker._active is False
            mock_end.assert_called_once()

    def test_end_run_noop_when_not_active(self, tracker: ExperimentTracker) -> None:
        with patch("mlflow.end_run") as mock_end:
            tracker.end_run()  # Should not raise even if not active.
            mock_end.assert_not_called()

    def test_log_llm_call(self, tracker: ExperimentTracker) -> None:
        with patch("mlflow.log_metrics") as mock_metrics:
            tracker.log_llm_call("openai/gpt-4o", 100, 50, 1200.0, 0.0002)
            mock_metrics.assert_called_once()
            kwargs = mock_metrics.call_args[0][0]
            assert "openai.gpt_4o.prompt_tokens" in kwargs
            assert kwargs["openai.gpt_4o.prompt_tokens"] == 100.0

    def test_log_quality_score(self, tracker: ExperimentTracker) -> None:
        with patch("mlflow.log_metric") as mock_metric:
            tracker.log_quality_score("openai/gpt-4o", prompt_id=2, score=4)
            mock_metric.assert_called_once_with(
                "openai.gpt_4o.quality_score", 4.0, step=2
            )

    def test_log_security_result(self, tracker: ExperimentTracker) -> None:
        with patch("mlflow.log_metrics") as mock_metrics:
            tracker.log_security_result("meta-llama/llama-3", leak_count=2, is_vulnerable=True)
            mock_metrics.assert_called_once()
            kwargs = mock_metrics.call_args[0][0]
            assert kwargs["meta_llama.llama_3.is_vulnerable"] == 1.0

    def test_context_manager_calls_end_run(self, tracker: ExperimentTracker) -> None:
        with (
            patch("mlflow.start_run"),
            patch("mlflow.end_run") as mock_end,
        ):
            tracker.start_run("ctx-run")
            with tracker:
                pass
            mock_end.assert_called()

    def test_log_dataframe_logs_artifact(self, tracker: ExperimentTracker) -> None:
        df = pd.DataFrame({"model": ["a"], "score": [4]})
        with (
            patch("mlflow.log_artifact") as mock_artifact,
            patch("os.unlink"),
        ):
            tracker.log_dataframe("results", df)
            mock_artifact.assert_called_once()


class TestSafeMetricKey:
    def test_replaces_slash_and_hyphen(self) -> None:
        assert _safe_metric_key("openai/gpt-4o") == "openai.gpt_4o"

    def test_no_special_chars_unchanged(self) -> None:
        assert _safe_metric_key("simplemodel") == "simplemodel"
