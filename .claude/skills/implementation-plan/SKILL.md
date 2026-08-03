---
name: implementation-plan
description: Create a detailed, codebase-aware implementation plan from a user story. Use this whenever the user has a story (or feature description) and wants to plan how to build it — "plan this story", "create an implementation plan", "how should we implement this", "break this into tasks", or any request to go from a story to a technical plan. This is the second step of the workflow after generate-stories and before execute-plan. Also use this when the user points at a story file in docs/stories/ and asks what to do next. When the invocation includes Figma URLs (`figma.com/file/...` or `figma.com/design/...`), this skill delegates to the `figma-extractor` agent to produce design documents that are referenced from the resulting plan.
---

# Implementation Plan

Turn a user story into a detailed, codebase-aware implementation plan. The plan lives in `docs/implementation-plans/` and becomes the input for the execute-plan skill.

The cardinal rule: **understand before you plan.** A plan that ignores the project's context is fiction. The whole point of this skill is to produce a plan grounded in the project's actual stack, patterns, and conventions — and detailed enough to serve as both an execution checklist AND documentation for the team.

## Invocation

`/delivery:implementation-plan <story-ref> [<figma-url-1> <figma-url-2> ...]`

`<story-ref>` is a path under `docs/stories/` or a verbal description of the feature. Subsequent arguments matching `figma.com/file/...` or `figma.com/design/...` trigger design extraction (Step 3.5 below). When no Figma URLs are provided, the skill plans without design context — fine for backend-only or design-already-documented stories.

## Step 1 — Get the story

If the user pointed you at a story file (e.g., `docs/stories/01-log-daily-water-intake.md`), read it. If they described the feature verbally, look for a matching story in `docs/stories/`. If there's no story file, ask whether you should create one first (via generate-stories) or plan from the verbal description directly.

Only plan stories with status `ready`. If the story is `draft`, tell the user it needs validation before planning — planning a draft wastes effort on something that might never ship.

## Step 2 — Read project instructions

Check for project-level instructions first — these are the team's explicitly written-down decisions and carry the most weight:

- **CLAUDE.md** (root of the project) — stack, conventions, file structure, testing expectations
- **agents.md**, **AI_RULES.md**, or similar — some projects use different names
- **README.md** — often has stack and setup info

These files are gold. They tell you the stack, conventions, and expectations without guessing. If CLAUDE.md says "Next.js 14 + Zustand + Tailwind," that's the answer — no detection needed.

## Step 3 — Explore the codebase

With the project instructions as your map, scan the actual codebase to validate and fill gaps:

- **Find existing patterns** — how does the codebase already handle similar features? If you're planning a new form, find an existing form. If you're planning an API endpoint, find an existing one. The plan should follow established conventions, not invent new ones.
- **Identify the relevant files** — which files will you need to modify or create? Be specific — file paths, not "the component directory."
- **Check what's already built** — does any part of this feature already exist? Is there shared infrastructure (auth, database client, API layer) the plan should use?

If the project is empty (greenfield) and there are no project instructions, ask the user about the stack before planning.

## Step 3.5 — Extract design specs from Figma (when applicable)

Scan `$ARGUMENTS` for Figma URLs (any token matching `figma.com/(file|design)/...`). If none are present, skip this step entirely — don't ask the user for one and don't invoke any agent.

For each Figma URL found, invoke the `extract-design` skill with the URL and a base name derived from the story (e.g., `water-tracker` for a hydration-tracking feature):

```
/delivery:extract-design <figma-url> <base-name>
```

With one URL, pass `<base-name>` as-is — the skill writes `docs/design/<base-name>.md`. With multiple URLs, derive a variant suffix from the Figma metadata's page or node name and pass the full name (e.g., `water-tracker-mobile`, `water-tracker-mobile-dark`) so each invocation produces a distinct file. If variants can't be derived from metadata, ask the user before invoking.

`extract-design` runs in a forked subagent context — Figma's metadata stays there and only the file path + a short summary come back. Use those references when you fold the design docs into the plan.

After all design docs are written, fold them into the plan:

- **Architecture** section: incorporate the design's component tree, layout system, and design tokens worth surfacing.
- **File Changes** section: list each design doc path so contributors know they exist.
- **Approach** section: cite specific design decisions (color palette, spacing, typography, responsive breakpoints) when they shape the implementation strategy.

