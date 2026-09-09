# Référence API

Cette page est générée directement depuis les docstrings des modules Python du
pipeline via le plugin `mkdocstrings`. Toute modification de docstring dans le
code source est reflétée ici au prochain `make docs-build` — aucune synchronisation
manuelle n'est nécessaire.

`dashboard/app.py` est volontairement **exclu** de cette référence : c'est un
script Streamlit avec des effets de bord au niveau module (rendu de page,
lecture de fichiers), pas une bibliothèque importable sans risque au moment du
build de la documentation. Son comportement est décrit en prose dans
[le guide de workflow](../workflow.md#9-lire-les-resultats).

## Configuration

::: src.core.config

## Client OpenRouter

::: src.api.openrouter_client

## Évaluateurs

### Coût

::: src.evaluators.cost_analyzer

### Qualité — pré-évaluation déterministe

::: src.evaluators.deterministic_eval

### Qualité — collecte et fusion des scores

::: src.evaluators.quality_judge

### Qualité — agrégation des métriques

::: src.evaluators.quality_metrics

### Model Compass — recommandations

::: src.evaluators.recommendation

### Sécurité

::: src.evaluators.security_scanner

## Observabilité

::: src.observability.tracker

## Orchestrateur du pipeline

::: src.main

## Tableau de bord

### Frontière de Pareto

::: dashboard.pareto

### Visualisations de sécurité

::: dashboard.security_viz
