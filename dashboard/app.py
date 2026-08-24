"""Streamlit dashboard for generic quality, security and cost screening.

Run with:
    streamlit run dashboard/app.py

The dashboard is a pre-selection aid for OpenRouter models. It surfaces
provider-neutral quality-screen confidence, security posture and operating cost;
it does not replace a domain-specific evaluation in gen-e2-eval.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.pareto import compute_pareto_front
from dashboard.security_viz import (
    build_cost_security_quadrant,
    build_owasp_heatmap,
    build_rsi_bar,
)
from src.evaluators.cost_analyzer import BUILTIN_WORKLOAD_PROFILES

_RESULTS_DIR = Path("results")

st.set_page_config(
    page_title="LLM screening dashboard",
    page_icon=":material/analytics:",
    layout="wide",
)
st.title("LLM screening dashboard")
st.caption("Generic pre-selection: quality fundamentals, security posture and monthly cost.")


@st.cache_data(show_spinner=False)
def _load_benchmark(path_text: str, modified_ns: int) -> pd.DataFrame:
    """Load a benchmark file once per modification timestamp."""
    del modified_ns
    return pd.read_csv(path_text)


def _parse_probe_details(raw: object) -> list[dict[str, object]]:
    """Parse the serialized probe details produced by the scanner safely."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed: object = json.loads(raw) if raw.lstrip().startswith("[{") else ast.literal_eval(raw)
    except (SyntaxError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, dict)]


def _security_long_frame(results_df: pd.DataFrame) -> pd.DataFrame:
    """Convert serialized probe rows into heatmap-friendly long format."""
    if "probe_details" not in results_df.columns:
        return pd.DataFrame()

    details_df = results_df[["model", "probe_details"]].copy()
    details_df["details"] = details_df["probe_details"].map(_parse_probe_details)
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
    details["vulnerability_rate"] = leaked.astype("float32")
    return details[["model", "category_id", "category_name", "vulnerability_rate"]]


def _numeric_series(results_df: pd.DataFrame, column: str, default: float = float("nan")) -> pd.Series:
    """Return a numeric column or a same-index fallback series."""
    if column not in results_df.columns:
        return pd.Series(default, index=results_df.index, dtype="float64")
    return pd.to_numeric(results_df[column], errors="coerce")


csv_files = sorted(_RESULTS_DIR.glob("*.csv"), reverse=True)
if not csv_files:
    st.warning(
        "No benchmark results found in `results/`. Run `make collect`, invoke "
        "`@judge-coordinator`, then run `make merge`."
    )
    st.stop()

selected_file = st.sidebar.selectbox(
    "Benchmark run",
    options=csv_files,
    format_func=lambda path: path.stem,
)
df = _load_benchmark(str(selected_file), selected_file.stat().st_mtime_ns)

required = {"model", "avg_quality_score", "prompt_price_per_token"}
missing = required - set(df.columns)
if missing:
    st.error(f"Missing required columns in the selected result: {sorted(missing)}")
    st.stop()

# Normalized columns used by all views. These are vectorized for one pass over
# potentially large benchmark result files.
df = df.copy()
df["cost_per_1m_tokens_usd"] = _numeric_series(df, "prompt_price_per_token", 0.0).fillna(0.0) * 1_000_000
for column, default in (("is_vulnerable", False), ("leak_count", 0), ("zero_data_retention", False)):
    if column not in df.columns:
        df[column] = default
vulnerable = df["is_vulnerable"].fillna(False).astype(bool)
leak_count = pd.to_numeric(df["leak_count"], errors="coerce").fillna(0)
df["security_status"] = (
    pd.Series("Safe", index=df.index).mask(leak_count > 0, "Partial risk").mask(vulnerable, "Vulnerable")
)

(
    tab_overview,
    tab_quality,
    tab_security,
    tab_cost,
) = st.tabs(
    [
        ":material/insights: Overview",
        ":material/fact_check: Quality screen",
        ":material/security: Security",
        ":material/payments: Cost intelligence",
    ]
)

# ── Overview ──────────────────────────────────────────────────────────────────

with tab_overview:
    plot_df = df.dropna(subset=["cost_per_1m_tokens_usd", "avg_quality_score"])
    pareto_df = compute_pareto_front(
        plot_df,
        cost_col="cost_per_1m_tokens_usd",
        quality_col="avg_quality_score",
    )

    color_map = {"Safe": "#2ecc71", "Partial risk": "#f39c12", "Vulnerable": "#e74c3c"}
    figure = go.Figure()
    for label, color in color_map.items():
        subset = plot_df.loc[plot_df["security_status"] == label]
        if subset.empty:
            continue
        figure.add_trace(
            go.Scatter(
                x=subset["cost_per_1m_tokens_usd"],
                y=subset["avg_quality_score"],
                mode="markers+text",
                name=label,
                marker=dict(color=color, size=14, line=dict(width=1, color="#333")),
                text=subset["model"].str.split("/").str[-1],
                textposition="top center",
                customdata=subset[["model", "zero_data_retention"]].values,
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "Cost / 1M input tokens: $%{x:.4f}<br>"
                    "Quality screen score: %{y:.2f}<br>"
                    "Zero data retention: %{customdata[1]}<extra></extra>"
                ),
            )
        )

    if not pareto_df.empty:
        figure.add_trace(
            go.Scatter(
                x=pareto_df["cost_per_1m_tokens_usd"],
                y=pareto_df["avg_quality_score"],
                mode="lines",
                name="Pareto frontier",
                line=dict(color="#3498db", dash="dot", width=2),
                hoverinfo="skip",
            )
        )

    figure.update_layout(
        xaxis_title="Cost per 1M input tokens (USD)",
        yaxis_title="Generic quality screen score (1–5)",
        legend_title="Security",
        height=560,
        hovermode="closest",
    )
    st.plotly_chart(figure, width="stretch")

    if not pareto_df.empty:
        with st.expander("Pareto-optimal models", expanded=True):
            overview_columns = [
                "model",
                "avg_quality_score",
                "quality_coverage_rate",
                "cost_per_1m_tokens_usd",
                "security_status",
            ]
            st.dataframe(
                pareto_df[[column for column in overview_columns if column in pareto_df.columns]],
                width="stretch",
                hide_index=True,
            )

