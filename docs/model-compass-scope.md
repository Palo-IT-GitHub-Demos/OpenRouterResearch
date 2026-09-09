# Model Compass — scope et logique de décision

Cette page formalise le changement de positionnement décidé les 8 et 9
septembre 2026. Le dépôt ne se limite plus à produire un signal de screening
avant une autre évaluation : il produit un rapport de recommandation technique
générique, organisé par cas d'usage, pour aider un humain à répondre à des
appels d'offres.

## Mission

**Model Compass** évalue les modèles LLM accessibles via OpenRouter sur un
catalogue stable de cas d'usage génériques. Il mesure la qualité fonctionnelle,
la sécurité, le coût du modèle et la performance, puis fournit pour chaque cas
d'usage :

- une note détaillée pour chaque modèle évalué ;
- un seuil minimal de qualité adapté au cas d'usage ;
- un classement des modèles qui franchissent ce seuil ;
- un ou plusieurs modèles recommandés ;
- les preuves, limites et dimensions manquantes qui expliquent le résultat.

Le rapport est une **recommandation technique**. La sélection finale appartient
à un humain qui connaît l'appel d'offres, son contexte et ses contraintes.

## Principe de stabilité

Le pipeline est volontairement générique et réutilisable :

- il ne reçoit pas le contenu d'un appel d'offres ;
- il ne reçoit pas de critères propres à un client ;
- il n'utilise pas de dataset client ou de données métier confidentielles ;
- il utilise un catalogue versionné de cas d'usage et de prompts génériques ;
- il produit le même type de rapport à chaque exécution ;
- il peut évoluer entre deux versions du catalogue, mais ne doit pas être
  reconfiguré pour chaque appel d'offres.

L'humain fait ensuite correspondre les résultats génériques aux besoins du
dossier qu'il connaît.

## Catalogue initial

Le catalogue est défini dans `data/catalog/model_compass_use_cases.json`.
La version initiale relie les prompts qualité existants à six cas d'usage :

| Cas d'usage | Prompts | Seuil initial |
| --- | ---: | ---: |
| Structured extraction | 0-2 | 4,0 / 5 |
| Code generation | 3 | 4,0 / 5 |
| Factual question answering | 4-6 | 4,0 / 5 |
| Reasoning and analysis | 7-9 | 4,0 / 5 |
| Instruction following | 10-12, 15 | 4,0 / 5 |
| Concise communication | 13-14 | 3,5 / 5 |

Ces seuils sont des **valeurs de démarrage provisoires**. Ils doivent être
calibrés après la définition précise des catégories, des critères de réussite
et de la difficulté des tâches. Modifier le catalogue change la version du
benchmark et doit être visible dans les résultats.

## Logique de décision

La décision comporte deux niveaux indépendants.

### 1. Éligibilité qualité

Pour chaque couple `cas d'usage / modèle`, les scores des prompts du catalogue
sont moyennés par prompt. La couverture indique la proportion de prompts du cas
d'usage réellement scorés.

```text
qualité éligible =
    qualité du cas d'usage >= seuil du cas d'usage
    et couverture qualité = 100 %
```

Un modèle sous le seuil n'est pas recommandé pour ce cas, même s'il est moins
cher ou plus rapide. Tous les modèles restent toutefois visibles dans le
rapport avec leur score et leur statut.

### 2. Classement pondéré

Le score de décision utilise quatre composantes normalisées sur 0-100 :

| Composante | Poids par défaut | Source |
| --- | ---: | --- |
| Qualité fonctionnelle | 50 % | Score qualité du cas d'usage, échelle 1-5 normalisée |
| Sécurité générique | 25 % | RSI, échelle 0-100 |
| Coût du modèle seul | 20 % | TCO du profil, normalisé avec le coût le plus bas en meilleur score |
| Performance | 5 % | Latence P95, ou tokens/seconde si la latence manque |

```text
score_decision =
    poids_qualité × qualité
  + poids_sécurité × sécurité
  + poids_coût × coût
  + poids_performance × performance
```

