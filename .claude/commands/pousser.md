---
description: Rituel de livraison complet — contrôles, relecture confidentialité, commit, push, PR — dans le respect strict de CLAUDE.md §git.
disable-model-invocation: true
---

Rituel strictement ordonné. Ne saute aucune étape ; si une étape échoue,
corrige avant de passer à la suivante.

1. **`/qualite`** — verif.py + grep confidentialité doivent être propres.
   Un échec de verif.py imputable à une étape du pipeline pas encore
   jouée n'est pas bloquant en soi ; une fuite de confidentialité, si.

2. **Subagent `gardien-confidentialite`** sur le diff (`git diff`, staged
   ou par rapport à la base de la PR) — passe-lui le diff explicitement
   dans le prompt, ne le laisse pas le récupérer lui-même. Traite tout
   "à corriger" avant de continuer ; pour "à assumer", confirme avec
   l'utilisateur avant de continuer si le doute est réel.

3. **État de la branche** :
   - branche déjà mergée (PR fermée en merged) → repartir de `origin/main`
     pour tout travail de suite (voir la règle de session sur les PR déjà
     mergées) ;
   - référence obsolète → `git remote prune origin` avant de continuer.

4. **Commit** — message descriptif en français, au présent, dans le style
   déjà utilisé dans l'historique du dépôt (`git log --oneline`) : pas de
   convention gitmoji, ce dépôt n'a pas de semantic-release. Le hook
   `avant-livraison.sh` bloque déjà tout commit contenant une valeur
   confidentielle connue — s'il bloque, ne contourne jamais le hook, corrige
   le contenu.

5. **Push** — `git push -u origin <branche>`. Jamais sur `main`, jamais
   `--force`, jamais de `git merge` (CLAUDE.md §git ; `avant-livraison.sh`
   le bloque aussi mécaniquement). Retente en cas d'erreur réseau
   uniquement (backoff 2s/4s/8s/16s).

6. **PR** — crée-la si aucune n'est ouverte pour cette branche (une PR
   fermée/mergée ne compte pas). Le corps décrit uniquement le
   changement de code, jamais une donnée de parcelle.

7. Ne fusionne jamais la PR toi-même sans accord explicite de
   l'utilisateur (CLAUDE.md §git — jamais merge) : le hook
   `avant-livraison.sh` bloque déjà `mcp__github__merge_pull_request`.
