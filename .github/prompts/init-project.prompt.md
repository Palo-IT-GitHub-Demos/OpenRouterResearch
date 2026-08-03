---
mode: agent
description: Initialise this project from the template — replaces all placeholders, installs hooks, and verifies the setup.
---

Initialise this project from the gen-e2 template. Do the following steps in order.

## Step 1 — Collect project information

Ask the user for the following values (ask all at once, one question):

1. **Project name** — short identifier, e.g. `my-api`
2. **Description** — one sentence describing what the project does
3. **GitHub team handle** — e.g. `my-org/backend-team` (used in CODEOWNERS)
4. **Security email** — e.g. `security@my-org.com` (used in SECURITY.md)

Wait for the answers before proceeding.

## Step 2 — Replace all placeholders

Using the values collected above, replace every placeholder in the following files:

| File | Placeholder | Replace with |
|---|---|---|
| `AGENTS.md` | `[PROJECT NAME]` | project name |
| `AGENTS.md` | `[DESCRIPTION]` | description |
| `.github/copilot-instructions.md` | `<!-- Replace with your project description -->` | description |
| `.github/CODEOWNERS` | `[your-org/your-team]` (all occurrences) | GitHub team handle |
| `SECURITY.md` | `[security@your-org.com]` | security email |
| `pyproject.toml` | `[project-name]` | project name (kebab-case) |
| `pyproject.toml` | `[description]` | description |
| `package.json` | `[project-name]` | project name (kebab-case) |
| `package.json` | `[description]` | description |

## Step 3 — Install dev tooling

Run the following commands:

```bash
pip install -e ".[dev]"
pip install "git+https://github.com/Palo-IT-GitHub-Demos/lab-registry-mcp@v0.2.0"
npm install
pre-commit install
```

## Step 4 — Verify

Confirm to the user:
- All placeholders have been replaced (grep for `\[` remaining)
- Pre-commit hooks are installed
- Remind them to set `REGISTRY_GITHUB_TOKEN` in their environment to enable gen-e2 plugin installation
