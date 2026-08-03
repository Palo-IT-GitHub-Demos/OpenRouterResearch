# Arborescences officielles : GitHub Copilot & Claude Code

> Sources : docs.github.com · code.claude.com — juillet 2026

---

## Arborescence complète (référence rapide)

```
repo/
├── CLAUDE.md                                   # Claude Code — instructions projet (versionné)
├── CLAUDE.local.md                             # Claude Code — notes perso (gitignore)
├── .mcp.json                                   # Claude Code — serveurs MCP partagés équipe (versionné)
├── .worktreeinclude                            # Claude Code — fichiers gitignorés → worktrees (versionné)
├── .gitignore                                  # Doit contenir CLAUDE.local.md
│
├── .claude/                                    # Claude Code
│   ├── settings.json                           # Permissions, hooks, env, modèle (versionné)
│   ├── settings.local.json                     # Overrides perso (gitignore)
│   ├── rules/
│   │   └── *.md                                # Règles globales ou path-scoped (paths: frontmatter)
│   ├── skills/
│   │   └── <skill-name>/SKILL.md               # Skills invocables — même format que .github/skills/
│   ├── agents/
│   │   └── <agent-name>.md                     # Sous-agents avec leur propre system prompt
│   ├── hooks/
│   │   └── *.sh                                # Scripts shell référencés depuis settings.json
│   ├── workflows/
│   │   └── *.js                                # Workflows dynamiques (orchestrent des subagents)
│   ├── output-styles/
│   │   └── *.md                                # Styles de system-prompt personnalisés
│   └── agent-memory/
│       └── <agent-name>/MEMORY.md              # Mémoire persistante des subagents (auto-générée)
│
└── .github/                                    # GitHub Copilot
    ├── copilot-instructions.md                 # Instructions repo-wide (toujours chargées)
    ├── instructions/
    │   └── NAME.instructions.md                # Règles path-scoped (applyTo: frontmatter)
    ├── prompts/
    │   └── NAME.prompt.md                      # Prompts réutilisables (invocation manuelle)
    ├── skills/
    │   └── <skill-name>/SKILL.md               # Skills — même open standard que .claude/skills/
    ├── agents/
    │   └── NAME.agent.md                       # Agents spécialisés (cloud agent)
    └── hooks/
        └── NAME.json                           # Hooks lifecycle (preToolUse, sessionStart...)
```

