# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `collect`/`merge` CLI output now states which phase is running (`Phase 1/3`,
  `Phase 3/3`), ends with a bordered `✅ Done` summary, and prints an explicit
  next command (`@judge-coordinator` + `make merge`, `make dashboard`, or
  `make export-html`); the unknown-subcommand error now lists every
  subcommand with a one-line description instead of a bare usage string
- Clarified that the security probe datasets are internally authored: `owasp`
  is aligned with OWASP categories, while `extended` adds advanced LLM01
  red-team probes; neither is an official OWASP test suite or certification

- Interactive `make select` now asks for each catalog filter, supports `skip`,
  offers numbered model choices with `0` for the recommendation, and saves the
  chosen IDs as reusable `MODELS=selection` runtime state
- `make select` now explains that pressing Enter keeps a filter default, shows
  recommended models separately from up to 20 additional matching models, and
  allows selecting either group by number
- The `free_general` preset now contains two free models instead of three, so
  its default basic run stays within the indicative 50-request free-tier quota
- `make select` now classifies zero-priced catalog routes, including
  `openrouter/free`, as free instead of presenting them as paid
- Dynamic pre-run model selector via `make select` / `python -m src.main select`:
  filters the live OpenRouter catalog by paid/free status, price, context size,
  and result count, then prints cost/request estimates and ready-to-run commands
- Added the `budget_paid` model preset with `mistralai/mistral-small-3.1-24b-instruct`
  and `openai/gpt-4o-mini` for lower-cost paid comparisons without free-tier quotas
- The live and static reports now place plain-language explanations beside
  the Overview, Quality, Security, Cost, and Performance indicators, so non-
  specialist readers can understand score direction, coverage, risk, cost,
  and latency without relying on the glossary alone
- Run provenance manifests written after `make merge`, with non-secret metadata
  and SHA-256 checksums for the pending, judge-score, and benchmark export
  artifacts; `make inspect-run` reports missing or modified files
- Merge runs now log the run ID, quality suite, repetitions, workload profile,
  and model count as non-sensitive MLflow parameters
- Collect and merge now emit content-free JSON log events with phase status and
  aggregate counters, making operational logs easier to ingest without exposing
  prompts or model responses
- Initial project-improvement tranche: CI now fails on real Python, npm, lint,
  type-check, test, coverage, or documentation errors; Python coverage is
  enforced at a documented 80% minimum, and npm test exits successfully when
  this Python-focused repository has no JS/TS test files
- Pending benchmark artifacts are validated before merge for required phase
  lists, model IDs, and complete alias-to-response mappings

- A real **Performance** surface in both dashboards: `actual_latency_p50_ms`,
  `actual_latency_p95_ms`, and `actual_tokens_per_second`, computed from
  network-only latency captured *after* the concurrency semaphore is
  acquired — excludes time spent queueing behind `MAX_CONCURRENT_REQUESTS`
  and retry back-off waits, unlike the legacy `actual_latency_ms` (a
  wall-clock sum that included both and was never actually displayed)
- `judge_disagreement` / `quality_judge_disagreement_rate` — the range across
  the 3 judges' raw scores per response, and the share of a model's judged
  prompts where that range is 2 or more. The arithmetic mean previously hid a
  real split of opinion (e.g. a 3/4/5 split averaging to 4.0) behind a single
  number; both are now surfaced in the CSV and both dashboards
