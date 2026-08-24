# Manager Brief - OpenRouter Research Progress

Date: 2026-08-18 (updated — see revision note at the end)

## 0. What This Project Is (Plain-English Primer)

This repository ("open-router-research") automatically benchmarks Large Language
Models (LLMs) available through the [OpenRouter](https://openrouter.ai/) API
aggregator, so we can build a **shortlist** before doing a deeper, business-specific
evaluation in the sister project `gen-e2-eval`. Full pitch and positioning vs.
`gen-e2-eval`: [README.md](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/README.md) and [docs/index.md](index.md).

It scores every model on **three axes**, computed by three independent modules:

| Axis | What it measures | Code | Key outputs |
| --- | --- | --- | --- |
| Quality | Generic pre-screen (not a business benchmark) | [src/evaluators/quality_judge.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/quality_judge.py) | `avg_quality_score`, `quality_coverage_rate` |
| Security | Prompt-injection / OWASP LLM Top 10 red-teaming | [src/evaluators/security_scanner.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/security_scanner.py) | `rsi`, `leak_count`, `zero_data_retention` |
| Cost | Live pricing + projected TCO + real per-call cost | [src/evaluators/cost_analyzer.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/cost_analyzer.py) | `tco_usd`, `actual_cost_credits`, `cer` |

The pipeline runs in **3 phases**, orchestrated by [src/main.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/main.py)
and driven by `make` targets defined in [Makefile](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/Makefile):

1. **`make collect`** — calls every target model, runs cheap deterministic checks
   in pure code, and (only for the prompts that need human-like judgment) writes
   an anonymised `judging_*.json` file to `data/intermediate/`.
2. **Blind judging in Copilot chat** — invoking `@judge-coordinator` runs three
   agents in parallel ([.github/agents/judge-anthropic.agent.md](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/.github/agents/judge-anthropic.agent.md),
   `judge-openai.agent.md`, `judge-google.agent.md`), each scoring the anonymised
   responses without knowing which model produced them (no extra OpenRouter cost).
3. **`make merge`** — averages the 3 judges' scores, merges in pricing + security
   results, and exports the final `results/benchmark_<timestamp>.{csv,json}`.

The full step-by-step, including configuration variables and metric definitions,
is documented in [docs/workflow.md](workflow.md). A local dashboard
(`streamlit run dashboard/app.py`, code in [dashboard/app.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/dashboard/app.py))
plots a quality-vs-cost Pareto frontier with security colour-coding.

Architecture rationale and trade-offs are recorded as ADRs in
[docs/adr/0001-architecture-initiale.md](adr/0001-architecture-initiale.md).
Planned/in-progress engineering work is tracked in
[docs/plans/feature-pipeline-v2-1.md](plans/feature-pipeline-v2-1.md) and
[docs/plans/feature-security-cost-specialization-1.md](plans/feature-security-cost-specialization-1.md).

## 1. Executive Summary

The project is operational end-to-end for LLM pre-selection on the three axes
above. Since the previous brief, the judging system moved fully to blind
Copilot agents (no OpenRouter LLM-judge call — see
[.github/agents/judge-coordinator.agent.md](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/.github/agents/judge-coordinator.agent.md)),
and the security scanner was extended toward full OWASP LLM Top 10 coverage
(see [docs/plans/feature-security-cost-specialization-1.md](plans/feature-security-cost-specialization-1.md),
status "In progress").

The pipeline runs, exports are generated, and the engineering baseline is stable.
Current test status is strong: **155/155 tests passing** (`tests/`, run via
`make test`, up from 147 in the previous brief).

> Note: the working tree currently has substantial uncommitted changes across
> `src/`, `dashboard/`, and `docs/` (in-progress engineering work not yet
> committed). Numbers above reflect the code as it stands today, not the last
> commit.

## 2. What Is Delivered

- A 3-phase benchmark pipeline (see [src/main.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/main.py) and
  [Makefile](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/Makefile) targets `collect` / `judge` / `merge`):
  - Phase 1: collect responses + deterministic checks + security scan
  - Phase 2: blind judging via 3 Copilot agents (only for undecidable prompts)
  - Phase 3: merge scores and export final results to `results/`
- A Streamlit dashboard for quality-cost-security comparison
  ([dashboard/app.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/dashboard/app.py), [dashboard/pareto.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/dashboard/pareto.py))
- A documented and repeatable workflow ([docs/workflow.md](workflow.md))
- Cost tracking and audit-ready artifacts (per-call cost ledger exported under
  `results/call_costs/`, see [src/evaluators/cost_analyzer.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/cost_analyzer.py))
- A gen-e2-eval export script for handing off the shortlist
  ([scripts/export_gen_e2_registry.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/scripts/export_gen_e2_registry.py))

## 3. How To Read The Metrics (Simple Definitions)

### Quality Dimensions

In this project, a "dimension" means one evaluation skill family. The prompt
suite lives in [data/prompts/quality_prompts.json](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/data/prompts/quality_prompts.json)
(versioned and hashed as `quality_suite_id`, so a score is always traceable to
an exact prompt set). We currently use 6 dimensions:

- structured_output (format correctness)
- code_contract (code-level contract correctness)
- factual_sanity (basic factual correctness)
- elementary_reasoning (basic reasoning correctness)
- instruction_reliability (following explicit instructions)
- concise_communication (clarity and conciseness)

Full dimension breakdown and prompt counts: [docs/workflow.md](workflow.md), section "Stage Qualité".

### Coverage

Coverage means how complete the evaluation is. These columns are computed in
[src/evaluators/quality_judge.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/quality_judge.py):

- quality_coverage_rate: percentage of prompts successfully scored
- quality_dimension_coverage_rate: percentage of dimensions represented in the final score

If coverage is low, confidence in ranking is lower.

### Other Key Acronyms (with meaning)

- LLM (Large Language Model)
- OWASP (Open Worldwide Application Security Project) — probes defined in
  `data/prompts/owasp_probes.json`, scored by
  [src/evaluators/security_scanner.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/security_scanner.py)
- RSI (Robustness Safety Index) — 0-100 aggregate security score, see
  [docs/workflow.md](workflow.md) section "Stage Sécurité"
- ZDR (Zero Data Retention) — provider policy flag
- TCO (Total Cost of Ownership) — see
  [src/evaluators/cost_analyzer.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/cost_analyzer.py) `compute_tco`
- CER (Cost Efficiency Ratio) — `quality_score / tco_per_month`
- API (Application Programming Interface)

## 4. Important Scope Note About Free-Tier Test Runs

Free-tier test runs were useful for technical validation of the pipeline.
They are not the right basis for business decision-making because they are
affected by rate limits (`429`) and shared-pool instability. Concurrency is
capped by `MAX_CONCURRENT_REQUESTS` (default `3`) in
[src/core/config.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/core/config.py), specifically to avoid free-tier
rate limits — see also the retry/back-off logic in
[src/api/openrouter_client.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/api/openrouter_client.py).

For management decisions, we should rely on stable runs with a dedicated project API key.

## 5. Current Status (Decision-Relevant)

- Platform readiness: done
- Technical quality baseline: done (186/186 tests passing as of 2026-08-24, `make test`;
  `ruff` and `mypy --strict` both clean — see [docs/audit-2026-08-21.md](audit-2026-08-21.md))
- Spend-safety guardrails: done — a preflight warning fires when a run's estimated
  request volume exceeds OpenRouter's free-tier daily cap, and every `TARGET_MODELS`
  entry is validated against the live catalog before a run starts (`src/main.py`,
  added 2026-08-21)
- Reproducible process: done ([docs/workflow.md](workflow.md))
- Security coverage expansion (OWASP LLM Top 10): in progress, see
  [docs/plans/feature-security-cost-specialization-1.md](plans/feature-security-cost-specialization-1.md)
- Business-grade benchmark confidence: in progress (blocked by free-tier limits)

## 6. Why We Need A Dedicated OpenRouter API Key

Without a dedicated key, free-tier limits create repeated `429` errors.
This causes:

- lower coverage
- lower comparability between models
- lower confidence in shortlist decisions

A dedicated key is needed to produce stable, decision-grade benchmark runs.

Since this brief was first written, two safeguards were added to protect a paid
key from being wasted on a misconfigured run (`src/main.py`, 2026-08-21 audit):
a preflight warning when the estimated request volume would exceed OpenRouter's
free-tier cap, and validation that every `TARGET_MODELS` entry exists in the live
model catalog before a run starts. Neither replaces the need for a dedicated key,
but both reduce the risk of spending budget on an avoidable configuration error.

## 7. Cost Calculation For Initial Development Request

Goal: justify a small initial budget request for one developer.

### Step 1: Planning cost range per request

For this initial request, the relevant volume is the benchmark itself, not a
monthly `enterprise_qa` workload. The price range below is retained as a
conservative planning range from the project's live-pricing calculations; the
final amount will be measured from OpenRouter's `usage.cost` field after each
run (see [docs/workflow.md](workflow.md), section "Stage Coût").

- TCO low: 94.62 USD/month
- TCO high: 437.04 USD/month
- Benchmark volume: 63 requests per standard run, or 138 requests with the
  extended OWASP probes

Formula:

- cost_per_request = monthly_tco / monthly_requests

Results:

- low: 94.62 / 15,000 = 0.00631 USD/request
- high: 437.04 / 15,000 = 0.02914 USD/request

### Step 2: Cost per full collect run

Baseline run assumptions:

- quality: 16 prompts x 3 models = 48 requests
- security baseline: 5 probes x 3 models = 15 requests
- total baseline run: 63 requests

Formula:

- run_cost_baseline = 63 x cost_per_request

Results:

- low: 0.40 USD/run
- high: 1.84 USD/run

Security-extended run assumptions:

- quality: 48 requests
- security OWASP: 30 probes x 3 models = 90 requests
- total extended run: 138 requests

Formula:

- run_cost_extended = 138 x cost_per_request

Results:

- low: 0.87 USD/run
- high: 4.02 USD/run

### Step 3: Initial 30 USD request justification

With 30 USD, expected capacity is:

- baseline mode: about 16 to 75 runs
- extended OWASP mode: about 7 to 34 runs

This provides room for several complete validation cycles, retries, and normal
variation in token usage. The actual cost ledger will be reported after the
first runs, and any further budget request will be based on measured usage.

## 8. Management Decision Requested

- Approve one dedicated OpenRouter API key for this project
- Approve an initial 30 USD development budget
- Reassess after actual usage data from first complete cycles

## 9. 60-Second Talking Script (Simple English)

"The benchmark pipeline is now working end-to-end, and our engineering quality is strong with all tests passing (186/186 as of 2026-08-24). We can already run quality, security, and cost evaluation in one process. The current limitation is not architecture, it is free-tier rate limits, which reduce evaluation coverage and confidence. To move from technical validation to decision-grade results, we need a dedicated OpenRouter API key. I am requesting an initial budget of 30 USD, based on the actual benchmark volume of 63 requests per standard run or 138 requests with the extended OWASP probes. We will measure the real cost returned by OpenRouter after each run and report the results before requesting any further budget."

## 10. Revision Note

This brief was refreshed on 2026-08-18 to reflect the current state of the
code (test count, blind-judging architecture, OWASP security expansion) and
to add direct links to the source files behind each claim. For a from-scratch
understanding of the project, start with [README.md](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/README.md) and
[docs/index.md](index.md), then [docs/workflow.md](workflow.md) for the
step-by-step pipeline mechanics.

**2026-08-24 update:** re-verified against the current code — 186/186 tests
passing, `ruff` and `mypy --strict` clean (full findings in
[docs/audit-2026-08-21.md](audit-2026-08-21.md)). Two spend-safety guardrails
landed since the last revision (free-tier volume preflight warning,
`TARGET_MODELS` catalog validation — both in `src/main.py`). The core ask in
§8 is unchanged apart from the requested budget, and, from an engineering
standpoint, ready to send: no open blocker requires resolving before requesting
the key/budget. The repository is clean and the baseline is reproducible.
