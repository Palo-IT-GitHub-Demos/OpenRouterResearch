# llm-model-screening — LLM Evaluation Pipeline (LLMOps)

> Automated, scalable screening of large language models available on
> [OpenRouter](https://openrouter.ai/) across three critical axes: **Quality**,
> **Cost**, and **Security**.
>
> Built at **Palo IT Singapore** to guide architecture choices for enterprise clients.

---

## Overview

This pipeline screens LLMs available through the OpenRouter API aggregator and
produces a comparison matrix for building a shortlist. Results are exported as
CSV/JSON and visualised in a local Streamlit dashboard with a **Pareto
frontier** overlay (best quality-to-cost trade-off).

It is a cross-provider screening tool, not a business benchmark. It measures
generic quality fundamentals together with cost, latency and security to reduce
the number of models to evaluate in the sister project
[`gen-e2-eval`](https://github.com/GLOBAL-PALO-IT/gen-e2-eval).

### Scope boundary

LLM Model Screening answers: **"Which models are worth evaluating further?"**

It does not answer: **"Which model is best for this specific business
workflow?"** That decision belongs to `gen-e2-eval`, using client-specific
tasks, reference data and functional evaluation. A result from this repository
must therefore be treated as a shortlist signal, never as a final adoption
recommendation.

### Evaluation axes

| Axis               | Method                                                                                                                                                                                              | Key metric                                              |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| **Quality**  | Versioned generic screen: deterministic contracts + blind LLM-as-a-Judge for open prompts                                                                                                           | Macro-average 1–5 by dimension, coverage and stability |
| **Cost**     | Live price projection + OpenRouter`response.usage.cost` ledger                                                                                                                                    | TCO monthly + actual credits per call                   |
| **Security** | 5 built-in prompt-injection probes, or a named`SECURITY_MODE` (`owasp`: 30 probes / OWASP GenAI LLM Top 10 2026, `extended`: 15 advanced jailbreak probes) + Zero Data Retention policy check | Leak count / RSI / ZDR flag                             |

---

## Architecture

```text
src/
├── core/
│   ├── config.py              # Pydantic-settings (env vars, target models)
│   └── model_presets.py       # Named, coherent TARGET_MODELS sets (free/paid/mixed)
├── api/
│   └── openrouter_client.py   # Sync + Async OpenAI SDK wrapper (tenacity retries, Semaphore)
├── evaluators/
│   ├── deterministic_eval.py  # JSON / Python syntax checks (no LLM call needed)
│   ├── cost_analyzer.py       # Pricing fetch + pandas cost matrix
│   ├── quality_judge.py       # Deterministic pre-eval + response collection (LLM judging is external)
│   └── security_scanner.py    # Injection probes + ZDR policy check
├── observability/
│   └── tracker.py             # MLflow experiment tracker
└── main.py                    # CollectPipeline / MergePipeline / DryRunPipeline orchestrators (CLI)

dashboard/
├── pareto.py                  # Pareto frontier computation
└── app.py                     # Streamlit scatter plot dashboard

data/prompts/
├── quality_prompts.json       # Generic screening prompts (JSON, code, reasoning…)
├── security_prompts.json      # 5 baseline injection probes
└── extended_probes.json       # 15 advanced red-team probes (JailbreakBench-style)

results/                       # Auto-generated CSV + JSON exports (timestamped)
docs/
├── adr/                       # Architecture Decision Records
└── plans/                     # Implementation plans

.github/agents/
├── judge-anthropic.agent.md   # Copilot judge — Claude (blind evaluation)
├── judge-openai.agent.md      # Copilot judge — GPT-4o (blind evaluation)
├── judge-google.agent.md      # Copilot judge — Gemini (blind evaluation)
└── judge-coordinator.agent.md # Invokes all 3 judges in parallel
```

### Key design decisions

- **`openai` SDK** pointed at OpenRouter via `base_url` — native compatibility, no custom HTTP client
- **`asyncio.gather`** across all three evaluation stages — total runtime ≈ slowest model, not sum
- **`asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)`** — defaults to `3` to avoid free-tier rate-limit errors
- **`tenacity.AsyncRetrying`** — exponential back-off on 429 / 5xx, releases semaphore during wait
- **Deterministic pre-eval** — JSON / Python syntax checked in pure code before calling a judge (saves cost)
- **Blind judging via Copilot agents** — no OpenRouter LLM-judge call. Undecidable responses are
  written to a `judging_*.json` file with model identities stripped, then scored by 3 Copilot
  agents (Claude/GPT-4o/Gemini) running in parallel. Scores are averaged per model — zero extra
  API cost, no single-provider bias
- **Generic quality screen** — versioned, provider-neutral prompts test structured output, code
  contracts, factual sanity, elementary reasoning, instruction reliability and concise communication.
  The aggregate is macro-averaged by dimension; coverage and optional repeat-run stability are exported
  alongside the score. This is a broad shortlist signal, not a replacement for a use-case evaluation.
- **MLflow** — local SQLite tracking (`sqlite:///mlruns.db`) by default, no external service required
- **Actual call-cost ledger** — every successful OpenRouter completion records the provider-returned
  `usage.cost`, token usage, resolved model, latency and evaluation stage. The raw ledger contains no
  prompts or responses and is exported under `results/call_costs/`.

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An [OpenRouter API key](https://openrouter.ai/keys)

### 2. Install

```bash
git clone <repo>
cd llm-model-screening
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev,docs]"
npm install
pre-commit install
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — minimum required:
#   OPENROUTER_API_KEY=sk-or-...
#   TARGET_MODELS=anthropic/claude-sonnet-5,openai/gpt-4o-mini
```

> Model slugs on OpenRouter change over time (renames, deprecations). Run
> `make verify` after editing `TARGET_MODELS` — it checks every entry against
> the live catalog for free, before any paid call is made.

#### Pick a model set faster with a preset

Instead of hand-typing model IDs, use a named, coherent preset — either in
`.env` (`TARGET_MODELS=paid_flagship`) or per run, without touching `.env`:

```bash
make models                          # list every preset + the models it contains
make verify MODELS=paid_flagship     # $0 — check a preset against the live catalog
make collect MODELS=paid_flagship SECURITY=owasp
```

`SECURITY=` picks the probe set for that run only: `basic` (5 built-in probes,
default), `owasp` (30 probes / OWASP GenAI LLM Top 10 2026 — required for the
dashboard's RSI/heatmap), or `extended` (15 advanced jailbreak/obfuscation
probes). The Streamlit dashboard's **"Plan a new run"** panel does the same
picking visually and prints the ready-to-run command.

### 4. Verify before spending anything

Two preflight checks, both **$0**, run in this order before a paid `make collect`:

```bash
make dry-run   # 100% offline — fake client, validates config/prompts/probes shape
make verify    # real network — GET /key + GET /models, validates the API key and
               # every TARGET_MODELS entry against the live catalog (no chat completions)
```

`make verify` fails fast (non-zero exit) on an invalid/expired key or an unknown model
slug — exactly the two mistakes that would otherwise only surface mid-way through a
paid `make collect`.

### 5. Run the benchmark

```bash
make collect
# Phase 1 — collects responses, runs deterministic checks + security scans.
# Writes data/intermediate/pending_<ts>.json and judging_<ts>.json
```

In VS Code Copilot chat, invoke the judge coordinator:

```text
@judge-coordinator
# Phase 2 — reads judging_<ts>.json and delegates the same anonymised batch
# to @judge-anthropic, @judge-openai, and @judge-google in parallel.
# Judges return JSON only; the coordinator validates and writes scores_<ts>_*.json.
# Each judge sees aliases (A, B, C…) only — blind evaluation.
```

The coordinator must confirm that all three score files were created and
validated before you run `make merge`. If a judge cannot return a valid payload,
do not merge; retry Phase 2 instead. The coordinator never substitutes
synthetic scores for a failed judge.

```bash
make merge
# Phase 3 — averages the 3 judges' scores per model, merges pricing + security,
# exports results/benchmark_<timestamp>.{csv,json}. MLflow run recorded in ./mlruns/
```

### 6. Open the dashboard

```bash
streamlit run dashboard/app.py
# Opens http://localhost:8501
```

---

## Configuration

All settings are loaded from environment variables (`.env`).

| Variable                    | Default                          | Description                                                                                                                                                                        |
| --------------------------- | -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OPENROUTER_API_KEY`      | —                               | **Required.** OpenRouter API key                                                                                                                                             |
| `OPENROUTER_BASE_URL`     | `https://openrouter.ai/api/v1` | API base URL                                                                                                                                                                       |
| `TARGET_MODELS`           | 3 preset models                  | Comma-separated model list,**or** a named preset (`free_general` / `paid_flagship` / `mixed_value`, see `make models`)                                               |
| `MAX_CONCURRENT_REQUESTS` | `3`                            | `asyncio.Semaphore` cap (conservative default for free-tier)                                                                                                                     |
| `MLFLOW_TRACKING_URI`     | `sqlite:///mlruns.db`          | MLflow tracking database (SQLite)                                                                                                                                                  |
| `SECURITY_MODE`           | `basic`                        | Named probe set:`basic` (5 built-in), `owasp` (30 probes, OWASP GenAI LLM Top 10 2026), `extended` (15 advanced probes). Also settable per run: `--security`/`SECURITY=` |
| `SECURITY_PROBES_PATH`    | —                               | Path to a custom probe JSON file (overrides`SECURITY_MODE` above)                                                                                                                |
| `QUALITY_REPETITIONS`     | `1`                            | Repeats per generic quality prompt; use`2`–`5` only for shortlist stability checks                                                                                            |

> **Note:** `JUDGE_MODEL` no longer exists. Quality judging for undecidable
> responses is done by 3 GitHub Copilot agents (`@judge-anthropic`,
> `@judge-openai`, `@judge-google`), not an OpenRouter model — zero extra
> API cost.

### Interpreting the quality result

`avg_quality_score` is a **generic pre-selection score**, not a claim that a model is best for a
specific client workflow. It is macro-averaged across the six quality dimensions so that a large
number of easy formatting prompts cannot dominate the result. Read it together with:

- `quality_coverage_rate` — fraction of configured prompts successfully scored;
- `quality_dimension_coverage_rate` — fraction of quality dimensions represented in the score;
- `quality_stability_score` — repeatability signal when `QUALITY_REPETITIONS >= 2`;
- `quality_collection_error_count` — API/transport failures, kept separate from model failures.

The cost-efficiency ratio (`cer`) is withheld when the result does not cover the required dimensions.
Use `gen-e2-eval` after this filter to measure success against a client-specific golden dataset.
See [docs/quality-methodology.md](docs/quality-methodology.md) for prompt provenance, coverage
limits, the validation protocol and the comparison procedure with `gen-e2-eval`.

### Actual cost versus TCO projection

- `actual_cost_credits` is the amount returned by OpenRouter in `response.usage.cost` for the calls
  made during the benchmark. `actual_cost_coverage_rate` indicates how many calls supplied this value.
  A free model is correctly represented by **0 credits with 100% coverage**.
- `tco_usd` is a forward-looking monthly estimate based on the selected workload profile and the
  pricing snapshot from `/models`; it is not the charge for the current benchmark run.
- Calls issued by Copilot judge agents are outside OpenRouter and therefore are not present in the
  OpenRouter call-cost ledger.

### Troubleshooting first runs

| Symptom                                                                | Likely cause                                                                                                        | Fix                                                                                                                                                         |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `make verify` fails with "API key check failed" / HTTP 401           | `OPENROUTER_API_KEY` in `.env` is missing, wrong, or the shell has a stale exported env var overriding `.env` | Check`openrouter.ai/keys`; run `env \| grep OPENROUTER_API_KEY` — if it's set in the shell, `unset OPENROUTER_API_KEY` so `.env` takes effect again |
| `make verify` lists model ID(s) "not in the live OpenRouter catalog" | Typo or a discontinued/renamed`:free` slug in `TARGET_MODELS`                                                   | Check[openrouter.ai/models](https://openrouter.ai/models) for the current slug                                                                               |
| `Unknown model preset '...'`                                         | Typo in`MODELS=`/`TARGET_MODELS=<preset>`                                                                       | Run`make models` to list valid preset names                                                                                                               |
| `make collect` warns about the free-tier request cap                 | `TARGET_MODELS` uses `:free` models and the account has < 10 USD lifetime credits                               | Buy ≥ 10 USD credits (raises the cap from 50 to 1000 req/day) or reduce`TARGET_MODELS` / `QUALITY_REPETITIONS`                                         |
| `make merge` errors with "Missing Copilot judge scores"              | `@judge-coordinator` (Phase 2) was never run, or was run before the current `make collect`                      | Run`@judge-coordinator` in Copilot chat against the latest `data/intermediate/judging_*.json`, then retry `make merge`                                |

---

## Development

```bash
pytest --tb=short          # run the test suite
ruff check src/            # lint
mypy src/ --strict         # type-check
make docs-build            # validate the documentation site
make docs-serve            # preview it locally with live reload
streamlit run dashboard/app.py   # dashboard
mlflow ui                  # view experiment runs
```

### Project conventions

- **Conventional Commits** enforced by `commitlint` (see `.commitlintrc.json`)
- **ruff** for linting + import sorting; **mypy strict** for type safety
- Every new public method must have a docstring
- Tests live in `tests/` and use `pytest` + `unittest.mock` (no real API calls in CI)

## Documentation

The documentation site is built with MkDocs. Its navigation keeps the operational
workflow, ADRs, implementation plans, and the Python reference in one place.
The API reference is rendered directly from the docstrings in `src/` and
`dashboard/`, so it always reflects the source code at build time.

```bash
make docs-build  # strict validation of pages, navigation, and API references
make docs-serve  # local preview at http://127.0.0.1:8000
```

Pull requests that change documentation or Python sources run the same strict
build. A push to `main` publishes the resulting site to GitHub Pages. Before the
first deployment, enable **GitHub Pages → Build and deployment → GitHub Actions**
in the repository settings.

See [the documentation maintenance guide](docs/documentation.md) for the source
of truth and the update checklist.

---

## Security

Vulnerabilities should be reported privately — see [SECURITY.md](SECURITY.md).

- API keys are never logged or committed (`.env` is gitignored; `SecretStr` prevents accidental prints)
- MLflow only logs token counts and model IDs — never prompt content
- The security scanner probes are for authorised red-team testing only

---

## Repository Layout

```text
repo/
  ├── tsconfig.json                 # TypeScript strict config
  ├── eslint.config.js              # ESLint flat config (ESLint 9+)
  ├── .commitlintrc.json            # Conventional Commits enforcement
  ├── .editorconfig
  ├── .env.example                  # Secret placeholders — copy to .env
  ├── .gitignore
  ├── .pre-commit-config.yaml       # Git hooks: ruff, secrets scan, yaml/json checks
  ├── docker-compose.yml            # Local dev environment
  │
  ├── .devcontainer/
  │   ├── devcontainer.json         # VS Code Dev Container (Python 3.11 + Node 20)
  │   └── Dockerfile                # Python + data/AI deps + lab-registry MCP
  │
  ├── .github/
  │   ├── copilot-instructions.md   # Repo-wide Copilot context + Conventional Commits rules
  │   ├── CODEOWNERS
  │   ├── PULL_REQUEST_TEMPLATE.md
  │   ├── dependabot.yml
  │   ├── ISSUE_TEMPLATE/
  │   │   ├── bug_report.md
  │   │   └── feature_request.md
  │   ├── workflows/
  │   │   └── ci.yml                # CI: Python (pytest+ruff+mypy) + TypeScript
  │   ├── instructions/             # Coding rules auto-applied by Copilot
  │   │   ├── python.instructions.md
  │   │   └── typescript.instructions.md
  │   ├── prompts/                  # Reusable agent prompts
  │   │   ├── init-project.prompt.md
  │   │   ├── setup-plugins.prompt.md
  │   │   ├── create-implementation-plan.prompt.md
  │   │   └── review-architecture.prompt.md
  │   ├── hooks/
  │   │   └── protect-secrets.json  # Blocks AI writes to .env / secrets
  │   ├── skills/                   # gen-e2 skills (Copilot)
  │   │   ├── commit-push-pr/
  │   │   ├── execute-plan/
  │   │   ├── extract-design/
  │   │   ├── generate-stories/
  │   │   ├── implementation-plan/
  │   │   ├── create-implementation-plan/
  │   │   ├── architecture-review/
  │   │   ├── architecture-review-session/
  │   │   ├── mermaid-creator/
  │   │   └── pdf-to-markdown/
  │   └── agents/                   # gen-e2 agents (Copilot)
  │       ├── figma-extractor.agent.md
  │       └── architecture-review-agent.agent.md
  │
  └── .claude/
  ├── settings.json             # autoMemory, hooks
  ├── rules/                    # Coding rules (Claude Code)
  │   ├── api-design.md
  │   └── typescript.md
  ├── hooks/
  │   └── protect-secrets.sh
  ├── skills/                   # gen-e2 skills (Claude Code — mirror of .github/skills/)
  │   └── ...
  ├── agents/                   # gen-e2 agents (Claude Code)
  │   ├── figma-extractor.md
  │   └── architecture-review-agent.md
  └── plugins/                  # Plugin registry for compliance checks
  ├── delivery/plugin.json
  ├── implementation-plan/plugin.json
  └── architecture-reviewer/plugin.json
```

## Standards Reference

See `AI-STANDARDS.md` for the complete Copilot ↔ Claude Code artefact mapping and file format specifications.
