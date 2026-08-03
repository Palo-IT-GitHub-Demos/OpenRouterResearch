---
mode: agent
description: Install delivery, implementation-plan, and architecture-reviewer plugins from the gen-e2 marketplace.
---

Install the following gen-e2 plugins into this project using the lab-registry MCP server:

1. `delivery` (v0.2.3) — story-to-PR delivery workflow
2. `implementation-plan` (v0.1.0) — deterministic, AI-executable implementation plans
3. `architecture-reviewer` (v0.1.0) — evidence-first architecture analysis + Mermaid diagrams

For each plugin:
- Fetch the full install package from the registry via `mcp_lab-registry_get_plugin_install_package`
- Write all skill files to `.github/skills/<name>/SKILL.md` (Copilot) and `.claude/skills/<name>/SKILL.md` (Claude Code)
- Write all agent files to `.github/agents/<name>.agent.md` (Copilot) and `.claude/agents/<name>.md` (Claude Code)
- Ensure `.claude/plugins/<plugin>/plugin.json` is up to date

After installation, list all installed artefacts grouped by plugin.
