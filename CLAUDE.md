# Instructions projet

Pipeline **IGN Géoplateforme -> Sweet Home 3D** : plan 3D géoréférencé d'une
parcelle cadastrale française. Sortie : `Plan 3D.sh3d` (racine, git-ignored).

## Confidentialité : dépôt public

La parcelle cible vit **uniquement** dans `config/site.local.toml` (git-ignored).
**Ne jamais** committer ce fichier, ni écrire une commune / un code INSEE / une
section / un numéro de parcelle / des coordonnées dans le code, les docstrings,
les commentaires, les docs ou les messages de commit. Avant tout commit :
`git grep -iE "<commune>|<insee>"` doit être vide. Tout `data/` est git-ignored
(géométrie exacte du site). `interieur/` (projets `.sh3d` intérieurs par
bâtiment, cf. Arborescence) et `Plan 3D (avec interieur).sh3d` (sortie de
`fusion_interieur.py`) le sont aussi : un plan intérieur réel dévoile
l'agencement d'un bâtiment habité, tout aussi sensible que la géométrie
exacte du site.

## Environnement

**Le pipeline de génération complet tourne sur Linux/macOS et Windows**
(`phase1_cadastre.py` → `terrain.py` → `bati.py` → `vegetation.py` →
`courbes.py` → `build_home.py`, via `./run.sh` ou `.\run.ps1`). Les deux
lancent par défaut, sans argument, exactement les mêmes six étapes dans le
même ordre.

