# OpenRouter Research

Pipeline de **pré-sélection générique** des modèles disponibles sur OpenRouter,
calibrée pour aider à constituer une shortlist avant une évaluation métier
dans [gen-e2-eval](https://github.com/GLOBAL-PALO-IT/gen-e2-eval).

## Trois axes de mesure

| Axe | Ce que ça mesure | Sortie clé |
| --- | --- | --- |
| **Qualité** | 16 prompts versionnés, 6 dimensions, score macro-moyen 1-5 + taux de couverture + stabilité optionnelle | `avg_quality_score`, `quality_coverage_rate`, `quality_stability_score` |
| **Sécurité** | 30 sondes [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/), score RSI 0-100 (pondération interne, non publiée par OWASP — cf. `_RSI_WEIGHTS` dans `security_scanner.py`), vérification ZDR | `rsi`, `leak_count`, `zero_data_retention` |
| **Coût** | Tarif OpenRouter × profil de charge → TCO mensuel projeté + coût réel par appel (`response.usage.cost`) | `tco_usd`, `actual_cost_credits`, `cer` |

## Parcours recommandés

- **Exécuter une évaluation** : suivre le [workflow du pipeline](workflow.md),
  de la configuration au tableau de bord.
- **Préparer un brief de pilotage** : utiliser le [brief manager](brief-manager-2026-08-17.md)
  comme support de point d'avancement.
- **Comprendre le code** : consulter la [référence API Python](reference/api.md),
  générée directement depuis les docstrings du projet.
- **Comprendre les décisions** : lire les [Architecture Decision Records](adr/0001-architecture-initiale.md).
- **Contribuer** : suivre le guide de contribution à la racine du dépôt
  (`CONTRIBUTING.md`).

## Positionnement par rapport à gen-e2-eval

```
OpenRouter Research          gen-e2-eval
──────────────────────────   ────────────────────────────────
~200 modèles OpenRouter       5-10 modèles présélectionnés

Question : « sain et         Question : « réussit-il
abordable ? »                mes tâches métier ? »

→ shortlist annotée           → recommandation par use-case
```

L'export `make export-gen-e2` génère un YAML injectable dans le shortlist
quadrant de gen-e2-eval avec les colonnes sécurité et TCO.

## Structure de la documentation

| Espace | Contenu | Source de vérité |
| --- | --- | --- |
| Guide du pipeline | Exécution, entrées, sorties et interprétation | `docs/workflow.md` |
| Référence API | Classes, fonctions et signatures publiques | Docstrings dans `src/` et `dashboard/` |
| ADR | Décisions d'architecture et compromis | `docs/adr/` |
| Plans | Travaux planifiés ou en cours | `docs/plans/` |

## Documentation vivante

La référence API est construite à la volée par `mkdocstrings` à partir du code
courant. Une modification de docstring est visible au prochain build sans
synchronisation manuelle.

Chaque pull request qui modifie les documents ou les sources Python lance une
validation stricte (`make docs-build --strict`). Après une fusion sur `main`,
GitHub Actions reconstruit et publie le site sur GitHub Pages.
