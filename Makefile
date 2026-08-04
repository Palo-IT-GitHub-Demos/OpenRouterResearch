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

run: ## Phase 1 — collecte réponses + éval déterministe + sécurité (alias de collect)
	python -m src.main collect
	@echo ""
	@echo "Étape suivante — Phase 2 : dans Copilot chat, invoquer :"
	@echo "  @judge-coordinator   (lance les 3 juges en parallèle automatiquement)"
	@echo "Puis Phase 3 : make merge"

collect: ## Phase 1 — collect responses + deterministic eval + security (lit TARGET_MODELS depuis .env)
	python -m src.main collect

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
	python -m src.main merge

dashboard: ## Launch the Streamlit dashboard
	streamlit run dashboard/app.py
