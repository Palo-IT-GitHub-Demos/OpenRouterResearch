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
| **Security** | 15 prompt-injection probes + Zero Data Retention policy check | Leak count / ZDR flag |

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
- **`asyncio.Semaphore(10)`** — caps concurrent requests to avoid rate-limit errors
- **`tenacity.AsyncRetrying`** — exponential back-off on 429 / 5xx, releases semaphore during wait
- **Deterministic pre-eval** — JSON / Python syntax checked in pure code before calling a judge (saves cost)
- **Blind judging via Copilot agents** — no OpenRouter LLM-judge call. Undecidable responses are
  written to a `judging_*.json` file with model identities stripped, then scored by 3 Copilot
  agents (Claude/GPT-4o/Gemini) running in parallel. Scores are averaged per model — zero extra
  API cost, no single-provider bias
- **MLflow** — local `./mlruns` by default, no external service required

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


A GitHub template repository pre-configured with GitHub Copilot and Claude Code artifacts, language-specific coding rules, and gen-e2 marketplace plugins ready to install.

## Quick Start

### 1. Create your repo

Click **Use this template** → create your repository → clone it locally.

### 2. Set up the Python environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pip install "git+https://github.com/Palo-IT-GitHub-Demos/lab-registry-mcp@v0.2.0"
```

### 3. Install Node dependencies and hooks

```bash
npm install
pre-commit install
```

### 4. Initialise the project (replaces all placeholders)

Open Copilot chat in agent mode and run:

```
@workspace /init-project
```

The prompt will ask for your project name, description, team handle, and security email, then replace all placeholders in one pass.

## What's Included

### AI Artifacts

| File | Tool | Purpose |
|---|---|---|
| `AGENTS.md` | All agents | Project-wide instructions (Copilot + Claude Code + others) |
| `.github/copilot-instructions.md` | Copilot | Repo-wide context injected in every request |
| `.github/instructions/python.instructions.md` | Copilot | Python rules auto-applied to `**/*.py` |
| `.github/instructions/typescript.instructions.md` | Copilot | TypeScript rules auto-applied to `**/*.ts`, `**/*.tsx` |
| `.github/hooks/protect-secrets.json` | Copilot | Blocks writes to `.env`, `secrets.json`, etc. |
| `.claude/rules/api-design.md` | Claude Code | Python API rules scoped to `**/*.py` |
| `.claude/rules/typescript.md` | Claude Code | TypeScript rules scoped to `**/*.ts`, `**/*.tsx` |
| `.claude/hooks/protect-secrets.sh` | Claude Code | Equivalent secrets protection hook |
| `.mcp.json` | Claude Code | MCP server for gen-e2 lab-registry |

### Prompts (manual invocation)

| Prompt | Purpose |
|---|---|
| `init-project` | **First-run** — replaces all placeholders and installs hooks |
| `setup-plugins` | Re-install or update the 3 gen-e2 plugins |
| `create-implementation-plan` | Generate a deterministic implementation plan for any task |
| `review-architecture` | Run an evidence-first architecture review with Mermaid output |

### gen-e2 Plugins (pre-installed)

| Plugin | Version | Skills + Agents |
|---|---|---|
| `delivery` | 0.2.3 | Story → implementation → PR — 5 skills + 1 agent |
| `implementation-plan` | 0.1.0 | Deterministic plans — 1 skill |
| `architecture-reviewer` | 0.1.0 | Architecture analysis + Mermaid — 4 skills + 1 agent |

## Customising

- **Add a language**: create `.github/instructions/<lang>.instructions.md` + `.claude/rules/<lang>.md` following the same pattern
- **Add a skill**: drop a `SKILL.md` in `.github/skills/<name>/` (Copilot picks it up automatically)
- **Add an agent**: create `.github/agents/<name>.agent.md` or `.claude/agents/<name>.md`
- **Add a plugin**: register it in `.claude/plugins/<name>/plugin.json` and run `setup-plugins`

## Project Structure

```
.
├── src/                          # Source code (replace with your stack)
├── tests/                        # Python tests (pytest)
│   └── test_example.py
├── docs/
│   └── adr/                      # Architecture Decision Records
│       └── 0001-architecture-initiale.md
│
├── AGENTS.md                     # AI instructions — Copilot + Claude Code + others
├── AI-STANDARDS.md               # Reference: Copilot ↔ Claude Code artefact mapping
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── Makefile                      # make test / lint / fmt / dev
├── pyproject.toml                # Python deps + ruff / mypy / pytest config
├── package.json                  # Node deps + scripts (vitest, eslint, commitlint)
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
