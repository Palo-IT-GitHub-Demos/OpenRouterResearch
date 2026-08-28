.PHONY: help install dev test test-cov lint fmt type-check docs-build docs-serve run collect judge merge dashboard verify dry-run export-gen-e2 models

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
	$(PYTHON) -m pytest --cov=src --cov-report=term-missing --tb=short

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

run: ## Phase 1 — collecte réponses + éval déterministe + sécurité (alias de collect ; MODELS=<preset|liste> SECURITY=<basic|owasp|extended> optionnels)
	$(PYTHON) -m src.main collect $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))
	@echo ""
	@echo "Étape suivante — Phase 2 : dans Copilot chat, invoquer :"
	@echo "  @judge-coordinator   (lance les 3 juges en parallèle automatiquement)"
	@echo "Puis Phase 3 : make merge"

collect: ## Phase 1 — collect responses + deterministic eval + security (MODELS=<preset|list> SECURITY=<basic|owasp|extended> optional, else .env)
	$(PYTHON) -m src.main collect $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

verify: ## Vérification réelle mais gratuite — clé API + TARGET_MODELS contre le catalogue live OpenRouter (GET /key + GET /models, $0, avant un run payant ; MODELS=/SECURITY= optionnels)
	$(PYTHON) -m src.main verify $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

dry-run: ## Simulation offline du pipeline complet — AUCUN appel OpenRouter, AUCUN agent juge (MODELS=/SECURITY= optionnels)
	$(PYTHON) -m src.main dry-run $(if $(MODELS),--models "$(MODELS)") $(if $(SECURITY),--security $(SECURITY))

judge: ## Phase 2 — ouvrir un agent juge Copilot (choisir parmi les 3 providers)
	@echo "Option A — coordinateur (recommandé) : lance les 3 juges automatiquement"
	@echo "  @judge-coordinator"
	@echo ""
	@echo "Option B — juges indépendants (lancer les 3 en parallèle) :"
	@echo "  @judge-anthropic  (Claude)  |  @judge-openai  (GPT-4o)  |  @judge-google  (Gemini)"
	@echo ""
	@echo "Fichier judging en attente :"
	@ls data/intermediate/judging_*.json 2>/dev/null | tail -1 || echo "  (aucun — lancer make collect d'abord)"

merge: ## Phase 3 — merge Copilot scores + export final results
	$(PYTHON) -m src.main merge

dashboard: ## Launch the Streamlit dashboard
	$(PYTHON) -m streamlit run dashboard/app.py

models: ## List the coherent model-set presets available for MODELS=<name> (see also: dashboard "Plan a new run")
	$(PYTHON) -m src.main models

export-gen-e2: ## Export latest benchmark to gen-e2-eval compatible YAML (set PROFILE=<name> to override)
	$(PYTHON) scripts/export_gen_e2_registry.py \
		--results $(shell ls -t results/benchmark_*.json 2>/dev/null | head -1) \
		--output evaluation/candidates/openrouter-security-pricing.yaml \
		--profile $(if $(PROFILE),$(PROFILE),enterprise_qa)
