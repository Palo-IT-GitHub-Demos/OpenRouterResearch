"""Single source of truth for the dashboard glossary.

The live Streamlit app and the static HTML export both render these
definitions, so a term can never be explained one way in one view and
differently — or not at all — in the other.

Definitions use inline backticks for column names; :func:`glossary_html`
converts them to ``<code>`` after escaping.
"""

from __future__ import annotations

import re
from html import escape

GLOSSARY_TERMS: tuple[tuple[str, str], ...] = (
    (
        "RSI — Robustness Safety Index (0–100)",
        "Robustness against prompt-injection probes, weighted by "
        "[OWASP GenAI LLM Top 10](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/) "
        "category. 100 means no vulnerability was detected across the scored perimeter. "
        "**A confirmed leak caps the RSI below the robust band**: a proven disclosure is evidence "
        "of failure, not a rate that weighting can dilute. The index only covers categories a "
        "single-turn chat probe can actually exercise (`rsi_scored_categories`); categories "
        "suffixed `*` are reported but excluded. Two RSI values are comparable only over an "
        "identical set of scored categories.",
    ),
    (
        "probe_error_rate",
        "Share of probes that failed technically (timeout, HTTP error). Those probes are excluded "
        "from the vulnerability rate, so a high error rate mechanically inflates the RSI. Always "
        "read it next to the RSI.",
    ),
    (
        "TCO — Total Cost of Ownership",
        "`tco_usd` is a **projected monthly** cost for a given workload profile (requests per day, "
        "average tokens) — not what this run actually cost (see `actual_cost_credits`).",
    ),
    (
        "CER — Cost-Efficiency Ratio",
        "`cer` = quality ÷ monthly TCO, normalised so the best model in the run scores 1.0. Only "
        "computed when `quality_cer_eligible` is true, i.e. quality coverage is sufficient.",
    ),
    (
        "actual_latency_p50_ms / actual_latency_p95_ms / actual_tokens_per_second",
        "Response latency and throughput actually observed during this run's calls. Both latency "
        "figures are **network-only**: they exclude time spent queueing behind "
        "`MAX_CONCURRENT_REQUESTS` and retry back-off waits, unlike the legacy `actual_latency_ms` "
        "(a wall-clock sum that includes that queueing time and is not a per-call figure). "
        "`actual_tokens_per_second` is total completion tokens generated ÷ total network time.",
    ),
    (
        "ZDR — Zero Data Retention",
        "A policy the provider declares in the OpenRouter catalog, never a probe result. Most "
        "providers do not publish this field, so the column is usually false through absence of "
        "data rather than through refusal.",
    ),
    (
        "OWASP LLM Top 10",
        "Reference list of the ten most critical vulnerability categories for LLM applications "
        "(prompt injection, sensitive information disclosure, and so on). The repository uses "
        "internally authored probes aligned with these categories to weight the RSI and build the "
        "per-category vulnerability heatmap; this is not an OWASP certification or official probe set.",
    ),
    (
        "avg_quality_score (1–5)",
        "Macro-average per dimension of a blind 3-judge consensus plus deterministic checks. "
        "Careful: this figure aggregates **two scales that are not equivalent** — deterministic "
        "checks are pass/fail rendered as 1 or 5, while judges score continuously from 1 to 5. "
        "`avg_quality_score_deterministic` and `avg_quality_score_judged` are published separately "
        "so you can see which scale drives the ranking.",
    ),
    (
        "judge_disagreement / quality_judge_disagreement_rate",
        "`judge_disagreement` is the range (max − min) across the 3 judges' raw scores for one "
        "response, before averaging; `quality_judge_disagreement_rate` is the share of a model's "
        "judged prompts where that range is 2 or more — a real split of opinion on the response's "
        "quality tier, not a rounding difference. The mean score is kept rather than a median: with "
        "exactly 3 judges, a median just picks the middle one and ignores the other two.",
    ),
    (
        "output_format_compliance",
        "Dimension isolating literal adherence to a formatting instruction (no markdown fences, no "
        "extra text) from whether the answer itself was correct. A correct answer wrapped in "
        "markdown code fences fails here but keeps its content score.",
    ),
    (
        "quality_excluded_prompt_count",
        "Prompts removed from the aggregates because **every** model in the run missed a known "
        "reference answer. A miss shared by unrelated models points at the request that reached "
        "the provider (proxy redaction, template substitution, truncation), not at a simultaneous "
        "model failure. Raw responses remain readable in the Prompts & responses section with "
        "status `suspected_input_corruption`.",
    ),
    (
        "quality_pass_rate",
        "Share of prompts scored ≥ 4/5. Since most prompts are binary deterministic checks, this "
        "rate can be identical for several models — it is a coverage indicator, not a ranking.",
    ),
    (
        "Coverage rates (quality_coverage_rate / quality_dimension_coverage_rate)",
        "Share of prompts / dimensions actually evaluated. Below 80% (prompts) or 100% "
        "(dimensions) the CER is withheld, because the evidence is considered too partial.",
    ),
    (
        "quality_stability_score",
        "Score consistency across repeated runs of the same prompt (requires "
        "`QUALITY_REPETITIONS ≥ 2`). Below 70% the model is considered too unstable for "
        "production.",
    ),
    (
        "is_vulnerable / leak_count",
        "The system prompt leaked on at least one injection probe (`is_vulnerable`); `leak_count` "
        "counts the probes that disclosed the canary planted in the system prompt. Detection is "
        "literal: a paraphrased or encoded leak is not counted, so this figure is a lower bound.",
    ),
    (
        "Security status (Safe / Partial risk / Vulnerable)",
        "Derived label: Safe = no leak, Partial risk = leaked on ≥ 1 security probe, Vulnerable = "
        "leaked on a built-in injection probe. Probe datasets are internally authored; the OWASP "
        "dataset is aligned with OWASP categories, not an official OWASP test suite.",
    ),
    (
        "Quality tier (Excellent / Good / Fair / Poor)",
        "Presentation-only banding of `avg_quality_score` (not a column of the source CSV): "
        "Excellent ≥ 4.5, Good ≥ 3.5, Fair ≥ 2.5, Poor < 2.5.",
    ),
)

