"""Shared, Streamlit-independent data-prep helpers for the benchmark dashboard.

Both the live Streamlit app (dashboard/app.py) and the static HTML export
(scripts/export_dashboard_html.py) import from here so the two views can never
disagree on how a derived column (cost/1M tokens, security status, TCO, CER,
quality tier...) is computed.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd

from src.evaluators.cost_analyzer import WorkloadProfile

NOT_SCORED_SUFFIX = " (not scored)"
"""Suffix marking an OWASP category reported but excluded from the RSI."""


def numeric_series(df: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    """Return a numeric column or a same-index fallback series."""
    if column not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[column], errors="coerce")


def short_name(model_id: object) -> str:
    """Return the trailing slug of an OpenRouter model id, e.g. 'gpt-4o-mini'."""
    return str(model_id).split("/")[-1]


def best_row(frame: pd.DataFrame, column: str, ascending: bool = False) -> pd.Series | None:
    """Return the row with the best value in *column* (max, or min if ascending), or None."""
    if column not in frame.columns or frame.empty:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.notna().sum() == 0:
        return None
    return frame.loc[values.idxmin() if ascending else values.idxmax()]


def safest_summary(frame: pd.DataFrame) -> tuple[str, str]:
    """Return a (headline, detail) pair describing the safest model or overall exposure."""
    rsi = numeric_series(frame, "rsi") if "rsi" in frame.columns else pd.Series(dtype="float64")
    if rsi.notna().any():
        row = frame.loc[rsi.idxmax()]
        return short_name(row["model"]), f"RSI {row['rsi']:.0f} / 100"
    safe_count = int((frame["security_status"] == "Safe").sum())
    return f"{safe_count} / {len(frame)} safe", "No probe leaked the system prompt"


def quality_tier(score: float) -> str:
    """Bucket avg_quality_score into a coarse, dashboard-only readability band."""
    if pd.isna(score):
        return "—"
    if score >= 4.5:
        return "Excellent"
    if score >= 3.5:
        return "Good"
    if score >= 2.5:
        return "Fair"
    return "Poor"


# Shared across the quality-tier and security-status columns so both use one visual language.
STATUS_STYLES = {
    "Safe": "background-color: #d4edda; color: #155724",
    "Excellent": "background-color: #d4edda; color: #155724",
    "Good": "background-color: #d1ecf1; color: #0c5460",
    "Partial risk": "background-color: #fff3cd; color: #856404",
    "Fair": "background-color: #fff3cd; color: #856404",
    "Vulnerable": "background-color: #f8d7da; color: #721c24",
    "Poor": "background-color: #f8d7da; color: #721c24",
}


def tint_status(value: object) -> str:
    """Return the CSS rule tinting a status/tier cell, or '' for an unknown value."""
    return STATUS_STYLES.get(str(value), "")


def parse_probe_details(raw: object) -> list[dict[str, object]]:
    """Parse the serialized probe details produced by the scanner safely.

    The scanner emits JSON (``json.dumps``), but older/foreign data may use a
    Python ``repr`` instead — try both rather than guessing from a prefix.
    """
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed: object = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        try:
            parsed = ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def parse_judge_verdicts(raw: object) -> list[dict[str, object]]:
    """Parse the per-judge score and reasoning stored in quality details."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed: object = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def security_long_frame(results_df: pd.DataFrame) -> pd.DataFrame:
    """Convert serialized probe rows into heatmap-friendly long format."""
    if "probe_details" not in results_df.columns:
        return pd.DataFrame()

    details_df = results_df[["model", "probe_details"]].copy()
    details_df["details"] = details_df["probe_details"].map(parse_probe_details)
    details_df = details_df.explode("details").dropna(subset=["details"]).reset_index(drop=True)
    if details_df.empty:
        return pd.DataFrame()

    details = pd.json_normalize(details_df["details"]).reset_index(drop=True)
    details["model"] = details_df["model"].to_numpy()
    if "category_id" not in details.columns:
        details["category_id"] = "LLM00"
    if "category_name" not in details.columns:
        details["category_name"] = "Uncategorized"
    leaked = details["leaked"] if "leaked" in details.columns else pd.Series(False, index=details.index)
    probe_error = details["probe_error"] if "probe_error" in details.columns else pd.Series(False, index=details.index)
    details["probe_error"] = probe_error.fillna(False).astype(bool)
    scored = details["scored"] if "scored" in details.columns else pd.Series(True, index=details.index)
    details["scored"] = scored.fillna(True).astype(bool)
    details["vulnerability_rate"] = leaked.astype("float32").mask(details["probe_error"])
    return details[["model", "category_id", "category_name", "vulnerability_rate", "probe_error", "scored"]]


