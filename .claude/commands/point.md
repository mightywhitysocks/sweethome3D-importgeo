---
description: Écrit une note de passation structurée avant une compaction, un /clear, ou la fin de session — pour reprendre à froid sans perdre le fil.
disable-model-invocation: true
---

Écris une note de passation, hors dépôt (fichier temporaire — répertoire
scratch de session, ou `mktemp`), puis envoie-la en fichier plutôt que de
la coller inline (un fichier rendu respecte les retours à la ligne ; un
texte collé casse en plein milieu de phrase sur un écran étroit).

Structure de la note :

- **Objectif** de la session, en une phrase.
- **Fait et vérifié** (verif.py rejoué avec succès, pas juste écrit) vs.
  **juste écrit** (code modifié mais pas encore contrôlé) — ne mélange
  pas les deux.
- **Reste à faire**, avec l'action concrète suivante (pas "continuer le
  travail sur X" mais "lancer verif.py sur data/terrain_stats.json une
  fois terrain.py rejoué").
- **Décisions prises** cette session, et si elles ont été journalisées
  (`/ecart` si c'est une déviation par rapport à une limite documentée
  dans `docs/PIPELINE.md`).
- **Chemins abandonnés** — ce qui a été essayé puis écarté, et pourquoi
  (évite de re-explorer la même impasse dans la session suivante).
- **État git** — branche, commits locaux non poussés, PR ouverte ou non.
- Si `.git/sitegeo-instructions.log` et `.git/sitegeo-usage.log` existent,
  jette un œil aux dernières lignes pour ne pas oublier un hook qui aurait
  signalé quelque chose sans qu'on y donne suite.

Ne rappelle jamais de donnée confidentielle (commune/section/numéro/
coordonnées) dans cette note, même si elle sort du dépôt — elle peut être
relue plus tard par quelqu'un d'autre.
