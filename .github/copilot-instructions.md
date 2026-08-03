# Copilot Repository Instructions

## Project Overview
Doing researches on openrouter llm evaluation considering Security, Performance and cost.
This repository is built from the **gen-e2 AI-ready project template**.
Stack: multi-language (Python + TypeScript).

## AI Asset Policy
- Skills → `.github/skills/<name>/SKILL.md`
- Agents → `.github/agents/<name>.agent.md`
- Prompts (manual invocation) → `.github/prompts/<name>.prompt.md`
- Hooks → `.github/hooks/<name>.json`
- Claude Code artifacts → `.claude/`
- Plugin registry → `.claude/plugins/<name>/plugin.json`

## Coding Standards
- Keep code simple and testable
- Prefer deterministic output contracts for AI-assisted features
- Add tests for any behavior-changing change

## Commit Messages — Conventional Commits (strict)
Every commit message **must** follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<optional scope>): <short description in lower-case>

[optional body]
[optional footer]
```

Allowed types: `feat` · `fix` · `chore` · `docs` · `test` · `refactor` · `perf` · `ci` · `build` · `revert`

Rules enforced by `.commitlintrc.json`:
- Type and subject must be lower-case
- Header ≤ 72 characters
- No trailing period on subject line

Examples:
```
feat(auth): add jwt refresh token rotation
fix(api): handle null response from upstream service
chore: bump ruff to 0.5.0
```

## Safety & Quality
- Do not hardcode secrets — use environment variables (see `.env.example`)
- Fallback to safe defaults when uncertainty is high
- Never expose raw model output to end users