def security_probe_details_frame(results_df: pd.DataFrame) -> pd.DataFrame:
    """Convert serialized probe rows into a full transcript: prompt + response per probe.

    Unlike :func:`security_long_frame` (heatmap-only columns), this keeps the
    probe's actual prompt text and the model's full response for a
    "Security prompts" drill-down. Scans predating these fields (or a custom
    probes file missing ``category_id``/``category_name``) default to an
    empty string / catch-all category rather than raising.
    """
    if "probe_details" not in results_df.columns:
        return pd.DataFrame()

    details_df = results_df[["model", "probe_details"]].copy()
    details_df["details"] = details_df["probe_details"].map(parse_probe_details)
    details_df = details_df.explode("details").dropna(subset=["details"]).reset_index(drop=True)
    if details_df.empty:
        return pd.DataFrame()

    details = pd.json_normalize(details_df["details"]).reset_index(drop=True)
    details["model"] = details_df["model"].to_numpy()
    defaults: dict[str, object] = {
        "probe": "",
        "category_id": "LLM00",
        "category_name": "Uncategorized",
        "prompt": "",
        "response": "",
        "preview": "",
        "leaked": False,
        "probe_error": False,
        "outcome": "legacy_unverified",
    }
    for column, default in defaults.items():
        if column not in details.columns:
            details[column] = default
        else:
            details[column] = details[column].fillna(default)
    return details[["model", *defaults]]


def quality_dimension_table(df: pd.DataFrame) -> pd.DataFrame:
    """Return a model x quality-dimension score table (wide), for exact numbers.

    Complements :func:`dashboard.quality_viz.build_quality_dimension_heatmap`
    (visual) with a sortable table of the same ``dimension_score`` values.
    """
    long_df = quality_dimension_long_frame(df)
    if long_df.empty:
        return pd.DataFrame()
    return long_df.pivot(index="model", columns="quality_dimension", values="dimension_score").reset_index()


def security_category_table(security_long_df: pd.DataFrame) -> pd.DataFrame:
    """Return a model x OWASP-category vulnerability-rate table (wide).

    Complements :func:`dashboard.security_viz.build_owasp_heatmap` (visual)
    with a sortable table of the same ``vulnerability_rate`` values. Category
    columns excluded from the RSI are suffixed so the table cannot be read as
    if every column carried the same weight.
    """
    required = {"model", "category_id", "vulnerability_rate"}
    if security_long_df.empty or not required.issubset(security_long_df.columns):
        return pd.DataFrame()
    work_df = security_long_df.copy()
    if "scored" in work_df.columns:
        work_df["category_id"] = work_df["category_id"].where(
            work_df["scored"].astype(bool), work_df["category_id"] + NOT_SCORED_SUFFIX
        )
    return work_df.pivot_table(
        index="model", columns="category_id", values="vulnerability_rate", aggfunc="mean"
    ).reset_index()


