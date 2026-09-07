.PHONY: help install dev test test-cov lint fmt type-check docs-build docs-serve run collect judge merge dashboard verify dry-run inspect-run select export-gen-e2 export-html verify-quality models

PYTHON ?= .venv/bin/python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install production dependencies
	pip install -e .
	npm install --omit=dev

dev: ## Install all dependencies (including dev)
	pip install -e ".[dev,docs]"
	npm install
	pre-commit install

test: ## Run all tests (Python)
	$(PYTHON) -m pytest --tb=short

test-cov: ## Run tests with a coverage report (requires pytest-cov, see [dev] extras)
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing --cov-fail-under=80 --tb=short

lint: ## Run all linters
	$(PYTHON) -m ruff check .
	npm run lint

fmt: ## Auto-format all code
	$(PYTHON) -m ruff format .
	npm run format

type-check: ## Run type checkers
	$(PYTHON) -m mypy src/
	npm run type-check

docs-build: ## Build documentation and validate links strictly
	$(PYTHON) -m mkdocs build --strict

docs-serve: ## Preview documentation with live reload
	$(PYTHON) -m mkdocs serve

run: ## Phase 1 — collect responses + deterministic eval + security (alias of collect; MODELS=<preset|list> SECURITY=<basic|owasp|extended> optional)
	$(PYTHON) -m src.main collect $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))
	@echo ""
	@echo "Next step — Phase 2 (required, no extra API cost): in Copilot chat, invoke:"
	@echo "  @judge-coordinator   (runs the 3 blind judges in parallel automatically)"
	@echo "Then Phase 3: make merge"

collect: ## Phase 1 — PAID, calls OpenRouter — collect responses + deterministic eval + security (MODELS=<preset|list> SECURITY=<basic|owasp|extended> optional, else .env)
	$(PYTHON) -m src.main collect $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

verify: ## Real but free preflight — API key + TARGET_MODELS against the live OpenRouter catalog (GET /key + GET /models, $0, before a paid run; MODELS=/SECURITY= optional)
	$(PYTHON) -m src.main verify $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

dry-run: ## Fully offline simulation of the whole pipeline — NO OpenRouter call, NO judge agent (MODELS=/SECURITY= optional)
	$(PYTHON) -m src.main dry-run $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

inspect-run: ## Verify the latest run manifest and artifact checksums
	$(PYTHON) -m src.main inspect-run

select: ## Preview dynamic OpenRouter model selection without starting a benchmark
	$(PYTHON) -m src.main select \
		$(if $(PAID_ONLY),--paid-only) $(if $(FREE_ONLY),--free-only) \
		$(if $(MAX_INPUT_PRICE),--max-input-price $(MAX_INPUT_PRICE)) \
		$(if $(MAX_OUTPUT_PRICE),--max-output-price $(MAX_OUTPUT_PRICE)) \
		$(if $(MIN_CONTEXT),--min-context $(MIN_CONTEXT)) $(if $(LIMIT),--limit $(LIMIT))

judge: ## Phase 2 — open a Copilot judge agent (pick one of the 3 providers)
	@echo "Option A — coordinator (recommended): runs all 3 judges automatically"
	@echo "  @judge-coordinator"
	@echo ""
	@echo "Option B — independent judges (run all 3 in parallel):"
	@echo "  @judge-anthropic  (Claude)  |  @judge-openai  (GPT-4o)  |  @judge-google  (Gemini)"
	@echo ""
	@echo "Pending judging file:"
	@ls data/intermediate/judging_*.json 2>/dev/null | tail -1 || echo "  (none — run make collect first)"

merge: ## Phase 3 — merge Copilot scores + export final results
	$(PYTHON) -m src.main merge

dashboard: ## Launch the Streamlit dashboard
	$(PYTHON) -m streamlit run dashboard/app.py

export-html: ## Export a static, self-contained HTML snapshot of the dashboard (RESULTS=/OUTPUT=/PROFILE= optional, else latest run + enterprise_qa)
	$(PYTHON) scripts/export_dashboard_html.py \
		$(if $(RESULTS),--results "$(RESULTS)") \
		$(if $(OUTPUT),--output "$(OUTPUT)") \
		$(if $(PROFILE),--profile "$(PROFILE)")

verify-quality: ## Recheck one k=1 objective failure twice through OpenRouter (pass ARGS="...")
	$(PYTHON) scripts/verify_quality_reproducibility.py $(ARGS)

models: ## List the coherent model-set presets available for MODELS=<name> (see also: dashboard "Plan a new run")
	$(PYTHON) -m src.main models

export-gen-e2: ## Export latest benchmark to gen-e2-eval compatible YAML (set PROFILE=<name> to override)
	$(PYTHON) scripts/export_gen_e2_registry.py \
		--results $(shell ls -t results/benchmark_*.json 2>/dev/null | head -1) \
		--output evaluation/candidates/openrouter-security-pricing.yaml \
		--profile $(if $(PROFILE),$(PROFILE),enterprise_qa)