> [!NOTE]
> **Seule différence entre les deux OS : le toit des bâtiments propriété.**
> `bati.py` appelle `roofer` (cf. Points durs > roofer) pour le toit
> multi-pans, et `roofer` n'a pas de build Windows officiel. Sur Windows,
> `roofer_roof.find_roofer_bin()` renvoie `None` (binaire introuvable) et
> `bati.py` se replie silencieusement sur un toit pyramidal simple pour
> **tous** les bâtiments, sans planter et sans affecter le reste du pipeline
> (comportement déjà écrit pour ce cas, pas un contournement ad hoc).
>
> Aucun autre écart connu : `courbes.py` (`gdal_contour`, cf.
> `_gdal_contour_cmd`) et `build_home.py`/`sh3d_xml.py` (JDK, `java`/`javac`
> sur le `PATH`) fonctionnent nativement sur les deux OS ; `arbaro` (variété
> des arbres) est optionnel des deux côtés, même repli gracieux (gabarit
> d'arbre unique) s'il est absent. `.\run.ps1` (sans argument) lance donc
> bien le pipeline complet, au même titre que `./run.sh` : seul le toit
> obtenu diffère (multi-pans vs pyramidal).
>
> Constat établi par lecture de code (`roofer_roof.py`,
> `courbes.py::_gdal_contour_cmd`, `run.ps1`), **pas encore revalidé par un
> run réel sur une machine Windows** dans une session Claude Code (cette
> session tourne sur un conteneur Linux, cf. point 3 ci-dessous) : à
> confirmer au premier retour d'un contributeur Windows.

- Conda `sitegeo` (`config/environment.yml`). Appeler
  `<conda>\envs\sitegeo\python.exe` **directement**.
- **Jamais** `py` (Python système). **Jamais** `conda run` (casse le
  multi-lignes).
- **Ne jamais installer `matplotlib`** dans cet env conda Windows
  précisément : crash DLL Windows (exit `-1066598273`), un conflit de
  bibliothèques natives propre à cette combinaison conda-forge/Windows, sans
  équivalent connu sous Linux/macOS. `pyvista` OK tant qu'on ne touche pas
  `pyvista.plotting`/`Plotter`/`.plot()`. `pv.Plane()` casse (même cause),
  d'où `solidify` qui utilise extrusion + `capping`.

  > [!NOTE]
  > Règle sans objet côté Linux/macOS/Docker : `pyvista` y déclare
  > `matplotlib` comme dépendance PyPI inconditionnelle (confirmé sur le
  > manifeste `0.48.4`, pas un extra optionnel). `pip install pyvista`
  > l'installe donc forcément, visible dans les logs de
  > `Dockerfile`/`run.sh`. Sans risque : jamais importé par le code du dépôt
  > (`pyvista.plotting` non plus, cf. ci-dessus), et le crash est
  > structurellement absent sur ces OS. Ne pas essayer de l'exclure
  > (`--no-deps` sur `pyvista` casserait ses autres dépendances réelles).

- Les aperçus se font en PIL.
- **Versions harmonisées** entre `environment.yml` (conda Windows) et
  `requirements-venv.txt` (venv pip Linux/macOS/Docker) : mêmes numéros de
  version des deux côtés (Python 3.14 compris), cf. en-tête de
  `requirements-venv.txt`. Seules exceptions structurelles : `lazrs`
  (backend LAZ requis seulement côté pip, `laspy` conda l'embarque
  autrement) et GDAL (`libgdal` conda vs `gdal-bin` système, mécanismes de
  paquet différents par nature).
- **Détection des montées de version** : `.github/dependabot.yml`
  (écosystèmes `pip` sur `config/requirements-venv.txt` et `github-actions`
  sur `.github/workflows/`, chacun groupé en une seule PR mensuelle plutôt
  qu'une par paquet, ce qui réduit le nombre d'allers-retours manuels) ouvre
  des PR de mise à jour, sans jamais reconstruire ni publier d'image
  *depuis Dependabot lui-même*.

  `build-image.yml` reste déclenché par push sur
  `Dockerfile`/`requirements-venv.txt`, manuellement, ou (depuis l'ajout du
  tag `:<sha>` et de la validation sur PR, ci-dessous) sur toute PR touchant
  ces mêmes chemins : construction seule, sans publication, pour détecter
  une PR Dependabot cassante avant le merge plutôt qu'après. Jamais
  planifié (un rebuild périodique n'apporterait qu'un gain marginal,
  apt/Debian étant le seul pan non épinglé du Dockerfile, pour un coût réel).

  Deux tags publiés hors PR : `:latest` (mutable, seul tag consommé par
  `generation.yml`/`render.yml` via le workflow réutilisable
  `image-name.yml`) et `:<sha>` (immutable). Le risque de tag mono-`latest`
  sans rollback, qui justifiait autrefois ce choix de ne jamais planifier de
  reconstruction, est désormais mitigé par ce second tag (rollback manuel
  possible sur un commit précis en attendant un correctif).

  > [!IMPORTANT]
  > Toute PR Dependabot sur `requirements-venv.txt` doit être répercutée à
  > la main dans `environment.yml` (Dependabot ne couvre pas conda).

  Restent hors périmètre de Dependabot, à vérifier manuellement et
  occasionnellement : `environment.yml` lui-même, et les pins durs du
  `Dockerfile` (roofer, Sweet Home 3D, volontairement non automatisés, cf.
  Points durs > roofer).

### Trois façons de lancer la génération complète (toit multi-pans)

1. **`./run.sh`** (Linux/macOS local ou distant) : port bash de `run.ps1`
   (mêmes menus, même boucle réessayer/sauter/arrêter), sur
   `config/requirements-venv.txt` (`.venv/`, créé automatiquement). C'est le
   point d'entrée général pour **tout** environnement Linux/macOS, y compris
   une session Claude Code distante (conteneur Linux éphémère), qui n'est
   qu'un cas particulier de ce mode, sans procédure séparée. Dans une
   session Claude Code (pas de terminal interactif persistant entre les
   appels), préférer `./run.sh --non-interactive` ou appeler `src/*.py`
   directement plutôt que le menu interactif.
2. **`.github/workflows/generation.yml`** (GitHub Actions,
   `workflow_dispatch`) : génère dans une image Docker dédiée (`Dockerfile`,
   publiée par `build-image.yml` sur `ghcr.io`), sur un runner éphémère à la
   demande, aucune machine Linux locale requise. Détail complet (secrets,
   modèle « un repo privé par utilisateur ») dans le README, section
   « Génération à la demande ».
3. **Session Claude Code distante (conteneur Linux éphémère)** : le JDK et
   le rendu photo headless Sweet Home 3D y fonctionnent, validé de bout en
   bout (`build_home.py` → `.sh3d` → rendu SunFlow réel via
   `RenderPhoto.java`/`xvfb-run`). À ne pas supposer impossible par défaut :
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
     directement, **`verif.py` compris**, validé de bout en bout côté
     imports/exécution avant l'harmonisation des versions ci-dessus (Python
     3.11 à l'époque, `courbes.py` sauté faute de `gdal_contour`).

     > [!WARNING]
     > **Non revalidé depuis** le passage à Python 3.14 harmonisé. Si le
     > `python3` par défaut de ce type de conteneur est resté à 3.11,
     > `requirements-venv.txt` (qui exige maintenant Python >= 3.12,
     > numpy 2.5.\*) n'installera pas tel quel : prévoir un `python3.12`+
     > explicite dans ce cas plutôt que supposer que le défaut du conteneur
     > suffit.

Le hook `SessionStart` (`.claude/hooks/session-start.sh`) reflète cette
distinction ; le corriger si elle redevient trop générale.

## Lancer

Génération complète (toit multi-pans) : `./run.sh` (Linux/macOS, cf.
Environnement) ou GitHub Actions (`generation.yml`, cf. README). `.\run.ps1`
ne sert qu'à ouvrir/rendre `Plan 3D.sh3d` sous Windows, ou à lancer un seul
script isolément (cf. Environnement), pas la génération complète.

```bash
./run.sh              # complet : phase1_cadastre -> terrain -> bati -> vegetation -> courbes -> build_home
./run.sh verif        # contrôle lecture seule
./run.sh terrain bati
./run.sh --site x.toml
```

```powershell
.\run.ps1            # idem, mais toit pyramidal seulement (roofer absent sous Windows)
.\run.ps1 verif      # contrôle lecture seule
.\run.ps1 terrain bati
.\run.ps1 -Site x.toml
```

**Plan 2D intérieur** (séparé de la génération 3D extérieure, cf. Points
durs > plan 2D intérieur) : jamais dans la génération complète par défaut,
toujours à la main.

```bash
./run.sh phase1_cadastre terrain bati   # prérequis (sol_max_cm par bâtiment)
./run.sh interieur_init                 # crée interieur/<id>.sh3d (jamais les existants)
# ... édition manuelle dans l'appli Sweet Home 3D native ...
./run.sh fusion_interieur               # -> "Plan 3D (avec interieur).sh3d", ponctuel
```

Sans machine Linux/macOS locale : `.github/workflows/interieur.yml`
(`workflow_dispatch`) fait uniquement la création (`interieur_init.py`), à
partir du dernier artefact `Plan 3D` déjà publié par `generation.yml` (comme
`render.yml`, aucun secret de site requis) → artefact `Interieurs` à
télécharger et dézipper dans `interieur/` avant édition locale. La fusion
(`fusion_interieur.py`) reste toujours locale, jamais en CI : elle a besoin
des fichiers édités à la main, jamais versionnés.

## Arborescence

- `src/` : Python (lancé en scripts ; `import sitegeo as cg`).
- `java/Conv.java` : helper Sweet Home 3D (génération `.sh3d`).
- `java/RenderPhoto.java` : helper rendu photo headless (`verif.py --render`,
  optionnel).
- `assets/` : gabarits stables versionnés (`home_template.xml` neutre,
  `tree.obj/.mtl` gabarit d'arbre historique, `arbaro_species/*.xml` presets
  de variété des arbres).
- `config/` : `environment.yml` + `site.example.toml` (versionnés) / `site.local.toml` (non).
- `docs/` : `PIPELINE.md` (détail `.sh3d` + limites), `journal-technique.md`
  (historique chronologique des investigations, extrait des Points durs
  ci-dessous pour garder ce fichier centré sur l'état courant -- consulté à
  la demande, pas chargé par défaut). `notice_calage.md` est généré.
- `data/` : **toutes** les sorties. Ne pas éditer à la main, ne pas versionner.
- `interieur/` : projets `.sh3d` intérieurs par bâtiment propriété (un
  fichier par emprise/ring, nommé par son id), créés par `interieur_init.py`
  puis **édités à la main** dans l'appli Sweet Home 3D native, à l'inverse
  de `data/`, jamais réécrit automatiquement par le pipeline de génération
  extérieur (`interieur_init.py` ne touche jamais un fichier déjà présent).
  Git-ignoré (cf. Confidentialité). `src/sh3d_xml.py` : génération de
  fragments XML SH3D (`<level>`/`<room>`/`<pieceOfFurniture>`/...) et
  conversion vers un `.sh3d` réel via `java/Conv.java`, factorisé hors de
  `build_home.py` pour être réutilisé par `interieur_init.py` et
  `fusion_interieur.py`.
- Chemins centralisés dans `sitegeo.py` : `cg.DATA` `cg.ASSETS` `cg.DOCS`
  `cg.JAVA` `cg.VERIF` `cg.HOME_SH3D` `cg.ENV_ROOT`. `cg.GEO` == `cg.DATA` (alias).

## Points durs

Cette section garde l'état **courant** de chaque point dur (ce qu'il faut
savoir pour travailler correctement dessus). L'historique des investigations
qui a mené à cet état (essais, mesures, sessions successives, pistes
rejetées) vit dans `docs/journal-technique.md`, pointé section par section
ci-dessous quand il existe.