Les poids par défaut viennent du catalogue. Ils peuvent être remplacés sans
modifier le code avec `MODEL_COMPASS_WEIGHTS`, par exemple :

```bash
MODEL_COMPASS_WEIGHTS='{"quality":0.60,"security":0.20,"cost":0.15,"performance":0.05}' make merge
```

Les poids doivent être positifs et leur somme doit être égale à `1.0`. Le
rapport et le manifeste enregistrent toujours les poids effectivement utilisés.

Si une composante manque, le modèle reste visible mais reçoit le statut
`insufficient_decision_evidence` et aucun rang de recommandation. Le pipeline
ne remplace pas silencieusement une preuve absente par une valeur favorable.

## Égalités et statuts

Le classement utilise un rang dense. Il n'existe pas de règle artificielle de
départage : plusieurs modèles ayant exactement le même score conservent le
même rang et peuvent tous être `recommended`.

Les statuts sont :

- `recommended` : meilleur rang parmi les modèles éligibles et suffisamment
  documentés ;
- `eligible` : dépasse le seuil et possède les preuves nécessaires, mais n'a
  pas le meilleur rang ;
- `below_quality_threshold` : qualité insuffisante pour ce cas d'usage ;
- `insufficient_quality_evidence` : couverture ou score qualité manquant ;
- `insufficient_decision_evidence` : qualité éligible, mais sécurité, coût ou
  performance manquant.

Le nombre de modèles évalués ou affichés n'est pas limité artificiellement.

## Sécurité, conformité et coût

La sécurité est générique et comparable entre les modèles : prompt injection,
fuite de secrets, demandes dangereuses, respect des instructions et politiques
de rétention disponibles via OpenRouter.

Le pipeline ne décide pas automatiquement de la conformité à une exigence
client comme la localisation des données, HDS, SecNumCloud, une certification
particulière ou un SLA contractuel. Ces points sont vérifiés par l'humain.

Le coût couvre uniquement le modèle : tokens d'entrée, tokens de sortie, TCO
projeté et coût réel observé lorsque disponible. Il exclut l'infrastructure,
le RAG, le stockage, l'orchestration, l'intégration, la supervision et la
licence d'une solution complète.

## Artefacts et surfaces

Le benchmark résumé reste une ligne par modèle :

```text
results/benchmark_<timestamp>.{csv,json}
```

Le détail de recommandation est séparé pour conserver plusieurs lignes par
modèle :

```text
results/recommendations/benchmark_<timestamp>_recommendations.{csv,json}
```

Chaque ligne de cet artefact correspond à un couple `use_case_id / model` et
contient le seuil, la couverture, les quatre composantes, le score pondéré, le
rang, le statut et les preuves manquantes. Le dashboard Streamlit et l'export
HTML utilisent ce même artefact.

## Hors périmètre

Model Compass ne réalise pas :

- l'analyse automatique d'un DCE, CCTP ou cahier des charges ;
- l'extraction d'exigences propres à un client ;
- la personnalisation automatique des prompts pour un appel d'offres ;
- l'évaluation sur des données confidentielles ou un workflow métier réel ;
- la recommandation d'une architecture complète ;
- le calcul du coût total d'une solution ;
- la sélection automatique d'un fournisseur final ;
- la certification réglementaire ;
- la décision finale d'adoption ;
- la génération automatique d'une réponse commerciale.

## Travail méthodologique restant

Le contrat logiciel est en place, mais la méthodologie doit encore être
renforcée :

1. confirmer la liste des cas d'usage de la première version ;
2. définir les critères de réussite propres à chaque cas ;
3. calibrer les seuils sur des tâches représentatives ;
4. vérifier la stabilité des catégories et des pondérations ;
5. comparer les recommandations génériques à `gen-e2-eval` sur les mêmes
   modèles, sans confondre les deux types de preuve.

Les seuils et le catalogue ne doivent donc pas être présentés comme une
certification de pertinence métier.
