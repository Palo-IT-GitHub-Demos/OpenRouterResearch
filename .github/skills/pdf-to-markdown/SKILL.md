---
name: pdf-to-markdown
description: Use when converting any PDF to markdown, especially when the PDF contains architecture diagrams, system topologies, or technical illustrations that should be represented as Mermaid. Triggers on requests like "convert this PDF to markdown", "extract the architecture diagram", "turn this PDF into a markdown doc with Mermaid diagrams", "ingest this PDF for the repo". Use when fidelity matters — the skill produces side-by-side Mermaid + preserved source images so a human can verify accuracy.
---

# pdf-to-markdown Skill

## Workflow

### Step 0 — Confirm
Ask the user three questions before proceeding:
1. **Where is the PDF?**
2. **Where should the final markdown and assets be saved?** (e.g., `docs/proposal/`) — this is the permanent destination folder.
3. **Is internet available for `npm install`?**

Do not proceed until all three are answered.

### Step 1 — Extract
Derive `<pdf-basename>` by stripping the `.pdf` extension from the PDF filename (keep spaces/special chars as-is). Extract to a temporary directory under `.tmp/` at repo root:

```bash
# Run from repo root
mkdir -p .tmp/<pdf-basename>
cd "${CLAUDE_PLUGIN_ROOT:-.claude}/skills/pdf-to-markdown/scripts"
npm install   # first run only
node extract.mjs <input.pdf> ../../../.tmp/<pdf-basename>
```
Outputs per page: `assets/page-NN.png` (300 DPI), `text/page-NN.txt`, `manifest.json`.  
**Verify:** pageCount matches; all PNGs > 100 KB; text files have readable content.

### Step 2 — Triage
View every PNG. Build a triage table (page | type | content note | approach) and present to user. Wait for confirmation.  
Types: **text-only** · **diagram** (two-pass Mermaid) · **table** (markdown table) · **mixed** (split by region). See `reference/diagram-triage.md`.

### Step 3 — Convert text pages
Strip: page numbers, running headers, `Error! Bookmark not defined.`, dotted TOC leaders.  
Preserve: section numbers, bullet structure, emphasis.

### Step 4 — Convert diagram pages — TWO PASSES MANDATORY
**Pass 1:** View PNG → identify type (`reference/mermaid-architecture-patterns.md`) → write node/edge inventory → draft Mermaid with `classDef` colours.  
**Pass 2:** View PNG again → walk inventory against draft → catch missed annotations/edges → complete verification checklist → refine until every item is genuinely ticked.  
Do not skip Pass 2 on diagrams that look simple.

### Step 5 — Convert table pages
Markdown table with text labels. If logos are used, zoom the PNG to read names. Preserve exact column/row structure.  
Do **not** embed the source PNG — the markdown table is the complete representation. No `![Source: page N]` line for table pages.

### Step 6 — Assemble `<pdf-basename>.md`
Combine sections in page order per `reference/output-format.md`. Every diagram: PNG above, Mermaid block, checklist below.  
Write to `.tmp/<pdf-basename>/<pdf-basename>.md` — **not** `output.md`.

### Step 7 — Self-check
Read `.tmp/<pdf-basename>/<pdf-basename>.md` end to end and confirm:
- Every page in `manifest.json` is represented
- No orphan headings, broken image refs, or unbalanced Mermaid fences
- No TOC artefacts, page footers, or "see PDF" copouts
- Every diagram has a diagram-specific (not boilerplate) verification checklist

Once the self-check passes, prune unreferenced page PNGs (text-only pages were rendered for triage but have no place in the final output), then delete the remaining intermediate files:

```bash
# Keep only diagram-page PNGs (referenced in markdown AND followed by a mermaid block or diagram note).
# Table and cover pages have no PNG reference in the markdown, so unreferenced PNGs are deleted.
for f in ".tmp/<pdf-basename>/assets"/page-*.png; do
  grep -qF "$(basename "$f")" ".tmp/<pdf-basename>/<pdf-basename>.md" || rm "$f"
done

# Remove extraction intermediates
rm -rf ".tmp/<pdf-basename>/text" ".tmp/<pdf-basename>/manifest.json"
```

### Step 8 — Deliver
Move the completed markdown and assets to the user-specified permanent destination, then remove the now-empty temp folder:

```bash
mkdir -p <user-destination>
mv ".tmp/<pdf-basename>/<pdf-basename>.md" "<user-destination>/"
mv ".tmp/<pdf-basename>/assets" "<user-destination>/"
rm -rf ".tmp/<pdf-basename>"
```

Do **not** remove `.tmp/` itself — other in-progress extractions may be there.

## Anti-patterns
- Skipping Pass 2 on a diagram that "looks simple"
- Omitting the source PNG above a Mermaid block
- Inventing content not visible in the PNG
- Using `graph LR` for layered top-down diagrams
- Encoding meaning in node labels instead of `classDef`

## Honest limits
Mermaid is semantic-fidelity, not pixel-fidelity. For diagrams where spatial layout, logos, or photographic content carry meaning, keep PNG-only with a prose description. Do not attempt a partial Mermaid that misleads.

## Directory layout
```
${CLAUDE_PLUGIN_ROOT:-.claude}/skills/pdf-to-markdown/
├── SKILL.md
├── scripts/
│   ├── extract.mjs
│   └── package.json
└── reference/
    ├── mermaid-architecture-patterns.md
    ├── diagram-triage.md
    └── output-format.md
```
