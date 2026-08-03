---
name: mermaid-creator
description: >
  Create, review, or fix any Mermaid diagram. Use when the user wants a
  flowchart, sequence, state machine, ER, C4, class, journey, Gantt, mindmap,
  timeline, git graph, sankey, quadrant, or any other Mermaid diagram type.
  Also use when an existing Mermaid diagram renders incorrectly, looks wrong,
  or needs a layout fix.
# Copilot-only field; ignored by Claude Code runtimes.
argument-hint: >
  Describe what you want to diagram — the system, flow, entities, lifecycle,
  or interactions. Optionally name a diagram type. Examples: "sequence diagram
  for our login flow", "layered architecture for the backend", "state machine
  for ticket status", "fix this flowchart that stacks subgraphs vertically".
---

# Mermaid Creator Skill

## Purpose

Produce correct, semantically clear Mermaid diagrams on first draft.
Layout renders as intended. Syntax is valid. Style is consistent.

---

## Procedure

### Step 1 — Gather intent

Collect before drafting. Ask once for anything missing:

| Question | Why it matters |
|---|---|
| **What to diagram?** | System, flow, entities, lifecycle, interactions? |
| **Audience?** | Engineering detail vs. exec overview vs. BA handoff? |
| **Preferred orientation?** | Top-down, left-right, or no preference? |
| **Rendering environment?** | GitHub, Confluence, VS Code, Lucid, Mermaid live? |

Never assume the diagram type — state your choice and the reasoning.

---

### Step 2 — Select diagram type

Read `reference/diagram-type-selector.md` and pick the single best type.
State your selection in one line: `Diagram type: X — because Y.`

---

### Step 3 — Build a node/edge inventory

Before writing any syntax, list every element:

- **Nodes / entities / actors / states** — with proposed ID and display label
- **Edges / transitions / messages** — with direction and label
- **Groups / subgraphs / clusters / swimlanes**

This inventory is the source of truth for Pass 2 verification.
If the inventory exceeds ~40 nodes, recommend splitting into multiple focused diagrams.

---

### Step 4 — Draft

Apply the matching pattern from `reference/diagram-patterns.md`:

- **IDs**: `camelCase` or `snake_case`; no spaces; no Mermaid reserved words
  (`end`, `class`, `call`, `graph`, `subgraph`, `direction`, `style`, `classDef`)
- **Labels**: ≤ 5 words; quote if they contain `( ) [ ] { } : / @ # > < & " '` (if the label contains `"`, encode it as `&quot;`)
- **Colour / style**: `classDef` only — never inline `style nodeId ...`
  Apply palette from `reference/style-palette.md`
- **Comments**: `%%` for context that doesn't belong in a label
- **`%%{init}%%`**: place on line 1, before the diagram type declaration

---

### Step 5 — Two-pass verification (MANDATORY — never skip Pass 2)

**Pass 1 — Structural correctness**

Walk the inventory against the draft:
- [ ] Every node present exactly once (no duplicates, no omissions)
- [ ] Every edge has correct direction and label
- [ ] Subgraph labels match their intended content
- [ ] No orphan nodes (disconnected from everything)
- [ ] Every `:::className` matches a defined `classDef` (order-independent; convention: define them at the bottom)

**Pass 2 — Syntax correctness**

- [ ] No spaces in node IDs
- [ ] No Mermaid reserved words used as IDs
- [ ] All brackets/parens/braces balanced
- [ ] Labels with special characters are quoted
- [ ] Arrow type matches diagram semantics (see pattern file)
- [ ] No semicolons in `classDiagram` attributes
- [ ] `%%{init}%%` directive is on line 1 if used
- [ ] Direction (`TB`, `LR`, `RL`, `BT`) matches visual intent

---

### Step 6 — Layout check

Before outputting, apply the rules in `reference/layout-troubleshooting.md`:

- Diagrams with sibling subgraphs in `direction LR`? → check for vertical stacking bug
- Diagram > 15 nodes? → consider ELK layout hint
- Any subgraph with external connections? → note that `direction` hint will be ignored

---

### Step 7 — Output

Emit the diagram in a fenced ` ```mermaid ``` ` block.

Follow with:
1. One sentence describing what the diagram shows
2. Any rendering notes (ELK requirement, known renderer gaps, split recommendation)

If fixing an existing diagram, also note what was wrong and what changed.

---

## Anti-patterns — never do these

| Anti-pattern | Why it fails |
|---|---|
| `style nodeId fill:#...` inline | Fragile; use `classDef` + `:::class` |
| Reserved word as node ID | Parse error (`end`, `call`, `graph`, etc.) |
| Spaces in node IDs | Parse error |
| Unquoted label with special characters | Parse error on `( ) [ ] { } : / @ #` |
| `-->` in `sequenceDiagram` | Wrong; `-->` = dashed; `->>` = solid sync |
| Semicolons in `classDiagram` | Mermaid doesn't use semicolons |
| `linkStyle N` for semantic colouring | Edge index shifts when you add edges; use node `classDef` instead |
| One giant diagram (> 50 nodes) | Unreadable and layout breaks; split it |
| Wrapper subgraph around LR siblings | Causes vertical stacking; flatten instead |
| Skipping Pass 2 on a "simple" diagram | Simple diagrams still have syntax errors |

---

## When NOT to use Mermaid

- Photographic, hand-drawn, or spatial diagrams where position = meaning
- Data-dense charts (bar, line, scatter, heatmap) — use a real charting tool
- Diagrams where after Pass 2 you cannot honestly verify every element

Use a PNG + prose description instead:

```markdown
![Diagram description](path/to/image.png)

> **Diagram note:** {What it shows and why Mermaid was not used.}
```

---

## Reference files

| File | Purpose |
|---|---|
| `reference/diagram-type-selector.md` | Decision tree for picking the right type |
| `reference/diagram-patterns.md` | Canonical pattern + example for every supported type |
| `reference/layout-troubleshooting.md` | Layout fixes, syntax error catalogue, rendering notes |
| `reference/style-palette.md` | `classDef` palettes, theming, edge styling |
