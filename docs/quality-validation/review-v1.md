# Revue de validation de la suite qualité v1

## Métadonnées

- **Date** : 2026-08-25
- **Portée** : auto-revue réalisée par l'auteur des prompts lors de la
  formalisation de la [méthodologie qualité](../quality-methodology.md),
  complétée par un jugement IA sur le contenu des prompts eux-mêmes (et pas
  seulement sur les réponses des modèles évalués). Aucune revue par une
  tierce personne externe au projet n'est planifiée ; ce choix est assumé
  pour un outil de screening interne.

## Objectif

Documenter la revue initiale de la suite de prompts de qualité (16 prompts,
6 dimensions, 13 corrections déterministes + 3 jugements à l'aveugle) utilisée
pour le screening de modèles.

## Résumé

- la suite cible des capacités de base pertinentes pour un pré-sélectionnement ;
- elle ne prétend pas mesurer la qualité métier complète ;
- elle doit être interprétée comme un signal de shortlist.

## Critères de revue

- le prompt est compréhensible ;
- la réponse attendue est clairement définie ;
- le prompt est provider-neutral ;
- la capacité testée est utile au screening.

## Verdict

La suite peut être utilisée comme outil de screening générique tant qu'elle est
interprétée dans ses limites (voir la section 3 de
[quality-methodology.md](../quality-methodology.md)). Complément prévu : faire
juger la suite de prompts elle-même par une IA, en plus de la relecture directe
par l'auteur, pour croiser les regards sans dépendre d'une revue humaine
externe.
