---
description: Lance le contrôle qualité lecture seule du pipeline (verif.py) plus le grep de confidentialité, et résume pass/fail.
---

Lance, dans cet ordre, sans rien modifier :

1. **Contrôle du pipeline** (lecture seule, ne touche à rien sous `data/`) :
   - si `pwsh`/`powershell` est disponible : `pwsh -File run.ps1 verif`
     (ou `.\run.ps1 verif` sous Windows) ;
   - sinon, invoque directement l'interpréteur conda du projet :
     `<conda>\envs\sitegeo\python.exe src/verif.py` (jamais `py`, jamais
     `conda run` — CLAUDE.md §Environnement). Si aucun des deux n'est
     exécutable dans cette session (ex. session distante sans l'env
     Windows/conda), dis-le clairement plutôt que d'improviser une
     alternative.
2. **Grep de confidentialité** — construis le motif à partir de ce qui
   existe réellement :
   ```
   git grep -iE "<insee>|<section>|<numeros>|<site_name>"
   ```
   avec les valeurs tirées de `config/site.local.toml` et/ou
   `data/meta.json` s'ils existent (jamais de valeur codée en dur). Doit
   être vide (CLAUDE.md §Confidentialité). Si ni l'un ni l'autre fichier
   n'existe encore, dis-le — rien à vérifier à ce stade du pipeline.

Résume en quelques lignes : verif.py OK/KO (avec le message d'erreur clé le
cas échéant), grep confidentialité vide/non-vide (et si non-vide, où).
Aucune correction automatique ici — /qualite ne fait que rapporter.

## Lire un échec

- Une erreur `FileNotFoundError` sur `data/meta.json` ou `data/
  terrain_stats.json` → l'étape correspondante du pipeline n'a pas encore
  tourné, ce n'est pas un bug de `verif.py`.
- Une divergence de contenance/surface au-delà des tolérances documentées
  dans `verif.py` → vérifier d'abord si le cadastre a changé côté API
  Carto avant de suspecter le code local.
- Un écart de calage de l'image de fond → voir `docs/notice_calage.md`
  (généré) avant de toucher à `build_home.py`.
