# model-compass — AI Agent Instructions

> This file is read by GitHub Copilot, Claude Code, and other AI agents.

## Project Overview

Research and decision-support tooling for evaluating OpenRouter LLMs across
quality, security, performance, and model-only cost. Model Compass produces
generic use-case recommendations and evidence; final client acceptance remains
human and domain-specific, with `gen-e2-eval` used when a client dataset exists.

## Architecture & Conventions

- Core pipeline code lives in `src/`; the versioned generic use-case catalog is
  `data/catalog/model_compass_use_cases.json`; Streamlit and shared presentation helpers
  live in `dashboard/`; operational scripts live in `scripts/`
- The production workflow is split into three phases:
  `make collect` → `@judge-coordinator` → `make merge`
- `make dry-run` is offline; `make verify` validates the OpenRouter key and
  model catalog without chat-completion cost
- `make export-html` builds a static dashboard; `make dashboard` launches the
  interactive Streamlit view
- `MODEL_COMPASS_WEIGHTS` optionally overrides the catalog's quality/security/
  cost/performance weights as JSON; effective weights and catalog version must
  remain in every recommendation artifact
- Follow language-specific rules in `.github/instructions/` (Copilot) and `.claude/rules/` (Claude Code)
- All AI artifacts are organised under `.github/` (Copilot) and `.claude/` (Claude Code)
- Experimental multi-turn scenario contracts live in `src/evaluators/scenario_runner.py`; keep them separate from legacy single-turn scoring until the security integration and comparability metadata are complete

## Quality Evidence Rules

- Preserve raw benchmark results. Post-run verification is sidecar evidence and
  must never rewrite the original response or score
- A wrong model response remains a quality failure. Only technical failures
  such as timeouts, HTTP/provider errors, and invalid API responses count as
  collection errors
- Exception: when *every* model in a run misses the same reference-answer
  prompt, the shared cause is the request that reached the provider, not the
  models. The prompt is dropped from the aggregates and their denominator and
  marked `suspected_input_corruption` — the raw response and score stay intact
- Content correctness and output-format compliance are scored as separate
  dimensions. Never let a formatting violation lower a content score
- `avg_quality_score` blends a pass/fail scale with a graded one. Always
  publish `avg_quality_score_deterministic` and `avg_quality_score_judged`
  alongside it
- A confirmed system-prompt disclosure caps the RSI below the robust band. Never
  present a model as robust and vulnerable on the same view
- Only score OWASP categories a single-turn chat probe can actually exercise;
  report the others as not scored. RSI is comparable only across identical
  `rsi_scored_categories`
- The 3 Copilot judges are each affiliated with a provider that may also be a
  benchmarked model; alias-based blindness is the only mitigation, and a
  response's self-identification is scrubbed (best-effort) before it reaches a
  judge. No further bias correction is applied after the fact — see
  `docs/quality-methodology.md` "Fiabilité et biais du panel de juges"
- `judge_disagreement` / `quality_judge_disagreement_rate` surface inter-judge
  disagreement instead of silently averaging over it. Keep the mean rather
  than a median: with exactly 3 judges a median just picks the middle one
- A judge that does not score every expected (prompt_id, attempt, alias) fails
  the merge immediately (`ValueError`) instead of silently reducing that
  response's average to fewer judges
- Quality eligibility is evaluated per generic use case before weighted ranking;
  a model below a use-case threshold cannot be recommended because it is cheap
  or fast
- Every model remains visible for every catalog use case. Equal recommendation
  scores keep the same dense rank; do not add arbitrary provider/model-name
  tie-breakers
- Missing security, cost, or performance evidence yields an explicit
  `insufficient_decision_evidence` status and no recommendation rank
- For `QUALITY_REPETITIONS > 1`, use the attempts already collected to assess
  stability; do not add redundant rechecks
- `make verify-quality ARGS="..."` is an optional, paid OpenRouter-only
  reproducibility check for failed objective prompts from `k=1` runs
- Reproducibility statuses (`confirmed_failure`, `not_reproduced`, `unstable`,
  `inconclusive`) do not attribute causality to OpenRouter, an upstream
  provider, or the model
- Never expose unescaped model output in HTML. Pandas `Styler.to_html()` callers
  must explicitly use HTML escaping
- `actual_latency_p50_ms`/`actual_latency_p95_ms`/`actual_tokens_per_second`
  are computed from latency captured *after* the concurrency semaphore is
  acquired. Never report the legacy `actual_latency_ms` (a wall-clock sum
  that includes queueing and retry back-off time) as a per-call latency figure

## Result Artifacts

- Summary benchmarks: `results/benchmark_<timestamp>.{csv,json}`
- Model Compass recommendations: `results/recommendations/benchmark_<timestamp>_recommendations.{csv,json}`
- Quality transcripts and judge reasoning: `results/quality_details/`
- Technical collection failures: `results/quality_diagnostics/`
- Optional `k=1` rechecks: `results/verification/`
- Per-call OpenRouter usage and costs: `results/call_costs/`
- Static report: `results/dashboard_<timestamp>.html` plus its sibling page bundle

## AI Asset Policy

| Artefact | GitHub Copilot | Claude Code |
|---|---|---|
| Skills | `.github/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` |
| Agents | `.github/agents/<name>.agent.md` | `.claude/agents/<name>.md` |
| Prompts | `.github/prompts/<name>.prompt.md` | — |
| Hooks | `.github/hooks/<name>.json` | `.claude/hooks/<name>.sh` + `settings.json` |
| Plugin registry | — | `.claude/plugins/<name>/plugin.json` |

## Installed gen-e2 Plugins

| Plugin | Version | Purpose |
|---|---|---|
| `delivery` | 0.2.3 | Story → implementation → PR workflow |
| `implementation-plan` | 0.1.0 | Deterministic, AI-executable implementation plans |
| `architecture-reviewer` | 0.1.0 | Evidence-first architecture analysis + Mermaid diagrams |

> To install full plugin artifacts (skills + agents), run the prompt in `.github/prompts/setup-plugins.prompt.md`.

## Coding Standards

- Keep code simple and testable
- Prefer deterministic output contracts for AI-assisted features
- Add tests for any behavior-changing change
- Keep Streamlit-independent transformations in `dashboard/data_prep.py` so
  live and static dashboards use the same logic
- Use Python 3.11+ typing and vectorized pandas operations
- Use Conventional Commits as defined in `.commitlintrc.json`

## Validation

Run the narrowest relevant tests first, then the applicable project checks:

```bash
make test
make lint
make type-check
make docs-build
```

Documentation changes must pass `mkdocs build --strict`. Dashboard changes
must be checked in Streamlit and, when applicable, in the static HTML export.

## Documentation Maintenance

- Update `CHANGELOG.md` under `[Unreleased]` for every user-visible feature,
  behavioral change, bug fix, deprecation, or operational command
- Review and update `AGENTS.md` whenever architecture, source ownership,
  workflow commands, result artifacts, safety invariants, or validation
  requirements change
- Do not add routine implementation details or test-count churn to either file
- Keep `README.md`, `docs/workflow.md`, and `docs/quality-methodology.md`
  aligned with public commands and quality-scoring semantics

## Safety & Quality

- Do not hardcode secrets — use environment variables
- Keep `.env` local and `.env.example` limited to placeholder values
- Fallback to safe defaults when uncertainty is high
- Treat all model output as untrusted content and escape it before HTML rendering