- Best-effort self-identification scrubbing (`quality_judge.py::_scrub_self_identification`)
  applied to the judge-facing copy of a response before it reaches
  `judging_{ts}.json`, so a response naming its own vendor ("As an AI
  developed by Anthropic...") does not defeat alias-based blind evaluation in
  front of a same-vendor judge. The raw copy used for evidence in
  `pending_{ts}.json` is never modified
- Strict per-judge coverage validation before merge: a judge that does not
  score every expected (prompt_id, attempt, alias) with a non-empty response
  now fails the merge immediately with the judge name and missing tuples,
  instead of silently reducing that response's average to fewer judges
- The 1-5 rubric in `.github/agents/judge-*.agent.md` now asks judges to count
  satisfied `judge_criteria` explicitly and forbids lowering a score for a
  subjective preference outside the listed criteria — targets a systematic
  severity-drift pattern observed between judges on the same responses
- README/`.env.example`: documented `REQUEST_TIMEOUT`, `MAX_RETRIES`,
  `MAX_QUALITY_COLLECTION_ERROR_RATE`, `MAX_SECURITY_PROBE_ERROR_RATE`, and
  `WORKLOAD_PROFILE` — five settings that existed in `src/core/config.py` but
  were absent from both
- `dashboard/glossary.py` — one glossary shared by the Streamlit app and the
  static HTML export, so a term can no longer be defined in one view, defined
  differently in the other, or missing entirely from one of them
- `COLUMN_TOOLTIPS` in `dashboard/glossary.py`: short, one-sentence reminders
  shown as a native tooltip next to technical column headers (both the static
  HTML export and Streamlit), complementing the full glossary section rather
  than replacing it
- A caption next to the Cost-vs-Security quadrant (Streamlit and static
  export) spelling out that every model is compared under the same assumed
  monthly workload, so a cheaper `tco_usd` means cheaper for identical usage —
  and that real spend still depends on each model's actual reply length
- `docs/security-methodology.md` — single reference for the RSI: formula,
  OWASP weights, interpretation thresholds, scoring perimeter, detection
  limits, and what the index does not measure
- Suspected input-corruption detection: a reference-answer prompt that *every*
  model in a run misses is excluded from the quality aggregates and their
  denominator, counted in `quality_excluded_prompt_count`, and recorded as
  `verification_status=suspected_input_corruption`. Raw responses and scores
  are preserved unchanged
- `avg_quality_score_deterministic` and `avg_quality_score_judged` — the
  pass/fail and graded scales that `avg_quality_score` blends are now published
  separately, so it is visible which one drives a model's rank
- `output_format_compliance` quality dimension — literal adherence to a
  `strict_output` contract is scored apart from whether the answer was correct
- RSI scoring perimeter travels with the score:
  `rsi_scored_categories`, `rsi_scored_category_count`,
  `rsi_scored_probe_count`, `rsi_leak_capped`, plus `probe_error_rate` in the
  merged results and both dashboards
- Auditable quality evidence exports under `results/quality_details/`, including
  the exact prompt, model response, score, evaluation reasoning, individual
  blind-judge verdicts, OpenRouter generation ID, resolved model, and a stable
  request fingerprint
- Optional `make verify-quality ARGS="..."` workflow for failed objective
  prompts from `QUALITY_REPETITIONS=1` runs. It performs two paid OpenRouter
  rechecks and records `confirmed_failure`, `not_reproduced`, `unstable`, or
  `inconclusive` under `results/verification/`; it does not claim causal
  attribution to OpenRouter, an upstream provider, or the model
- `verification_status` in quality evidence: `optional_openrouter_recheck` for
  failed objective `k=1` responses, `run_repetitions_available` when the run
  already contains `k>1` attempts, and the completed recheck result when a
  sidecar verification report exists
- Technical quality-collection diagnostics under `results/quality_diagnostics/`.
  Timeouts, HTTP/provider failures, and invalid API responses remain separate
  from model-quality failures and reduce collection success/coverage
- Quality drill-down in the Streamlit and static dashboards: model/dimension
  filters, selectable full prompts and responses, per-judge scores and
  reasoning, request diagnostics, and reproducibility status
- Static, escaped, multi-page dashboard export via `make export-html`, with
  linked Overview, Quality, Evidence, Security, and Cost pages
- Quality-dimension heatmap and exact per-dimension evidence derived from the
  same shared data-preparation helpers as the live dashboard
- `src/core/model_presets.py` — named, coherent `TARGET_MODELS` presets
  (`free_general`, `paid_flagship`, `mixed_value`) with `resolve_models_arg()`
  and `format_model_presets()`. `TARGET_MODELS=<preset name>` now works in
  `.env`, and `--models`/`MODELS=` accepts a preset name or an explicit
  comma-separated model list on `collect`/`run`/`dry-run`/`verify`
- `python -m src.main models` / `make models` — lists every preset and its
  models without requiring an API key or network access
- `Settings.security_mode` (`SECURITY_MODE` env var, default `"basic"`) —
  names the 3 probe sets already shipped (`basic`: 5 built-in, `owasp`:
  `data/prompts/owasp_probes.json` 30 internally authored OWASP-aligned probes,
  `extended`: `data/prompts/extended_probes.json` 15 single-turn LLM01 red-team
  probes) so a full file path no
  longer has to be typed/remembered. `--security`/`SECURITY=` overrides it
  per run; an explicit `SECURITY_PROBES_PATH` still wins over both
- `src/main._resolve_security_probes_path()` — single resolution point for
  the probes-path precedence above, replacing 5 duplicated call sites;
  `_run_preflight_checks()` (used by `make dry-run`/`make verify`) now
  validates whichever probes file `SECURITY_MODE` resolves to, not just an
  explicit `SECURITY_PROBES_PATH`
- Argparse-based CLI in `src/main.py` (`--models`, `--security`) — the
  subcommand itself stays a free-form positional so an unknown subcommand
  keeps exiting with code 1 (not argparse's own code 2), preserving the
  existing CLI contract
- Dashboard "Plan a new run" panel (`dashboard/app.py`) — pick a model
  preset and a security mode visually and get the ready-to-run `make
  verify`/`make collect` command; does not launch a run itself
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

- README and Makefile: the mandatory `@judge-coordinator` step (Phase 2) is now
  stated before `make collect` with an explicit cost warning, instead of being
  documented mid-prose after the paid step. Added a condensed "first
  benchmark" command sequence at the top of the Quick Start section
- Makefile `help` text is now entirely in English (`run`, `verify`, `dry-run`,
  `judge` targets mixed French and English before)
- `docs/audit-2026-08-21.md` marked as an archived, point-in-time snapshot,
  pointing to the current CHANGELOG and security methodology doc for anything
  found since
- All user-facing surfaces are now in English. The Streamlit app was English
  while the static HTML export, its glossary, and the dry-run CLI output were
  French, so the same metric was named two different ways depending on the view
- A confirmed system-prompt disclosure now caps the RSI below the "robust"
  band. The weighted average alone left a model that had verifiably leaked its
  system prompt at 91.7 (green) while `security_status` reported it as
  "Vulnerable" on the same page
- OWASP categories that a single-turn chat probe cannot exercise (LLM04 supply
  chain, LLM06 unbounded consumption, LLM09 vector and embedding weaknesses)
  are reported but excluded from the RSI instead of scoring a baseless 0%
  vulnerability rate and diluting the categories actually tested
- RSI interpretation thresholds moved from the visualisation code into
  `security_scanner.py`, so the score and its colour banding cannot diverge
- A correct answer wrapped in markdown fences no longer scores 1/5 on content.
  The `code_contract` dimension is renamed `code_correctness` and now measures
  the code, while formatting is scored under `output_format_compliance`
- Exact-answer checks compare content after normalisation; strict literal
  formatting is reported through the format dimension rather than failing the
  answer
- Quality failures are classified conservatively: an incorrect answer remains
  scored as a model-quality failure even when its text contains an unexpected
  placeholder. Only technical request/API failures are excluded from scoring
- `QUALITY_REPETITIONS>1` is now the preferred reproducibility evidence for
  shortlist decisions. `verify-quality` rejects prompts that already have
  multiple attempts instead of issuing redundant paid calls
- Streamlit Quality now presents coverage, stability, CER eligibility, completed
  OpenRouter recheck counts, and one non-duplicated per-dimension visualization;
  post-run verification qualifies confidence without rewriting historical scores
- Dashboard data transformations were moved into `dashboard/data_prep.py` so
  Streamlit and static HTML use the same cost, quality, security, and evidence logic
- `README.md`, `docs/workflow.md`, and `docs/quality-methodology.md` now document
  the three-phase benchmark, quality evidence artifacts, $k$-repetition semantics,
  the optional `k=1` recheck, and its non-causal interpretation limits
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

### Fixed

- `make dry-run` no longer reports every quality response as a transport
  failure. The offline fake client did not expose the generation ID and
  resolved model that the collector reads, so the pre-flight check emptied its
  own quality axis and still exited 0
- The dry run now enforces the same collection error budget as `collect`,
  instead of silently passing with a fully degraded quality axis
- Streamlit Prompts & responses no longer raises `KeyError: 'model'` when a
  historical, partial, or malformed quality-details artifact is selected;
  legacy evidence receives safe default columns and invalid schemas degrade to
  an empty-state message
- Removed the duplicated quality table that repeated the same per-dimension
  values immediately below the heatmap
- Judge reasoning is no longer hidden behind a concatenated summary: selecting
  a judged response shows each judge ID, score, and full rationale separately
- Static evidence tables explicitly HTML-escape untrusted model output before
  rendering, including the Pandas Styler path
- `security_probe_details_frame()` no longer drops the `model` column from the
  per-probe transcript — the Security axis of Prompts & responses (Streamlit
  and the static HTML export) previously showed prompts/responses with no way
  to tell which model produced them
- The static HTML export no longer repeats the per-dimension quality table and
  the per-category OWASP vulnerability table right below their respective
  heatmaps, which already print the exact value in every cell; the Streamlit
  Security tab's equivalent redundant table was removed for the same reason
- The Pareto chart's Pareto-optimal marker no longer answers hover itself: it
  overlapped the colored security-status point at the same coordinates, so
  hovering the marker's edge versus its center could show different tooltip
  content depending on cursor position

## [0.2.0] — 2026-07-10 — V2: Async, Observability, Hybrid Judge, Dashboard, Red Team

### Added in 0.2.0

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

### Changed in 0.2.0

- `compute_cost_matrix` extracted to module-level function shared by sync and async
  analyzers
- `ModelScore` Pydantic field order: `reasoning` validated before `score` (CoT enforcement)
- `SecurityScanner` accepts optional `probes_path` parameter

## [0.1.0] — 2026-07-09 — V1: Foundation

### Added in 0.1.0

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
