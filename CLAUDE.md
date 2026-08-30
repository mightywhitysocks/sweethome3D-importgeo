# Instructions projet

Pipeline **IGN Géoplateforme → Sweet Home 3D** : plan 3D géoréférencé d'une
parcelle cadastrale française. Sortie : `Plan 3D.sh3d` (racine, git-ignored).

## Confidentialité — dépôt public

La parcelle cible vit **uniquement** dans `config/site.local.toml` (git-ignored).
**Ne jamais** committer ce fichier, ni écrire une commune / un code INSEE / une
section / un numéro de parcelle / des coordonnées dans le code, les docstrings,
les commentaires, les docs ou les messages de commit. Avant tout commit :
`git grep -iE "<commune>|<insee>"` doit être vide. Tout `data/` est git-ignored
(géométrie exacte du site).

## Environnement

- Conda `sitegeo` (`config/environment.yml`). Appeler
  `<conda>\envs\sitegeo\python.exe` **directement**.
- **Jamais** `py` (Python système). **Jamais** `conda run` (casse le multi-lignes).
- **Ne jamais installer `matplotlib`** dans cet env → crash DLL Windows
  (exit `-1066598273`). `pyvista` OK tant qu'on ne touche pas
  `pyvista.plotting` / `Plotter` / `.plot()`. `pv.Plane()` casse (même cause) →
  `solidify` utilise extrusion + `capping`.
- Les aperçus se font en PIL.

## Lancer

```
.\run.ps1            # complet : phase1_cadastre → terrain → bati → vegetation → courbes → build_home
.\run.ps1 verif      # contrôle lecture seule
.\run.ps1 terrain bati
.\run.ps1 -Site x.toml
```

## Arborescence

- `src/` — Python (lancé en scripts ; `import sitegeo as cg`).
- `java/Conv.java` — helper Sweet Home 3D.
- `assets/` — gabarits stables versionnés (`home_template.xml` neutre, `tree.obj/.mtl`).
- `config/` — `environment.yml` + `site.example.toml` (versionnés) / `site.local.toml` (non).
- `docs/` — `PIPELINE.md` (détail `.sh3d` + limites). `notice_calage.md` est généré.
- `data/` — **toutes** les sorties. Ne pas éditer à la main, ne pas versionner.
- Chemins centralisés dans `sitegeo.py` : `cg.DATA` `cg.ASSETS` `cg.DOCS`
  `cg.JAVA` `cg.VERIF` `cg.HOME_SH3D` `cg.ENV_ROOT`. `cg.GEO` == `cg.DATA` (alias).

## Points durs

- **Repère plan figé** : `data/meta.json` — origine Lambert-93 calculée en Phase 1,
  réutilisée telle quelle partout. `verif.py` la contrôle.
- **`sitegeo.META`** est un proxy paresseux (`meta.json` n'existe pas au 1er run).
- **Winding OBJ** : `write_obj` écrit y-up (réflexion) → faces émises `f c b a`
  pour ne pas être cullées ; vérif = `signed_volume > 0` d'un mesh fermé.
- **Ancrage sol** : objets posés à `cg.terrain_z_at(x, y)` = altitude de la
  **surface du maillage** (pas le MNT brut 0,5 m ; le maillage est à 2 m).
- **`.mtl` 100 % mat** : `Ka 0`, `Ks 0`, `Ns 1`, `illum 1` (`write_mtl`).
- **Génération `.sh3d`** : le loader Sweet Home 3D exige l'entrée `Home`
  sérialisée Java → produite par `java/Conv.java` (JDK requis). Un `.sh3d` avec
  seulement `Home.xml` est rejeté. Voir `docs/PIPELINE.md`.
- **Plugin MCP Sweet Home 3D** : `load_home` / `get_state` / `save_home`
  mésaffichent les niveaux (tout sur un calque) — bug plugin. La vérité =
  relecture par `Conv` + ouverture native. Ne pas s'y fier pour vérifier les calques.
- **`bati.py` `_fnum`** filtre les NaN (BD TOPO `altitude_maximale_toit` souvent
  absente sur les parcelles voisines) sinon apex de toit NaN → mesh cassé.

## git

git n'est pas installé sur la machine de dev. Ne pas `init` / committer à la place
de l'utilisateur sans accord. Jamais `push` sur `main`, jamais `--force`, jamais
`merge`.