# ── Quality screen ────────────────────────────────────────────────────────────

with tab_quality:
    st.subheader("Generic quality-screen confidence")
    st.info(
        "This is a broad pre-selection signal, not a domain recommendation. "
        "Use gen-e2-eval for task-specific acceptance testing after shortlisting."
    )

    suite_ids = df.get("quality_suite_id", pd.Series(dtype="string")).dropna().unique()
    if len(suite_ids) == 1:
        st.caption(f"Prompt suite: `{suite_ids[0]}`")
    elif len(suite_ids) > 1:
        st.warning("The selected result contains multiple quality-suite identifiers; compare it with caution.")
    else:
        st.caption("This is a legacy result without an audit-able quality-suite identifier.")

    coverage = _numeric_series(df, "quality_coverage_rate", 0.0)
    dimension_coverage = _numeric_series(df, "quality_dimension_coverage_rate", 0.0)
    stability = _numeric_series(df, "quality_stability_score")
    cer_eligible = df.get("quality_cer_eligible", pd.Series(False, index=df.index)).fillna(False).astype(bool)

    metric_columns = st.columns(4)
    metric_columns[0].metric("Models screened", len(df), border=True)
    metric_columns[1].metric("Full prompt coverage", int((coverage >= 1.0).sum()), border=True)
    metric_columns[2].metric("All dimensions covered", int((dimension_coverage >= 1.0).sum()), border=True)
    metric_columns[3].metric("CER eligible", int(cer_eligible.sum()), border=True)

    if "quality_stability_score" not in df.columns or stability.notna().sum() == 0:
        st.caption("Stability is not measured in this run. Set `QUALITY_REPETITIONS=2` or higher for a shortlist.")

    quality_columns = [
        "model",
        "avg_quality_score",
        "quality_pass_rate",
        "quality_coverage_rate",
        "quality_dimension_coverage_rate",
        "quality_stability_score",
        "quality_collection_success_rate",
        "quality_collection_error_count",
        "quality_cer_eligible",
    ]
    quality_display = df[[column for column in quality_columns if column in df.columns]].copy()
    st.dataframe(
        quality_display,
        width="stretch",
        hide_index=True,
        column_config={
            "avg_quality_score": st.column_config.NumberColumn("Quality score", format="%.2f / 5"),
            "quality_pass_rate": st.column_config.NumberColumn("Prompt pass rate", format="percent"),
            "quality_coverage_rate": st.column_config.NumberColumn("Prompt coverage", format="percent"),
            "quality_dimension_coverage_rate": st.column_config.NumberColumn("Dimension coverage", format="percent"),
            "quality_stability_score": st.column_config.NumberColumn("Stability", format="percent"),
            "quality_collection_success_rate": st.column_config.NumberColumn("Collection success", format="percent"),
            "quality_collection_error_count": st.column_config.NumberColumn("Collection errors", format="%d"),
            "quality_cer_eligible": st.column_config.CheckboxColumn("Eligible for CER"),
        },
    )

    incomplete = df.loc[(coverage < 0.8) | (dimension_coverage < 1.0), "model"].tolist()
    if incomplete:
        st.warning("CER is withheld for incomplete quality evidence: " + ", ".join(map(str, incomplete)))