### Plan 2D intérieur séparé de la modélisation 3D extérieure

`interieur_init.py`, `fusion_interieur.py`, `.github/workflows/interieur.yml` :
le pipeline de génération ne modélise que l'extérieur géoréférencé
(parcelle/terrain/bâtis/végétation) -- l'agencement intérieur réel d'un
bâtiment (pièces, cloisons, mobilier) n'a aucune source IGN et se dessine à
la main.

`interieur.yml` (`workflow_dispatch`) télécharge le dernier artefact
`Plan 3D` de `generation.yml` (`data/meta.json`/`bati.json`/
`bati_propriete_ref.json`, ajoutés à cet artefact pour ce besoin -- même
niveau de sensibilité que le reste, déjà la géométrie exacte du site),
lance `interieur_init.py` dans l'image CI et publie `interieur/*.sh3d` en
artefact `Interieurs` -- aucun secret de site requis (même principe que
`render.yml` : valeurs fictives, seul le parsing de `sitegeo.py` l'exige).
Ne couvre QUE la création initiale : l'édition et la fusion
(`fusion_interieur.py`) restent toujours locales, ces étapes ont besoin des
fichiers édités à la main (jamais versionnés, jamais publiés en CI).

`interieur_init.py` crée un `.sh3d` PAR bâtiment propriété
(`interieur/<id>.sh3d`, un niveau par étage BD TOPO, repli à 1 si
absent/NaN) avec un `<room>` "guide" par niveau reproduisant l'emprise
exacte du bâtiment (même géométrie que le `<room>` "Emprise `<id>`" de
`build_home.py`) -- convention de calage visuelle, PAS un verrou : SH3D n'a
pas de mécanisme de lock sur `<room>`, rien n'empêche une
suppression/modification accidentelle. Ne réécrit **jamais** un fichier
déjà présent (travail manuel utilisateur). **Même repère plan absolu** (cm,
origine Lambert-93 du site) que `Plan 3D.sh3d` -- pas de repère local par
bâtiment : les murs dessinés dans l'appli native atterrissent directement à
la bonne position réelle, ce qui évite toute translation de coordonnées à
la fusion (le point le plus fragile d'un tel mécanisme).

`fusion_interieur.py` fusionne ponctuellement (jamais dans `run.sh`/
`generation.yml` par défaut, jamais automatique) les `interieur/*.sh3d`
dans `Plan 3D.sh3d` -> **nouveau fichier séparé** `Plan 3D (avec
interieur).sh3d`, ne modifie jamais `Plan 3D.sh3d` lui-même (cycles de vie
découplés : génération extérieure automatique vs édition intérieure
manuelle). Format XML natif **vérifié avant d'écrire le parseur** (JDK +
`SweetHome3D.jar`, programme Java jetable) plutôt que supposé : un objet
(`<wall>`/`<pieceOfFurniture>`/`<room>`) porte un attribut `level='...'`
explicite dès qu'il y a plusieurs niveaux dans le fichier (absent seulement
si un seul niveau existe -- cas alors sans ambiguïté) ; un meuble de
catalogue embarque sa propre copie de modèle/icône dans le zip sous forme
d'entrées numériques (`model='1'`, `icon='0'`), jamais une référence
catalogue pure -- `fusion_interieur.py` ne copie donc que les entrées zip
réellement référencées par les éléments retenus (jamais `Home`/
`ContentDigests`, artefacts internes à l'écriture Conv.java du fichier
source), sous un préfixe par bâtiment, et réécrit les attributs `model=`/
`icon=`/`planIcon=`/`image=`/`texture=` en conséquence. `elevationIndex`
(ordre d'affichage des niveaux, sans rapport avec la géométrie -- confirmé
par le gabarit `home_template.xml`, 5 niveaux à la même `elevation='0.0'`
mais des `elevationIndex` différents) est réattribué en continu après le
plus grand déjà utilisé côté extérieur ; chaque niveau/élément intérieur
reçoit un id UUID frais (pas seulement les niveaux -- y compris `<room>`/
`<wall>`/`<pieceOfFurniture>`/`<furnitureGroup>`, `wallAtStart`/`wallAtEnd`
réécrits en conséquence), stratégie purement additive qui ne touche jamais
aux niveaux/emprises extérieurs existants. Nécessaire même si les ids
source sont des UUID a priori uniques : un `interieur/<id>.sh3d` dupliqué à
la main (copie du fichier lui-même) pour amorcer un 2e bâtiment
reproduirait des ids identiques -- sans ce remap, deux fichiers source
distincts pourraient collisionner sur le même id dans le `Home.xml` fusionné
et casser la résolution de `wallAtStart`/`wallAtEnd` par `HomeXMLHandler`.
`Plan 3D (avec interieur).sh3d` existant est sauvegardé en `.sh3d.bak` avant
réécriture, même logique que `Plan 3D.sh3d`/`build_home.py`.

