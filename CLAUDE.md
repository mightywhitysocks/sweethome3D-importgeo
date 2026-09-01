# Instructions projet

Pipeline **IGN Géoplateforme -> Sweet Home 3D** : plan 3D géoréférencé d'une
parcelle cadastrale française. Sortie : `Plan 3D.sh3d` (racine, git-ignored).

## Confidentialité : dépôt public

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
- **Ne jamais installer `matplotlib`** dans cet env -> crash DLL Windows
  (exit `-1066598273`). `pyvista` OK tant qu'on ne touche pas
  `pyvista.plotting` / `Plotter` / `.plot()`. `pv.Plane()` casse (même cause) ->
  `solidify` utilise extrusion + `capping`.
- Les aperçus se font en PIL.

### Session Claude Code distante (conteneur Linux éphémère)

`.\run.ps1` lui-même (création de l'env conda `sitegeo`, détection de chemins
d'install Windows) ne s'exécute pas dans ce type de session. **Mais le JDK et
le rendu photo headless Sweet Home 3D fonctionnent dans ce conteneur** —
validé de bout en bout (`build_home.py` -> `.sh3d` -> rendu SunFlow réel via
`RenderPhoto.java`/`xvfb-run`), à ne pas supposer impossible par défaut :
- JDK (java + javac) déjà présent dans ce type de conteneur.
- `SweetHome3D.jar` + jars de rendu (`sunflow-*.jar`, `j3dcore.jar`,
  `j3dutils.jar`, `vecmath.jar`, `batik-svgpathparser-*.jar`) récupérables
  depuis l'archive Linux officielle SourceForge `SweetHome3D-<version>-linux-x64.tgz`
  (`lib/`) ; référencer les chemins dans `config/site.local.toml` (`[tools]
  sweethome3d_jar`, `render_libs_dir`, git-ignored).
- `xvfb-run` disponible et nécessaire (cf. limitation Linux dans
  `docs/PIPELINE.md`).
- Un venv pip classique (`config/requirements-venv.txt`, git-suivi) remplace
  l'env conda pour lancer `src/*.py` directement, **`verif.py` compris** :
  `python3 -m venv .venv && .venv/bin/pip install -r
  config/requirements-venv.txt` puis `.venv/bin/python src/verif.py` --
  validé de bout en bout (tous les imports passent : `sitegeo`, `rasterio`,
  `PIL`, `shapely`, `javaobj` ; seul échec observé = `FileNotFoundError` sur
  `data/*.json` quand le pipeline n'a pas encore tourné dans la session,
  exactement le même échec non bloquant que sous Windows avant le premier
  run, cf. `/qualite` > "Lire un échec"). Le `python3` par défaut de ce type
  de conteneur est 3.11 (pas 3.12 comme le conda `sitegeo`) : les pins de
  `requirements-venv.txt` sont donc figées aux versions réellement testées
  sous 3.11, pas un simple report des pins conda de `environment.yml`.
- Seul point réellement indisponible : `gdal_contour.exe` (`courbes.py`,
  binaire GDAL Windows) — ne bloque pas `build_home.py`, qui ne consomme pas
  sa sortie.

Le hook `SessionStart` (`.claude/hooks/session-start.sh`) reflète cette
distinction ; le corriger si elle redevient trop générale.

## Lancer

```
.\run.ps1            # complet : phase1_cadastre -> terrain -> bati -> vegetation -> courbes -> build_home
.\run.ps1 verif      # contrôle lecture seule
.\run.ps1 terrain bati
.\run.ps1 -Site x.toml
```

## Arborescence

- `src/` : Python (lancé en scripts ; `import sitegeo as cg`).
- `java/Conv.java` : helper Sweet Home 3D (génération `.sh3d`).
- `java/RenderPhoto.java` : helper rendu photo headless (`verif.py --render`,
  optionnel).
- `assets/` : gabarits stables versionnés (`home_template.xml` neutre, `tree.obj/.mtl`).
- `config/` : `environment.yml` + `site.example.toml` (versionnés) / `site.local.toml` (non).
- `docs/` : `PIPELINE.md` (détail `.sh3d` + limites). `notice_calage.md` est généré.
- `data/` : **toutes** les sorties. Ne pas éditer à la main, ne pas versionner.
- Chemins centralisés dans `sitegeo.py` : `cg.DATA` `cg.ASSETS` `cg.DOCS`
  `cg.JAVA` `cg.VERIF` `cg.HOME_SH3D` `cg.ENV_ROOT`. `cg.GEO` == `cg.DATA` (alias).

## Points durs

- **Repère plan figé** : `data/meta.json`, origine Lambert-93 calculée en Phase 1,
  réutilisée telle quelle partout. `verif.py` la contrôle.
- **`sitegeo.META`** est un proxy paresseux (`meta.json` n'existe pas au 1er run).
- **Winding OBJ** : `write_obj` écrit y-up (réflexion) -> faces émises `f c b a`
  pour ne pas être cullées ; vérif = `signed_volume > 0` d'un mesh fermé.
- **Ancrage sol** : objets posés à `cg.terrain_z_at(x, y)` = altitude de la
  **surface du maillage** (pas le MNT brut 0,5 m ; le maillage est à 2 m).
- **`.mtl` 100 % mat** : `Ka 0`, `Ks 0`, `Ns 1`, `illum 1` (`write_mtl`).
- **Génération `.sh3d`** : le loader Sweet Home 3D exige l'entrée `Home`
  sérialisée Java -> produite par `java/Conv.java` (JDK requis). Un `.sh3d` avec
  seulement `Home.xml` est rejeté. Voir `docs/PIPELINE.md`.
- **Plugin MCP Sweet Home 3D** : `load_home` / `get_state` / `save_home`
  mésaffichent les niveaux (tout sur un calque), bug plugin. La vérité =
  relecture par `Conv` + ouverture native. Ne pas s'y fier pour vérifier les calques.
- **`bati.py` `_fnum`** filtre les NaN (BD TOPO `altitude_maximale_toit` souvent
  absente sur les parcelles voisines) sinon apex de toit NaN -> mesh cassé.
- **Rendu photo headless** (`verif.py --render`, `src/preview.py`) : `RenderPhoto.java`
  compilé comme `Conv.java`, moteur SunFlow de Sweet Home 3D. `.jar` et jars de
  rendu auto-détectés (installeur classique + Microsoft Store). Détails, cas Linux
  (`xvfb-run`) et limites : `docs/PIPELINE.md`.
- **`roof_lidar.py`** (toit multi-pans de la propriété) : `MIN_INLIERS` RANSAC
  et `MIN_COMPONENT_PTS` (repli coin en L) sont volontairement bas -- un seuil
  trop haut traite un vrai pan/segment de jonction comme du bruit statistique
  (constaté : un amas de 3-5 points gagnait par hasard le ratio des valeurs
  singulières devant un amas réel de 40-80 points). Toujours revalider par
  cohérence spatiale (composantes connexes), jamais par un seul seuil. `None`
  en sortie (nuage trop petit, aucun plan, partition non close) -> `bati.py`
  se replie sur le toit pyramidal, jamais de bâtiment propriété sans toit.
- **Solide fermé PyVista** : `mesh.volume` (et tout calcul de volume signé)
  n'est fiable qu'APRÈS `compute_normals(auto_orient_normals=True,
  consistent_normals=True)` -- `extrude(capping=True)` seul peut laisser des
  faces à l'envers (constaté : volume 2,3x trop grand avant, correct après).
- **Dépendance externe optionnelle : `roofer`** (moteur 3DBAG/TU Delft,
  https://github.com/3DBAG/roofer, **licence GPLv3**) -- utilisé uniquement par
  `src/roofer_compare.py`, un outil de diagnostic ponctuel qui compare
  `roof_lidar.build_roof` à `roofer` sur le(s) bâtiment(s) propriété. **Jamais
  intégré à `run.ps1` / `build_home.py`**, ni redistribué dans ce dépôt : appelé
  en sous-processus CLI (binaire externe, aucun code copié/lié) -- pas de
  contamination de licence sur le code du dépôt. Installation : script officiel
  `distribution/install.sh` du dépôt `roofer` (binaire précompilé Linux x86_64,
  pas de sudo requis, pose `~/.local/bin/roofer`). Entrée attendue : dalle(s)
  LAZ IGN (déjà ce que télécharge `cg.lidar_points_l93`, dalle brute non
  filtrée par classe) + empreinte bâtiment en GeoPackage EPSG:2154 ; sortie :
  CityJSONSequence (`*.city.jsonl`), attributs `rf_roof_planes`,
  `rf_h_roof_ridge`, `rf_rmse_lod22`, etc. -- `rf_h_roof_ridge` peut être `None`
  (aucun faîtage détecté), toujours protéger le formatage. Validé mécaniquement
  (installation + CLI + parsing CityJSON) sur le jeu de test officiel du projet
  (`wippolder.zip`, 60 bâtiments, ~2 s) dans une session Claude Code distante ;
  jamais exécuté sur les données réelles du site (nécessite `config/site.local.toml`
  rempli, absent par construction de ce type de session -- cf. section
  Environnement).

## git

Dépôt publié sur GitHub (`git` via GitHub Desktop). Ne pas `init` / committer /
merger sans accord explicite de l'utilisateur. Passer par une branche + PR ;
jamais de `push` direct sur `main`, jamais `--force`.
