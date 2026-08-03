# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] — 2026-07-10 — V2: Async, Observability, Hybrid Judge, Dashboard, Red Team

### Added
- `AsyncOpenRouterClient` — async wrapper with `openai.AsyncOpenAI`, `httpx.AsyncClient`,
  `asyncio.Semaphore(10)` for rate-limiting, and `tenacity.AsyncRetrying`
- `AsyncCostAnalyzer`, `AsyncQualityJudge`, `AsyncSecurityScanner` — async variants of
  all evaluators
- `AsyncPipeline` in `main.py` — runs cost, quality, and security stages concurrently
  via `asyncio.gather`
- `src/evaluators/deterministic_eval.py` — `JsonValidityCheck`, `PythonSyntaxCheck`,
  `ExactFormatCheck`; LLM judge skipped when result is deterministic
- Chain-of-Thought judge prompt — reasoning 3-5 sentences required before score
- `src/observability/tracker.py` — `ExperimentTracker` wrapping MLflow; logs token
  counts, latency, cost, quality scores, and CSV artifacts
- `dashboard/pareto.py` — Pareto frontier computation (O(n log n), pure pandas)
- `dashboard/app.py` — Streamlit scatter plot (Cost vs Quality) with Pareto overlay
  and security colour-coding
- `data/prompts/extended_probes.json` — 15 JailbreakBench-style red-team probes
  (base64, Unicode lookalike, hypothetical framing, developer mode, payload split…)
- External probe loading — `SECURITY_PROBES_PATH` env var overrides built-in probes
- New settings: `MAX_CONCURRENT_REQUESTS`, `MLFLOW_TRACKING_URI`, `SECURITY_PROBES_PATH`
- New dependencies: `mlflow>=2.0`, `streamlit>=1.35`, `plotly>=5.0`
- New dev dep: `pytest-asyncio>=0.23` (`asyncio_mode = "auto"`)
- 40 new tests (total: 76 passing)

### Changed
- `compute_cost_matrix` extracted to module-level function shared by sync and async
  analyzers
- `ModelScore` Pydantic field order: `reasoning` validated before `score` (CoT enforcement)
- `SecurityScanner` accepts optional `probes_path` parameter

## [0.1.0] — 2026-07-09 — V1: Foundation

### Added
- `src/core/config.py` — `Settings` via `pydantic-settings` with `lru_cache` singleton
- `src/api/openrouter_client.py` — `OpenRouterClient` wrapping `openai.OpenAI` +
  `httpx.Client`; tenacity retry decorator on 429/5xx
- `src/evaluators/cost_analyzer.py` — `CostAnalyzer`: live pricing from
  `/api/v1/models`, pandas cost matrix
- `src/evaluators/quality_judge.py` — `QualityJudge`: LLM-as-a-Judge with position
  bias (alias shuffle) and verbosity bias mitigation
- `src/evaluators/security_scanner.py` — `SecurityScanner`: 5 injection probes +
  Zero Data Retention policy check
- `src/main.py` — synchronous `Pipeline` orchestrator; CSV + JSON export
- `data/prompts/quality_prompts.json` — 5 benchmark prompts (categories: json_output,
  code_generation, logical_reasoning, instruction_following)
- `data/prompts/security_prompts.json` — 5 baseline injection probes
- 36 unit tests with mocked API calls
- Project initialisation from gen-e2 template (pyproject.toml, .env.example, CI)

