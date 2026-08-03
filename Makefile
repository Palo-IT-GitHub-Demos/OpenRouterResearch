.PHONY: help install dev test lint fmt type-check run collect judge merge dashboard

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -e .
	npm install --omit=dev

dev: ## Install all dependencies (including dev)
	pip install -e ".[dev]"
	npm install
	pre-commit install

test: ## Run all tests (Python)
	pytest --tb=short

lint: ## Run all linters
	ruff check .
	npm run lint

fmt: ## Auto-format all code
	ruff format .
	npm run format

type-check: ## Run type checkers
	mypy src/
	npm run type-check

run: ## Full pipeline (Python + OpenRouter judge)
	env -u TARGET_MODELS -u JUDGE_MODEL -u MLFLOW_TRACKING_URI -u MAX_CONCURRENT_REQUESTS python -m src.main

collect: ## Phase 1 — collect responses + deterministic eval + security (no LLM judge)
	env -u TARGET_MODELS -u JUDGE_MODEL -u MLFLOW_TRACKING_URI -u MAX_CONCURRENT_REQUESTS python -m src.main collect

judge: ## Phase 2 info — open judge-benchmark prompt in Copilot agent mode
	@echo "In VS Code Copilot chat, run:"
	@echo "  #prompt:judge-benchmark"
	@echo ""
	@echo "Latest pending file:"
	@ls data/intermediate/pending_*.json 2>/dev/null | tail -1 || echo "  (none — run make collect first)"

merge: ## Phase 3 — merge Copilot scores + export final results
	env -u TARGET_MODELS -u JUDGE_MODEL -u MLFLOW_TRACKING_URI -u MAX_CONCURRENT_REQUESTS python -m src.main merge

dashboard: ## Launch the Streamlit dashboard
	streamlit run dashboard/app.py