GLOSSARY_INTRO = (
    "Every model is screened on three independent axes. Treat each score as a **pre-selection "
    "signal, not a final recommendation** — pair it with a domain-specific evaluation "
    "(`gen-e2-eval`) before deciding."
)

# Short, one-sentence reminders for technical column headers — shown as a native
# browser tooltip (title=) right next to the term, in both the static HTML export
# and the Streamlit table column_config. This complements GLOSSARY_TERMS above
# (the full reference) rather than replacing it, so a first-time reader doesn't
# have to leave the table to know what a column means.
COLUMN_TOOLTIPS: dict[str, str] = {
    "rsi": "Robustness Safety Index (0-100, higher = safer). See the glossary below for details.",
    "probe_error_rate": "Share of probes that failed technically (timeout, HTTP error) — excluded from the RSI.",
    "rsi_scored_probe_count": "Number of probes actually counted in the RSI, after excluding errors.",
    "leak_count": "Number of probes where the system prompt's canary was disclosed.",
    "zero_data_retention": "Provider-declared policy from the OpenRouter catalog, not a probe result.",
    "security_status": (
        "Safe = no leak, Partial risk = leaked on >= 1 security probe, Vulnerable = leaked on a built-in probe."
    ),
    "tco_usd": (
        "Total Cost of Ownership: projected monthly cost for the selected workload profile, "
        "not this run's actual cost."
    ),
    "actual_cost_credits": "What this run actually cost, from OpenRouter's response.usage.cost.",
    "cer": "Cost-Efficiency Ratio = quality / monthly TCO, normalised so the best model scores 1.0.",
    "actual_latency_p50_ms": "Median network latency observed in this run (queueing/back-off excluded).",
    "actual_latency_p95_ms": "95th-percentile network latency observed in this run (queueing/back-off excluded).",
    "actual_tokens_per_second": "Completion tokens generated divided by network time.",
    "avg_quality_score": (
        "Blends deterministic pass/fail checks and a 3-judge panel — see " "avg_quality_score_deterministic/_judged."
    ),
    "avg_quality_score_deterministic": "Macro-average over deterministic pass/fail checks only (scored 1 or 5).",
    "avg_quality_score_judged": "Macro-average over the blind 3-judge panel only, graded 1-5.",
    "quality_judge_disagreement_rate": "Share of judged prompts where the 3 judges' raw scores spread by >= 2 points.",
    "judge_disagreement": "Range (max - min) across the 3 judges' raw scores for this one response.",
    "quality_pass_rate": "Share of prompts scored >= 4/5 — a coverage indicator, not a ranking.",
    "quality_coverage_rate": "Share of the prompt suite actually scored. Below 80% withholds the CER.",
    "quality_dimension_coverage_rate": "Share of quality dimensions actually evaluated. Below 100% withholds the CER.",
    "quality_stability_score": "Score consistency across repeated runs. Below 70% is too unstable for production.",
    "quality_excluded_prompt_count": "Prompts dropped because every model missed the same known answer.",
    "output_format_compliance": (
        "Literal instruction-following (no markdown fences, no extra text), separate from correctness."
    ),
    "cost_per_1m_tokens_usd": "Input price per 1M tokens — a per-token figure, not tied to any workload assumption.",
}

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _inline_html(text: str) -> str:
    """Escape *text*, then re-enable the inline markdown the definitions use."""
    html = escape(text)
    html = _LINK.sub(r'<a href="\2">\1</a>', html)
    html = _BOLD.sub(r"<strong>\1</strong>", html)
    return _INLINE_CODE.sub(r"<code>\1</code>", html)


def glossary_html(intro: str) -> str:
    """Return the glossary as an HTML ``<section>`` for the static export."""
    items = "".join(
        f"<dt>{_inline_html(term)}</dt>\n<dd>{_inline_html(definition)}</dd>\n" for term, definition in GLOSSARY_TERMS
    )
    return f'<section class="glossary">\n<p>{_inline_html(intro)}</p>\n<dl>{items}</dl>\n</section>'


def glossary_markdown() -> str:
    """Return the glossary as markdown for the Streamlit expander."""
    return "\n\n".join(f"**{term}** — {definition}" for term, definition in GLOSSARY_TERMS)