def enrich_benchmark(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns every view relies on: cost/1M tokens + security_status.

    Expects *df* to already contain ``prompt_price_per_token``. Missing
    security columns default to a leak-free/no-ZDR baseline.
    """
    df = df.copy()
    df["cost_per_1m_tokens_usd"] = numeric_series(df, "prompt_price_per_token", 0.0).fillna(0.0) * 1_000_000
    for column, default in (("is_vulnerable", False), ("leak_count", 0), ("zero_data_retention", False)):
        if column not in df.columns:
            df[column] = default
    vulnerable = df["is_vulnerable"].fillna(False).astype(bool)
    leak_count = pd.to_numeric(df["leak_count"], errors="coerce").fillna(0)
    df["security_status"] = (
        pd.Series("Safe", index=df.index).mask(leak_count > 0, "Partial risk").mask(vulnerable, "Vulnerable")
    )
    return df


def compute_cost_columns(df: pd.DataFrame, profile: WorkloadProfile) -> pd.DataFrame:
    """Add ``tco_usd`` and a run-normalized ``cer`` for *profile*.

    CER is re-derived against *this* profile's TCO rather than trusting any
    ``cer`` baked into the CSV at collect time, so switching profiles never
    leaves a stale value behind.
    """
    cost_df = df.copy()
    input_price = numeric_series(cost_df, "prompt_price_per_token")
    completion_price = numeric_series(cost_df, "completion_price_per_token")
    cost_df["tco_usd"] = (
        input_price * profile.monthly_prompt_tokens + completion_price * profile.monthly_completion_tokens
    )

    if "quality_cer_eligible" in cost_df.columns:
        eligible = cost_df["quality_cer_eligible"].fillna(False).astype(bool)
        eligible_quality = numeric_series(cost_df, "avg_quality_score").where(eligible, 0.0).fillna(0.0)
        raw_cer = (eligible_quality / cost_df["tco_usd"]).replace([float("inf"), -float("inf")], 0.0).fillna(0.0)
        max_cer = raw_cer.max()
        cost_df["cer"] = (raw_cer / max_cer).round(4) if max_cer > 0 else raw_cer

    return cost_df


_QUALITY_DIM_PREFIX = "quality_dim_"


def quality_dimension_long_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Melt the wide ``quality_dim_<dimension>`` columns back into long format.

    Returns:
        DataFrame with ``model``, ``quality_dimension``, ``dimension_score``
        columns (rows with a missing score are dropped), ready for
        :func:`dashboard.quality_viz.build_quality_dimension_heatmap`.
    """
    dimension_columns = [c for c in df.columns if c.startswith(_QUALITY_DIM_PREFIX)]
    if not dimension_columns or "model" not in df.columns:
        return pd.DataFrame(columns=["model", "quality_dimension", "dimension_score"])

    long_df = df[["model", *dimension_columns]].melt(
        id_vars="model", var_name="quality_dimension", value_name="dimension_score"
    )
    long_df["quality_dimension"] = long_df["quality_dimension"].str.removeprefix(_QUALITY_DIM_PREFIX)
    return long_df.dropna(subset=["dimension_score"]).reset_index(drop=True)


def load_quality_details(benchmark_path: Path) -> pd.DataFrame:
    """Load scored quality details and collection diagnostics for a benchmark.

    Mirrors the ``results/call_costs/benchmark_<ts>_call_costs.csv`` naming
    convention: ``results/quality_details/benchmark_<ts>_quality_details.csv``.
    Returns an empty DataFrame (not an error) for runs predating this export,
    or when no prompt/response detail was collected.
    """
    details_path = benchmark_path.parent / "quality_details" / f"{benchmark_path.stem}_quality_details.csv"
    diagnostics_path = benchmark_path.parent / "quality_diagnostics" / f"{benchmark_path.stem}_quality_diagnostics.csv"
    frames: list[pd.DataFrame] = []
    if details_path.exists():
        details_df = pd.read_csv(details_path)
        if not details_df.empty:
            details_df["evidence_status"] = "Scored"
            frames.append(details_df)
    if diagnostics_path.exists():
        diagnostics_df = pd.read_csv(diagnostics_path)
        if not diagnostics_df.empty:
            diagnostics_df["evidence_status"] = "Collection anomaly"
            diagnostics_df["source"] = "collection_error"
            diagnostics_df["reasoning"] = diagnostics_df.get("error", "")
            frames.append(diagnostics_df)
    if not frames:
        return pd.DataFrame()
    details_df = pd.concat(frames, ignore_index=True, sort=False)
    if details_df.empty or "model" not in details_df.columns:
        return pd.DataFrame()
    defaults: dict[str, object] = {
        "quality_dimension": "legacy",
        "prompt": "",
        "response": "",
        "score": pd.NA,
        "reasoning": "",
        "judge_verdicts": "",
        "source": "legacy",
        "evidence_status": "Scored",
        "generation_id": "",
        "resolved_model": "",
        "request_sha256": "",
        "error": "",
        "expected_answers_json": "[]",
        "verification_status": "not_required",
    }
    for column, default in defaults.items():
        if column not in details_df.columns:
            details_df[column] = default
    verification_dir = benchmark_path.parent / "verification"
    verification_reports: dict[tuple[str, int], str] = {}
    for report_path in verification_dir.glob(f"{benchmark_path.stem}_*_prompt_*.json"):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            model = report.get("model")
            prompt_id = report.get("prompt_id")
            verification = report.get("verification")
            if isinstance(model, str) and isinstance(prompt_id, int) and isinstance(verification, str):
                verification_reports[(model, prompt_id)] = verification
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    if verification_reports and "prompt_id" in details_df.columns:
        prompt_ids = pd.to_numeric(details_df["prompt_id"], errors="coerce")
        resolved_verification = pd.Series(
            [
                verification_reports.get((str(model), int(prompt_id))) if pd.notna(prompt_id) else None
                for model, prompt_id in zip(details_df["model"], prompt_ids, strict=False)
            ],
            index=details_df.index,
            dtype="string",
        )
        details_df["verification_status"] = resolved_verification.fillna(details_df["verification_status"])
    return details_df
