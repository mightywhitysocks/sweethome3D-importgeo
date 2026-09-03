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

**Le pipeline de génération suppose désormais un environnement Linux/macOS**
(`phase1_cadastre.py` -> `terrain.py` -> `bati.py` -> `vegetation.py` ->
`courbes.py` -> `build_home.py`) : `bati.py` appelle `roofer` (cf. "Points
durs" > roofer) pour le toit multi-pans des bâtiments propriété, et `roofer`
n'a pas de build Windows officiel. **Windows + conda `sitegeo` sert
uniquement à ouvrir/rendre `Plan 3D.sh3d` dans l'application Sweet Home 3D
native** — pas à relancer le pipeline de génération : `bati.py` s'y
replierait silencieusement sur le toit pyramidal (binaire `roofer`
introuvable), sans planter. `.\run.ps1` reste documenté dans le README pour
un lancement partiel (un seul script, ex. `terrain.py` seul) ou historique,
pas comme méthode principale de génération.

- Conda `sitegeo` (`config/environment.yml`). Appeler
  `<conda>\envs\sitegeo\python.exe` **directement**.
- **Jamais** `py` (Python système). **Jamais** `conda run` (casse le multi-lignes).
- **Ne jamais installer `matplotlib`** dans **cet env conda Windows précisément**
  -> crash DLL Windows (exit `-1066598273`) : un conflit de bibliothèque
  natives propre à cette combinaison conda-forge/Windows, sans équivalent
  connu sous Linux/macOS. `pyvista` OK tant qu'on ne touche pas
  `pyvista.plotting` / `Plotter` / `.plot()`. `pv.Plane()` casse (même cause) ->
  `solidify` utilise extrusion + `capping`. **Règle sans objet côté
  Linux/macOS/Docker** : `pyvista` y déclare `matplotlib` comme dépendance
  PyPI inconditionnelle (confirmé sur le manifeste `0.48.4`, pas un extra
  optionnel) — `pip install pyvista` l'installe donc forcément, visible dans
  les logs de `Dockerfile`/`run.sh`. Sans risque : jamais importé par le code
  du dépôt (`pyvista.plotting` non plus, cf. ci-dessus), et le crash est
  structurellement absent sur ces OS. Ne pas essayer de l'exclure
  (`--no-deps` sur `pyvista` casserait ses autres dépendances réelles).
- Les aperçus se font en PIL.
- **Versions harmonisées** entre `environment.yml` (conda Windows) et
  `requirements-venv.txt` (venv pip Linux/macOS/Docker) : mêmes numéros de
  version des deux côtés (Python 3.14 compris), cf. en-tête de
  `requirements-venv.txt`. Seules exceptions structurelles : `lazrs`
  (backend LAZ requis seulement côté pip, `laspy` conda l'embarque
  autrement) et GDAL (`libgdal` conda vs `gdal-bin` système, mécanismes de
  paquet différents par nature).

### Trois façons de lancer la génération complète (toit multi-pans)

1. **`./run.sh`** (nouveau, Linux/macOS local ou distant) : port bash de
   `run.ps1` (mêmes menus, même boucle réessayer/sauter/arrêter), sur
   `config/requirements-venv.txt` (`.venv/`, créé automatiquement). C'est
   maintenant le point d'entrée général pour **tout** environnement
   Linux/macOS, y compris une session Claude Code distante (conteneur Linux
   éphémère) — qui n'est qu'un cas particulier de ce mode, plus besoin de
   procédure séparée pour elle. Dans une session Claude Code (pas de
   terminal interactif persistant entre les appels), préférer
   `./run.sh --non-interactive` ou appeler `src/*.py` directement plutôt que
   le menu interactif.
2. **`.github/workflows/generation.yml`** (GitHub Actions, `workflow_dispatch`) :
   génère dans une image Docker dédiée (`Dockerfile`, publiée par
   `build-image.yml` sur `ghcr.io`), sur un runner éphémère à la demande —
   aucune machine Linux locale requise. Détail complet (secrets, modèle
   « un repo privé par utilisateur ») dans le README, section « Génération à
   la demande ».
3. **Session Claude Code distante (conteneur Linux éphémère)** : le JDK et
   le rendu photo headless Sweet Home 3D y fonctionnent — validé de bout en
   bout (`build_home.py` -> `.sh3d` -> rendu SunFlow réel via
   `RenderPhoto.java`/`xvfb-run`), à ne pas supposer impossible par défaut :
   - JDK (java + javac) déjà présent dans ce type de conteneur.
   - `SweetHome3D.jar` + jars de rendu (`sunflow-*.jar`, `j3dcore.jar`,
     `j3dutils.jar`, `vecmath.jar`, `batik-svgpathparser-*.jar`)
     récupérables depuis l'archive Linux officielle SourceForge
     `SweetHome3D-<version>-linux-x64.tgz` (`lib/`) ; référencer les chemins
     dans `config/site.local.toml` (`[tools] sweethome3d_jar`,
     `render_libs_dir`, git-ignored).
   - `xvfb-run` disponible et nécessaire (cf. limitation Linux dans
     `docs/PIPELINE.md`).
   - `./run.sh` (ou un venv pip manuel) y fonctionne pour lancer `src/*.py`
     directement, **`verif.py` compris** — validé de bout en bout côté
     imports/exécution avant l'harmonisation des versions ci-dessus (Python
     3.11 à l'époque, `courbes.py` sauté faute de `gdal_contour`). **Non
     revalidé depuis** le passage à Python 3.14 harmonisé : si le `python3`
     par défaut de ce type de conteneur est resté à 3.11, `requirements-venv.txt`
     (qui exige maintenant Python >=3.12, numpy 2.5.\*) n'installera pas tel
     quel — prévoir un `python3.12`+ explicite dans ce cas plutôt que
     supposer que le défaut du conteneur suffit.

Le hook `SessionStart` (`.claude/hooks/session-start.sh`) reflète cette
distinction ; le corriger si elle redevient trop générale.

## Lancer

Génération complète (toit multi-pans) : `./run.sh` (Linux/macOS, cf.
Environnement) ou GitHub Actions (`generation.yml`, cf. README). `.\run.ps1`
ne sert qu'à ouvrir/rendre `Plan 3D.sh3d` sous Windows, ou à lancer un seul
script isolément (cf. Environnement) — pas la génération complète.

```
./run.sh              # complet : phase1_cadastre -> terrain -> bati -> vegetation -> courbes -> build_home
./run.sh verif        # contrôle lecture seule
./run.sh terrain bati
./run.sh --site x.toml
```

```
.\run.ps1            # idem, mais toit pyramidal seulement (roofer absent sous Windows)
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
  pour ne pas être cullées ; invariant contrôlé par `verif.py`
  (`_check_closed_mesh` : 0 arête ouverte + volume signé positif, calculé par
  une formule maison -- `PolyData.volume`/vtkMassProperties ne convient pas,
  il renvoie une magnitude insensible au winding) sur `terrain.obj`/`haies.obj`
  (les seuls OBJ garantis fermés par construction).
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
- **Cache disque WFS/WMS** (`sitegeo._cached`, `data/net_cache/`) : le
  Géoplateforme IGN limite le nombre d'accès consécutifs (constaté :
  `ConnectionResetError` répétées en usage normal, PAS une coupure réseau).
  `wfs_l93`, `wms_getmap` (donc `wms_ortho_rgb`/`wms_raster`) et
  `lidar_tile_index` mettent leur réponse déjà parsée en cache disque,
  indéfiniment -- **jamais invalidé automatiquement**. Si les données
  source changent (nouvelle bbox, nouveau site, données BD TOPO/LiDAR mises
  à jour côté IGN) : `rm -rf data/net_cache` avant de relancer. Même
  répertoire `data/` que le reste (git-ignore).
- **Rendu photo headless** (`verif.py --render`, `src/preview.py`) : `RenderPhoto.java`
  compilé comme `Conv.java`, moteur SunFlow de Sweet Home 3D. `.jar` et jars de
  rendu auto-détectés (installeur classique + Microsoft Store). Détails, cas Linux
  (`xvfb-run`) et limites : `docs/PIPELINE.md`.
- **`roof_lidar.py`** (ancienne méthode de reconstruction du toit multi-pans
  de la propriété par RANSAC direct sur le nuage LiDAR ; **plus appelée par
  `bati.py`**, remplacée par `roofer` -- cf. "Dépendance externe : roofer"
  ci-dessous -- conservée dans le dépôt uniquement pour référence/comparaison
  via `roofer_compare.py`) : `MIN_INLIERS` RANSAC et `MIN_COMPONENT_PTS`
  (repli coin en L) y sont volontairement bas -- un seuil trop haut traite un
  vrai pan/segment de jonction comme du bruit statistique (constaté : un
  amas de 3-5 points gagnait par hasard le ratio des valeurs singulières
  devant un amas réel de 40-80 points). Toujours revalider par cohérence
  spatiale (composantes connexes), jamais par un seul seuil. `None` en
  sortie (nuage trop petit, aucun plan, partition non close) -> repli sur le
  toit pyramidal côté appelant (comportement d'origine, non exercé par le
  pipeline actuel).
- **Solide fermé PyVista** : `mesh.volume` (et tout calcul de volume signé)
  n'est fiable qu'APRÈS `compute_normals(auto_orient_normals=True,
  consistent_normals=True)` -- `extrude(capping=True)` seul peut laisser des
  faces à l'envers (constaté : volume 2,3x trop grand avant, correct après).
- **Dépendance externe : `roofer`** (moteur 3DBAG/TU Delft,
  https://github.com/3DBAG/roofer, **licence GPLv3**) -- **méthode principale**
  du toit + mur de TOUS les bâtiments (propriété et voisinage), appelée depuis
  `bati.py` via `src/roofer_roof.py` (remplace l'ancien `roof_lidar.py`,
  conservé dans le dépôt pour référence/comparaison avec
  `src/roofer_compare.py`, plus appelés depuis `bati.py`). Non redistribué
  dans ce dépôt : appelé en sous-processus CLI (binaire externe, aucun code
  copié/lié) -- pas de contamination de licence sur le code du dépôt.
  Installation : script officiel `distribution/install.sh` du dépôt `roofer`
  (binaire précompilé Linux x86_64, pas de sudo requis, pose
  `~/.local/bin/roofer`) -- **pas de build Windows officiel** (cf. section
  Environnement : le pipeline de génération tourne donc en environnement
  Linux, Windows sert uniquement au rendu/visualisation Sweet Home 3D).
  Binaire absent ou en échec -> `roofer_roof.run_roofer` renvoie `None`, log
  explicite, `bati.py` se replie sur le toit pyramidal pour tous les
  bâtiments (jamais d'exception qui remonte). Entrée attendue : dalle(s) LAZ
  IGN (déjà ce que télécharge `cg.lidar_points_l93`, dalle brute non filtrée
  par classe) + empreinte de TOUS les bâtiments du site en un seul
  GeoPackage EPSG:2154 (colonne `cleabs`, un seul appel CLI pour tout le lot
  -- `roofer_roof.write_footprint_gpkg`) ; sortie : CityJSONSequence
  (`*.city.jsonl`), géométrie `Solid` LoD2.2 par bâtiment (portée par le
  `BuildingPart` enfant, PAS le `Building` parent qui porte `cleabs` -- cf.
  `roofer_roof._find_roof_geometry`).
  **`roofer_roof.py` consomme le `Solid` de roofer TEL QUEL** (aucune
  reconstruction géométrique propre du mur ni regroupement de faces en pans
  -- ni Union-Find sur les normales, ni ajustement de plan SVD, ni
  extrapolation) : les semantics CityJSON (`GroundSurface`/`WallSurface`/
  `RoofSurface`, `_solid_faces`) donnent directement le type de chaque face
  et son pan d'appartenance (un index de surface `RoofSurface` = un pan
  complet, roofer ne fragmente jamais un pan en plusieurs faces -- vérifié
  sur 18 bâtiments réels). Seul ajout : un décalage vertical RIGIDE (une
  seule translation, jamais de reconstruction par sommet) pour ancrer le
  solide sous le maillage terrain, avec la même marge de sécurité que les
  autres types de bâtiments du pipeline (`base_cm`, calculé par `bati.py`).
  Chaque face est triangulée par éventail-centroïde (ajout du centroïde de
  la face, un triangle par arête) plutôt que via `.triangulate()` générique
  -- **constaté sur un bâtiment réel** : `.triangulate()` (VTK) peut laisser
  un petit trou au milieu d'un pan à forme très étirée/complexe (11 sommets),
  l'éventail-centroïde couvre par construction tout polygone simple, quelle
  que soit sa forme. Approche alignée sur la pratique du projet officiel
  `3DBAG/3dbag-surfaces` (classification par semantics, jamais de
  reconstruction de mur à part) et sur l'algorithme documenté de roofer
  (partition de l'empreinte d'entrée puis extrusion -- garantit que
  l'empreinte du `Solid` en sortie correspond à l'empreinte BD TOPO fournie
  en entrée, vérifié au cm près). Découpage en groupes de matériau pour
  l'OBJ multi-matériaux (mur = Ground+Wall, un groupe par pan coloré via
  `cg.roof_color_from_ortho`) fait sur le solide déjà validé fermé -- ne
  réintroduit pas de trou (les arêtes de bord entre deux groupes restent
  géométriquement coïncidentes, cf. vérification empirique : 0 arête ouverte
  sur les 18 bâtiments reconstruits de cette session, groupes inclus).
  **Deux garde-fous ajoutés lors d'une revue de code ultérieure** (issues
  #35/#42) : un bâtiment `MultiPolygon` (parties disjointes) reçoit un
  identifiant `cleabs` suffixé par polygone (`roofer_roof.cleabs_for`,
  utilisé à la fois par `write_footprint_gpkg` et par l'appelant de
  `build_roof` dans `bati.py`) -- sinon toutes les parties récupéraient à
  tort le `Solid` de la première (même `cleabs` réutilisé) ; un `Solid` avec
  des faces `RoofSurface` mais aucune `GroundSurface`/`WallSurface` (sortie
  `roofer` atypique) est désormais traité comme un échec de reconstruction
  (repli pyramidal) plutôt que de produire un toit flottant sans mur.
  **Bug confirmé (roofer 1.1.0-beta.1), n'affecte QUE `roofer_compare.py`**
  (attributs CityJSON `rf_h_*`, pas la géométrie du `Solid` que consomme
  `roofer_roof.py`) : `rf_h_ground` est exposé relatif à
  `transform.translate[2]` (translation Z interne du CityJSON, pour la
  compression des coordonnées), PAS en NGF absolu -- contrairement à
  `rf_h_roof_min/max/50p/70p`, qui eux le sont bien. Confirmé empiriquement en
  comparant le nuage rogné par roofer lui-même (`--crop-output`) : le Z réel
  des points sol retombe à quelques cm de `rf_h_ground + transform.translate[2]`.
  Écarté : bug connu "garbage value avec plusieurs pointclouds en entrée"
  (déjà corrigé en v1.0.0-beta.6, testé ici avec 1 seule dalle -- résultat
  identique). `rf_h_roof_ridge` (hauteur relative au sol) était déjà correct
  tel quel ; seul `rf_h_ground` manquait ce recalage. Correctif appliqué dans
  `_roofer_metrics` (`roofer_compare.py`) : lire `transform.translate[2]` sur
  la ligne de métadonnées du `.city.jsonl` et l'ajouter à `rf_h_ground`.
  Validé mécaniquement (installation + CLI + parsing CityJSON) sur le jeu de
  test officiel du projet (`wippolder.zip`, 60 bâtiments, ~2 s), **et exécuté
  de bout en bout sur les données réelles du site** dans une session Claude
  Code distante (`config/site.local.toml` renseigné manuellement pour ce test,
  jamais committé) : 5 bâtiments propriété, résultats cohérents avec
  `roof_lidar.py` sur les cas simples (écart de quelques cm), divergents sur
  un cas complexe (nombre de pans) et sur 2 cas limites (chacune des deux
  méthodes réussit là où l'autre échoue) -- pas de verdict tranché en faveur
  de l'une ou l'autre à ce stade, juste une confirmation que la comparaison
  est mécaniquement fiable.
- **Couverture LiDAR/BD TOPO incomplète en entrée de `roofer` : implémenté
  (issues #22, #23).** Diagnostic d'origine (comparaison emprise BD TOPO vs
  union des pans reconstruits, 18 bâtiments) : écarts systémiques, jusqu'à
  55 % de l'emprise non couverte sur certains bâtiments. Deux causes racines,
  alignées sur l'exemple officiel IGN
  [`ignfab/roofer-with-ignf-datasets`](https://github.com/ignfab/roofer-with-ignf-datasets)
  (Docker-first, PDAL) et sur `roofer --help-all` -- corrigées en préparant
  l'entrée dans un format que `roofer` sait déjà consommer (paramètres CLI
  existants), jamais par une reconstruction géométrique ou un calcul
  d'altitude côté projet (cohérent avec le choix déjà fait de consommer le
  `Solid` de `roofer` tel quel, cf. plus haut) :
  - **Classification LiDAR** : les dalles LAZ IGN brutes contiennent des
    points classés **67 (« Divers -- bâtis »)**, une classe IGN propre,
    hors nomenclature ASPRS. `roofer` ne regarde que `--bld-class`
    (défaut **6**) / `--grnd-class` (défaut **2**) -- les points 67 lui
    sont donc invisibles. `roofer_roof._remap67` (appelée par
    `lidar_tile_paths`) remap ces points 67 -> 6, en pur laspy/numpy (pas de
    dépendance PDAL, cf. `config/environment.yml`), sur une copie de chaque
    dalle mise en cache disque dans `data/lidar_cache/roofer_remap67to6/`
    (jamais le fichier source, partagé avec `cg.lidar_points_l93`) --
    reproduit le remap PDAL `filters.assign` **67 -> 6** documenté par
    `roofer-with-ignf-datasets`. Une dalle dont le remap échoue (LAZ
    corrompu, backend LAZ absent) est fournie à `roofer` sans remap plutôt
    qu'écartée -- dégrade la couverture, ne bloque jamais l'appel.
  - **Attributs de repli d'altitude** : `roofer_roof.write_footprint_gpkg`
    écrit désormais, en plus de `cleabs` + géométrie, les colonnes
    `altitude_minimale_sol`/`altitude_maximale_toit` (mêmes noms que
    `roofer-with-ignf-datasets`), complétées autant que possible par
    `_complete_altitudes` (toit manquant -> sol + `hauteur` ; sol manquant
    -> toit - `hauteur` -- cascade simplifiée aux 3 champs BD TOPO déjà
    extraits par `bati.py`, pas les 4 colonnes min/max complètes du script
    de référence `set_building_attributes.sh`). `roofer_roof.run_roofer`
    transmet ces deux colonnes via `--h-terrain-attribute`/
    `--h-roof-attribute` (confirmés dans `roofer --help-all`), utilisés par
    `roofer` uniquement quand sa couverture LiDAR est insuffisante pour
    dériver l'altitude sol/toit d'un bâtiment depuis le nuage. Bonus repéré
    dans `roofer --help-all`, pas configuré explicitement (comportement par
    défaut conservé) : avec `--clear-insufficient` (vrai par défaut), un
    bâtiment à couverture insuffisante SANS `--h-roof-attribute` ne recevait
    aucun modèle de `roofer` (repli pyramidal maison) ; avec l'attribut
    désormais fourni, `roofer` produit lui-même une extrusion LoD1.1 -- un
    cas de plus couvert par `roofer` plutôt que par le repli pyramidal du
    projet.
  - Validé mécaniquement (tests unitaires ciblés : remap sur une dalle LAS
    synthétique avec points classés 67, cascade `_complete_altitudes` sur
    les 4 combinaisons de valeurs manquantes, écriture GPKG des deux
    colonnes) dans une session Claude Code distante. **Pas encore revalidé
    sur données réelles** (pas de site configuré dans cette session,
    confidentialité) : reprendre la comparaison emprise BD TOPO vs pans
    reconstruits sur le même jeu de 18 bâtiments qui a servi au diagnostic
    d'origine, lors d'un prochain run complet sur le site.
- **Décision actée (issue #25) : `roof_lidar.py`/`roofer_compare.py` restent
  dans le dépôt comme filet de comparaison**, pas de purge pour l'instant.
  Les deux fixes de couverture `roofer` ci-dessus sont désormais appliqués
  (remap classe 67, attributs d'altitude), mais -- comme noté juste au-dessus
  -- pas encore revalidés sur données réelles faute de site configuré dans
  la session qui les a écrits. Tant que cette revalidation (même jeu de 18
  bâtiments que le diagnostic d'origine) n'a pas eu lieu, purger le filet de
  comparaison serait prématuré : revisiter cette décision une fois la
  revalidation faite.
- **Investigué et écarté pour l'instant (issue #24) : crop LiDAR streamé
  (COPC) en remplacement du téléchargement de dalle entière.** Les dalles
  LiDAR HD IGN sont bien diffusées au format COPC (`.copc.laz`, confirmé en
  inspectant `ignfab/roofer-with-ignf-datasets` : `readers.copc` PDAL ciblé
  sur la même colonne `url` que celle que `cg.lidar_tile_index` lit déjà) --
  un crop spatial est donc structurellement possible côté serveur. Mais :
  - `copclib` (bindings Python du moteur COPC, wheels manylinux précompilées
    sur PyPI pour CPython 3.9-3.13 -- pas de sudo/conda requis, contrairement
    à PDAL) ne résout PAS le problème réseau visé ici : son unique classe
    exposée en Python, `FileReader(path)`, ne lit qu'un fichier LOCAL déjà
    complet -- le constructeur C++ générique sur `std::istream*` (qui
    permettrait en théorie un flux HTTP custom) n'est pas exposé côté
    bindings Python (vérifié dans `python/bindings.cpp` du dépôt
    `RockRobotic/copc-lib`). L'installer n'évite donc pas de télécharger la
    dalle entière au préalable.
  - Un vrai crop réseau demanderait un client Range-HTTP maison (parser les
    VLR COPC info/hiérarchie via `requests`, ne récupérer que les chunks des
    nœuds octree qui intersectent la bbox, reconstruire un fichier COPC
    local partiel/sparse pour le passer ensuite à `copclib.FileReader`) :
    faisable en pur Python (aucune nouvelle dépendance native), mais un
    travail d'implémentation substantiel et une nouvelle surface de bugs,
    pour un gain (moins de `ConnectionResetError`) documenté comme
    "potentiellement lié", jamais mesuré.
  - Le mécanisme de résilience existant (cache disque permanent
    `data/net_cache`/`data/lidar_cache`, jamais retéléchargé une fois en
    cache ; boucle réessayer/sauter/arrêter de `run.sh`/`run.ps1` en cas
    d'échec réseau) couvre déjà le problème en pratique.
  - PDAL natif reste écarté pour la raison d'origine (dépendance système,
    deux échecs déjà documentés sur ce même obstacle d'installation :
    `ign-pdal-tools`, Entwine).
  - Décision : ne pas engager ce travail maintenant. À reconsidérer
    seulement si les erreurs réseau redeviennent un blocage récurrent réel
    (pas seulement théorique) en usage normal du pipeline.

## git

Dépôt publié sur GitHub (`git` via GitHub Desktop). Ne pas `init` / committer /
merger sans accord explicite de l'utilisateur. Passer par une branche + PR ;
jamais de `push` direct sur `main`, jamais `--force`.
