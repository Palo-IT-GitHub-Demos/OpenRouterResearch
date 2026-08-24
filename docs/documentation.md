# Maintenir la documentation

Source de vérité par section :

| Section | Source | Mise à jour |
|---|---|---|
| Workflow (`workflow.md`) | Écrite à la main | À chaque changement de comportement du pipeline |
| Référence API (`reference/api.md`) | Docstrings dans `src/` et `dashboard/` | Automatique — `mkdocstrings` régénère au build |
| ADR (`adr/`) | Écrite à la main, un fichier par décision | À chaque décision d'architecture significative |
| Plans (`plans/`) | Écrite à la main | À la création ou à la clôture d'un plan d'implémentation |

## Avant de committer un changement de documentation

```bash
make docs-build   # validation stricte (liens, navigation, mkdocstrings)
make docs-serve   # aperçu local avec rechargement à chaud
```

`make docs-build --strict` échoue si :

- un lien interne pointe vers une page absente ou hors de `nav` (voir `mkdocs.yml`) ;
- un module référencé par une directive `::: chemin.du.module` n'est pas importable ;
- mkdocs détecte un avertissement (warnings-as-errors en mode strict).

## Ajouter un module à la référence API

1. Ajouter le module dans `docs/reference/api.md` avec une directive `::: chemin.du.module`.
2. Le module doit être importable sans effet de bord au niveau module — voir
   `dashboard/app.py`, volontairement exclu de la référence API pour cette raison
   (script Streamlit, pas une bibliothèque).
3. Lancer `make docs-build` pour valider avant de committer.