Sauvegarde normale (Ctrl+S) dans l'appli desktop réelle : **confirmé** (pas
supposé) par désassemblage de `SweetHome3D.class` dans le `.jar` 7.5 pinné
par le `Dockerfile` -- le `HomeFileRecorder` par défaut de l'appli
(`getHomeRecorder()`, utilisé pour un enregistrement normal, comme sa
variante `COMPRESSED`) passe déjà `preferXmlEntry=true`, exactement comme
`java/Conv.java` -- une édition puis sauvegarde native écrira donc bien
l'entrée `Home.xml` que `fusion_interieur.py` lit.

> [!WARNING]
> Mécanisme validé de bout en bout sur une fixture synthétique (2 bâtiments,
> murs joints, meuble de catalogue, ids dupliqués -- tous résolus sans
> collision), mais **pas encore sur un site réel** avec un vrai bâtiment
> édité dans l'appli desktop. Détail de la validation :
> `docs/journal-technique.md`.

### Repère plan figé

`data/meta.json`, origine Lambert-93 calculée en Phase 1, réutilisée telle
quelle partout. `verif.py` la contrôle.

### `sitegeo.META`

Proxy paresseux (`meta.json` n'existe pas au 1er run).

### Winding OBJ

`write_obj` écrit y-up (réflexion) -> faces émises `f c b a` pour ne pas
être cullées ; invariant contrôlé par `verif.py` (`_check_closed_mesh` :
0 arête ouverte + volume signé positif, calculé par une formule maison --
`PolyData.volume`/vtkMassProperties ne convient pas, il renvoie une
magnitude insensible au winding) sur `terrain.obj`/`haies.obj` (les seuls
OBJ garantis fermés par construction).

### Ancrage sol

Objets posés à `cg.terrain_z_at(x, y)` = altitude de la **surface du
maillage** (pas le MNT brut 0,5 m ; le maillage est à 2 m).

### Emprises `<room>` visibles des bâtiments propriété

Un `<room>` SH3D n'a pas d'élévation propre, seulement celle de son niveau
(`<level elevation=...>`, partagée par tout ce qui y est placé) --
contrairement à un `<pieceOfFurniture>` qui porte son propre `elevation`.
Un niveau *Bâti propriété* unique (élévation 0.0, cf. gabarit) suffit pour
les pièces de repère invisibles existantes (`floorVisible='false'`, ne
servent qu'aux étiquettes 2D -- la vraie géométrie vient de
`bati_propriete.obj`, ancré lui via `cg.terrain_z_at` par bâtiment). Mais
une emprise VISIBLE (demandée pour matérialiser au sol le contour d'un
bâtiment) sur ce même niveau partagé se retrouverait clippée dans le
maillage terrain dès que celui-ci dépasse l'élévation du niveau -- constaté
sur le site réel : jusqu'à ~2,5 m d'écart de sol entre deux bâtiments
propriété.

Solution : `bati.py` calcule, par emprise
(`bati_propriete_ref.json[footprints[].sol_max_cm]`, même ordre que les
commandes `create_room_polygon`), le point de terrain le plus haut sous
cette emprise (`cg.terrain_z_at` sur ses sommets) ; `build_home.py` lit
cette valeur telle quelle (aucun nouvel appel `cg.terrain_z_at`, conforme à
son propre rôle d'assembleur hors-ligne depuis `data/`) et crée un niveau
dédié par bâtiment ("Emprise `<id>`", id privé -- jamais dans `LEVELS`, le
registre stable du gabarit, passé explicitement à `_room` via son paramètre
`levels`), élévation = `sol_max_cm` + `FOOTPRINT_CLEARANCE_CM` (3 cm) --
jamais clippée, quitte à légèrement flotter au-dessus du terrain sur les
coins bas d'une emprise en pente (compromis assumé : une pièce reste un
plan plat, pas un maillage suivant le relief).

### `.mtl` 100 % mat

`Ka 0`, `Ks 0`, `Ns 1`, `illum 1` (`write_mtl`).

### Génération `.sh3d`

Le loader Sweet Home 3D exige l'entrée `Home` sérialisée Java -> produite
par `java/Conv.java` (JDK requis). Un `.sh3d` avec seulement `Home.xml` est
rejeté. Voir `docs/PIPELINE.md`.

### Plugin MCP Sweet Home 3D

`load_home` / `get_state` / `save_home` mésaffichent les niveaux (tout sur
un calque), bug plugin. La vérité = relecture par `Conv` + ouverture
native. Ne pas s'y fier pour vérifier les calques.

### `bati.py` `_fnum`

Filtre les NaN (BD TOPO `altitude_maximale_toit` souvent absente sur les
parcelles voisines) sinon apex de toit NaN -> mesh cassé.

### Cache disque WFS/WMS

`sitegeo._cached`, `data/net_cache/` : le Géoplateforme IGN limite le
nombre d'accès consécutifs (constaté : `ConnectionResetError` répétées en
usage normal, PAS une coupure réseau). `wfs_l93`, `wms_getmap` (donc
`wms_ortho_rgb`/`wms_raster`) et `lidar_tile_index` mettent leur réponse
déjà parsée en cache disque, indéfiniment.