# ── Security ──────────────────────────────────────────────────────────────────

with tab_security:
    st.subheader("Security analysis")
    security_df = _security_long_frame(df)
    if security_df.empty:
        st.info(
            "No per-category probe detail is available. Run with "
            "`SECURITY_PROBES_PATH=data/prompts/owasp_probes.json` to populate the OWASP heatmap."
        )
    else:
        st.plotly_chart(build_owasp_heatmap(security_df), width="stretch")

    if "rsi" in df.columns:
        st.plotly_chart(build_rsi_bar(df[["model", "rsi"]].drop_duplicates()), width="stretch")
    else:
        st.caption("The selected result does not contain a Robustness Safety Index (RSI).")

    with st.container(border=True):
        st.markdown("**Zero data retention policy**")
        zdr_df = df[["model", "zero_data_retention"]].drop_duplicates()
        st.dataframe(zdr_df, width="stretch", hide_index=True)

# ── Cost intelligence ─────────────────────────────────────────────────────────

with tab_cost:
    st.subheader("Cost intelligence")
    profile_name = st.selectbox(
        "Workload profile",
        options=list(BUILTIN_WORKLOAD_PROFILES),
        help="Select the workload used to model monthly token cost.",
    )
    profile = BUILTIN_WORKLOAD_PROFILES[profile_name]
    st.caption(
        f"{profile.daily_requests} requests/day · "
        f"{profile.avg_prompt_tokens} input tokens/request · "
        f"{profile.avg_completion_tokens} output tokens/request · "
        f"{profile.working_days_per_month} working days/month"
    )

    cost_df = df.copy()
    input_price = _numeric_series(cost_df, "prompt_price_per_token")
    completion_price = _numeric_series(cost_df, "completion_price_per_token")
    cost_df["tco_usd"] = (
        input_price * profile.monthly_prompt_tokens + completion_price * profile.monthly_completion_tokens
    )

    cost_columns = [
        "model",
        "prompt_price_per_token",
        "completion_price_per_token",
        "tco_usd",
        "actual_cost_credits",
        "actual_cost_call_count",
        "actual_cost_coverage_rate",
        "avg_quality_score",
        "quality_cer_eligible",
        "cer",
        "rsi",
    ]
    st.dataframe(
        cost_df[[column for column in cost_columns if column in cost_df.columns]],
        width="stretch",
        hide_index=True,
        column_config={
            "tco_usd": st.column_config.NumberColumn("Monthly TCO", format="$%.2f"),
            "actual_cost_credits": st.column_config.NumberColumn(
                "Actual run cost (credits)",
                format="%.8f",
            ),
            "actual_cost_call_count": st.column_config.NumberColumn("Billed calls", format="%d"),
            "actual_cost_coverage_rate": st.column_config.NumberColumn(
                "Actual cost coverage",
                format="percent",
            ),
            "avg_quality_score": st.column_config.NumberColumn("Quality score", format="%.2f / 5"),
            "cer": st.column_config.NumberColumn("Normalized CER", format="%.4f"),
            "quality_cer_eligible": st.column_config.CheckboxColumn("Eligible for CER"),
        },
    )

    if "actual_cost_coverage_rate" not in cost_df.columns:
        st.info(
            "This is a legacy result without an actual OpenRouter cost ledger. "
            "Run a new `make collect` and `make merge` to capture `response.usage.cost` per call."
        )
    else:
        actual_coverage = _numeric_series(cost_df, "actual_cost_coverage_rate", 0.0)
        if (actual_coverage < 1.0).any():
            st.warning(
                "Some completions did not return a cost in their OpenRouter usage metadata; "
                "their actual charge is marked as unavailable rather than estimated."
            )
        else:
            st.caption(
                "Actual run cost is taken directly from OpenRouter's `response.usage.cost`. "
                "The detailed ledger is exported under `results/call_costs/`."
            )

    st.download_button(
        "Download enriched results",
        data=cost_df.to_csv(index=False).encode(),
        file_name=f"benchmark_tco_{profile_name}.csv",
        mime="text/csv",
    )

    if "rsi" in cost_df.columns:
        st.plotly_chart(build_cost_security_quadrant(cost_df), width="stretch")
    else:
        st.caption("The cost-versus-security quadrant requires RSI data from an OWASP security scan.")

st.subheader("Full benchmark results")
st.dataframe(df, width="stretch", hide_index=True)
