# Brief Manager - Model Compass

> **Statut du document :** support de pilotage pour le point manager du 8 septembre 2026.
> Les résultats techniques de référence restent le code courant, les tests et les
> artefacts de benchmark. Ce document résume l'état du projet et les décisions à prendre.

> **Mise à jour du 9 septembre 2026 :** le positionnement est désormais **Model Compass**.
> Le pipeline reste générique et ne lit pas les appels d'offres ; il produit un classement
> et une recommandation technique par cas d'usage à partir d'un catalogue versionné. Voir
> [model-compass-scope.md](model-compass-scope.md) pour le contrat courant.

**Date :** 2026-09-08
**Dernier benchmark de référence :** 2026-09-04 (`benchmark_20260904_110806`)
**Branche de travail :** `chore/project-improvements-2026`

## 1. Résumé exécutif

Le projet est désormais opérationnel de bout en bout pour le pré-screening de modèles
LLM disponibles via OpenRouter. Il mesure la qualité générique, la robustesse sécurité,
le coût réel et la performance, puis produit des résultats CSV/JSON et des dashboards
Streamlit et HTML statique.

La validation d'ingénierie est au vert : **382/382 tests passent**, Ruff et MyPy ne
signalent aucune erreur, et la documentation MkDocs se construit en mode strict.

Le dernier benchmark exploitable couvre 3 modèles avec une couverture qualité de 100 %
et 46 appels observés par modèle. Il confirme qu'un modèle peut obtenir un excellent
score de qualité tout en restant plus coûteux ou plus lent, et qu'un modèle peu coûteux
peut présenter un risque de sécurité réel. Le système permet donc déjà de comparer les
compromis au lieu de classer les modèles sur la seule qualité.

Le principal point de vigilance est opérationnel : les évolutions récentes et plusieurs
artefacts de rapports sont encore présents comme changements non committés dans l'arbre
Git. Il faut stabiliser et intégrer ce lot avant de considérer cette version comme une
base de référence durable.

## 2. Ce que fait le projet

Le dépôt sert à présélectionner des modèles avant une évaluation métier plus approfondie
dans le projet frère `gen-e2-eval`. Il ne remplace pas un benchmark métier et ne produit
pas à lui seul une recommandation finale.

| Axe | Mesure | Sorties principales |
| --- | --- | --- |
| Qualité | Réponses génériques, format, code, raisonnement, factualité et suivi d'instructions | `avg_quality_score`, couverture, scores par dimension |
| Sécurité | Résistance à des probes d'injection et de divulgation alignées OWASP | `rsi`, fuites détectées, catégories couvertes |
| Coût | Coût OpenRouter réellement remonté et projection de charge | coût par appel, `tco_usd`, `cer` |
| Performance | Latence réseau et débit de génération | p50, p95, tokens/seconde |

Le workflow reste en trois phases :

1. `make collect` collecte les réponses et produit les artefacts intermédiaires.
2. `@judge-coordinator` orchestre trois juges aveugles Copilot pour les cas nécessitant
   un jugement qualitatif.
3. `make merge` fusionne les scores, les résultats sécurité et les données de coût, puis
   exporte le benchmark et les preuves associées.

## 3. État actuel des livraisons

### Livré et validé

- Pipeline asynchrone OpenRouter avec limitation de concurrence et retries.
- Évaluation qualité déterministe complétée par jugement aveugle à trois juges.
- Sécurité avec profils `basic`, `owasp` et `extended`, RSI et périmètre de catégories
  explicitement publié.
- Cost modeling avec coût réel par appel, TCO et ratio d'efficacité coût/qualité.
- Mesures de performance corrigées : latence capturée après acquisition du sémaphore,
  avec p50, p95 et tokens/seconde.
- Dashboards Streamlit et HTML statique, avec pages qualité, preuves, sécurité, coût et
  performance.
- Preuves qualité détaillées, diagnostics techniques, ledger de coûts et manifeste de
  provenance avec checksums.
- Sélection interactive de modèles via `make select`, presets de modèles et modes de
  sécurité réutilisables.
- Garde-fous de dépense : validation du catalogue de modèles, estimation des appels et
  avertissement avant un run trop volumineux.
- Documentation publiée et construite avec `mkdocs build --strict`.
- Fondation expérimentale pour des scénarios sécurité multi-tours bornés, séparée du
  scoring historique tant que sa comparabilité n'est pas validée.

### Validation d'ingénierie au 8 septembre

| Contrôle | Résultat |
| --- | --- |
| Suite de tests | **382 tests passés** |
| Ruff | Aucun problème |
| MyPy strict | Aucun problème sur 20 fichiers source |
| Documentation MkDocs strict | Build réussi |
| Appels réseau dans les tests | Aucun appel réel requis |

## 4. Dernier benchmark disponible

Le benchmark `results/benchmark_20260904_110806.json` porte sur 3 modèles. Chaque modèle
compte 46 appels observés, soit 138 appels au total. La qualité a une couverture de 100 %
et les probes sécurité n'ont généré aucune erreur technique. Les coûts ci-dessous sont
les coûts effectivement rapportés par OpenRouter dans le ledger ; ils ne constituent pas
une projection mensuelle.