> [!WARNING]
> Jamais invalidé automatiquement. Si les données source changent (nouvelle
> bbox, nouveau site, données BD TOPO/LiDAR mises à jour côté IGN) :
> `rm -rf data/net_cache` avant de relancer. Même répertoire `data/` que le
> reste (git-ignore).

### Rendu photo headless

`verif.py --render`, `src/preview.py` : `RenderPhoto.java` compilé comme
`Conv.java`, moteur SunFlow de Sweet Home 3D. `.jar` et jars de rendu
auto-détectés (installeur classique + Microsoft Store). Détails, cas Linux
(`xvfb-run`) et limites : `docs/PIPELINE.md`.

### `roof_lidar.py`

Ancienne méthode de reconstruction du toit multi-pans de la propriété par
RANSAC direct sur le nuage LiDAR ; **plus appelée par `bati.py`**, remplacée
par `roofer` (cf. "Dépendance externe : `roofer`" ci-dessous) -- conservée
dans le dépôt uniquement pour référence/comparaison via `roofer_compare.py`.
`MIN_INLIERS` RANSAC et `MIN_COMPONENT_PTS` (repli coin en L) y sont
volontairement bas -- un seuil trop haut traite un vrai pan/segment de
jonction comme du bruit statistique (constaté : un amas de 3-5 points
gagnait par hasard le ratio des valeurs singulières devant un amas réel de
40-80 points). Toujours revalider par cohérence spatiale (composantes
connexes), jamais par un seul seuil. `None` en sortie (nuage trop petit,
aucun plan, partition non close) -> repli sur le toit pyramidal côté
appelant (comportement d'origine, non exercé par le pipeline actuel).

### Solide fermé PyVista

`mesh.volume` (et tout calcul de volume signé) n'est fiable qu'APRÈS
`compute_normals(auto_orient_normals=True, consistent_normals=True)` --
`extrude(capping=True)` seul peut laisser des faces à l'envers (constaté :
volume 2,3x trop grand avant, correct après).

### Dépendance externe : `roofer`

