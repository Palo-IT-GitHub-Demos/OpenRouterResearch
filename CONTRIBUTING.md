# Contributing to llm-model-screening

## Setup

```bash
git clone <repo>
cd llm-model-screening
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
npm install
pre-commit install
```

Copy `.env.example` to `.env` and fill in `OPENROUTER_API_KEY` before running any
benchmark. **Never commit `.env`.**

## Branches

| Pattern | Purpose |
| --- | --- |
| `main` | Production-ready, protected |
| `feat/<short-description>` | New features |
| `fix/<short-description>` | Bug fixes |
| `chore/<short-description>` | Maintenance, deps, config |
| `docs/<short-description>` | Documentation only |

## Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
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
make docs-build    # build the documentation site strictly
```

## Documentation

- Put user guides, ADRs, and plans in `docs/` using descriptive headings.
- Keep docstrings accurate for every public Python class or function; the API
 reference is generated from them during the MkDocs build.
- Do not duplicate API signatures in prose. Link to the API reference instead.
- Run `make docs-build` when changing `docs/`, `src/`, `dashboard/`, or
 `mkdocs.yml`. The documentation workflow runs this same validation on pull
 requests and publishes `main` to GitHub Pages.

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

To switch between the internally authored probe sets already shipped in the repo
(`basic` built-in, `owasp` — `data/prompts/owasp_probes.json`, aligned with the
OWASP categories, `extended` — `data/prompts/extended_probes.json`, advanced
LLM01 red-team probes), prefer the higher-level `SECURITY_MODE`
env var or the `--security`/`SECURITY=` override instead of spelling out a
path — see `make models` and `src/core/model_presets.py` for the equivalent
on the model-selection side (`TARGET_MODELS`/`--models`/`MODELS=`).

## Pre-commit hooks

Hooks run automatically on `git commit`. To run manually:

```bash
pre-commit run --all-files
```
