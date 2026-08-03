# open-router-research — AI Agent Instructions

> This file is read by GitHub Copilot, Claude Code, and other AI agents.
> Replace `[PROJECT NAME]` and `[DESCRIPTION]` with your project details before using this template.

## Project Overview

Doing researches on openrouter llm evaluation considering Security, Performance and cost.

## Architecture & Conventions

- Source code lives in `src/`
- Follow language-specific rules in `.github/instructions/` (Copilot) and `.claude/rules/` (Claude Code)
- All AI artifacts are organised under `.github/` (Copilot) and `.claude/` (Claude Code)

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

## Safety & Quality

- Do not hardcode secrets — use environment variables
- Fallback to safe defaults when uncertainty is high
- Never expose raw model output to end users