Moteur 3DBAG/TU Delft (https://github.com/3DBAG/roofer, **licence GPLv3**)
-- **méthode principale** du toit + mur de TOUS les bâtiments (propriété et
voisinage), appelée depuis `bati.py` via `src/roofer_roof.py` (remplace
l'ancien `roof_lidar.py`, conservé dans le dépôt pour référence/comparaison
avec `src/roofer_compare.py`, plus appelés depuis `bati.py`). Non
redistribué dans ce dépôt : appelé en sous-processus CLI (binaire externe,
aucun code copié/lié) -- pas de contamination de licence sur le code du
dépôt. Installation : script officiel `distribution/install.sh` du dépôt
`roofer` (binaire précompilé Linux x86_64, pas de sudo requis, pose
`~/.local/bin/roofer`) -- **pas de build Windows officiel** (cf. section
Environnement). Binaire absent ou en échec -> `roofer_roof.run_roofer`
renvoie `None`, log explicite, `bati.py` se replie sur le toit pyramidal
pour tous les bâtiments (jamais d'exception qui remonte). Entrée attendue :
dalle(s) LAZ IGN (déjà ce que télécharge `cg.lidar_points_l93`, dalle brute
non filtrée par classe) + empreinte de TOUS les bâtiments du site en un
seul GeoPackage EPSG:2154 (colonne `cleabs`, un seul appel CLI pour tout le
lot -- `roofer_roof.write_footprint_gpkg`) ; sortie : CityJSONSequence
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
Chaque face est triangulée par éventail-centroïde (ajout du centroïde de la
face, un triangle par arête) plutôt que via `.triangulate()` générique --
constaté sur un bâtiment réel : `.triangulate()` (VTK) peut laisser un
petit trou au milieu d'un pan à forme très étirée/complexe (11 sommets),
l'éventail-centroïde couvre par construction tout polygone simple, quelle
que soit sa forme. Approche alignée sur la pratique du projet officiel
`3DBAG/3dbag-surfaces` (classification par semantics, jamais de
reconstruction de mur à part) et sur l'algorithme documenté de roofer
(partition de l'empreinte d'entrée puis extrusion -- garantit que
l'empreinte du `Solid` en sortie correspond à l'empreinte BD TOPO fournie
en entrée, vérifié au cm près). Découpage en groupes de matériau pour l'OBJ
multi-matériaux (mur = Ground+Wall, un groupe par pan coloré via
`cg.roof_color_from_ortho`) fait sur le solide déjà validé fermé -- ne
réintroduit pas de trou (les arêtes de bord entre deux groupes restent
géométriquement coïncidentes, 0 arête ouverte sur les 18 bâtiments
reconstruits testés, groupes inclus).

Deux garde-fous ajoutés lors d'une revue de code ultérieure (issues
#35/#42) : un bâtiment `MultiPolygon` (parties disjointes) reçoit un
identifiant `cleabs` suffixé par polygone (`roofer_roof.cleabs_for`, utilisé
à la fois par `write_footprint_gpkg` et par l'appelant de `build_roof` dans
`bati.py`) -- sinon toutes les parties récupéraient à tort le `Solid` de la
première (même `cleabs` réutilisé) ; un `Solid` avec des faces
`RoofSurface` mais aucune `GroundSurface`/`WallSurface` (sortie `roofer`
atypique) est désormais traité comme un échec de reconstruction (repli
pyramidal) plutôt que de produire un toit flottant sans mur.

`roofer_compare.py` corrige un bug connu de roofer 1.1.0-beta.1
(`rf_h_ground` mal recalé par rapport à `transform.translate[2]`, n'affecte
que les attributs CityJSON de comparaison, jamais la géométrie que consomme
`roofer_roof.py`).

`roofer_roof.write_footprint_gpkg` écrit, en plus de `cleabs` + géométrie,
les colonnes `altitude_minimale_sol`/`altitude_maximale_toit` (mêmes noms
que le script officiel IGN
[`ignfab/roofer-with-ignf-datasets`](https://github.com/ignfab/roofer-with-ignf-datasets)),
complétées autant que possible par `_complete_altitudes` (toit manquant ->
sol + `hauteur` ; sol manquant -> toit - `hauteur`). `roofer_roof.run_roofer`
transmet ces deux colonnes via `--h-terrain-attribute`/`--h-roof-attribute`,
utilisés par `roofer` uniquement quand sa couverture LiDAR est insuffisante
pour dériver l'altitude sol/toit d'un bâtiment depuis le nuage -- corrige un
déficit de couverture systémique (jusqu'à 55 % de l'emprise non couverte
sur certains bâtiments avant ce fix, issues #22/#23). Deuxième cause du
même diagnostic : les dalles LAZ IGN brutes contiennent des points classés
**67 (« Divers -- bâtis »)**, hors nomenclature ASPRS, invisibles pour
`roofer` (qui ne regarde que `--bld-class`/`--grnd-class`, défauts 6/2) --
`roofer_roof._remap67` (appelée par `lidar_tile_paths`) les remap 67 -> 6 en
pur laspy/numpy (pas de dépendance PDAL), sur une copie mise en cache disque
dans `data/lidar_cache/roofer_remap67to6/` (jamais le fichier source). Une
dalle dont le remap échoue est fournie à `roofer` sans remap plutôt
qu'écartée -- dégrade la couverture, ne bloque jamais l'appel.

`bati.py` clippe chaque bâtiment à son camp après classification
(`geom.intersection(prop_zone)` pour `"propriete"`,
`geom.difference(prop_zone)` pour `"voisinage"`) : un polygone BD TOPO peut
englober une structure du camp opposé (constaté sur le site réel, jusqu'à
33,7 %/26 % d'aire débordante selon le sens -- fusion du polygone source par
la vectorisation IGN à grande échelle, pas un défaut de la règle de
classification). `_propriete_ref` suffixe l'id/nom par index de ring quand
un bâtiment en a plusieurs, pour ne jamais faire collisionner deux niveaux
SH3D "Emprise `<id>`" si ce clip produit un `MultiPolygon`. `verif.py`
contrôle désormais, dans les deux sens, que l'empiétement d'un bâtiment sur
le camp opposé reste quasi nul (<2 m², pas 26-33 %).

> [!NOTE]
> Réserve honnête sur ce dernier fix : corrige à coup sûr l'emprise/l'aire
> (calcul Python déterministe), mais rien ne garantit à 100 % le
> comportement interne de `roofer` (boîte noire externe, GPLv3) pour
> l'ajustement des pans de toit tout près de la nouvelle limite.

> [!IMPORTANT]
> Décision actée (issue #25) : `roof_lidar.py`/`roofer_compare.py` restent
> dans le dépôt comme filet de comparaison, pas de purge pour l'instant --
> à revisiter une fois les fixes de couverture ci-dessus revalidés sur
> données réelles (pas encore fait, cf. `docs/journal-technique.md`).

> [!NOTE]
> Crop LiDAR streamé (COPC) en remplacement du téléchargement de dalle
> entière : investigué et écarté pour l'instant (issue #24, dépendance
> PDAL/limites des bindings Python `copclib`, cf.
> `docs/journal-technique.md` pour le détail) -- à reconsidérer seulement
> si les erreurs réseau redeviennent un blocage récurrent réel.

Historique complet des investigations ci-dessus (bug roofer 1.1.0-beta.1,
diagnostic de couverture, diagnostic camp-opposé, décision COPC) :
`docs/journal-technique.md`.

### Dépendance externe optionnelle : `arbaro` (variété des arbres)

Implémentation Java de l'algorithme Weber & Penn de génération procédurale
d'arbres (https://github.com/wdiestel/arbaro, **licence GPL-2**) -- variété
des arbres (issues #81/#82) : silhouettes conifère/feuillu/arbuste générées
par `src/arbaro_tree.py`, appelé en sous-processus CLI depuis
`vegetation.py`/`build_home.py` (même principe que roofer : aucun code
arbaro copié/lié). Contrairement à roofer, **optionnel** : binaire absent
(`arbaro_tree.find_arbaro_jar` -> None) -> `prepare_species_models` renvoie
`{}`, tous les arbres réutilisent le gabarit unique historique
(`assets/tree.obj`, comportement inchangé), jamais bloquant. Pas
d'installeur officiel ni de binaire Linux précompilé publié (à la
différence de roofer) -- à construire depuis les sources (`javac`/`jar`,
package `gui/` exclu -- inutile en CLI) ou récupérer l'archive SourceForge
`1.9.9` ; chemin renseigné dans `[tools].arbaro_jar`
(`config/site.local.toml`). L'image CI (`Dockerfile`) le construit
automatiquement depuis un commit git figé (`ARBARO_COMMIT`).

**Les 3 presets d'espèce** (`assets/arbaro_species/*.xml`) sont des
paramètres Weber & Penn ORIGINAUX écrits par ce projet -- PAS une copie des
arbres de démonstration du dépôt arbaro : un preset de démonstration
standard produit environ 300 000 faces pour un seul arbre (beaucoup trop
lourd pour un objet répété dans une scène SH3D face au gabarit historique,
~5000 faces). Les 3 presets (`Levels=2`, `CurveRes=3`, `--smooth 0.0`)
visent le même ordre de grandeur (~5000-6000 faces). **État courant** (cf.
`docs/journal-technique.md` pour l'historique du réglage) :
`conifere.xml` `1Branches`=75, `LeafScale`=1.0, `LeafScaleX`=2.0 ;
`feuillu.xml` `1Branches`=50 ; `arbuste.xml` `1Branches`=22 (inchangé).

> [!WARNING]
> `LeafScale`/`LeafScaleX` du conifère sont **délibérément non
> botaniques** (~2,9x la référence réelle `tamarack.xml`) : compensent un
> plafond d'échantillonnage SunFlow à qualité `low`/distance normale, pas
> une caractéristique de l'espèce. Ne pas reprendre ces valeurs comme
> référence Weber & Penn si ce fichier sert de modèle ailleurs -- détail de
> l'investigation (pourquoi tous les autres leviers ont échoué) dans
> `docs/journal-technique.md`.

**Bug CLI arbaro confirmé** (`arbaro.java`, toutes versions du dépôt à ce
jour) : `--uvleaves`/`--uvstems` incrémentent l'index d'argument une fois
DE TROP (`i++` en plus de l'incrément normal de la boucle `for`), ce qui
avale silencieusement l'option suivante -- placé juste avant `-o <fichier>`,
ce dernier est sauté et le nom du fichier de sortie est pris à tort comme
fichier D'ENTRÉE (`FileNotFoundException` sur le chemin de sortie).
Contournement appliqué dans `arbaro_tree.py` : ces deux options ne sont
jamais passées (inutiles ici, les `.mtl` écrits par ce projet sont des
couleurs plates sans texture, cf. convention ".mtl 100% mat" ci-dessus).

**Pas de détection d'essence réelle** : `vegetation.py::_classify_essence`
est une heuristique grossière à 2 indices (forme du houppier depuis le MNH
+ teinte depuis l'ortho) choisissant entre les 3 archétypes ci-dessus, pas
une identification botanique -- aucun outil open source mature trouvé en
recherche documentaire pour aller plus loin (cf. issue #81 §3).

**Bug SweetHome3D confirmé sur données réelles et corrigé** :
`HomeContentContext.lookupContent` cache le `Content` résolu par le
PREMIER SEGMENT du chemin `model=`, pas le chemin complet -- tant que tous
les arbres écrivaient `model='tree/{model_key}.obj'` (même premier segment
pour toutes les variantes), tous les arbres du `.sh3d` final héritaient du
Content du premier arbre résolu (silhouette identique partout, malgré un
calcul/embarquement corrects en amont). Corrigé dans `build_home.py` :
chaque modèle espèce x variante écrit désormais dans son PROPRE dossier de
premier niveau (`{model_key}/{model_key}.obj` + `.mtl` dupliqué dans ce
même dossier) au lieu d'un dossier `tree/` commun. Confirmé sur un run CI
réel (76 arbres du site réel, chacun avec son propre modèle espèce x
variante) -- détail de la reproduction/investigation :
`docs/journal-technique.md`.

Historique complet du réglage de densité/feuillage (études SIGGRAPH 1995,
essais rejetés, mesures en pixels sur plusieurs runs CI réels) :
`docs/journal-technique.md`.

### Compatibilité `Plan 3D.sh3d` avec l'appli mobile / Sweet Home 3D Online

L'appli mobile Sweet Home 3D (eTeks, Google Play/App Store) déclare
officiellement partager sa compatibilité de format avec **Sweet Home 3D
Online** : les deux utilisent le même moteur JS, `SweetHome3DJS` (transpilé
depuis le code Java via **JSweet**, projet CINCHEO x eTeks). Ce moteur sait
parser du XML (`HomeXMLHandler` transpilé) mais **ne sait pas désérialiser
l'entrée Java `Home`** (`ObjectInputStream`, sans équivalent JS) que
`java/Conv.java` écrivait seule via `HomeFileRecorder` -- confirmé
empiriquement en chargeant un `.sh3d` réel dans le **vrai moteur JS
officiel eTeks** (mêmes fichiers `.min.js` que Sweet Home 3D Online,
embarqués par le paquet npm `@node-projects/sweethome3d-webcomponent`,
GPL-2.0) via Chromium headless : échec explicite `No Home.xml entry`, alors
que le même fichier s'ouvre normalement sur le desktop.

**Corrigé** : `HomeFileRecorder(9, false, null, false, true, false)`
(`preferXmlEntry=true`) dans `java/Conv.java` fait écrire, EN PLUS de
l'entrée `Home` sérialisée (seule lue par le desktop), une entrée
`Home.xml` via `HomeXMLExporter` -- classe déjà intégrée à
`SweetHome3D.jar`, pas une reconstruction maison : les chemins de modèles
renumérotés par `ContentDigests` y sont donc déjà corrects, sans risque de
désynchronisation. Sans impact desktop (l'entrée `Home` reste lue en
priorité) : un seul `.sh3d` reste compatible desktop **et** mobile/Online,
sans dupliquer aucun contenu. `verif.py --mobile-compat` automatise ce
contrôle via `tools/mobile_compat_check/` (repli explicite si Node/le
paquet npm sont absents, comme les autres dépendances externes optionnelles
-- mais ÉCHEC si le chargement lui-même rapporte une erreur, contrairement
à `--render` qui est un simple smoke-test visuel). L'image CI embarque
désormais Node.js + `node_modules`/Chromium (cf. `Dockerfile`), et
`generation.yml` appelle `verif.py --mobile-compat` sur chaque run.

> [!WARNING]
> Validé de bout en bout sur une fixture synthétique (chargement propre,
> rendu cohérent) et le build/l'installation Playwright en CI réels ont
> réussi, mais **pas encore confirmé sur un `Plan 3D.sh3d` de site réel**
> au poids géométrique complet (terrain ~43k faces, toits `roofer`
> multi-bâtiments, jusqu'à ~76 arbres `arbaro`) -- performance/fluidité sur
> mobile restent à observer sur un run complet. Détail :
> `docs/journal-technique.md`.

### Visibilité niveau/groupe sur l'appli mobile réelle

Une fois `Plan 3D.sh3d` ouvert sur mobile, peut-on masquer un niveau (ex.
Terrain/Végétation) ou un groupe de mobilier entier, comme sur desktop
(`Ctrl+Maj+H` pour un niveau) ? Recherche documentaire d'abord (blog eTeks :
l'appli mobile reprend le guide utilisateur desktop sauf
impression/photo-vidéo/plugins -- rien d'explicite sur la visibilité ;
[forum officiel](https://www.sweethome3d.com/support/forum/viewthread_thread,6334) :
masquer un élément **individuel à l'intérieur d'un groupe** sans le
dégrouper n'a jamais été implémenté, desktop compris -- décision volontaire
du développeur pour éviter de compliquer la gestion de la taille/altitude
d'un groupe partiellement visible). Confirmé ensuite **empiriquement sur
l'appli mobile officielle réelle** (Android, version non consignée -- pas
seulement `tools/mobile_compat_check/`, qui teste une bibliothèque JS tierce
et ne partage pas forcément la même interface), avec le fixture synthétique
existant de `tools/mobile_compat_check/fixture/` (3 niveaux + un
`furnitureGroup`, aucune modification nécessaire) :

- Masquer un **groupe de mobilier entier** (case "Visible" dans la liste du
  mobilier) fonctionne sur mobile.
- Masquer un **niveau entier** ne fonctionne PAS sur mobile -- aucun
  équivalent au raccourci desktop `Ctrl+Maj+H` n'est accessible dans
  l'interface mobile testée.
- Masquer un élément individuel dans un groupe reste impossible partout
  (cf. recherche documentaire ci-dessus).

**Conséquence pour une éventuelle "vue mobile" allégée** (pas construite à
ce stade) : le seul levier disponible sur mobile est de placer le contenu à
masquer/afficher à la demande dans un **groupe de mobilier**, jamais de
compter sur le découpage en niveaux (Cadastre/Terrain/Bâti voisinage/
Végétation/"Emprise `<id>`" ne sont pas masquables individuellement sur
mobile aujourd'hui).

> [!NOTE]
> Deux points restent à trancher avant de coder quoi que ce soit dans cette
> direction : `viewable`/`visible` sont des propriétés du fichier, pas du
> visionneur -- un état par défaut adapté au mobile s'appliquerait aussi à
> l'ouverture desktop du même `Plan 3D.sh3d` (probablement besoin d'un
> second export dédié plutôt que de modifier le fichier canonique) ; et mur
> + toit d'un même bâtiment propriété sortent de `roofer_roof.py`/`bati.py`
> comme un seul solide multi-matériaux (une seule pièce SH3D) -- masquer le
> toit seul en gardant les murs visibles demanderait de scinder ce solide
> en deux pièces distinctes, hors de portée d'un simple attribut de
> visibilité.

## git

Dépôt publié sur GitHub (`git` via GitHub Desktop). Ne pas `init` / committer /
merger sans accord explicite de l'utilisateur. Passer par une branche + PR ;
jamais de `push` direct sur `main`, jamais `--force`.
