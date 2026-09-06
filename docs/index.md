# LLM Model Screening

Pipeline de **screening comparatif et reproductible** des modèles disponibles
sur OpenRouter. Elle réduit l'espace de recherche en comparant les modèles sur
des critères transverses de qualité générique, de coût, de latence et de
sécurité, afin de constituer une shortlist avant l'évaluation métier dans
[gen-e2-eval](https://github.com/GLOBAL-PALO-IT/gen-e2-eval).

## Trois axes de mesure

| Axe | Ce que ça mesure | Sortie clé |
| --- | --- | --- |
| **Qualité** | 16 prompts versionnés, 6 dimensions, score macro-moyen 1-5 + taux de couverture + stabilité optionnelle | `avg_quality_score`, `quality_coverage_rate`, `quality_stability_score` |
| **Sécurité** | 30 sondes [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/), score RSI 0-100 (pondération interne, non publiée par OWASP — cf. `_RSI_WEIGHTS` dans `security_scanner.py`), vérification ZDR | `rsi`, `leak_count`, `zero_data_retention` |
| **Coût** | Tarif OpenRouter × profil de charge → TCO mensuel projeté + coût réel par appel (`response.usage.cost`) | `tco_usd`, `actual_cost_credits`, `cer` |

## Voir les résultats

| Besoin | Action |
| --- | --- |
| Consulter le dernier rapport partageable | Ouvrir `results/dashboard_<timestamp>.html` ; sa navigation mène aux pages Qualité, Preuves, Sécurité et Coûts. |
| Explorer un résultat avec filtres | Lancer `make dashboard`, puis ouvrir `http://localhost:8501`. |
| Générer le rapport HTML du dernier benchmark fusionné | Lancer `make export-html`. |

Le [workflow du pipeline](workflow.md) indique les commandes dans l'ordre,
depuis la vérification gratuite jusqu'au rapport final.

## Parcours recommandés

- **Exécuter une évaluation** : suivre le [workflow du pipeline](workflow.md),
  de la configuration au tableau de bord.
- **Défendre ou auditer le score qualité** : consulter la
  [méthodologie qualité](quality-methodology.md) — provenance des prompts,
  couverture, validation et comparaison avec `gen-e2-eval`.
- **Comprendre le code** : consulter la [référence API Python](reference/api.md),
  générée directement depuis les docstrings du projet.
- **Comprendre les décisions** : lire les [Architecture Decision Records](adr/0001-architecture-initiale.md).
- **Contribuer** : suivre le guide de contribution à la racine du dépôt
  (`CONTRIBUTING.md`).

## Positionnement par rapport à gen-e2-eval

Les deux projets répondent à des questions différentes et ne produisent pas
le même type de décision :

```text
LLM Model Screening          gen-e2-eval
──────────────────────────   ────────────────────────────────
~200 modèles OpenRouter       5-10 modèles présélectionnés

Question : « sain et         Question : « réussit-il
abordable ? »                mes tâches métier ? »

→ shortlist annotée           → recommandation par use-case
```

L'export `make export-gen-e2` génère un YAML injectable dans le shortlist
quadrant de gen-e2-eval avec les colonnes sécurité et TCO.

### Périmètre et règle de décision

LLM Model Screening inclut :

- la comparaison à grande échelle de modèles accessibles via OpenRouter ;
- un screen de qualité générique, provider-neutral et versionné ;
- les mesures de coût, de latence et de sécurité ;
- la production d'une shortlist et de métadonnées traçables pour la suite.

LLM Model Screening n'inclut pas :

- la validation d'un workflow métier ou d'une golden dataset client ;
- la mesure de la réussite fonctionnelle sur un use case ;
- la recommandation finale d'un modèle pour une application ;
- le remplacement des annotations humaines ou de l'évaluation dans
  `gen-e2-eval`.

La règle de décision est donc la suivante : les résultats de ce projet servent
à filtrer et prioriser les modèles ; toute décision d'adoption doit être
confirmée dans `gen-e2-eval` sur les tâches métier concernées.

## Structure de la documentation

| Espace | Contenu | Source de vérité |
| --- | --- | --- |
| Guide du pipeline | Exécution, entrées, sorties et interprétation | `docs/workflow.md` |
| Méthodologie qualité | Provenance des prompts, couverture, validation, comparaison `gen-e2-eval` | `docs/quality-methodology.md` |
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