Multiple URLs typically mean responsive or theme variants — call out the variant differences in the Approach section so reviewers can challenge the responsive strategy alongside the rest of the plan.

## Step 4 — Load the stack profile

Check `references/` in this skill's directory for a matching profile:
- `references/nextjs-react.md` — Next.js / React / TypeScript projects
- `references/generic.md` — fallback for any stack without a dedicated profile

Read the relevant profile. It contains stack-specific conventions that inform the plan's structure. If no profile matches, use `generic.md`.

## Step 5 — Write the plan

Save the plan to `docs/implementation-plans/NN-kebab-case-matching-the-story.md` (use the same numbering and slug as the story file).

The plan has this structure:

```markdown
# Implementation Plan: NN — [Story title]

## Story

[Copy the full user story — As a / I want / so that + ACs]

## Context

[What the project instructions (CLAUDE.md) and codebase scan revealed:
stack, conventions, existing patterns, infrastructure already in place.
This section proves you understood the project before planning.]

## Approach

[2-3 paragraphs explaining HOW to implement this. This is the strategic
decision — what architecture, data flow, patterns to follow. Justify
choices by referencing the project's conventions. Explain WHY this
approach over alternatives — a reviewer should be able to challenge
the reasoning.]

## Architecture

[Visual or structured description of how the pieces fit together. Use
Mermaid diagrams for data flow, component relationships, or sequence
of operations when they add clarity. Include key type/interface
definitions that establish the data contracts between layers.

Only include diagrams and types that are real — based on the actual
story and project stack. This section is where documentation value
lives: a future developer reading this plan should understand the
feature's design without reading the code.]

## File Changes

[Files to create or modify, with a one-line description of each change.
Use checkboxes — the execute skill marks these as it works.]

- [ ] `path/to/file.ext` — [what to create or change]
- [ ] `path/to/other.ext` — [what to create or change]

## Task Breakdown

[Ordered list of implementation tasks. Each task is a single, independently
testable unit of work. These are what the execute skill iterates through.]

1. [ ] [Task description — specific enough to act on without re-reading the plan]
2. [ ] [Task description]
3. [ ] ...

## Acceptance Criteria Mapping

[How each AC from the story maps to tasks above. This is the traceability
that ensures nothing falls through the cracks.]

| AC | Task(s) |
|----|---------|
| [AC text] | Task 1, 3 |
| [AC text] | Task 2 |

## Testing Strategy

[What to test and how. Reference the project's existing test setup if one
exists. Include edge cases the ACs imply but don't spell out.]

## Dependencies

[External libraries needed, API contracts assumed, other stories that must
be done first. If none, say "None."]

## Open Questions

[Anything discovered during exploration that could affect implementation.
If none, say "None."]
```

Every section should contain **project-specific content** from your codebase exploration. If a section would only contain generic boilerplate ("use proper error handling"), either make it specific to this project or drop it.

## Step 6 — Hand off

After writing the plan, summarize: the story being planned, the approach in one sentence, how many tasks, and any blockers or open questions. Then offer the next step:

> Ready to start implementing? I can pick up task 1 with the execute-plan skill.

This is the third step of the workflow — `generate-stories` → `implementation-plan` → `execute-plan`.

## What makes a good plan

A good plan serves three purposes:

1. **Reviewable** — a tech lead or PO can read the Approach and Architecture sections and challenge design decisions before any code is written. The reasoning should be explicit enough to debate.
2. **Executable** — a developer (or the execute skill) can pick up any task from the Task Breakdown and implement it without re-reading the original story or re-exploring the codebase. Every task references specific files and describes a concrete change.
3. **Documentable** — the plan becomes a lasting record of what was built and why. The Architecture section (diagrams, type definitions) and Approach section (design rationale) have value beyond execution — they help future developers understand the feature.

A bad plan is a filled-in template with generic content — "create the component," "add error handling," "write tests." Those aren't tasks, they're wishes. Be specific: "Create `src/app/hydration/_components/WaterTracker.tsx` as a client component with a button that calls the `logWater` server action and displays the current count from `useHydrationStore`."
