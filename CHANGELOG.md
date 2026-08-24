# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `mkdocs.yml` — the documentation site config never existed in this repo (no git
  history at all); `make docs-build`/`make docs-serve` were non-functional
- `docs/reference/api.md` — mkdocstrings-generated API reference for `src/` and
  `dashboard/pareto.py` / `dashboard/security_viz.py` (`dashboard/app.py` excluded:
  Streamlit script with module-level side effects, unsafe to import at build time)
- `docs/documentation.md` — maintenance guide, previously linked from the README
  but missing
- `docs/audit-2026-08-21.md` — critical, sourced audit of the pipeline
- `_unknown_target_models()` in `src/main.py` — preflight check that flags
  `TARGET_MODELS` entries absent from the live OpenRouter catalog with a clear,
  actionable log message instead of an opaque transport-error budget failure
- `docs` CI job — runs `mkdocs build --strict` on every PR (previously no CI
  validated documentation at all)
- `pytest-cov` dev dependency + `make test-cov` target
- `_estimate_free_tier_request_volume()` / `_warn_on_free_tier_request_volume()`
  in `src/main.py` — non-blocking preflight warning when a run's estimated
  request volume against `:free` models exceeds OpenRouter's 50 req/day cap
  for accounts with <10 USD lifetime credits
- `probe_count()` public helper in `src/evaluators/security_scanner.py`
- Integration tests for `CollectPipeline.run()`, `MergePipeline.run()`, and
  `main()`'s CLI dispatch (`tests/test_main.py`) — `src/main.py` coverage:
  39% → 59% (project-wide: 69% → 76%)
- `TestRsiWeights` regression tests (`tests/test_security_scanner.py`) —
  assert `_RSI_WEIGHTS` sums to 1.0 and its keys exactly match the
  `category_id`s present in `data/prompts/owasp_probes.json`
- 3 new security probes for `LLM10` "Improper Output Handling" (OWASP GenAI
  LLM Top 10 2026) — a category the probe set previously had zero coverage
  for: unsanitized HTML/script embedding, unparameterized SQL construction,
  Markdown-based data exfiltration

### Changed
- CI: removed `|| true` from the Python `ruff`/`mypy` steps — these previously
  could never fail the build regardless of lint/type errors
- `docs/brief-manager-2026-08-17.md`: converted 14 relative links pointing
  outside `docs/` (source files, README, agent files) to absolute GitHub URLs,
  and dropped a heading anchor that didn't match the actual generated slug —
  both were breaking the (now-working) strict mkdocs build
- `docs/workflow.md`: replaced the stale "147 tests" claim, added a sourced
  free-tier rate-limit guidance box (OpenRouter `:free` models are capped at
  50 req/day per account below 10 USD lifetime credits — a default `make collect`
  already uses 63 requests, the OWASP probe set uses 138); updated the RSI
  weight table to the OWASP GenAI LLM Top 10 2026 categories
- `docs/adr/0001-architecture-initiale.md`, `docs/index.md`: noted that the cited
  "OWASP LLM Top 10 (2025)" is now the archived legacy edition (OWASP GenAI LLM
  Top 10 2026 is current per OWASP's own site), and clarified that RSI category
  weights are an internal heuristic, not an OWASP-published weighting
- `.gitignore`: added `site/` (mkdocs build output, was untracked and unignored)
- `src/core/config.py`: replaced non-existent default model
  `meta-llama/llama-3.3-70b-instruct:free` with `openai/gpt-oss-20b:free`
  (verified live against `/api/v1/models`); removed the unused `_DEFAULT_MODELS`
  dead-code constant, which also still referenced the non-existent
  `qwen/qwen3-coder:free`
- `.env.example`: replaced non-existent `qwen/qwen3-coder:free` example model
  with `cohere/north-mini-code:free`
- `README.md`: fixed the architecture diagram comment incorrectly labeling
  `main.py` as an "AsyncPipeline orchestrator" — `AsyncPipeline` is never
  invoked by the CLI (`main()` only dispatches `CollectPipeline`/
  `MergePipeline`/`DryRunPipeline`) and has no test coverage; `AsyncPipeline`'s
  docstring now documents this explicitly
- `data/prompts/owasp_probes.json`: fully remapped from an internally
  inconsistent mix of the 2023 and 2025 OWASP editions to the single current
  OWASP GenAI LLM Top 10 2026 structure (all 10 categories renumbered/renamed
  to their 2026 codes; see `docs/audit-2026-08-21.md` §6.4 for the full
  before/after mapping and sourcing)
- `_RSI_WEIGHTS` in `src/evaluators/security_scanner.py`: rewritten for the
  2026 category codes; weighting methodology (OWASP 2026 rank as primary
  anchor, with two documented project-specific deviations) now explained in a
  code comment directly above the dict



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
