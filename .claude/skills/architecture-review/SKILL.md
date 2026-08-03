---
name: architecture-review
description: Review repository architecture from repo evidence. Use for architecture reviews, design trade-offs, ADR and gen-e2 `.arch` decision records, system/domain diagrams, threat-modelling prompts, and improving an existing design from code, config, tests, and docs. Do not use for simple bug fixes, style-only refactors, or generic best-practice brainstorming without repo evidence.
---

# Architecture Review

Reason about software architecture from **repository evidence**, not generic patterns.

## Ask, don't invent

Before advising, stop and ask the user — once — when:

- the target area, decision, or non-functional requirement is unclear
- there is no usable repo evidence and the user wants invented target architecture
- a constraint (compliance, deadline, owner) is referenced but undefined

Do not fill evidence gaps with generic best-practice prose.

## When to use

Architecture review, ADR / gen-e2 `.arch` decision records, system/domain/C4/sequence/deployment/data-flow diagrams, decomposition or boundary review, risk analysis, design challenge before implementation.

## When not to use

Local bug fixes, generic brainstorming, style/naming clean-up, invented target architecture with no repo evidence.

## Required inputs (one or more)

- target area, module, service, app, or decision
- relevant paths or files
- problem statement or non-functional requirement
- existing diagram, ADR, RFC, or design note

Clarify only if required to proceed.

## Repo evidence to inspect (only what's relevant)

READMEs and architecture docs · `docs/architecture/`, `docs/adr/`, `adr/`, `decisions/`, RFCs · entry points, service boundaries, package/workspace structure · dependency manifests, build files · API/event schemas, route definitions, contracts · DB schemas, migrations, ORM models · queues, jobs, schedulers, workflows · infra/deploy/orchestration/env config · authn/authz, policy, secrets, network boundaries · logs, metrics, traces, alerts, dashboards, runbooks · integration/contract/resilience tests · incident notes, postmortems.

## Protocol

1. Clarify only if required.
2. Identify relevant evidence.
3. Inspect before advising.
4. List facts (evidence-traceable).
5. List assumptions and unknowns separately.
6. Analyse quality attributes.
7. Challenge weak or missing requirements.
8. Identify options and trade-offs.
9. Recommend one option.
10. Propose or update the most useful diagram.
11. Record the decision when justified — as an ADR **and** a gen-e2 `.arch` `decisions[]` entry.

If evidence is weak: **Insufficient evidence** and list missing artefacts.

## Reasoning discipline

**Facts** are traceable to repo evidence, supplied docs, or explicit user statements. **Assumptions** are marked, never shown as facts.

**Risks to call out:** architectural mismatch · unclear ownership · hidden coupling · boundary leakage · missing resilience · unsafe data flows · operational blind spots · migration/rollout risk.

**Trade-offs per option:** benefits · drawbacks · complexity · migration cost · reversibility · quality-attribute impact.

**Recommendation:** what to do · why · what to change in repo/docs · what to validate next.

## Diagrams

**Default lens (~60%):** domain / application / system diagrams. If the repo already has a canonical application-architecture diagram, update it rather than creating a parallel one.

**Secondary lens (~40%):** C4, sequence, deployment, or data-flow — only when that specific lens is genuinely required.

Reach for **C4** only when the user asks by name, the multi-zoom hierarchy is the point, or structural decomposition at several zoom levels is the review's purpose. Do not default to C4 just because it's familiar.

**Selection guide:**

- domain — bounded contexts, ownership, language boundaries
- application — apps, services, integration surfaces (default; update canonical diagram if it exists)
- system — high-level topology, external actors
- C4 context / container / component — only when that zoom level is the point
- sequence — runtime behaviour or request flows
- deployment — environments, nodes, infra mapping
- data flow — trust boundaries, sensitive data, integration analysis

**Rules (every diagram):**

- derived from evidence; do not invent components, stores, integrations, or trust boundaries
- uncertain element → omit or mark as assumption
- Mermaid preferred
- smallest diagram that answers the current question
- label edges with intent; include protocol/technology where known
- show boundaries, data stores, external systems, trust boundaries
- note the evidence the diagram was derived from
- when emitting Mermaid, follow the co-located `mermaid-creator` skill (syntax, layout, palette)

## Decisions (ADR + gen-e2 `.arch`)

**Record a decision when** it is architecturally significant · hard to reverse · boundary-shaping · deployment-shaping · data-ownership-related · materially affects security/reliability/operability/maintainability/cost.

**Do not** record one for trivial code choices, local naming/style, or obvious one-way implementation details.

Output **both** forms for every recorded decision:

1. **ADR** (narrative) — one decision per ADR · context · decision drivers · considered options (with trade-offs and rejected ones) · decision · consequences · follow-up. Supersede prior ADRs rather than rewriting history.
2. **gen-e2 `.arch` `decisions[]` entry** (machine-readable) — append to an existing `*.gen-e2.arch` file in the target repo (search for one; create one per the schema if none exists). Never overwrite a versioned artefact; consult the gen-e2 arch schema/instructions available in the repo or runtime you are using.

**ADR → `decisions[]` field mapping:**

| ADR element | `decisions[]` field |
|---|---|
| title / topic | `topic` |
| decision | `choice` |
| context + decision drivers | `rationale` |
| considered / rejected options | `alternatives[]` (string list) |
| confidence | `confidence` — `validated` / `strong-signal` / `assumption` |
| stable identifier | `id` (kebab-case) |

Consequences and follow-up stay in the ADR narrative; unresolved follow-ups also go to the artefact's `openQuestions[]`. The `.arch` `confidence` enum has no `hypothesis` — record a speculative call as `assumption` and flag the speculation in the ADR.

## Output format

Default structure (unless user asks otherwise):

```
### Facts
### Assumptions and unknowns
### Architecture reading
### Quality attribute review
### Risks and trade-offs
### Recommendation
### Diagram proposal
### Decision record (ADR + gen-e2 `.arch`)
### Next evidence to inspect
```

Add a Mermaid block when it adds clarity.

## Quality attributes (relevant subset)

Review only the quality attributes materially impacted by the current decision, and tie each claim to repo evidence (facts), explicit uncertainty (assumptions), and concrete ADR trade-offs.

## Anti-patterns

- generic best-practice dumps
- "microservices" / "event-driven" recommendations without evidence
- invented future-state diagrams presented as current state
- mixing facts and assumptions
- ADRs for insignificant decisions
- technology churn without migration reasoning
- advice that ignores repo constraints
- diagrams with unlabelled edges or undefined scope

## Quality bar

A good answer starts from repo evidence, separates facts from assumptions, surfaces risks and trade-offs, gives one practical recommendation, includes a diagram only when it adds clarity, says **Insufficient evidence** when needed, and avoids generic clichés.

## Example invocations

- Review the architecture of `services/payments` from repo evidence.
- Create a system diagram for this app from the current codebase.
- Turn this decision into an ADR.
- Challenge this design before implementation.
- Find architecture risks in the ingestion pipeline.
