"""Export a static, self-contained HTML snapshot of the benchmark dashboard.

Reuses the exact same data-prep (:mod:`dashboard.data_prep`) and chart-building
(:mod:`dashboard.pareto`, :mod:`dashboard.security_viz`) code as the live
Streamlit app (``dashboard/app.py``), so the static export can never drift
from the live view. The output is a single ``.html`` file — open it in any
browser, no server required — with a French glossary explaining every acronym
(RSI, TCO, CER, ZDR, OWASP...).

Usage
-----
    python scripts/export_dashboard_html.py \\
        --results results/benchmark_<ts>.csv \\
        --output  results/dashboard_<ts>.html \\
        --profile enterprise_qa

    # Uses the latest results/benchmark_*.csv and enterprise_qa by default
    python scripts/export_dashboard_html.py
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

# Running this file directly (``python scripts/export_dashboard_html.py``) does not
# put the project root on sys.path — only the script's own directory. Add it so the
# sibling `dashboard`/`src` packages (not pip-installed, unlike the editable `src`
# wheel) are importable regardless of how this script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dashboard.data_prep import (  # noqa: E402
    best_row,
    compute_cost_columns,
    enrich_benchmark,
    load_quality_details,
    load_recommendations,
    quality_dimension_long_frame,
    quality_tier,
    safest_summary,
    security_long_frame,
    security_probe_details_frame,
    short_name,
    tint_status,
)
from dashboard.glossary import COLUMN_TOOLTIPS, GLOSSARY_INTRO, glossary_html  # noqa: E402
from dashboard.pareto import build_pareto_scatter, compute_pareto_front  # noqa: E402
from dashboard.performance_viz import build_latency_bar  # noqa: E402
from dashboard.quality_viz import build_quality_dimension_heatmap  # noqa: E402
from dashboard.security_viz import build_cost_security_quadrant, build_owasp_heatmap, build_rsi_bar  # noqa: E402
from src.evaluators.cost_analyzer import BUILTIN_WORKLOAD_PROFILES, WorkloadProfile  # noqa: E402

_RESULTS_DIR = Path("results")
_REQUIRED_COLUMNS = {"model", "avg_quality_score", "prompt_price_per_token"}

_CSS = """
:root { color-scheme: light; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; padding: 2rem; max-width: 1200px; margin-inline: auto; color: #1a1a2e; }
h1 { margin-bottom: 0.25rem; }
h2 { margin-top: 2.5rem; border-bottom: 2px solid #eee; padding-bottom: 0.4rem; }
.subtitle { color: #555; margin-top: 0; }
.meta { color: #777; font-size: 0.9rem; }
section.glossary { background: #f6f8fb; border: 1px solid #e1e6ee; border-radius: 8px;
                    padding: 1.2rem 1.5rem; margin: 1.5rem 0; }
section.glossary dt { font-weight: 600; margin-top: 0.7rem; }
section.glossary dd { margin-left: 0; color: #333; }
.kpi-row { display: flex; flex-wrap: wrap; gap: 1rem; margin: 1rem 0; }
.kpi-card { flex: 1 1 220px; border: 1px solid #e1e6ee; border-radius: 8px; padding: 1rem; }
.kpi-card .label { color: #666; font-size: 0.85rem; }
.kpi-card .value { font-size: 1.4rem; font-weight: 700; margin: 0.2rem 0; }
.kpi-card .detail { color: #2e7d32; font-size: 0.85rem; }
.table-wrap { overflow-x: auto; margin: 1rem 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
th, td { border: 1px solid #e1e6ee; padding: 0.45rem 0.6rem; text-align: left; white-space: nowrap; }
th { background: #f6f8fb; }
table.wrap-table td { white-space: normal; word-break: break-word; max-width: 28rem; vertical-align: top; }
.chart { margin: 1rem 0; }
details summary { cursor: pointer; font-weight: 600; margin: 1rem 0 0.5rem; }
.callout { background: #eef4fb; border-left: 4px solid #3498db; padding: 0.7rem 1rem; margin: 1rem 0; }
nav.toc { background: #fff; border: 1px solid #e1e6ee; border-radius: 8px; padding: 1rem 1.5rem; margin: 1.5rem 0; }
nav.toc p { margin: 0 0 0.5rem; font-weight: 600; }
nav.toc ul { margin: 0; padding-left: 1.2rem; columns: 2; }
nav.toc a { color: #3498db; text-decoration: none; }
nav.toc a:hover { text-decoration: underline; }
h2 { scroll-margin-top: 1rem; }
h3 { margin-top: 1.8rem; }
"""

_GLOSSARY_INTRO = "This document is a static snapshot of the Model Compass dashboard (OpenRouter). " + GLOSSARY_INTRO

_GLOSSARY_HTML = glossary_html(_GLOSSARY_INTRO)


def _latest_results_csv() -> Path | None:
    csv_files = sorted(_RESULTS_DIR.glob("benchmark_*.csv"), reverse=True)
    return csv_files[0] if csv_files else None


_PAGES = [
    ("overview", "Overview", "index.html"),
    ("recommendations", "Model Compass", "recommendations.html"),
    ("quality", "Quality", "quality.html"),
    ("evidence", "Prompts & responses", "evidence.html"),
    ("security", "Security", "security.html"),
    ("cost", "Cost", "cost.html"),
    ("performance", "Performance", "performance.html"),
]


def _navigation_html(active_page: str, href_prefix: str = "") -> str:
    """Render the shared navigation for a static dashboard page."""
    items = "".join(
        (
            f'<li><a href="{href_prefix}{filename}" aria-current="page">{label}</a></li>'
            if page_id == active_page
            else f'<li><a href="{href_prefix}{filename}">{label}</a></li>'
        )
        for page_id, label, filename in _PAGES
    )
    return f'<nav class="toc" aria-label="Dashboard navigation"><ul>{items}</ul></nav>'


def _fig_html(fig: go.Figure, include_js: bool) -> str:
    """Render a Plotly figure to an embeddable HTML snippet.

    The first figure of every *section* must set ``include_js=True``: sections
    become standalone files in the multi-page bundle, so a section that relies
    on another one having loaded Plotly renders blank charts there.
    """
    return str(
        fig.to_html(
            full_html=False,
            include_plotlyjs="cdn" if include_js else False,
            config={"displaylogo": False},
        )
    )


def _kpi_card(label: str, value: str, detail: str) -> str:
    return (
        '<div class="kpi-card">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{value}</div>'
        f'<div class="detail">{detail}</div>'
        "</div>"
    )


_TH_HEADING = re.compile(r'(<th\s+[^>]*class="[^"]*col_heading[^"]*"[^>]*)(>)([^<]*)(</th>)')


def _annotate_header_tooltips(html: str) -> str:
    """Add a native title= tooltip to <th> headers matching a known glossary column.

    pandas Styler has no first-class per-header title attribute, so this does a
    light string post-process instead of a second render pass.
    """

    def _inject(match: re.Match[str]) -> str:
        attrs, gt, label, close = match.groups()
        tooltip = COLUMN_TOOLTIPS.get(label)
        if not tooltip:
            return match.group(0)
        return f'{attrs} title="{escape(tooltip)}"{gt}{label}{close}'

    return _TH_HEADING.sub(_inject, html)


def _table_html(
    df: pd.DataFrame,
    formats: dict[str, str] | None = None,
    status_column: str | None = None,
    table_class: str = "data-table",
) -> str:
    """Render *df* to an HTML table, escaping every cell to prevent injected markup.

    Some columns (e.g. security probe previews, or full model responses) hold
    raw LLM completions — untrusted text that must never be interpreted as
    HTML/JS by a browser. ``Styler.to_html`` does not escape by default, so
    ``format(..., escape="html")`` is mandatory here (verified against pandas 2.3).
    """
    styler = df.style.hide(axis="index").format(formats or {}, escape="html", na_rep="—")
    styler = styler.set_table_attributes(f'class="{table_class}"')
    if status_column and status_column in df.columns:
        styler = styler.map(tint_status, subset=[status_column])
    return _annotate_header_tooltips(str(styler.to_html()))


def _bool_icon(value: object) -> str:
    return "✓" if bool(value) else "—"


def _overview_section(df: pd.DataFrame) -> str:
    plot_df = df.dropna(subset=["cost_per_1m_tokens_usd", "avg_quality_score"])
    pareto_df = compute_pareto_front(plot_df, cost_col="cost_per_1m_tokens_usd", quality_col="avg_quality_score")

    best_quality = best_row(plot_df, "avg_quality_score")
    cheapest = best_row(plot_df, "cost_per_1m_tokens_usd", ascending=True)
    best_value = None
    if not pareto_df.empty:
        quality_floor = plot_df["avg_quality_score"].max() * 0.9
        value_candidates = pareto_df.loc[pareto_df["avg_quality_score"] >= quality_floor]
        best_value = value_candidates.iloc[0] if not value_candidates.empty else pareto_df.iloc[0]
    safest_headline, safest_detail = safest_summary(df)

    kpi_cards = "".join(
        [
            _kpi_card(
                "Highest quality",
                short_name(best_quality["model"]) if best_quality is not None else "—",
                f"{best_quality['avg_quality_score']:.2f} / 5" if best_quality is not None else "",
            ),
            _kpi_card(
                "Lowest cost",
                short_name(cheapest["model"]) if cheapest is not None else "—",
                f"${cheapest['cost_per_1m_tokens_usd']:.2f} / 1M tokens" if cheapest is not None else "",
            ),
            _kpi_card(
                "Best value",
                short_name(best_value["model"]) if best_value is not None else "—",
                "Cheapest within 10% of peak quality" if best_value is not None else "",
            ),
            _kpi_card("Safest", safest_headline, safest_detail),
        ]
    )

    overview_columns = ["model", "avg_quality_score", "quality_coverage_rate", "cost_per_1m_tokens_usd"]
    if "security_status" in pareto_df.columns:
        overview_columns.append("security_status")
    pareto_table = _table_html(
        pareto_df[[c for c in overview_columns if c in pareto_df.columns]],
        formats={
            "avg_quality_score": "{:.2f} / 5",
            "quality_coverage_rate": "{:.0%}",
            "cost_per_1m_tokens_usd": "${:.4f}",
        },
        status_column="security_status",
    )

    return f"""
    <h2 id="overview">Overview</h2>
    <p class="callout"><strong>How to read this:</strong> quality runs from 1 (poor) to 5 (excellent),
    while input-token cost is better when lower. The Pareto frontier highlights models that cannot be
    beaten on both quality and cost at the same time.</p>
    <div class="kpi-row">{kpi_cards}</div>
    <p class="callout">The best models sit in the top-left of the chart: high quality score for a
    low cost. The dashed line traces the Pareto frontier — no model on it is beaten on both cost
    <em>and</em> quality by another one.</p>
    <div class="chart">{_fig_html(build_pareto_scatter(plot_df, pareto_df), include_js=True)}</div>
    <h3>Pareto-optimal models</h3>
    <div class="table-wrap">{pareto_table}</div>
    """


def _quality_section(df: pd.DataFrame) -> str:
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
    quality_display = df[[c for c in quality_columns if c in df.columns]].copy()
    quality_display["quality_tier"] = df["avg_quality_score"].map(quality_tier)
    quality_display = quality_display[[c for c in quality_columns if c in quality_display.columns]]
    quality_display = quality_display.sort_values("avg_quality_score", ascending=False, na_position="last")
    if "quality_cer_eligible" in quality_display.columns:
        quality_display["quality_cer_eligible"] = quality_display["quality_cer_eligible"].map(_bool_icon)

    table = _table_html(
        quality_display,
        formats={
            "avg_quality_score": "{:.2f} / 5",
            "avg_quality_score_deterministic": "{:.2f} / 5",
            "avg_quality_score_judged": "{:.2f} / 5",
            "quality_judge_disagreement_rate": "{:.0%}",
            "quality_pass_rate": "{:.0%}",
            "quality_coverage_rate": "{:.0%}",
            "quality_dimension_coverage_rate": "{:.0%}",
            "quality_stability_score": "{:.0%}",
            "quality_collection_success_rate": "{:.0%}",
            "quality_collection_error_count": "{:.0f}",
            "quality_excluded_prompt_count": "{:.0f}",
        },
        status_column="quality_tier",
    )

    dimension_long_df = quality_dimension_long_frame(df)
    heatmap = ""
    if not dimension_long_df.empty:
        heatmap = (
            f'<div class="chart">{_fig_html(build_quality_dimension_heatmap(dimension_long_df), include_js=True)}'
            "</div>"
        )

    return f"""
    <h2 id="quality">Quality screen</h2>
    <p class="callout"><strong>How to read this:</strong> the quality score is an average from 1 (poor)
    to 5 (excellent). Coverage tells you how much of the test was completed; stability tells you whether
    repeated tests agree; CER eligibility means there is enough evidence to compare value.</p>
    <p class="callout">Generic pre-selection signal — not a business recommendation.
    Use <code>gen-e2-eval</code> for a use-case evaluation after this screening.</p>
    <div class="table-wrap">{table}</div>
    {heatmap}
    """


def _recommendations_section(recommendations_df: pd.DataFrame) -> str:
    """Render the Model Compass use-case/model recommendation table."""
    if recommendations_df.empty:
        return """
        <h2 id="recommendations">Model Compass</h2>
        <p class="callout">No Model Compass recommendation artifact is available for this run.
        Re-run <code>make collect</code>, complete the judge phase, then run <code>make merge</code>.</p>
        """

    columns = [
        "use_case_name",
        "model",
        "recommendation_status",
        "recommendation_rank",
        "recommendation_score",
        "quality_score",
        "quality_coverage_rate",
        "security_score",
        "cost_score",
        "performance_score",
        "evidence_missing",
    ]
    display = recommendations_df[[column for column in columns if column in recommendations_df.columns]].copy()
    table = _table_html(
        display,
        formats={
            "recommendation_rank": "{:.0f}",
            "recommendation_score": "{:.1f} / 100",
            "quality_score": "{:.2f} / 5",
            "quality_coverage_rate": "{:.0%}",
            "security_score": "{:.1f}",
            "cost_score": "{:.1f}",
            "performance_score": "{:.1f}",
        },
        status_column="recommendation_status",
    )
    catalog_version = escape(str(recommendations_df["catalog_version"].iloc[0]))
    return f"""
    <h2 id="recommendations">Model Compass</h2>
    <p class="callout"><strong>How to read this:</strong> every model remains visible for every
    generic use case. A model must first pass that use case's quality threshold; only then can the
    weighted decision score rank it. Equal scores keep the same rank. The final choice remains human.</p>
    <p class="meta">Use-case catalog: <strong>{catalog_version}</strong> · Weights: quality 50%,
    security 25%, cost 20%, performance 5%.</p>
    <div class="table-wrap">{table}</div>
    """


def _prompts_responses_section(quality_details_df: pd.DataFrame, security_probe_df: pd.DataFrame) -> str:
    quality_block = """
    <p class="callout">No prompt/response detail file for this run — available under
    <code>results/quality_details/</code> for runs merged after this feature was added.</p>
    """
    if not quality_details_df.empty:
        evidence_status = quality_details_df.get("evidence_status", pd.Series("Scored", index=quality_details_df.index))
        scored_df = quality_details_df.loc[evidence_status == "Scored"]
        anomalies_df = quality_details_df.loc[evidence_status == "Collection anomaly"]
        quality_parts: list[str] = []
        if not scored_df.empty:
            transcript_columns = [
                "model",
                "quality_dimension",
                "prompt",
                "response",
                "score",
                "judge_disagreement",
                "verification_status",
                "source",
                "reasoning",
            ]
            quality_table = _table_html(
                scored_df[[c for c in transcript_columns if c in scored_df.columns]],
                formats={"score": "{:.1f} / 5", "judge_disagreement": "{:.0f}"},
                table_class="data-table wrap-table",
            )
            quality_parts.append(
                f"""
                <details>
                  <summary>Show the {len(scored_df)} scored quality evaluation(s)</summary>
                  <div class="table-wrap">{quality_table}</div>
                </details>
                """
            )
        if not anomalies_df.empty:
            diagnostic_columns = [
                "model",
                "quality_dimension",
                "prompt",
                "response",
                "error",
                "verification_status",
                "generation_id",
                "resolved_model",
                "request_sha256",
            ]
            diagnostics_table = _table_html(
                anomalies_df[[c for c in diagnostic_columns if c in anomalies_df.columns]],
                table_class="data-table wrap-table",
            )
            quality_parts.append(
                f"""
                <p class="callout"><strong>{len(anomalies_df)} collection anomaly/anomalies excluded
                from the quality score.</strong> These attempts failed technically (for example a
                timeout or an HTTP/provider error); the identifiers let you investigate the call.</p>
                <details open>
                  <summary>Show collection diagnostics</summary>
                  <div class="table-wrap">{diagnostics_table}</div>
                </details>
                """
            )
        quality_block = "".join(quality_parts)

    security_block = """
    <p class="callout">No per-probe detail in this run (<code>probe_details</code> column missing or
    empty) — re-run <code>make collect</code> then <code>make merge</code>.</p>
    """
    if not security_probe_df.empty:
        probe_columns = ["model", "category_name", "probe", "outcome", "prompt", "response", "leaked"]
        security_probe_display = security_probe_df[[c for c in probe_columns if c in security_probe_df.columns]].copy()
        if "leaked" in security_probe_display.columns:
            security_probe_display["leaked"] = security_probe_display["leaked"].map(_bool_icon)
        for column in ("prompt", "response"):
            if column in security_probe_display.columns:
                # Scans predating these fields default to "" (see security_probe_details_frame),
                # not NaN, so na_rep alone wouldn't render the usual "—" placeholder here.
                security_probe_display[column] = security_probe_display[column].replace("", "—")
        security_table = _table_html(security_probe_display, table_class="data-table wrap-table")
        security_block = f"""
        <details>
          <summary>Show the {len(security_probe_df)} security probe(s)</summary>
          <div class="table-wrap">{security_table}</div>
        </details>
        """

    return f"""
    <h2 id="prompts-responses">Prompts &amp; responses</h2>
    <p class="callout">Exactly what was sent to each model and what it replied — for the quality
    prompts scored in this run, and for every security probe sent.</p>
    <h3>Quality</h3>
    {quality_block}
    <h3>Security</h3>
    {security_block}
    """


def _security_section(df: pd.DataFrame) -> str:
    charts = ""
    if "rsi" in df.columns:
        rsi_columns = [c for c in ("model", "rsi", "leak_count") if c in df.columns]
        rsi_fig = build_rsi_bar(df[rsi_columns].drop_duplicates("model"))
        charts += f'<div class="chart">{_fig_html(rsi_fig, include_js=True)}</div>'

    security_long = security_long_frame(df)
    if not security_long.empty:
        heatmap = build_owasp_heatmap(security_long)
        charts += f'<div class="chart">{_fig_html(heatmap, include_js=not charts)}</div>'

    summary_columns = [
        "model",
        "security_status",
        "rsi",
        "leak_count",
        "probe_error_rate",
        "rsi_scored_probe_count",
        "zero_data_retention",
    ]
    summary = df[[c for c in summary_columns if c in df.columns]].drop_duplicates("model").copy()
    if "zero_data_retention" in summary.columns:
        summary["zero_data_retention"] = summary["zero_data_retention"].map(_bool_icon)
    table = _table_html(
        summary,
        formats={
            "rsi": "{:.0f}",
            "leak_count": "{:.0f}",
            "probe_error_rate": "{:.0%}",
            "rsi_scored_probe_count": "{:.0f}",
        },
        status_column="security_status",
    )

    perimeter = ""
    if "rsi_scored_categories" in df.columns:
        scored = df["rsi_scored_categories"].dropna()
        if not scored.empty and str(scored.iloc[0]):
            perimeter = (
                f" RSI scored over categories <code>{escape(str(scored.iloc[0]))}</code>; "
                "columns suffixed <code>*</code> are reported but excluded from the calculation."
            )

    return f"""
    <h2 id="security">Security</h2>
    <p class="callout"><strong>How to read this:</strong> RSI is a safety score from 0 to 100, where
    higher is safer. A leak means a probe exposed hidden instructions. Probe errors are technical
    failures, not safe answers, so read the error rate beside RSI. ZDR is a provider data-retention
    policy, not a probe result.</p>
    <p class="callout">Injection probes try to leak the system prompt across the OWASP GenAI LLM
    Top 10 categories — a generic robustness screening, not a full penetration test. A confirmed
    leak caps the RSI below the robust threshold.{perimeter}</p>
    {charts}
    <h3>Security summary by model</h3>
    <div class="table-wrap">{table}</div>
    """


def _cost_section(df: pd.DataFrame, profile_name: str, profile: WorkloadProfile) -> str:
    cost_df = compute_cost_columns(df, profile)

    cheapest_tco = best_row(cost_df, "tco_usd", ascending=True)
    priciest_tco = best_row(cost_df, "tco_usd", ascending=False)
    best_cer = None
    if "cer" in cost_df.columns and cost_df.get("quality_cer_eligible", pd.Series(dtype=bool)).fillna(False).any():
        best_cer = best_row(cost_df, "cer")

    kpi_cards = "".join(
        [
            _kpi_card(
                "Cheapest monthly TCO",
                short_name(cheapest_tco["model"]) if cheapest_tco is not None else "—",
                f"${cheapest_tco['tco_usd']:.2f}/mo" if cheapest_tco is not None else "",
            ),
            _kpi_card(
                "Priciest monthly TCO",
                short_name(priciest_tco["model"]) if priciest_tco is not None else "—",
                f"${priciest_tco['tco_usd']:.2f}/mo" if priciest_tco is not None else "",
            ),
            _kpi_card(
                "Best cost-efficiency (CER)",
                short_name(best_cer["model"]) if best_cer is not None else "—",
                f"{best_cer['cer']:.4f}" if best_cer is not None else "",
            ),
        ]
    )

    cost_columns = [
        "model",
        "prompt_price_per_token",
        "completion_price_per_token",
        "tco_usd",
        "actual_cost_credits",
        "avg_quality_score",
        "cer",
        "rsi",
    ]
    cost_display = cost_df[[c for c in cost_columns if c in cost_df.columns]]
    table = _table_html(
        cost_display,
        formats={
            "prompt_price_per_token": "${:.8f}",
            "completion_price_per_token": "${:.8f}",
            "tco_usd": "${:.2f}",
            "actual_cost_credits": "${:.8f}",
            "avg_quality_score": "{:.2f} / 5",
            "cer": "{:.4f}",
            "rsi": "{:.0f}",
        },
    )

    quadrant = ""
    if "rsi" in cost_df.columns:
        quadrant = f"""
        <div class="chart">{_fig_html(build_cost_security_quadrant(cost_df), include_js=True)}</div>
        <p class="callout">Every model is priced on the <strong>same</strong> assumed monthly workload
        above ({profile.daily_requests} requests/day, {profile.avg_prompt_tokens} input +
        {profile.avg_completion_tokens} output tokens/request) — so a cheaper <code>tco_usd</code> here
        means cheaper for identical usage. <code>avg_completion_tokens</code> is a workload assumption,
        not each model's actual reply length, so real spend will differ from this projection.</p>
        """

    return f"""
    <h2 id="cost">Cost intelligence</h2>
    <p class="callout"><strong>How to read this:</strong> TCO is the estimated monthly bill for the
    selected usage pattern, not the cost of this benchmark. CER is quality per dollar, normalised so
    1.0 is the best eligible model in this comparison. Actual run cost is what OpenRouter reported.</p>
    <p class="meta">Workload profile: <strong>{profile_name}</strong> —
    {profile.daily_requests} requests/day · {profile.avg_prompt_tokens} input tokens/request ·
    {profile.avg_completion_tokens} output tokens/request · {profile.working_days_per_month}
    working days/month. Re-run with <code>--profile</code> for another profile.</p>
    <div class="kpi-row">{kpi_cards}</div>
    <div class="table-wrap">{table}</div>
    {quadrant}
    """


def _performance_section(df: pd.DataFrame) -> str:
    performance_columns = [
        "model",
        "actual_latency_p50_ms",
        "actual_latency_p95_ms",
        "actual_tokens_per_second",
        "actual_cost_call_count",
    ]
    performance_df = df[[c for c in performance_columns if c in df.columns]].copy()
    has_latency_data = (
        "actual_latency_p50_ms" in performance_df.columns
        and pd.to_numeric(performance_df["actual_latency_p50_ms"], errors="coerce").notna().any()
    )

    if not has_latency_data:
        return """
        <h2 id="performance">Performance</h2>
        <p class="callout"><strong>How to read this:</strong> p50 is the typical response time, p95 is a
        slower-case response time, and tokens/second is how quickly the model generated its answer. Lower
        latency and higher throughput are generally better.</p>
        <p class="callout">No per-call latency data in this run \u2014 expected for <code>make dry-run</code>
        (no real network calls) or a legacy result predating this metric. Run a new <code>make collect</code>
        and <code>make merge</code>.</p>
        """

    fastest_p50 = best_row(performance_df, "actual_latency_p50_ms", ascending=True)
    fastest_p95 = best_row(performance_df, "actual_latency_p95_ms", ascending=True)
    best_throughput = best_row(performance_df, "actual_tokens_per_second")

    kpi_cards = "".join(
        [
            _kpi_card(
                "Fastest median response",
                short_name(fastest_p50["model"]) if fastest_p50 is not None else "\u2014",
                f"{fastest_p50['actual_latency_p50_ms']:.0f} ms" if fastest_p50 is not None else "",
            ),
            _kpi_card(
                "Fastest worst-case response",
                short_name(fastest_p95["model"]) if fastest_p95 is not None else "\u2014",
                f"{fastest_p95['actual_latency_p95_ms']:.0f} ms" if fastest_p95 is not None else "",
            ),
            _kpi_card(
                "Highest throughput",
                short_name(best_throughput["model"]) if best_throughput is not None else "\u2014",
                f"{best_throughput['actual_tokens_per_second']:.1f} tok/s" if best_throughput is not None else "",
            ),
        ]
    )

    table = _table_html(
        performance_df.sort_values("actual_latency_p50_ms", na_position="last"),
        formats={
            "actual_latency_p50_ms": "{:.0f} ms",
            "actual_latency_p95_ms": "{:.0f} ms",
            "actual_tokens_per_second": "{:.1f}",
            "actual_cost_call_count": "{:.0f}",
        },
    )
    chart = f'<div class="chart">{_fig_html(build_latency_bar(performance_df), include_js=True)}</div>'

    return f"""
    <h2 id="performance">Performance</h2>
    <p class="callout">Response latency and throughput observed during this specific run \u2014 not a
    synthetic benchmark. Latency excludes time spent queueing behind <code>MAX_CONCURRENT_REQUESTS</code>
    and retry back-off waits, so it reflects the model/provider's actual response time.</p>
    <div class="kpi-row">{kpi_cards}</div>
    <div class="table-wrap">{table}</div>
    {chart}
    """


def _raw_data_section(df: pd.DataFrame) -> str:
    # probe_details holds raw model completions from injection probes — never trust it as HTML.
    safe_columns = [c for c in df.columns if c != "probe_details"]
    table = _table_html(df[safe_columns])
    return f"""
    <h2 id="raw-data">Raw data</h2>
    <details>
      <summary>
        Show all columns ({len(safe_columns)} columns; probe_details omitted, see the source CSV)
      </summary>
      <div class="table-wrap">{table}</div>
    </details>
    """


def build_page(
    df: pd.DataFrame,
    profile_name: str,
    profile: WorkloadProfile,
    source_label: str,
    page_title: str,
    active_page: str,
    page_body: str,
    href_prefix: str = "",
) -> str:
    """Assemble one standalone page of the static dashboard."""
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Compass — {page_title}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Model Compass dashboard</h1>
<p class="subtitle">Evidence-based selection of OpenRouter models by generic use case.</p>
<p class="meta">Source: {source_label} — generated on {generated_at}</p>
{_navigation_html(active_page, href_prefix)}
{page_body}
</body>
</html>"""


def build_reports(
    df: pd.DataFrame,
    profile_name: str,
    profile: WorkloadProfile,
    source_label: str,
    quality_details_df: pd.DataFrame | None = None,
    recommendations_df: pd.DataFrame | None = None,
) -> dict[str, str]:
    """Build the named pages that form one static dashboard bundle."""
    security_probe_df = security_probe_details_frame(df)
    quality_details = quality_details_df if quality_details_df is not None else pd.DataFrame()
    recommendations = recommendations_df if recommendations_df is not None else pd.DataFrame()
    pages = {
        "index.html": ("Overview", "overview", f"{_GLOSSARY_HTML}{_overview_section(df)}"),
        "recommendations.html": ("Model Compass", "recommendations", _recommendations_section(recommendations)),
        "quality.html": ("Quality", "quality", _quality_section(df)),
        "evidence.html": (
            "Prompts & responses",
            "evidence",
            f"{_prompts_responses_section(quality_details, security_probe_df)}{_raw_data_section(df)}",
        ),
        "security.html": ("Security", "security", _security_section(df)),
        "cost.html": ("Cost", "cost", _cost_section(df, profile_name, profile)),
        "performance.html": ("Performance", "performance", _performance_section(df)),
    }
    return {
        filename: build_page(
            df,
            profile_name,
            profile,
            source_label,
            page_title,
            active_page,
            page_body,
        )
        for filename, (page_title, active_page, page_body) in pages.items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a static HTML snapshot of the benchmark dashboard.")
    parser.add_argument("--results", type=Path, default=None, help="Benchmark CSV (default: latest in results/)")
    parser.add_argument(
        "--output", type=Path, default=None, help="Output HTML path (default: results/dashboard_<ts>.html)"
    )
    parser.add_argument("--profile", default="enterprise_qa", help="Workload profile for the Cost section")
    args = parser.parse_args(argv)

    results_path = args.results or _latest_results_csv()
    if results_path is None or not results_path.exists():
        print("No benchmark CSV found. Pass --results or run `make collect` + `make merge` first.", file=sys.stderr)
        return 1

    profile = BUILTIN_WORKLOAD_PROFILES.get(args.profile)
    if profile is None:
        print(f"Unknown profile '{args.profile}'. Available: {list(BUILTIN_WORKLOAD_PROFILES)}", file=sys.stderr)
        return 1

    df = pd.read_csv(results_path)
    missing = _REQUIRED_COLUMNS - set(df.columns)
    if missing:
        print(f"Missing required columns in {results_path}: {sorted(missing)}", file=sys.stderr)
        return 1
    df = enrich_benchmark(df)

    output_path = args.output
    if output_path is None:
        suffix = results_path.stem.removeprefix("benchmark_")
        output_path = _RESULTS_DIR / f"dashboard_{suffix}.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    quality_details_df = load_quality_details(results_path)
    recommendations_df = load_recommendations(results_path)
    bundle_dir = output_path.with_suffix("")
    bundle_dir.mkdir(parents=True, exist_ok=True)
    reports = build_reports(df, args.profile, profile, results_path.name, quality_details_df, recommendations_df)
    for filename, html_doc in reports.items():
        (bundle_dir / filename).write_text(html_doc, encoding="utf-8")

    # Keep the requested output path as the opening page, while linked pages live
    # in a sibling directory that can be copied or opened as a complete bundle.
    output_path.write_text(
        build_page(
            df,
            args.profile,
            profile,
            results_path.name,
            "Vue d'ensemble",
            "overview",
            f"{_GLOSSARY_HTML}{_overview_section(df)}",
            href_prefix=f"{bundle_dir.name}/",
        ),
        encoding="utf-8",
    )
    print(f"Wrote {output_path} and navigable pages in {bundle_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
