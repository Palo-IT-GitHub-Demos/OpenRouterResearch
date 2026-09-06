"""Streamlit dashboard for generic quality, security and cost screening.

Run with:
    streamlit run dashboard/app.py

The dashboard is a pre-selection aid for OpenRouter models. It surfaces
provider-neutral quality-screen confidence, security posture and operating cost;
it does not replace a domain-specific evaluation in gen-e2-eval.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from dashboard.data_prep import best_row as _best_row
from dashboard.data_prep import compute_cost_columns, enrich_benchmark
from dashboard.data_prep import load_quality_details as _load_quality_details
from dashboard.data_prep import numeric_series as _numeric_series
from dashboard.data_prep import parse_judge_verdicts as _parse_judge_verdicts
from dashboard.data_prep import quality_dimension_long_frame as _quality_dimension_long_frame
from dashboard.data_prep import quality_tier as _quality_tier
from dashboard.data_prep import safest_summary as _safest_summary
from dashboard.data_prep import security_long_frame as _security_long_frame
from dashboard.data_prep import security_probe_details_frame as _security_probe_details_frame
from dashboard.data_prep import short_name as _short_name
from dashboard.data_prep import tint_status as _tint_status
from dashboard.glossary import glossary_markdown as _glossary_markdown
from dashboard.pareto import build_pareto_scatter, compute_pareto_front
from dashboard.performance_viz import build_latency_bar
from dashboard.quality_viz import build_quality_dimension_heatmap
from dashboard.security_viz import (
    build_cost_security_quadrant,
    build_owasp_heatmap,
    build_rsi_bar,
)
from src.core.model_presets import MODEL_PRESETS
from src.evaluators.cost_analyzer import BUILTIN_WORKLOAD_PROFILES

_RESULTS_DIR = Path("results")
_SECURITY_MODE_HELP = {
    "basic": "5 built-in probes — fastest, always available.",
    "owasp": "30 probes across the OWASP GenAI LLM Top 10 2026 (10 categories) — populates the heatmap/RSI below.",
    "extended": "15 advanced jailbreak/obfuscation probes (base64, unicode smuggling, DAN, payload splitting…).",
}

st.set_page_config(
    page_title="LLM Model Screening dashboard",
    page_icon=":material/analytics:",
    layout="wide",
)
st.title("LLM Model Screening dashboard")
st.caption("Generic pre-selection: quality fundamentals, security posture and monthly cost.")

with st.expander(":material/help: How to read this dashboard", expanded=False):
    st.markdown(
        "Every model is screened on **three independent axes**. Treat every score below as a "
        "pre-selection signal, not a final recommendation — pair it with a domain-specific "
        "evaluation (`gen-e2-eval`) before deciding.\n"
        "\n"
        "**:material/fact_check: Quality (1–5)** — `avg_quality_score` blends two scales that are "
        "*not* interchangeable: deterministic pass/fail checks (scored 1 or 5) and a blind consensus "
        "of 3 LLM judges (graded 1–5). `avg_quality_score_deterministic` and "
        "`avg_quality_score_judged` are published side by side so you can see which scale drives a "
        "model's rank. `quality_judge_disagreement_rate` is the share of judged prompts where the 3 "
        "judges' raw scores spread by 2 points or more — the average alone hides this. "
        "`output_format_compliance` isolates literal instruction-following (no markdown "
        "fences, no extra text) from whether the answer was actually correct. Coverage rates below "
        "100% mean the score rests on partial evidence, and `quality_stability_score` below 70% is too "
        "unstable for production. `quality_excluded_prompt_count` counts prompts dropped from the "
        "aggregates because *every* model missed a known answer — the usual cause is the request being "
        "altered before it reached the provider, not a simultaneous model failure. The heatmap on that "
        "tab breaks the score down per dimension, and the **Prompts & responses** tab shows the exact "
        "text sent to and returned by each model.\n"
        "\n"
        "**:material/security: Security (RSI 0–100)** — `rsi` weighs OWASP LLM Top 10 categories by "
        "criticality, over the categories a single-turn chat probe can actually exercise "
        "(`rsi_scored_categories`); categories marked `*` are reported but excluded. A **confirmed "
        "leak caps the RSI below the robust band**, because a proven disclosure is evidence of "
        "failure, not a rate to be averaged away. `is_vulnerable` / `leak_count` flag a system-prompt "
        "leak on a probe, `probe_error_rate` is the share of probes that failed technically (those are "
        "excluded from the rate, so read them together), and `zero_data_retention` is a provider "
        "policy flag, not a probe result. The **Prompts & responses** tab (switch its Axis toggle to "
        "Security) shows the exact probe text and each model's raw reply, per OWASP category.\n"
        "\n"
        "**:material/payments: Cost** — `tco_usd` is a *projected* monthly cost for a workload "
        "profile, not real spend. `actual_cost_credits` is what this specific run was actually "
        "billed, and `cer` is quality ÷ cost, normalized so the best model in the run scores 1.0.\n"
        "\n"
        "**:material/speed: Performance** — `actual_latency_p50_ms`/`actual_latency_p95_ms` are the "
        "actual network response time observed during this run, excluding time spent queueing behind "
        "`MAX_CONCURRENT_REQUESTS` or waiting through a retry back-off. `actual_tokens_per_second` is "
        "completion tokens generated per second of that network time."
    )
    st.markdown("**Glossary**")
    st.markdown(_glossary_markdown())


@st.cache_data(show_spinner=False)
def _load_benchmark(path_text: str, modified_ns: int) -> pd.DataFrame:
    """Load a benchmark file once per modification timestamp."""
    del modified_ns
    return pd.read_csv(path_text)


csv_files = sorted(_RESULTS_DIR.glob("*.csv"), reverse=True)

with st.expander(":material/tune: Plan a new run — pick a model set & security mode", expanded=not csv_files):
    st.caption(
        "Generates the exact `make` command for your next `make verify` / `make collect` / "
        "`make dry-run` — copy it into your terminal. Nothing runs from the dashboard itself."
    )
    plan_col_models, plan_col_security = st.columns(2)
    with plan_col_models:
        preset_name = st.selectbox(
            "Model set",
            options=list(MODEL_PRESETS),
            format_func=lambda name: name.replace("_", " ").capitalize(),
            help="A coherent, cross-provider set of models for one comparison purpose.",
        )
        preset = MODEL_PRESETS[preset_name]
        st.caption(preset.description)
        st.dataframe(pd.DataFrame({"model": preset.models}), width="stretch", hide_index=True)
    with plan_col_security:
        security_mode = st.segmented_control(
            "Security probes",
            options=list(_SECURITY_MODE_HELP),
            default="basic",
            required=True,
            format_func=lambda mode: "OWASP" if mode == "owasp" else mode.capitalize(),
        )
        st.caption(_SECURITY_MODE_HELP[security_mode])

    st.code(
        f"make verify MODELS={preset_name} SECURITY={security_mode}\n"
        f"make collect MODELS={preset_name} SECURITY={security_mode}",
        language="bash",
    )

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
df = enrich_benchmark(df)

all_models = sorted(df["model"].unique())
selected_models = st.sidebar.multiselect(
    "Models to compare",
    options=all_models,
    default=all_models,
    help="Narrow every tab below to a subset of models.",
)
if not selected_models:
    st.warning("Select at least one model in the sidebar to see results.")
    st.stop()
df = df[df["model"].isin(selected_models)].reset_index(drop=True)
quality_details_df = _load_quality_details(selected_file)
if not quality_details_df.empty:
    quality_details_df = quality_details_df[quality_details_df["model"].isin(selected_models)]

(
    tab_overview,
    tab_quality,
    tab_transcripts,
    tab_security,
    tab_cost,
    tab_performance,
    tab_raw,
) = st.tabs(
    [
        ":material/insights: Overview",
        ":material/fact_check: Quality screen",
        ":material/forum: Prompts & responses",
        ":material/security: Security",
        ":material/payments: Cost intelligence",
        ":material/speed: Performance",
        ":material/table_rows: Raw data",
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

    best_quality = _best_row(plot_df, "avg_quality_score")
    cheapest = _best_row(plot_df, "cost_per_1m_tokens_usd", ascending=True)
    best_value = None
    if not pareto_df.empty:
        # "Sweet spot": cheapest Pareto-optimal model within 10% of the best quality score.
        quality_floor = plot_df["avg_quality_score"].max() * 0.9
        value_candidates = pareto_df.loc[pareto_df["avg_quality_score"] >= quality_floor]
        best_value = value_candidates.iloc[0] if not value_candidates.empty else pareto_df.iloc[0]
    safest_headline, safest_detail = _safest_summary(df)

    with st.container(horizontal=True):
        st.metric(
            "Highest quality",
            _short_name(best_quality["model"]) if best_quality is not None else "—",
            f"{best_quality['avg_quality_score']:.2f} / 5" if best_quality is not None else None,
            border=True,
            help="Highest `avg_quality_score` in the current selection.",
        )
        st.metric(
            "Lowest cost",
            _short_name(cheapest["model"]) if cheapest is not None else "—",
            f"${cheapest['cost_per_1m_tokens_usd']:.2f} / 1M tokens" if cheapest is not None else None,
            border=True,
            help="Lowest input-token list price in the current selection.",
        )
        st.metric(
            "Best value",
            _short_name(best_value["model"]) if best_value is not None else "—",
            "Cheapest within 10% of peak quality" if best_value is not None else None,
            border=True,
            help="Cheapest Pareto-optimal model whose quality score is within 10% of the best one.",
        )
        st.metric(
            "Safest",
            safest_headline,
            safest_detail,
            border=True,
            help=(
                "Highest Robustness Safety Index (RSI, 0–100), or the count of leak-free models "
                "if RSI isn't available."
            ),
        )

    st.caption(
        "Ideal models land toward the top-left of the chart below: high quality-screen score at low "
        "cost. The dotted line traces the Pareto frontier — every model on it avoids being beaten on "
        "cost *and* quality simultaneously by another model."
    )

    figure = build_pareto_scatter(plot_df, pareto_df)
    st.plotly_chart(figure, width="stretch")

    if not pareto_df.empty:
        with st.expander(":material/insights: Pareto-optimal models", expanded=True):
            st.caption(
                "None of these is beaten on cost *and* quality simultaneously by another model in the selection."
            )
            overview_columns = [
                "model",
                "avg_quality_score",
                "quality_coverage_rate",
                "cost_per_1m_tokens_usd",
                "security_status",
            ]
            pareto_display = pareto_df[[column for column in overview_columns if column in pareto_df.columns]]
            st.dataframe(
                pareto_display.style.map(_tint_status, subset=["security_status"]),
                width="stretch",
                hide_index=True,
                column_config={
                    "avg_quality_score": st.column_config.ProgressColumn(
                        "Quality score", format="%.2f / 5", min_value=0, max_value=5
                    ),
                    "quality_coverage_rate": st.column_config.NumberColumn("Prompt coverage", format="percent"),
                    "cost_per_1m_tokens_usd": st.column_config.NumberColumn("Cost / 1M tokens", format="$%.4f"),
                    "security_status": st.column_config.TextColumn("Security"),
                },
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

    metric_columns = st.container(horizontal=True)
    with metric_columns:
        st.metric("Models screened", len(df), border=True, help="Number of models in the current selection.")
        st.metric(
            "Full prompt coverage",
            int((coverage >= 1.0).sum()),
            border=True,
            help="Models where every prompt in the suite was successfully scored (`quality_coverage_rate` = 100%).",
        )
        st.metric(
            "All dimensions covered",
            int((dimension_coverage >= 1.0).sum()),
            border=True,
            help="Models with evidence across all 6 quality dimensions (`quality_dimension_coverage_rate` = 100%).",
        )
        st.metric(
            "CER eligible",
            int(cer_eligible.sum()),
            border=True,
            help=(
                "Models with enough coverage (≥ 80% prompts, 100% dimensions) to trust their "
                "Cost-Efficiency Ratio."
            ),
        )

    if "quality_stability_score" not in df.columns or stability.notna().sum() == 0:
        st.caption("Stability is not measured in this run. Set `QUALITY_REPETITIONS=2` or higher for a shortlist.")

    if not quality_details_df.empty and "verification_status" in quality_details_df.columns:
        verification_counts = quality_details_df["verification_status"].value_counts()
        confirmed_failures = int(verification_counts.get("confirmed_failure", 0))
        unstable_rechecks = int(verification_counts.get("unstable", 0))
        inconclusive_rechecks = int(verification_counts.get("inconclusive", 0))
        not_reproduced = int(verification_counts.get("not_reproduced", 0))
        optional_rechecks = int(verification_counts.get("optional_openrouter_recheck", 0))
        if confirmed_failures or unstable_rechecks or inconclusive_rechecks or not_reproduced:
            st.markdown("**OpenRouter reproducibility checks**")
            st.caption(
                f"Confirmed failures: {confirmed_failures} · Unstable: {unstable_rechecks} · "
                f"Not reproduced: {not_reproduced} · Inconclusive: {inconclusive_rechecks}. "
                "These checks qualify confidence; they do not replace the original run score."
            )
        elif optional_rechecks:
            st.caption(
                f"{optional_rechecks} failed objective response(s) from this k=1 run can be rechecked "
                "through OpenRouter from the command line."
            )

    quality_columns = [
        "model",
        "avg_quality_score",
        "quality_tier",
        "avg_quality_score_deterministic",
        "avg_quality_score_judged",
        "quality_judge_disagreement_rate",
        "quality_pass_rate",
        "quality_coverage_rate",
        "quality_dimension_coverage_rate",
        "quality_stability_score",
        "quality_collection_success_rate",
        "quality_collection_error_count",
        "quality_excluded_prompt_count",
        "quality_cer_eligible",
    ]
    quality_display = df[[column for column in quality_columns if column in df.columns]].copy()
    quality_display["quality_tier"] = _numeric_series(df, "avg_quality_score").map(_quality_tier)
    quality_display = quality_display[[column for column in quality_columns if column in quality_display.columns]]
    quality_display = quality_display.sort_values("avg_quality_score", ascending=False, na_position="last")
    st.dataframe(
        quality_display.style.map(_tint_status, subset=["quality_tier"]),
        width="stretch",
        hide_index=True,
        column_config={
            "avg_quality_score": st.column_config.ProgressColumn(
                "Quality score",
                help="Macro-average across 6 skill dimensions, judged blind by 3 LLMs plus deterministic checks.",
                format="%.2f / 5",
                min_value=0,
                max_value=5,
            ),
            "quality_tier": st.column_config.TextColumn(
                "At a glance",
                help=(
                    "Dashboard-only banding of the quality score: Excellent ≥ 4.5, Good ≥ 3.5, "
                    "Fair ≥ 2.5, Poor < 2.5."
                ),
            ),
            "quality_pass_rate": st.column_config.NumberColumn(
                "Prompt pass rate",
                help=(
                    "Share of prompts scored \u2265 4 out of 5. Most prompts are deterministic "
                    "pass/fail, so this rate can be identical across models and is not a ranking."
                ),
                format="percent",
            ),
            "avg_quality_score_deterministic": st.column_config.NumberColumn(
                "Deterministic",
                help=(
                    "Macro-average over deterministic checks only. These are pass/fail rendered as "
                    "1 or 5, so they move in large steps."
                ),
                format="%.2f / 5",
            ),
            "avg_quality_score_judged": st.column_config.NumberColumn(
                "Judged",
                help=(
                    "Macro-average over the blind 3-judge panel only, on a graded 1\u20135 scale. "
                    "Empty when no prompt for this model needed a judge."
                ),
                format="%.2f / 5",
            ),
            "quality_judge_disagreement_rate": st.column_config.NumberColumn(
                "Judge disagreement",
                help=(
                    "Share of judged prompts where the 3 judges' raw scores spread by \u2265 2 points — a "
                    "real split of opinion, not just rounding. High values mean the average score for "
                    "this model is less trustworthy than it looks. See the Prompts & responses tab for "
                    "which prompts disagreed."
                ),
                format="percent",
            ),
            "quality_excluded_prompt_count": st.column_config.NumberColumn(
                "Excluded prompts",
                help=(
                    "Prompts dropped from the aggregates because every model missed a known answer \u2014 "
                    "a shared miss points at the request that reached the provider, not at the models. "
                    "The raw responses are kept in the Prompts & responses tab."
                ),
                format="%d",
            ),
            "quality_coverage_rate": st.column_config.NumberColumn(
                "Prompt coverage",
                help="Share of the prompt suite that was actually scored. Below 80% withholds the CER.",
                format="percent",
            ),
            "quality_dimension_coverage_rate": st.column_config.NumberColumn(
                "Dimension coverage",
                help="Share of the 6 quality dimensions represented in the score. Below 100% withholds the CER.",
                format="percent",
            ),
            "quality_stability_score": st.column_config.NumberColumn(
                "Stability",
                help=(
                    "Consistency across repeated runs (needs QUALITY_REPETITIONS ≥ 2). Below 70% "
                    "is too unstable for production."
                ),
                format="percent",
            ),
            "quality_collection_success_rate": st.column_config.NumberColumn(
                "Collection success",
                help=(
                    "Share of API calls that succeeded at the transport level (no 429/5xx) — "
                    "separate from the quality score itself."
                ),
                format="percent",
            ),
            "quality_collection_error_count": st.column_config.NumberColumn("Collection errors", format="%d"),
            "quality_cer_eligible": st.column_config.CheckboxColumn(
                "Eligible for CER",
                help=(
                    "True when coverage is high enough to trust this model's Cost-Efficiency Ratio "
                    "on the Cost intelligence tab."
                ),
            ),
        },
    )

    incomplete = df.loc[(coverage < 0.8) | (dimension_coverage < 1.0), "model"].tolist()
    if incomplete:
        st.warning("CER is withheld for incomplete quality evidence: " + ", ".join(map(str, incomplete)))

    dimension_long_df = _quality_dimension_long_frame(df)
    if dimension_long_df.empty:
        st.caption(
            "No per-dimension breakdown in this run. Re-run `make collect` + `make merge` after this "
            "feature was added to see a score per skill dimension below."
        )
    else:
        st.plotly_chart(build_quality_dimension_heatmap(dimension_long_df), width="stretch")
        st.caption(
            "Select Quality in Prompts & responses to inspect each scored answer and the reasoning from every judge."
        )

# ── Prompts & responses ────────────────────────────────────────────────────────

with tab_transcripts:
    st.subheader("Prompts & responses")
    st.caption(
        "Exactly what was sent to each model and what it returned — useful to sanity-check a "
        "surprising quality score, or to read exactly how a security probe was answered."
    )
    transcript_axis = st.segmented_control(
        "Axis",
        options=["Quality", "Security"],
        default="Quality",
        label_visibility="collapsed",
    )

    if transcript_axis == "Security":
        transcript_df = _security_probe_details_frame(df)
        group_column, group_label = "category_name", "OWASP category"
        empty_message = (
            "No per-probe prompt/response detail in this run's `probe_details` column. Re-run "
            "`make collect` after this feature was added, then `make merge`."
        )
    else:
        transcript_df = quality_details_df.copy()
        group_column, group_label = "quality_dimension", "Dimension"
        empty_message = (
            "No prompt/response detail file found for this run. It is exported to "
            "`results/quality_details/` starting with runs merged after this feature was added — "
            "re-run `make collect` + `make merge` to populate it."
        )
    if not transcript_df.empty:
        transcript_df = transcript_df[transcript_df["model"].isin(selected_models)]

    if transcript_df.empty:
        st.info(empty_message)
    else:
        filter_models, filter_group = st.columns(2)
        with filter_models:
            picked_models = st.multiselect(
                "Model",
                options=sorted(transcript_df["model"].unique()),
                default=sorted(transcript_df["model"].unique()),
                key=f"transcript_models_{transcript_axis}",
            )
        with filter_group:
            picked_groups = st.multiselect(
                group_label,
                options=sorted(transcript_df[group_column].dropna().unique()),
                default=sorted(transcript_df[group_column].dropna().unique()),
                key=f"transcript_group_{transcript_axis}",
            )
        filtered_df = transcript_df[
            transcript_df["model"].isin(picked_models) & transcript_df[group_column].isin(picked_groups)
        ]
        st.caption(f"{len(filtered_df)} quality evidence row(s) — select one to inspect it below.")

        if transcript_axis == "Security":
            transcript_columns = ["model", "category_name", "probe", "outcome", "prompt", "response", "leaked"]
            transcript_column_config = {
                "category_name": st.column_config.TextColumn("OWASP category"),
                "probe": st.column_config.TextColumn("Probe"),
                "outcome": st.column_config.TextColumn(
                    "Outcome",
                    help="safe_refusal, confirmed_leak, inconclusive, or execution_error.",
                ),
                "prompt": st.column_config.TextColumn("Prompt", help="Full prompt is shown when you select a row."),
                "response": st.column_config.TextColumn(
                    "Response", help="Full response is shown when you select a row."
                ),
                "leaked": st.column_config.CheckboxColumn("Leaked"),
            }
        else:
            transcript_columns = [
                "model",
                "quality_dimension",
                "evidence_status",
                "verification_status",
                "prompt",
                "response",
                "score",
                "judge_disagreement",
                "source",
            ]
            transcript_column_config = {
                "quality_dimension": st.column_config.TextColumn("Dimension"),
                "evidence_status": st.column_config.TextColumn("Status"),
                "verification_status": st.column_config.TextColumn("Reproducibility check"),
                "prompt": st.column_config.TextColumn("Prompt", help="Full prompt is shown when you select a row."),
                "response": st.column_config.TextColumn(
                    "Response", help="Full response is shown when you select a row."
                ),
                "score": st.column_config.ProgressColumn("Score", format="%.1f / 5", min_value=0, max_value=5),
                "judge_disagreement": st.column_config.NumberColumn(
                    "Judge spread",
                    help=(
                        "Range (max − min) across the 3 judges' raw scores for this response, before "
                        "averaging. Empty for deterministic responses (no judge involved). ≥ 2 means the "
                        "panel disagreed on the response's quality tier, not just a rounding difference."
                    ),
                    format="%d",
                ),
            }

        event = st.dataframe(
            filtered_df[[c for c in transcript_columns if c in filtered_df.columns]],
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            column_config=transcript_column_config,
            key=f"transcript_table_{transcript_axis}",
        )
        if event.selection.rows:  # type: ignore[attr-defined]  # on_select="rerun" always returns DataframeState
            selected_row = filtered_df.iloc[event.selection.rows[0]]  # type: ignore[attr-defined]
            with st.container(border=True):
                if transcript_axis == "Security":
                    st.markdown(
                        f"**Model:** `{selected_row['model']}` &nbsp;·&nbsp; "
                        f"**Category:** `{selected_row.get('category_name', '—')}` &nbsp;·&nbsp; "
                        f"**Outcome:** `{selected_row.get('outcome', 'legacy_unverified')}`"
                    )
                else:
                    st.markdown(
                        f"**Model:** `{selected_row['model']}` &nbsp;·&nbsp; "
                        f"**Dimension:** `{selected_row.get('quality_dimension', '—')}` &nbsp;·&nbsp; "
                        f"**Score:** {selected_row.get('score', '—')}"
                    )
                    disagreement_series = pd.to_numeric(
                        pd.Series([selected_row.get("judge_disagreement")]), errors="coerce"
                    )
                    disagreement = disagreement_series.iloc[0]
                    if pd.notna(disagreement) and disagreement >= 2:
                        st.warning(
                            f"Judges disagreed by {int(disagreement)} points on this response — the average "
                            "above blends a real split of opinion, not a rounding difference."
                        )
                    if selected_row.get("evidence_status") == "Collection anomaly":
                        st.warning(
                            "This attempt was excluded from the quality score because collection failed "
                            "technically (for example, timeout or HTTP/provider error)."
                        )
                st.markdown("**Prompt sent**")
                st.text(selected_row.get("prompt", ""))
                st.markdown("**Response received**")
                st.text(selected_row.get("response", ""))
                verdicts = _parse_judge_verdicts(selected_row.get("judge_verdicts"))
                if verdicts:
                    st.markdown("**Judge verdicts**")
                    for verdict in verdicts:
                        judge_id = verdict.get("judge_id", "Unknown judge")
                        judge_score = verdict.get("score", "—")
                        st.markdown(f"**{judge_id} · {judge_score} / 5**")
                        st.write(verdict.get("reasoning", "No reasoning provided."))
                elif selected_row.get("reasoning"):
                    st.markdown("**Evaluation reasoning**")
                    st.write(selected_row["reasoning"])
                if transcript_axis == "Quality" and selected_row.get("generation_id"):
                    st.markdown("**Request diagnostics**")
                    st.code(
                        "\n".join(
                            [
                                f"generation_id: {selected_row['generation_id']}",
                                f"resolved_model: {selected_row.get('resolved_model', '')}",
                                f"request_sha256: {selected_row.get('request_sha256', '')}",
                            ]
                        ),
                        language="text",
                    )

# ── Security ──────────────────────────────────────────────────────────────────

with tab_security:
    st.subheader("Security analysis")
    st.caption(
        "Injection probes attempt to leak the system prompt across OWASP GenAI LLM Top 10 categories. "
        "This is a generic robustness screen, not a full penetration test."
    )

    zdr_count = int(df["zero_data_retention"].fillna(False).astype(bool).sum())
    with st.container(horizontal=True):
        st.metric(
            "Models scanned", len(df), border=True, help="Number of models probed in the current selection."
        )
        st.metric(
            "Flagged vulnerable",
            int((df["security_status"] == "Vulnerable").sum()),
            border=True,
            help="Models where the system prompt leaked on at least one built-in injection probe.",
        )
        st.metric(
            "Zero data retention",
            f"{zdr_count} / {len(df)}",
            border=True,
            help=(
                "Models whose provider declares a zero-retention policy in the OpenRouter catalog "
                "— a policy flag, not a probe result."
            ),
        )
        rsi_values = _numeric_series(df, "rsi") if "rsi" in df.columns else pd.Series(dtype="float64")
        if rsi_values.notna().any():
            st.metric(
                "Average RSI",
                f"{rsi_values.mean():.0f} / 100",
                border=True,
                help=(
                    "Robustness Safety Index: 100 = no vulnerability detected across "
                    "OWASP-weighted probes, 0 = every probe succeeded."
                ),
            )

    if "rsi" in df.columns:
        rsi_columns = [c for c in ("model", "rsi", "leak_count") if c in df.columns]
        st.plotly_chart(build_rsi_bar(df[rsi_columns].drop_duplicates("model")), width="stretch")
        scored_categories = df["rsi_scored_categories"].dropna().iloc[0] if "rsi_scored_categories" in df else ""
        scored_probes = _numeric_series(df, "rsi_scored_probe_count").dropna()
        perimeter = f"RSI scored over categories {scored_categories}." if scored_categories else ""
        if not scored_probes.empty:
            perimeter += f" {int(scored_probes.iloc[0])} scored probes per model."
        st.caption(
            (perimeter + " " if perimeter else "")
            + "A confirmed leak caps the RSI below the robust threshold: a proven disclosure is not "
            "a rate that weighting can dilute. Two RSI values are comparable only over the same set "
            "of scored categories."
        )
    else:
        st.caption("The selected result does not contain a Robustness Safety Index (RSI).")

    security_df = _security_long_frame(df)
    if security_df.empty:
        st.info(
            "No per-category probe detail is available. Run with "
            "`SECURITY_PROBES_PATH=data/prompts/owasp_probes.json` to populate the OWASP heatmap."
        )
    else:
        st.plotly_chart(build_owasp_heatmap(security_df), width="stretch")

    with st.container(border=True):
        st.markdown("**Security summary by model**")
        st.caption(
            "`rsi` below 50 means several OWASP categories are exploitable \u2014 exclude those models from "
            "use cases with sensitive data."
        )
        summary_columns = [
            "model",
            "security_status",
            "rsi",
            "leak_count",
            "probe_error_rate",
            "rsi_scored_probe_count",
            "zero_data_retention",
        ]
        security_summary = df[[column for column in summary_columns if column in df.columns]].drop_duplicates(
            "model"
        )
        st.dataframe(
            security_summary.style.map(_tint_status, subset=["security_status"]),
            width="stretch",
            hide_index=True,
            column_config={
                "security_status": st.column_config.TextColumn(
                    "Status",
                    help=(
                        "Safe: no leak. Partial risk: leaked on ≥ 1 probe. Vulnerable: leaked on a "
                        "built-in probe."
                    ),
                ),
                "rsi": st.column_config.ProgressColumn(
                    "RSI",
                    help=(
                        "Robustness Safety Index (0\u2013100, higher is safer). Capped below the robust "
                        "band as soon as one probe confirmed a system-prompt leak."
                    ),
                    format="%.0f",
                    min_value=0,
                    max_value=100,
                ),
                "leak_count": st.column_config.NumberColumn(
                    "Leaks",
                    help=(
                        "Number of probes where the model disclosed the scan canary planted in its "
                        "system prompt \u2014 a literal disclosure, so this under-counts paraphrased leaks."
                    ),
                    format="%d",
                ),
                "probe_error_rate": st.column_config.NumberColumn(
                    "Probe errors",
                    help=(
                        "Share of probes that failed technically. Failed probes are excluded from the "
                        "vulnerability rate, so a high value inflates the RSI \u2014 read the two together."
                    ),
                    format="percent",
                ),
                "rsi_scored_probe_count": st.column_config.NumberColumn(
                    "Scored probes (n)",
                    help="Probes actually counted in the RSI, after excluding errors and non-scored categories.",
                    format="%d",
                ),
                "zero_data_retention": st.column_config.CheckboxColumn(
                    "Zero data retention",
                    help=(
                        "Provider policy declared in the OpenRouter catalog, not a probe result. "
                        "Most providers do not publish this field, so it is usually false."
                    ),
                ),
            },
        )

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

    cost_df = compute_cost_columns(df, profile)

    cheapest_tco = _best_row(cost_df, "tco_usd", ascending=True)
    priciest_tco = _best_row(cost_df, "tco_usd", ascending=False)
    best_cer = None
    if "cer" in cost_df.columns and cost_df.get("quality_cer_eligible", pd.Series(dtype=bool)).fillna(False).any():
        best_cer = _best_row(cost_df, "cer")

    with st.container(horizontal=True):
        st.metric(
            "Cheapest monthly TCO",
            _short_name(cheapest_tco["model"]) if cheapest_tco is not None else "—",
            f"${cheapest_tco['tco_usd']:.2f}/mo" if cheapest_tco is not None else None,
            border=True,
            help="Lowest projected monthly cost under the workload profile selected above.",
        )
        st.metric(
            "Priciest monthly TCO",
            _short_name(priciest_tco["model"]) if priciest_tco is not None else "—",
            f"${priciest_tco['tco_usd']:.2f}/mo" if priciest_tco is not None else None,
            border=True,
            help="Highest projected monthly cost under the workload profile selected above.",
        )
        st.metric(
            "Best cost-efficiency (CER)",
            _short_name(best_cer["model"]) if best_cer is not None else "—",
            f"{best_cer['cer']:.4f}" if best_cer is not None else None,
            border=True,
            help="Highest quality-per-dollar among models with enough quality evidence to be CER-eligible.",
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
            "prompt_price_per_token": st.column_config.NumberColumn(
                "Input price/token", help="Live OpenRouter list price per input token (USD).", format="%.8f"
            ),
            "completion_price_per_token": st.column_config.NumberColumn(
                "Output price/token", help="Live OpenRouter list price per output token (USD).", format="%.8f"
            ),
            "tco_usd": st.column_config.NumberColumn(
                "Monthly TCO",
                help="Projected monthly cost for the workload profile selected above — not this run's actual spend.",
                format="$%.2f",
            ),
            "actual_cost_credits": st.column_config.NumberColumn(
                "Actual run cost (credits)",
                help="What this specific benchmark run was actually billed, from OpenRouter's `response.usage.cost`.",
                format="%.8f",
            ),
            "actual_cost_call_count": st.column_config.NumberColumn("Billed calls", format="%d"),
            "actual_cost_coverage_rate": st.column_config.NumberColumn(
                "Actual cost coverage",
                help=(
                    "Share of calls that returned a cost in their usage metadata. Below 100% means "
                    "some spend is unavailable rather than estimated."
                ),
                format="percent",
            ),
            "avg_quality_score": st.column_config.ProgressColumn(
                "Quality score", format="%.2f / 5", min_value=0, max_value=5
            ),
            "cer": st.column_config.ProgressColumn(
                "Normalized CER",
                help=(
                    "Quality ÷ monthly TCO, normalized so the best model in this run scores 1.0. "
                    "0 when not CER-eligible."
                ),
                format="%.4f",
                min_value=0,
                max_value=1,
            ),
            "quality_cer_eligible": st.column_config.CheckboxColumn(
                "Eligible for CER", help="False means quality coverage was too thin to trust this model's CER."
            ),
            "rsi": st.column_config.ProgressColumn(
                "RSI",
                help="Robustness Safety Index (0–100, higher is safer) — see the Security tab for detail.",
                format="%.0f",
                min_value=0,
                max_value=100,
            ),
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
        st.caption(
            f"Every model is priced on the **same** assumed monthly workload above "
            f"({profile.daily_requests} requests/day, {profile.avg_prompt_tokens} input + "
            f"{profile.avg_completion_tokens} output tokens/request) — so a cheaper `tco_usd` here "
            "means cheaper for identical usage. `avg_completion_tokens` is a workload assumption, not "
            "each model's actual reply length, so real spend will differ from this projection."
        )
    else:
        st.caption("The cost-versus-security quadrant requires RSI data from an OWASP security scan.")

with tab_performance:
    st.subheader("Performance")
    st.caption(
        "Response latency and throughput observed during this specific run — not a synthetic "
        "benchmark. Latency excludes time spent queueing behind `MAX_CONCURRENT_REQUESTS` and retry "
        "back-off waits, so it reflects the model/provider's actual response time."
    )

    performance_columns = [
        "model",
        "actual_latency_p50_ms",
        "actual_latency_p95_ms",
        "actual_tokens_per_second",
        "actual_cost_call_count",
    ]
    performance_df = df[[c for c in performance_columns if c in df.columns]].copy()
    has_latency_data = "actual_latency_p50_ms" in performance_df.columns and _numeric_series(
        performance_df, "actual_latency_p50_ms"
    ).notna().any()

    if not has_latency_data:
        st.info(
            "No per-call latency data in this run — this is expected for `make dry-run` (no real network "
            "calls) or a legacy result predating this metric. Run a new `make collect` and `make merge`."
        )
    else:
        fastest_p50 = _best_row(performance_df, "actual_latency_p50_ms", ascending=True)
        fastest_p95 = _best_row(performance_df, "actual_latency_p95_ms", ascending=True)
        best_throughput = _best_row(performance_df, "actual_tokens_per_second")

        with st.container(horizontal=True):
            st.metric(
                "Fastest median response",
                _short_name(fastest_p50["model"]) if fastest_p50 is not None else "—",
                f"{fastest_p50['actual_latency_p50_ms']:.0f} ms" if fastest_p50 is not None else None,
                border=True,
                help="Lowest p50 (median) network latency — half of this model's calls were faster than this.",
            )
            st.metric(
                "Fastest worst-case response",
                _short_name(fastest_p95["model"]) if fastest_p95 is not None else "—",
                f"{fastest_p95['actual_latency_p95_ms']:.0f} ms" if fastest_p95 is not None else None,
                border=True,
                help="Lowest p95 network latency — only 5% of this model's calls were slower than this.",
            )
            st.metric(
                "Highest throughput",
                _short_name(best_throughput["model"]) if best_throughput is not None else "—",
                f"{best_throughput['actual_tokens_per_second']:.1f} tok/s" if best_throughput is not None else None,
                border=True,
                help="Completion tokens generated per second of network time, summed across this run's calls.",
            )

        st.dataframe(
            performance_df.sort_values("actual_latency_p50_ms", na_position="last"),
            width="stretch",
            hide_index=True,
            column_config={
                "actual_latency_p50_ms": st.column_config.NumberColumn(
                    "p50 latency",
                    help="Median network latency per call, in milliseconds. Lower is faster.",
                    format="%.0f ms",
                ),
                "actual_latency_p95_ms": st.column_config.NumberColumn(
                    "p95 latency",
                    help="95th-percentile network latency per call, in milliseconds — a worst-case signal.",
                    format="%.0f ms",
                ),
                "actual_tokens_per_second": st.column_config.NumberColumn(
                    "Throughput",
                    help="Total completion tokens generated \u00f7 total network time, in tokens/second.",
                    format="%.1f",
                ),
                "actual_cost_call_count": st.column_config.NumberColumn(
                    "Calls",
                    help="Number of calls these figures are based on.",
                    format="%d",
                ),
            },
        )
        st.plotly_chart(build_latency_bar(performance_df), width="stretch")

with tab_raw:
    st.subheader("Full benchmark results")
    st.caption(
        "Every column from the selected run for the models chosen in the sidebar — useful for audits, "
        "spreadsheets, or spotting a column the curated tabs above don't surface. See “How to read this "
        "dashboard” above the tabs for column definitions."
    )
    st.dataframe(df, width="stretch", hide_index=True)
