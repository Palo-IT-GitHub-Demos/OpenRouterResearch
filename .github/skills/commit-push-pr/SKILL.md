---
name: commit-push-pr
description: Commit all current changes, push to a branch, and create or update a pull request — all in one step. Use this when the user says "commit and PR", "push and create a PR", "open a PR for this", "ship it", or any request to go from local changes to a pull request. Also triggers on "commit-push-pr" or "cpp".
disable-model-invocation: true
---

# Commit, Push, and PR

Take the current working tree changes, create a commit, push to a remote branch, and open (or update) a pull request — all in one shot.

## Step 1 — Gather context

Before doing anything, collect the state of the repo. Run all of these in parallel:

- `git status` — see what's staged, unstaged, and untracked
- `git diff HEAD` — see the actual changes
- `git branch --show-current` — which branch you're on
- `git log --oneline -5` — recent commit messages for style reference
- `gh pr view --json number,title,url 2>/dev/null || true` — check if a PR already exists for this branch

Also determine the default branch: check `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null` or fall back to `main`.

## Step 2 — Create a branch if needed

If you're on the default branch (main/master), create a new feature branch before committing. Name it `username/short-description` where:
- `username` comes from `$USER` or `whoami`
- `short-description` is a kebab-case summary of the changes

If you're already on a feature branch, stay on it.

## Step 3 — Stage and commit

Stage the relevant files and create a single commit. Follow the repository's existing commit message style (check the recent log from Step 1).

Use heredoc syntax for the commit message to handle multi-line content cleanly:

```bash
git commit -m "$(cat <<'EOF'
Short summary of changes

Optional longer description if the changes warrant it.
EOF
)"
```

Guidelines:
- Keep the first line under 72 characters
- Summarize the *why*, not the *what* — the diff shows the what
- Do NOT commit files that likely contain secrets (`.env`, credentials, tokens)
- Do NOT use `git add -A` or `git add .` blindly — stage specific files

## Step 4 — Push

Push the branch to origin:

```bash
git push -u origin <branch-name>
```

If the branch already exists on the remote, a regular `git push` is fine.

## Step 5 — Create or update the PR

Check the `gh pr view` output from Step 1:

**If no PR exists** — create one:

```bash
gh pr create --title "Short, descriptive title" --body "$(cat <<'EOF'
## Summary
- [1-3 bullet points describing the changes]

## Test plan
- [ ] [How to verify this works]
EOF
)"
```

**If a PR already exists** — update it to reflect the current state:

```bash
gh pr edit --title "Updated title if needed" --body "$(cat <<'EOF'
## Summary
- [Updated bullet points]

## Test plan
- [ ] [Updated verification steps]
EOF
)"
```

PR guidelines:
- Keep the title under 70 characters — use the body for details
- The summary should explain what changed and why, not list files
- The test plan should be actionable — what would a reviewer do to verify?

## Step 6 — Report

Return the PR URL so the user can see it. If CLAUDE.md mentions posting to a Slack channel, ask the user if they'd like you to share the PR URL there.

## Git Safety Protocol

These are non-negotiable:
- NEVER update the git config
- NEVER run destructive git commands (`push --force`, `reset --hard`, etc.) unless the user explicitly asks
- NEVER skip hooks (`--no-verify`, `--no-gpg-sign`) unless the user explicitly asks
- NEVER force push to main/master — warn the user if they request it
- NEVER commit files that likely contain secrets
- NEVER use interactive git flags (`-i`) — they require terminal input that isn't supported

## Efficiency

You can call multiple tools in a single response. Do as much as possible in parallel — gather all context at once, then execute the branch→commit→push→PR sequence without unnecessary round-trips. The goal is to go from local changes to a PR URL in one shot.
