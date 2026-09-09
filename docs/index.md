# Model Compass

Pipeline de **recommandation technique, comparative et reproductible** des
modèles disponibles sur OpenRouter. Model Compass compare les modèles sur des
critères transverses de qualité, sécurité, coût du modèle et performance, puis
les classe par cas d'usage générique pour aider un humain à répondre à
différents appels d'offres.

Le [scope détaillé](model-compass-scope.md) formalise les décisions prises, les
limites et les seuils provisoires du catalogue initial.

## Quatre dimensions de mesure

| Axe | Ce que ça mesure | Sortie clé |
| --- | --- | --- |
| **Qualité** | 16 prompts versionnés, 6 dimensions, score macro-moyen 1-5 + taux de couverture + stabilité optionnelle | `avg_quality_score`, `quality_coverage_rate`, `quality_stability_score` |
| **Sécurité** | 30 sondes [OWASP GenAI LLM Top 10 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/), score RSI 0-100 (pondération interne, non publiée par OWASP — cf. `_RSI_WEIGHTS` dans `security_scanner.py`), vérification ZDR | `rsi`, `leak_count`, `zero_data_retention` |
| **Coût** | Tarif OpenRouter × profil de charge → TCO mensuel projeté + coût réel par appel (`response.usage.cost`) | `tco_usd`, `actual_cost_credits`, `cer` |
| **Performance** | Latence P50/P95 et tokens/seconde mesurés après acquisition du semaphore | `actual_latency_p50_ms`, `actual_latency_p95_ms`, `actual_tokens_per_second` |
| **Recommandation** | Catalogue versionné, seuil qualité par cas d'usage et score pondéré configurable | `results/recommendations/` |

## Voir les résultats

| Besoin | Action |
| --- | --- |
| Consulter le dernier rapport partageable | Ouvrir `results/dashboard_<timestamp>.html` ; sa navigation mène aux pages Qualité, Preuves, Sécurité et Coûts. |
| Explorer un résultat avec filtres | Lancer `make dashboard`, puis ouvrir `http://localhost:8501`. |
| Générer le rapport HTML du dernier benchmark fusionné | Lancer `make export-html`. |
| Choisir les modèles avant un run | Lancer `make select`, répondre aux filtres, puis utiliser `MODELS=selection`. |

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
Model Compass                gen-e2-eval
──────────────────────────   ────────────────────────────────
Tous les modèles évalués     Modèles testés sur les tâches métier

Question : « quel modèle      Question : « réussit-il
est pertinent par cas ? »    mes tâches métier ? »

→ recommandation technique    → acceptation métier
```

L'export `make export-gen-e2` génère un YAML injectable dans le registry
quadrant de gen-e2-eval avec les colonnes sécurité et TCO.

### Périmètre et règle de décision

Model Compass inclut :

- la comparaison à grande échelle de modèles accessibles via OpenRouter ;
- un screen de qualité générique, provider-neutral et versionné ;
- les mesures de coût, de latence et de sécurité ;
- la production d'un classement et d'un ou plusieurs modèles recommandés par
  cas d'usage générique ;
- un rapport de preuves sous `results/recommendations/`.

Model Compass n'inclut pas :

- la validation d'un workflow métier ou d'une golden dataset client ;
- la mesure de la réussite fonctionnelle sur un use case ;
- l'analyse automatique d'un appel d'offres ou l'extraction de ses exigences ;
- la recommandation finale d'adoption pour une application ;
- le remplacement de l'évaluation métier dans `gen-e2-eval`.

La règle de décision est donc la suivante : tous les modèles restent visibles,
le seuil qualité filtre l'éligibilité par cas d'usage, puis le score pondéré
classe les modèles dont les preuves sont complètes. Les égalités sont
conservées. Toute décision d'adoption reste humaine et peut être confirmée
dans `gen-e2-eval` sur les tâches métier concernées.

## Structure de la documentation

| Espace | Contenu | Source de vérité |
| --- | --- | --- |
| Guide du pipeline | Exécution, entrées, sorties et interprétation | `docs/workflow.md` |
| Scope Model Compass | Mission, logique de décision, limites et calibrations restantes | `docs/model-compass-scope.md` |
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
