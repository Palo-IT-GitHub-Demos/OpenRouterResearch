# Contributing to open-router-research

## Setup

```bash
git clone <repo>
cd open-router-research
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
npm install
pre-commit install
```

Copy `.env.example` to `.env` and fill in `OPENROUTER_API_KEY` before running any
benchmark. **Never commit `.env`.**

## Branches

| Pattern | Purpose |
|---|---|
| `main` | Production-ready, protected |
| `feat/<short-description>` | New features |
| `fix/<short-description>` | Bug fixes |
| `chore/<short-description>` | Maintenance, deps, config |
| `docs/<short-description>` | Documentation only |

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(evaluators): add async quality judge
fix(scanner): handle probe timeout gracefully
chore: bump mlflow to 2.15
docs: update README quick start
```

Header ≤ 72 characters. No trailing period. Lower-case type and subject.
Enforced by `commitlint` — runs on `git commit` via pre-commit.

## Pull requests

1. Branch from `main`
2. Keep PRs small — one concern per PR
3. All CI checks must pass before merging
4. At least one approval required
5. Fill in the PR template checklist

## Running checks locally

```bash
make test          # pytest (76 tests, API calls mocked)
make lint          # ruff check
make fmt           # ruff format
mypy src/ --strict # type-check
```

## Adding a new evaluator

1. Create `src/evaluators/<name>.py` with a sync class and an `Async` variant.
2. Both must accept the matching client (`OpenRouterClient` / `AsyncOpenRouterClient`).
3. Return a `pd.DataFrame` from `run_full_scan` / `run_dataset`.
4. Register the async variant in `AsyncPipeline` in `src/main.py`.
5. Add tests in `tests/test_<name>.py` using `unittest.mock.AsyncMock`.

## Adding security probes

Place a JSON file with the schema `[{"name": "", "description": "", "message": ""}]`
anywhere and set `SECURITY_PROBES_PATH=<path>` in `.env`. The scanner will load
your probes instead of the built-in set.

## Pre-commit hooks

Hooks run automatically on `git commit`. To run manually:

```bash
pre-commit run --all-files
```


## Branches

| Pattern | Purpose |
|---|---|
| `main` | Production-ready, protected |
| `feat/<short-description>` | New features |
| `fix/<short-description>` | Bug fixes |
| `chore/<short-description>` | Maintenance, deps, config |
| `docs/<short-description>` | Documentation only |

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add user authentication
fix: handle empty API response
chore: bump ruff to 0.5
docs: improve setup instructions
```

## Pull requests

1. Branch from `main`
2. Keep PRs small — one concern per PR
3. All CI checks must pass before merging
4. At least one approval required
5. Fill in the PR template — especially the checklist

## Running checks locally

```bash
make test     # run all tests
make lint     # run all linters
make fmt      # auto-format code
```

Or individually:

```bash
# Python
pytest --tb=short
ruff check .
mypy src/

# TypeScript
npm test
npm run lint
npm run type-check
```

## Pre-commit hooks

```bash
pip install pre-commit
pre-commit install
```

Hooks run automatically on `git commit`.