> **Point clé 1** : `.github/skills/` et `.claude/skills/` partagent **exactement le même format** `SKILL.md` ([agentskills.io](https://agentskills.io) — open standard).
> **Point clé 2** : `.mcp.json` et `.worktreeinclude` sont à la **racine du projet**, pas dans `.claude/`.

---

## Table de correspondance Copilot ↔ Claude Code

| Besoin | GitHub Copilot | Claude Code |
|---|---|---|
| Instructions toujours actives | `.github/copilot-instructions.md` | `CLAUDE.md` |
| Règles scoped à des chemins | `.github/instructions/*.instructions.md` | `.claude/rules/*.md` |
| Prompts invocables manuellement | `.github/prompts/*.prompt.md` | — |
| Skills auto + invocables | `.github/skills/<name>/SKILL.md` | `.claude/skills/<name>/SKILL.md` |
| Agents spécialisés | `.github/agents/NAME.agent.md` | `.claude/agents/<name>.md` |
| Hooks lifecycle | `.github/hooks/NAME.json` | `.claude/settings.json` + `.claude/hooks/*.sh` |
| Serveurs MCP | `mcp.json` (IDE) ou `mcp-servers` dans agent | `.mcp.json` (racine) |
| Mémoire persistante | Copilot Memory (settings GitHub) | `CLAUDE.md` + auto memory |

---

## GitHub Copilot — `.github/`

### `copilot-instructions.md`

Instructions repo-wide injectées automatiquement dans **chaque requête**. Garder sous 200 lignes.

### `instructions/NAME.instructions.md`

Instructions scoped à des chemins via frontmatter `applyTo` :

```yaml
---
applyTo: "**/*.py"
excludeAgent: "code-review"   # optionnel
---
Use Python 3.11+ type hints on all public functions.
```

### `prompts/NAME.prompt.md`

Prompts réutilisables invocables manuellement depuis le chat. Non chargés automatiquement.
Disponibles dans VS Code, Visual Studio, et JetBrains.

### `skills/<name>/SKILL.md`

Skills chargés dynamiquement selon le contexte, ou invocables via `/skill-name`.
Voir la section **Format SKILL.md** ci-dessous — format identique à `.claude/skills/`.

Gestion via CLI : `gh skill install OWNER/REPO SKILL`, `gh skill update`, `gh skill publish`
Communauté : [`github/awesome-copilot`](https://github.com/github/awesome-copilot) · [`anthropics/skills`](https://github.com/anthropics/skills)

### `agents/NAME.agent.md`

Agents spécialisés avec leur propre system prompt, outillage, et modèle.
Créés via l'IDE (dropdown agents → "Configure Custom Agents") ou manuellement.

```yaml
---
name: test-specialist            # optionnel (défaut : nom du fichier)
description: Ce que fait l'agent # requis
tools: ["read", "search", "edit"]
model: claude-sonnet-4-5
target: vscode                   # "vscode" | "github-copilot" | omit for both
mcp-servers: {}
handoffs: []
---

Markdown body = system prompt (max 30 000 caractères)
```

Disponibilité : VS Code (GA), JetBrains / Eclipse / Xcode (public preview).

### `hooks/NAME.json`

Hooks exécutés déterministement à des points précis du workflow. GA sur cloud agent et CLI, preview sur VS Code.

```json
{
  "version": 1,
  "hooks": {
    "preToolUse": [
      {
        "type": "command",
        "bash": "./scripts/security-check.sh",
        "powershell": "./scripts/security-check.ps1",
        "timeoutSec": 15
      }
    ]
  }
}
```

Événements : `sessionStart`, `sessionEnd`, `userPromptSubmitted`, `preToolUse`, `postToolUse`, `agentStop`, `subagentStop`, `errorOccurred`.
`preToolUse` peut **approuver ou bloquer** un appel d'outil. Hooks personnels : `~/.copilot/hooks/*.json`

### `AGENTS.md` (n'importe où dans le repo)

Instructions lues par Copilot, Claude Code, et d'autres agents IA. Le fichier le plus proche dans l'arbre prend la priorité. Équivalent de `CLAUDE.md` ou `GEMINI.md` pour un usage multi-outils.

### Fonctionnalités sans fichier projet

| Fonctionnalité | Configuration |
|---|---|
| **MCP Servers** | `mcp.json` (chemin selon l'IDE) ou settings repository GitHub |
| **Copilot Memory** (preview) | Settings GitHub uniquement — pas de fichier à créer |
| **Subagents** | Runtime — sélectionnable via `@mention` dans le chat |

> `~/.copilot/` est **user-level uniquement** (Copilot CLI), jamais commité. Il n'existe pas de dossier `.copilot/` au niveau projet.

---

## Claude Code — racine + `.claude/`

### Fichiers à la racine

| Fichier | Rôle | Committer |
|---|---|---|
| `CLAUDE.md` | Instructions projet chargées à chaque session | ✅ Oui |
| `CLAUDE.local.md` | Notes perso, non partagées | ❌ gitignore |
| `.mcp.json` | Serveurs MCP partagés avec l'équipe | ✅ Oui |
| `.worktreeinclude` | Fichiers gitignorés à copier dans chaque worktree | ✅ Oui |

`.mcp.json` : utiliser des références d'env vars pour les secrets — `"GITHUB_TOKEN": "${GITHUB_TOKEN}"`

Niveaux de portée pour `CLAUDE.md` :

| Niveau | Emplacement | Versionné |
|---|---|---|
| Organisation | `/Library/Application Support/ClaudeCode/CLAUDE.md` | Non (MDM) |
| User | `~/.claude/CLAUDE.md` | Non |
| Projet | `./CLAUDE.md` ou `./.claude/CLAUDE.md` | ✅ Oui |
| Local | `./CLAUDE.local.md` | ❌ gitignore |

### `.claude/settings.json`

Permissions, hooks, variables d'env, modèle par défaut. Versionné.
`.claude/settings.local.json` = overrides perso (gitignore).

```json
{
  "permissions": { "allow": ["Bash(npm test *)"], "deny": ["Bash(rm -rf *)"] },
  "hooks": {
    "PostToolUse": [{ "matcher": "Edit|Write", "hooks": [{ "type": "command", "command": "..." }] }]
  },
  "autoMemoryEnabled": true
}
```

Événements hooks : `PreToolUse`, `PostToolUse`, `SessionStart`, `SessionEnd`, `Stop`, `Notification`, `SubagentStart`, `SubagentStop`, `CwdChanged`, `FileChanged`, etc.

### `.claude/rules/*.md`

Instructions scoped à des chemins précis. Sans `paths:` → chargé à chaque session.

```yaml
---
paths:
  - "src/api/**/*.ts"
  - "**/*.py"
---
Règles qui s'appliquent uniquement aux fichiers correspondants.
```

### `.claude/agents/<name>.md`

Sous-agents avec leur propre system prompt et accès aux outils.

```yaml
---
name: code-reviewer
description: Reviews code for correctness, security, and maintainability
tools: Read, Grep, Glob
---
System prompt de l'agent...
```

### `.claude/hooks/*.sh`

Scripts shell exécutés via les hooks définis dans `settings.json`. Doivent être `chmod +x`.

### `.claude/workflows/*.js`

Workflows dynamiques orchestrant de nombreux subagents. Écrits par Claude et sauvegardés depuis `/workflows`. Chaque fichier devient une commande `/<name>`.

### `.claude/output-styles/*.md`

Styles de system-prompt qui adaptent le comportement de Claude (ex : mode enseignement, mode revue). Sélectionnables via `outputStyle` dans settings.

### `.claude/agent-memory/<name>/MEMORY.md`

Mémoire persistante des subagents configurés avec `memory: project`. Auto-générée et maintenue par Claude.

---

## Format SKILL.md (open standard partagé Copilot + Claude Code)

Le format est identique pour `.github/skills/` et `.claude/skills/`.

```yaml
---
name: skill-name                    # requis, lowercase, tirets
description: Ce que fait le skill   # requis — utilisé pour l'auto-invocation
allowed-tools: Read Grep Glob       # optionnel
disable-model-invocation: true      # true = seulement invocable manuellement
argument-hint: "[arg1] [arg2]"      # optionnel
context: fork                       # fork = sous-agent isolé
license: MIT                        # optionnel
---

Markdown body avec les instructions...
```

Structure du dossier :

```
my-skill/
├── SKILL.md        # fichier principal (requis, nom fixe)
├── helper.sh       # scripts référençables
└── examples.md     # ressources optionnelles
```

---

## Plugins Claude Code

Les plugins empaquettent skills, agents, hooks et MCP servers pour les partager entre projets.

```
my-plugin/
├── .claude-plugin/
│   └── plugin.json           # manifeste (nom, version, description)
├── skills/<skill-name>/SKILL.md
├── agents/<agent-name>.md
├── hooks/hooks.json          # même format que settings.json hooks
└── .mcp.json
```

Manifeste minimal :

```json
{
  "name": "my-plugin",
  "description": "Description du plugin",
  "version": "1.0.0"
}
```

Les skills d'un plugin sont **namespaced** : `/my-plugin:skill-name` (évite les conflits).
Commandes : `claude plugin install`, `/plugin list`, `/reload-plugins`, `claude plugin init <name>`

---

## Ce qui N'est PAS un standard officiel

| Ce qu'on voit parfois | Réalité |
|---|---|
| `ai/` à la racine | Convention custom — aucun outil ne le lit nativement |
| `.copilot/` au niveau projet | N'existe pas — c'est `~/.copilot/` user-level uniquement |
| `ai/plugins/`, `ai/agents/` | Standards gen-e2 marketplace, non reconnus par Copilot ou Claude Code |
| `.claude/commands/` | Déprécié — remplacé par `.claude/skills/` |

---

*Sources : [Copilot customization cheat sheet](https://docs.github.com/en/copilot/reference/customization-cheat-sheet) · [About agent skills](https://docs.github.com/en/copilot/concepts/agents/about-agent-skills) · [About hooks (Copilot)](https://docs.github.com/en/copilot/concepts/agents/hooks) · [Custom agents in IDE](https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/create-custom-agents-in-your-ide) · [Claude Code .claude directory](https://code.claude.com/docs/en/claude-directory) · [Claude Code skills](https://code.claude.com/docs/en/skills) · [Claude Code hooks](https://code.claude.com/docs/en/hooks-guide) · [Claude Code plugins](https://code.claude.com/docs/en/plugins) · [agentskills.io](https://agentskills.io)*
