---
name: generate-stories
description: Extract INVEST-shaped, vertically-sliced user stories from product or business sources — meeting transcripts, PRDs, epics, requirements briefs, interview notes, or any text describing what a system should do. Use this whenever the user has a source document and wants user stories from it, even if they don't say "user story" explicitly. Phrases like "extract stories from this transcript", "turn this PRD into a backlog", "give me stories for this brief", "break this epic into smaller stories", or "what user stories come out of this meeting" should all trigger this skill.
---

# Generate user stories

Extract user stories from a source document and write one Markdown file per story under `docs/stories/`. Each story is a thin, vertical slice of user value, shaped by INVEST. Every story carries a **status** that tracks its lifecycle from extraction through delivery.

The shape of the input shapes how you read it. A transcript is mostly noise around a few signal moments. A PRD is structured and dense, written from a system perspective. An epic is already story-shaped and just needs decomposition. A brief is informal and you'll need to infer the structure. **Same output, different paths in** — identify the source type before you start, and let it guide the intake.

## Step 1 — Get the source

If the user pointed you at a file or pasted text, use it. If they didn't, ask where the source is — file path or pasted text — before going further. Don't invent stories from thin air.

If the source is in a format you can't read (binary, locked, very large), say so and ask how the user wants to proceed.

## Step 2 — Identify the source type

Determine which of these the source most resembles. Don't ask the user unless it's genuinely ambiguous — most documents declare themselves on the first page.

- **Transcript** — meeting or interview notes with speaker turns, conversational filler, timestamps, off-topic asides. Multiple voices, low signal-to-noise, requirements implied rather than stated.
- **PRD / spec** — structured product document with sections like goals, scope, requirements, success metrics. Single voice, dense, requirements explicit but framed as system capabilities.
- **Epic** — a single coarse user story that needs breaking down into smaller deliverable stories. Already in user-story format but too large for one iteration.
- **Brief / business doc** — informal document describing a problem, opportunity, or initiative. Often missing explicit requirements; you'll need to infer them.

If none of these fit cleanly, treat the source as a brief and apply the most flexible intake.

## Step 3 — Read with the right lens

**Transcripts.** Filter aggressively. Most lines are conversational glue. Look for moments where someone names a user need, describes a frustration, or proposes a feature. Track who said what — speakers often map to roles in the resulting stories. Ignore process discussion (sprint dates, who's free Friday) and surface anything tagged as a parking lot or open question.

**PRDs and specs.** The requirements are already there but framed as system capabilities, not user value. Your job is to flip them: for each capability, find the user, the action, and the *so-that* benefit. Be ruthless about vertical slicing — a PRD section like "search and filtering" usually wants to become several thin stories, not one fat one.

**Epics.** Decompose, don't paraphrase. The epic itself is one story — your output is the smaller stories that, taken together, deliver it. Each child story should still be independently demoable.

**Briefs.** Infer the missing structure. Ask: what is the user trying to accomplish? What's blocking them today? What would success look like? Then write stories that close that gap.

## Step 4 — Check for existing stories

Before writing anything, look at `docs/stories/`. If it exists and contains numbered files, continue the numbering from the highest existing number — don't restart at `01-`. If a story you were about to write is already there in spirit, skip it or extend the existing file rather than duplicating.

## Step 5 — Write the stories

Create one file per story under `docs/stories/`, named `NN-kebab-case-of-the-goal.md` (e.g., `04-filter-products-by-category.md`). The two-digit prefix gives you natural ordering up to 99 stories per backlog.

Each file contains exactly one story in this format:

```markdown
# User Story: NN — Brief title describing the goal

**Status:** draft | ready

**As a** [role],
**I want** [action or capability],
**so that** [benefit or value].

## Acceptance Criteria

- [Criterion 1]
- [Criterion 2]

## Notes

- [Context, open questions, links to source — optional]
```

### Story statuses

Every story gets a status that reflects how committed it is:

- **`draft`** — Extracted from the source but not yet validated or committed by a stakeholder. The item was mentioned (as vision, wish, or idea) but no one with authority said "build this now." Draft stories are real signal worth keeping — they'll likely become `ready` in a future iteration — but they are not actionable yet.
- **`ready`** — Validated and committed for the current scope. A stakeholder explicitly said this should be built, and the story is clear enough to plan and implement.

Later skills in the workflow (`implementation-plan`, `execute-plan`) extend this lifecycle with `in progress` and `done`. This skill only assigns `draft` or `ready`.

**How to decide:** look for explicit scope decisions in the source. If a PO says "let's start with X," then X stories are `ready` and everything else is `draft`. If a PRD has a "must-have" vs "nice-to-have" split, map those to `ready` and `draft`. When there's no clear signal, default to `draft` — it's safer to under-commit than to over-commit.

Apply INVEST as you write. The principles aren't a checklist — they're a way of pressure-testing each story before you commit it:

- **Independent** — the story should make sense on its own. Natural feature dependencies are fine, but don't tightly couple unrelated concepts in one story.
- **Negotiable** — capture the essence, not the contract. Implementation details get refined later.
- **Valuable** — the *so-that* must name a real benefit to a real user (or to the system itself, for non-functional stories). If you can't write a meaningful *so-that*, the story isn't valuable yet — keep digging or drop it.
- **Estimable** — clear enough that a team could size it. Vague stories aren't estimable.
- **Small** — one iteration's worth of work. If it's bigger, it's an epic and needs decomposition.
- **Testable** — acceptance criteria should be verifiable. If an AC reads as opinion, rewrite it as observable behavior.

**Vertical slicing is the single most common failure mode, so it's worth being explicit.** Each story is a thin, end-to-end slice of user value — UI + logic + data, not a layer or a component.

- ✅ "As a shopper, I want to log in with my email so that I can access my account."
- ❌ "Build the login database table." / "Build the login API endpoint." / "Design the login UI."

If you find yourself writing a story about a database table, an API endpoint, or a UI component in isolation, stop and re-slice along the user-value axis instead.

If the source explicitly mentions acceptance criteria, include them. Otherwise, leave AC empty and note that they need definition — don't fabricate criteria the source doesn't support. Inferring AC the user never agreed to is worse than admitting the gap.

## Step 6 — Hand off

After writing the files, give the user a short summary: how many stories you created (and how many are `ready` vs `draft`), the title of each, and any open questions. Then offer the natural next step:

> Want me to plan one of these next? I can pick one and run the implementation-plan skill.

This is the second step of the workflow — `generate-stories` → `implementation-plan` → `execute-plan` — and the user should know the chain exists.

## When stories don't fit

Some signals in the source won't yield a clean story. They might be too vague, too far from the user, or describe non-user-facing infrastructure. If they're deferred features worth capturing, write them as `draft` stories — they preserve the signal without over-committing. If they're open questions or ambiguities, attach them to the `## Notes` section of the story they affect. If they're just noise, drop them. It's better to leave gaps for the user to fill than to ship stories that fail INVEST.
