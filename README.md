# open-router-research — LLM Evaluation Pipeline (LLMOps)

> Automated, scalable benchmarking of large language models available on
> [OpenRouter](https://openrouter.ai/) across three critical axes: **Quality**,
> **Cost**, and **Security**.
>
> Built at **Palo IT Singapore** to guide architecture choices for enterprise clients.

---

## Overview

This pipeline evaluates LLMs available through the OpenRouter API aggregator and
produces a ranked comparison matrix. Results are exported as CSV/JSON and
visualised in a local Streamlit dashboard with a **Pareto frontier** overlay
(best quality-to-cost trade-off).

### Evaluation axes

| Axis | Method | Key metric |
|---|---|---|
| **Quality** | Deterministic pre-checks + blind LLM-as-a-Judge (3 Copilot agents: Claude, GPT-4o, Gemini) | Avg score 1–5 per prompt |
| **Cost** | Live pricing from `/api/v1/models` + pandas cost matrix | USD per 1M tokens |
| **Security** | 5 built-in prompt-injection probes (+ optional extended set) + Zero Data Retention policy check | Leak count / ZDR flag |

---

## Architecture

```
src/
├── core/
│   └── config.py              # Pydantic-settings (env vars, target models)
├── api/
│   └── openrouter_client.py   # Sync + Async OpenAI SDK wrapper (tenacity retries, Semaphore)
├── evaluators/
│   ├── deterministic_eval.py  # JSON / Python syntax checks (no LLM call needed)
│   ├── cost_analyzer.py       # Pricing fetch + pandas cost matrix
│   ├── quality_judge.py       # Deterministic pre-eval + response collection (LLM judging is external)
│   └── security_scanner.py    # Injection probes + ZDR policy check
├── observability/
│   └── tracker.py             # MLflow experiment tracker
└── main.py                    # AsyncPipeline orchestrator

dashboard/
├── pareto.py                  # Pareto frontier computation
└── app.py                     # Streamlit scatter plot dashboard

data/prompts/
├── quality_prompts.json       # Benchmark prompts (JSON output, code gen, reasoning…)
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
- **MLflow** — local SQLite tracking (`sqlite:///mlruns.db`) by default, no external service required

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- An [OpenRouter API key](https://openrouter.ai/keys)

### 2. Install

```bash
git clone <repo>
cd open-router-research
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
npm install
pre-commit install
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env — minimum required:
#   OPENROUTER_API_KEY=sk-or-...
#   TARGET_MODELS=anthropic/claude-3.5-sonnet,openai/gpt-4o-mini
```

### 4. Run the benchmark

```bash
make collect
# Phase 1 — collects responses, runs deterministic checks + security scans.
# Writes data/intermediate/pending_<ts>.json and judging_<ts>.json
```

In VS Code Copilot chat, invoke the judge coordinator:

```
@judge-coordinator
# Phase 2 — delegates to @judge-anthropic, @judge-openai, @judge-google in parallel.
# Each judge only sees anonymised aliases (A, B, C…) — blind evaluation.
```

```bash
make merge
# Phase 3 — averages the 3 judges' scores per model, merges pricing + security,
# exports results/benchmark_<timestamp>.{csv,json}. MLflow run recorded in ./mlruns/
```

### 5. Open the dashboard

```bash
streamlit run dashboard/app.py
# Opens http://localhost:8501
```

---

## Configuration

All settings are loaded from environment variables (`.env`).

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **Required.** OpenRouter API key |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | API base URL |
| `TARGET_MODELS` | 3 preset models | Comma-separated list of models to benchmark |
| `MAX_CONCURRENT_REQUESTS` | `3` | `asyncio.Semaphore` cap (conservative default for free-tier) |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlruns.db` | MLflow tracking database (SQLite) |
| `SECURITY_PROBES_PATH` | — | Path to a custom probe JSON file (overrides built-in probes) |

> **Note:** `JUDGE_MODEL` no longer exists. Quality judging for undecidable
> responses is done by 3 GitHub Copilot agents (`@judge-anthropic`,
> `@judge-openai`, `@judge-google`), not an OpenRouter model — zero extra
> API cost.

---

## Development

```bash
pytest --tb=short          # run tests (76 total)
ruff check src/            # lint
mypy src/ --strict         # type-check
streamlit run dashboard/app.py   # dashboard
mlflow ui                  # view experiment runs
```

### Project conventions

- **Conventional Commits** enforced by `commitlint` (see `.commitlintrc.json`)
- **ruff** for linting + import sorting; **mypy strict** for type safety
- Every new public method must have a docstring
- Tests live in `tests/` and use `pytest` + `unittest.mock` (no real API calls in CI)

---

## Security

Vulnerabilities should be reported privately — see [SECURITY.md](SECURITY.md).

- API keys are never logged or committed (`.env` is gitignored; `SecretStr` prevents accidental prints)
- MLflow only logs token counts and model IDs — never prompt content
- The security scanner probes are for authorised red-team testing only
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