| Modèle | Qualité | Coût observé | Latence p50 | Latence p95 | Débit | Fuites | RSI | CER |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `anthropic/claude-sonnet-5` | 5,00/5 | 0,1371 | 6,77 s | 9,00 s | 46,83 tok/s | 0 | 100 | 0,039 |
| `meta-llama/llama-3.3-70b-instruct` | 4,76/5 | 0,0025 | 1,92 s | 14,49 s | 19,98 tok/s | 1 | 65 | 1,000 |
| `openai/gpt-4o-mini` | 4,76/5 | 0,0015 | 1,83 s | 3,08 s | 18,52 tok/s | 0 | 100 | 0,578 |

**Lecture manager :**

- `claude-sonnet-5` est le meilleur sur la qualité et la robustesse de ce run, mais avec
  le coût et la latence les plus élevés.
- `gpt-4o-mini` offre le compromis le plus intéressant sur ce petit échantillon : coût
  très faible, absence de fuite détectée et p95 plus stable.
- `llama-3.3-70b-instruct` est très économique mais une fuite confirmée abaisse son RSI
  à 65 ; il ne doit donc pas être présenté comme robuste malgré son bon score qualité.
- Ces résultats sont des signaux de présélection sur un run donné, pas une vérité
  générale ni une recommandation métier finale.

## 5. Points encore ouverts

### Stabilisation technique

Le lot courant contient 14 fichiers suivis modifiés, environ 398 lignes ajoutées et 37
supprimées, ainsi que de nouveaux artefacts de dashboards, preuves qualité et tests de
scénarios. Les tests passent, mais le lot doit encore être relu, regroupé et committé
pour devenir la nouvelle base de référence.

### Confiance benchmark

La qualité statistique doit être renforcée par des répétitions (`QUALITY_REPETITIONS > 1`)
et par un jeu de modèles plus large avant toute décision d'achat ou de standardisation.
Les limites de quota et de stabilité du free tier restent un risque pour la
comparabilité ; un run décisionnel doit utiliser une clé OpenRouter dédiée.

### Périmètre sécurité

Le dernier run score 7 catégories OWASP et 21 probes effectivement scorées sur un jeu de
30 probes. Les catégories non exercées par une interaction single-turn restent
explicitement non scorées. L'extension multi-tours est en cours d'expérimentation et ne
doit pas être mélangée aux scores historiques avant validation de sa comparabilité.

## 6. Décisions demandées au manager

1. **Valider la stabilisation du lot courant** : revue finale, commit de référence et
   conservation des artefacts de benchmark associés.
2. **Autoriser un run décisionnel dédié** avec une clé OpenRouter de projet, un ensemble de
   modèles convenu et `QUALITY_REPETITIONS > 1`.
3. **Confirmer le budget initial de développement de 30 USD** comme enveloppe plafonnée,
   avec suivi du coût réel par run et aucune extension automatique.
4. **Valider le passage à l'étape métier** : utiliser les modèles présélectionnés dans
   `gen-e2-eval` avec les datasets et critères propres au cas d'usage.

## 7. Prochaines étapes proposées

| Horizon | Action | Critère de sortie |
| --- | --- | --- |
| Immédiat | Relire et committer le lot courant | Branche propre, CI et contrôles verts |
| Court terme | Lancer un benchmark répété sur l'ensemble de modèles retenu | Couverture complète, coûts et provenance vérifiés |
| Ensuite | Comparer les résultats avec les critères métier dans `gen-e2-eval` | Shortlist validée sur données métier |
| Après validation | Étendre progressivement les scénarios multi-tours | Comparabilité documentée avec les scores historiques |

## 8. Script oral de 60 secondes

> Le projet est maintenant opérationnel de bout en bout pour présélectionner des modèles
> LLM sur quatre critères : qualité, sécurité, coût et performance. La base technique est
> solide : 382 tests passent, le lint, le typage strict et la documentation sont verts.
> Le dernier benchmark compare trois modèles sur 138 appels avec une couverture qualité
> complète. Il montre clairement les compromis : Claude Sonnet obtient la meilleure
> qualité et le meilleur score sécurité mais coûte plus cher ; GPT-4o-mini est le compromis
> coût-stabilité le plus intéressant sur ce run ; Llama est peu coûteux mais présente une
> fuite de prompt confirmée. La prochaine étape n'est donc pas de reconstruire le pipeline,
> mais de stabiliser le lot de code actuel, lancer un benchmark répété avec une clé dédiée,
> puis transmettre la shortlist à gen-e2-eval pour la validation métier. Je demande la
> validation de cette trajectoire et d'une enveloppe plafonnée de 30 USD, suivie par les
> coûts réels de chaque run.

## 9. Références

- [Accueil du projet](index.md)
- [Workflow détaillé](workflow.md)
- [Méthodologie qualité](quality-methodology.md)
- [Méthodologie sécurité](security-methodology.md)
- [Plan d'amélioration 2026](plans/project-improvement-roadmap-2026.md)
- Dernier benchmark : `results/benchmark_20260904_110806.json` dans le dépôt
