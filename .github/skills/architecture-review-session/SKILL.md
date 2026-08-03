---
name: architecture-review-session
description: Explicit user-invokable entry command for evidence-first architecture review sessions with evidence labels, fact/assumption separation, and code-graph-first analysis. Use when the user asks to start an architecture review.
disable-model-invocation: true
---

# Architecture Review Session Entry

Use this as the explicit entry command when the user asks to run an architecture review.

## Routing

1. Activate the `architecture-review-agent` persona for the conversation. **Note:** In Claude Code, each invocation is single-shot — re-invoke this skill at the start of each new review task. In VS Code Copilot, `@architecture-review-agent` persists across turns in the same chat.
   - **Claude Code**: Request "Load the architecture-review-agent persona" or use agent activation syntax.
   - **VS Code Copilot**: Mention `@architecture-review-agent` to activate the persona.
   - **Fallback**: If agent activation is unavailable, continue — steps 2–4 below provide the methodology protocol. Evidence labelling and code-graph-first analysis still apply.
2. Load the `architecture-review` skill as the methodology source.
3. Keep evidence labels (`validated`, `strong-signal`, `assumption`, `hypothesis`) on non-trivial claims.
4. Prefer code-graph artefacts over broad text search when available.

## Scope

Use for architecture review sessions, ADR challenge/review, and evidence-first boundary/ownership/risk analysis.

Do not use for simple bug fixes, style-only refactors, or generic brainstorming without repo evidence.
