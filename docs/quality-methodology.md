# Méthodologie de la suite de qualité

Cette page formalise la manière dont la suite de prompts de qualité doit être
comprise, validée et utilisée dans ce projet.

## 1. Objectif

La suite de qualité est un outil de **screening générique** pour réduire une
liste de modèles OpenRouter à une shortlist avant une évaluation métier.

Elle ne remplace pas une évaluation fonctionnelle dans
[gen-e2-eval](https://github.com/GLOBAL-PALO-IT/gen-e2-eval). Son rôle est de
répondre à la question :

> « Quels modèles sont suffisamment solides sur les capacités fondamentales pour
> mériter une évaluation plus approfondie ? »

## 2. Origine et mode de correction des prompts

Les 16 prompts sont **rédigés en interne par l'équipe du projet** ; ils ne
proviennent pas d'un jeu de données de benchmark public. Chacun est rattaché à
exactement une dimension (`quality_dimension`) et une catégorie (`category`)
définies dans
[data/prompts/quality_prompts.json](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/data/prompts/quality_prompts.json).

La catégorie détermine le mode de correction :

- si la catégorie est enregistrée dans `CHECKS`
  ([deterministic_eval.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/deterministic_eval.py)),
  la réponse est corrigée en Python pur (JSON, syntaxe, réponse exacte), sans
  aucun appel à un modèle ;
- sinon (`generic_judgment`), le prompt doit fournir des `judge_criteria`
  explicites et est envoyé au panel de juges à l'aveugle (alias A/B/C… pour
  neutraliser le biais de position), selon le protocole de
  Zheng, Chiang, Sheng et al., *Judging LLM-as-a-Judge with MT-Bench and
  Chatbot Arena*, NeurIPS 2023 —
  [arXiv:2306.05685](https://arxiv.org/abs/2306.05685), déjà cité dans
  l'[audit du 2026-08-21](audit-2026-08-21.md).

Sans mitigation, cette étude mesure un biais de position marqué et variable
selon le juge : 23,8 % de verdicts cohérents après inversion de l'ordre des
deux réponses pour Claude-v1, 46,2 % pour GPT-3.5, 65,0 % pour GPT-4 (leur
Table 2 ; un verdict « cohérent » signifie que le juge garde le même avis une
fois l'ordre inversé). **Ce chiffre de référence inclut déjà, dans leur prompt
« default », une instruction explicite du type « évite tout biais de
position »** — comparable à la règle « Do NOT favour the first response you
read » de notre propre prompt système — et cette seule instruction ne suffit
pas à supprimer le biais (65 % de cohérence pour GPT-4, donc encore 35 %
d'inconsistance).

**Ce qui est réellement prouvé par ce papier, et ce qui ne l'est pas :**

- Prouvé : le biais de position est réel et significatif, y compris avec une
  instruction anti-biais dans le prompt.
- Prouvé (Table 13) : rejouer le jugement en inversant l'ordre et ne compter
  une victoire que si elle est confirmée dans les deux sens (« conservative
  swap ») est la méthode que les auteurs ont effectivement utilisée et
  mesurée dans toutes leurs expériences.
- **Non chiffré par le papier** : « assigner les positions aléatoirement » est
  seulement mentionné comme une alternative plausible (« can be effective at a
  large scale with the correct expectations »), sans table de résultats
  dédiée — les auteurs précisent explicitement qu'ils ont utilisé l'approche
  conservative, pas celle-ci, pour leurs mesures.
- **Écart avec notre pipeline** : leurs chiffres portent sur une comparaison
  à 2 réponses (A vs B). `quality_judge.py` fait noter **N réponses
  anonymisées simultanément** dans un seul appel (voir le prompt système :
  *"score multiple model responses"*), un cadre que ce papier ne mesure pas.

`_blind_alias_map` dans `quality_judge.py` implémente la variante « position
aléatoire » : l'association lettre ↔ modèle est re-mélangée par un tirage
pseudo-aléatoire propre à chaque prompt et chaque tentative (seed dérivée de
`quality_suite_id`, de l'index et du texte du prompt). C'est un choix
théoriquement motivé et cohérent avec la littérature, **mais non validé
empiriquement dans ce projet** : aucun test interne ne mesure à ce jour si nos
3 juges (Claude, GPT, Gemini) restent cohérents quand on rejoue le même
prompt avec un autre tirage d'alias. Tant que ce test n'est pas fait, la
mitigation doit être présentée comme une précaution documentée, pas comme une
preuve d'efficacité.

Ce contrat (référence objective **ou** critères de jugement explicites) est
imposé à l'entrée par le schéma Pydantic `QualityPrompt` — voir la décision
**D9** de l'[ADR 0001](adr/0001-architecture-initiale.md).

### Dimensions couvertes

| Dimension | Prompts | Catégorie(s) | Mode de correction |
| --- | --- | --- | --- |
| structured_output | 3 | json_output | déterministe (JSON strict) |
| code_contract | 1 | code_generation | déterministe (syntaxe Python, non exécutée) |
| factual_sanity | 3 | factual_sanity | déterministe (réponse exacte) |
| elementary_reasoning | 3 | exact_answer, logical_reasoning | déterministe (réponse exacte) |
| instruction_reliability | 4 | instruction_following (3), generic_judgment (1) | 3 déterministes + 1 jugé |
| concise_communication | 2 | generic_judgment | jugé à l'aveugle |

13 prompts sur 16 sont donc corrigés sans aucun appel à un juge externe ; les
3 prompts restants suivent le protocole de jugement à l'aveugle ci-dessus.

## 3. Couverture du périmètre

Le module de correction déterministe résume lui-même sa limite :

> « The screen deliberately measures only provider-neutral fundamentals:
> structured output, factual sanity, elementary reasoning and instruction
> reliability. It is not a substitute for domain-specific task evaluation. »
> — [deterministic_eval.py](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/src/evaluators/deterministic_eval.py)

| Capacité | État |
| --- | --- |
| respect de format | couvert |
| suivi d'instructions | couvert |
| factualité simple | couvert |
| raisonnement simple | couvert |
| code minimal | partiellement couvert (une seule signature de fonction) |
| communication concise | couvert |
| long contexte | non couvert |
| tâches métier | non couvert |
| exécution réelle de code | non couvert (vérification syntaxique seulement) |
| évaluation de domaine spécialisé | non couvert |

Cette limitation doit être explicitement communiquée à chaque utilisation du
score qualité.

## 4. Validation de la suite

La qualité de la suite doit être validée selon trois niveaux.

### 4.1 Validation du contenu

Chaque prompt doit être revu par au moins une personne connaissant le projet et
vérifier :

- le prompt est non ambigu ;
- la réponse attendue est correcte ;
- la capacité testée est pertinente pour le screening ;
- le prompt n'introduit pas de biais artificiel ;
- le prompt reste provider-neutral.

Le document de revue initiale se trouve dans
[quality-validation/review-v1.md](quality-validation/review-v1.md).

### 4.2 Validation technique (déjà appliquée par le code)

Le schéma `QualityPrompt` et le pipeline garantissent, à l'entrée et à
l'export :

- chaque prompt a un type de correction défini (déterministe ou
  `judge_criteria` non vide) — décision D9 de l'[ADR 0001](adr/0001-architecture-initiale.md) ;
- `avg_quality_score` est une macro-moyenne par dimension, pas une moyenne
  plate sur tous les prompts — décision D10 du même ADR ;
- la suite est identifiée par `quality_suite_id` (hash du fichier de prompts),
  ce qui lie chaque résultat à une version exacte de la suite ;
- la couverture (`quality_coverage_rate`, `quality_dimension_coverage_rate`) et
  les erreurs de collecte (`quality_collection_error_count`) sont exportées
  séparément du score qualité.

Le détail de toutes les colonnes exportées est dans
[workflow.md](workflow.md) (section *Métriques de qualité exportées*).

### 4.3 Validation empirique (à la charge de l'opérateur du run)

- **Répétitions** : `QUALITY_REPETITIONS=1` par défaut, donc
  `quality_stability_score` reste `null` tant que cette variable n'est pas
  relevée à ≥ 2. Tout résultat utilisé pour une décision de shortlist doit être
  produit avec `QUALITY_REPETITIONS≥2` — limite déjà identifiée dans
  l'[audit du 2026-08-21](audit-2026-08-21.md) (section 3.5).
- vérifier que les scores ne sont pas tous identiques entre modèles ;
- comparer les classements obtenus sur plusieurs modèles ;
- noter les prompts qui ne discriminent pas assez et les revoir en priorité.

## 5. Comparaison avec gen-e2-eval

Le score qualité de ce projet et la validation métier de `gen-e2-eval` ne sont
pas directement comparables, car ils ne mesurent pas le même objet.

La bonne pratique est de comparer leur **capacité à sélectionner les mêmes
modèles pertinents**.

### Protocole recommandé

1. exécuter la suite LLM Model Screening sur les mêmes modèles ;
2. exécuter `gen-e2-eval` sur les mêmes modèles ;
3. comparer le top 3 et les classements globaux ;
4. noter les désaccords et les raisons possibles ;
5. conserver le résultat dans un fichier de comparaison.

Le template est dans
[quality-validation/gen-e2-eval-comparison-template.md](quality-validation/gen-e2-eval-comparison-template.md).

## 6. Critères d'acceptation

La suite est considérée comme correctement justifiée si elle remplit au moins
les règles suivantes :

- 100 % des prompts ont un mode de correction défini (déterministe ou
  `judge_criteria`) — déjà imposé par le schéma `QualityPrompt` ;
- le run utilisé pour une décision de shortlist a `quality_coverage_rate ≥ 0.8`
  et `quality_dimension_coverage_rate = 1.0` — seuils déjà appliqués par le
  pipeline pour activer `quality_cer_eligible` (décision D12 de
  l'[ADR 0001](adr/0001-architecture-initiale.md)) ;
- le run a été exécuté avec `QUALITY_REPETITIONS≥2` si son résultat sert de
  base à une décision d'exclusion ou de shortlist ;
- la couverture et les limites du périmètre (§3) sont rappelées à côté du
  score dans tout livrable ;
- le score est toujours interprété comme un signal de shortlist, jamais comme
  une recommandation finale d'adoption.

## Voir aussi

- [workflow.md](workflow.md) — déroulé complet du pipeline et détail des
  colonnes exportées ;
- [ADR 0001](adr/0001-architecture-initiale.md) — décisions D9, D10, D12 ;
- [audit du 2026-08-21](audit-2026-08-21.md) — limites connues, dont
  l'absence de répétitions par défaut ;
- [README.md](https://github.com/Palo-IT-GitHub-Demos/OpenRouterResearch/blob/main/README.md)
  et [index.md](index.md) — périmètre et positionnement vs `gen-e2-eval`.
