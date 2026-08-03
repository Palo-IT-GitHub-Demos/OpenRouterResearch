---
name: execute-plan
description: Execute tasks from an implementation plan — one task at a time, with Definition of Done checks and plan-file updates. Use this whenever the user wants to start building from a plan, says "execute task 1", "implement the next task", "start building", or points at a plan file and asks to begin. This is the third step of the workflow after generate-stories and implementation-plan. Also use this when the user says "pick up where we left off" on a partially-completed plan.
---

# Execute Plan

Execute the full implementation plan — work through every task from first to last, updating the plan as you go. Don't stop to ask "should I continue?" between tasks unless you hit a genuine blocker or need clarification. The user invoked this skill to get the plan built, not to approve each step.

The execute skill is the only skill in the workflow that writes production code. It's also the one that updates the plan's checkboxes and the story's status, keeping both artifacts current as implementation progresses.

## Step 1 — Load the plan

If the user pointed you at a plan file (e.g., `docs/implementation-plans/01-log-daily-water-intake.md`), read it. If they didn't, look in `docs/implementation-plans/` for the most recently modified plan. If there's nothing there, tell the user to create one first (via implementation-plan).

Read the full plan. Understand the story, the approach, the architecture, and the task breakdown. You need all of this context before touching any code.

## Step 2 — Pick the task

If the user specified a task ("execute task 3"), start there. Otherwise, start from the first unchecked task (`[ ]`) in the Task Breakdown and work through the plan sequentially until every task is checked off.

Each task gets its own implement → quick-verify → update cycle, but you move to the next one immediately — no asking for permission between tasks. The only reasons to stop are:
- A **blocker** you can't resolve (missing dependency, ambiguous requirement, failing build that isn't your fault)
- A **clarification** that genuinely changes what you'd implement next
- The user explicitly told you to execute only a single task

## Step 3 — Read project instructions

Before implementing, check for project-level quality expectations:

1. **CLAUDE.md** — coding conventions, testing expectations, lint/format requirements
2. **Definition of Done** — check for `docs/definition-of-done.md`. If it exists, it defines what "done" means for this project/client. If it doesn't exist, fall back to CLAUDE.md's testing expectations. If neither exists, ask the user once what their DoD looks like and offer to save it as `docs/definition-of-done.md` for future tasks.

The Definition of Done is the quality gate. A task is not done until every DoD criterion passes. Common DoD items include:
- Code compiles / builds without errors
- Tests pass (unit, component, integration — as specified)
- No lint/type errors
- Acceptance criteria verified
- Plan file updated

## Step 4 — Implement

Now write the code. Follow the plan's approach and architecture — don't reinvent. If the plan says "create `src/stores/useHydrationStore.ts` as a Zustand store," do exactly that. The plan already made the design decisions; your job is to execute them faithfully.

Key principles:
- **Scope discipline** — implement ONLY what the current task describes. If you notice something else that needs fixing, note it but don't do it. Scope creep in execution is how plans go sideways.
- **Follow the codebase** — use existing patterns. If the project has a way of doing things (from CLAUDE.md or from what you see in the code), match it.
- **Tests are part of the task** — if the plan's task description mentions tests, write them. If the DoD requires tests, write them. Don't treat testing as a separate step that happens "later."

## Step 5 — Verify (tiered)

Don't run the full build/lint/test suite after every single task — that's wasteful and slow. Use tiered checks instead:

### After each task (quick check)
- **Syntax/import check** — does the file you just wrote have obvious errors? Can it be parsed? Do imports resolve? A quick typecheck of just the changed files (e.g., `tsc --noEmit path/to/file.ts`) is enough.
- **New tests pass** — if this task included writing tests, run just those tests (e.g., `vitest run path/to/file.test.ts`), not the entire suite.
- **AC spot-check** — glance at the plan's AC Mapping. Does what you just wrote clearly address the mapped ACs?

If the quick check fails, fix it before moving to the next task.

### After the final task (full DoD)
Once every task in the plan is checked off, run the full Definition of Done:

1. **Build** — run the project's build command (`bun run build`, `npm run build`, etc.)
2. **Lint + typecheck** — run the linter and type checker across the whole project
3. **Full test suite** — run all tests, not just the ones you wrote
4. **AC review** — walk through every acceptance criterion in the story and confirm it's met

If anything fails at this stage, fix it. This is the real quality gate — the earlier quick checks are just guardrails to avoid accumulating broken code.

### When to escalate mid-plan
Run a full build/test mid-plan only if:
- You suspect a task broke something in an earlier task (e.g., you changed a shared type)
- The quick check reveals an error that might cascade
- The task is a natural integration point (e.g., "wire everything together")

## Step 6 — Update the plan

After the task passes the DoD, update the plan file:

1. **Task Breakdown** — change the task's checkbox from `[ ]` to `[x]`
2. **File Changes** — mark any files this task touched as `[x]`
3. **Story status** — if this is the first task being executed, update the story file's status from `ready` to `in progress`. If this is the last task (all checkboxes are now `[x]`), update the story status to `done`.

The plan file is the persistent record of progress. Anyone looking at it should immediately see what's done and what's left.

## Step 7 — Continue or report

**If there are more tasks**: move straight to the next one. No need to ask — just briefly note what you completed ("Task 1 done — created `useHydrationStore.ts` + tests") and keep going.

**If all tasks are complete**: run the full DoD (Step 5), update the story status to `done`, and give a final summary:
- What was built (files created/modified)
- Whether all DoD checks passed
- Any issues or observations worth noting

Then offer the natural next step:

> All tasks complete, story marked `done`. Want me to run a final review, move to the next story, or open a PR?

## What makes good execution

Good execution is invisible — the code follows the plan, matches the project's patterns, and passes the DoD without drama. The best sign of good execution is a clean diff that a reviewer can understand in 30 seconds.

Bad execution is when the executor second-guesses the plan, introduces new patterns, adds unrequested features, or skips the DoD because "it's a small change." Small changes with skipped checks are how bugs ship.

If the plan is wrong (the approach won't work, a dependency is missing, the architecture doesn't fit), **stop and say so** rather than silently diverging. It's better to go back and update the plan than to implement something that doesn't match it.
