# Parcelle -> Sweet Home 3D

Génère un **plan 3D géoréférencé d'une parcelle cadastrale française** pour
[Sweet Home 3D](https://www.sweethome3d.com/), à partir des données publiques
**IGN Géoplateforme** :

- **PCI Express** (cadastre) : limites et numéros de parcelles ;
- **Ortho HR** : photo aérienne 20 cm/px, drapée sur le terrain ;
- **LIDAR HD** : MNT (relief) et MNH (hauteur de végétation) ;
- **BD TOPO** : emprises et hauteurs des bâtiments.

Résultat : `Plan 3D.sh3d`, double-cliquable, avec 5 calques (Cadastre / Terrain /
Bâti voisinage / Bâti propriété / Végétation) — toit + mur multi-pans de
chaque bâtiment reconstruits par `roofer` (LiDAR HD IGN), repli sur un toit
pyramidal simple si non exploitable.

La parcelle cible **n'est pas codée dans le dépôt** : elle se règle dans
`config/site.local.toml` (git-ignored).

## Prérequis

Le pipeline de **génération** (`phase1_cadastre` -> ... -> `build_home`)
suppose désormais un **environnement Linux/macOS** : `bati.py` appelle
l'outil externe `roofer` (toit multi-pans), qui n'a pas de build Windows
officiel (cf. CLAUDE.md section Environnement). Sans lui, `bati.py` se
replie silencieusement sur un toit pyramidal simple pour tous les bâtiments,
sans planter — donc sans avertissement visible si vous ne le remarquez pas.
Trois façons d'obtenir un vrai toit multi-pans, au choix :

1. **Une machine Linux/macOS déjà là** (ou WSL2/Docker) : `./run.sh`, un
   venv pip (`config/requirements-venv.txt`) + `roofer` installé (script
   officiel du dépôt `roofer`, licence GPLv3, cf. CLAUDE.md) +
   `gdal-bin` (apt) / `gdal` (Homebrew) pour `courbes.py`.
2. **Aucune machine Linux/macOS disponible** : générer à la demande via
   GitHub Actions (voir « Génération à la demande » ci-dessous) — un runner
   Linux éphémère fait tout le travail, rien à installer localement.
3. **Windows + PowerShell + Anaconda/Miniconda** (`.\run.ps1`) : suffit pour
   **ouvrir/rendre** `Plan 3D.sh3d` dans l'application Sweet Home 3D native,
   mais pas pour la génération avec toit multi-pans (cf. ci-dessus).

Dans tous les cas : un **JDK** (`java` et `javac` sur le `PATH`), p.ex.
Oracle JDK 21 (assemblage/relecture du `.sh3d`, rendu photo headless), et
**Sweet Home 3D** installé (le pipeline lit son `SweetHome3D.jar`).

**Optionnel** : `arbaro_cmd.jar` (variété des arbres, silhouettes conifère/
feuillu/arbuste au lieu d'un gabarit unique répété, cf. issue #82) — aucun
binaire officiel Linux publié, à construire depuis les sources (`git clone
https://github.com/wdiestel/arbaro`, licence GPL-2, puis `javac`/`jar`, cf.
`Dockerfile` pour la séquence exacte), chemin renseigné dans
`[tools].arbaro_jar` (`config/site.local.toml`). Absent : `vegetation.py` se
replie sur le gabarit d'arbre unique historique, sans planter. Déjà construit
automatiquement dans l'image CI (génération à la demande via GitHub Actions,
ci-dessous).

**Optionnel** : **Node.js** (`node` sur le `PATH`) pour `verif.py
--mobile-compat` (vérifie que `Plan 3D.sh3d` se charge sans erreur dans le
vrai moteur JS partagé par l'appli mobile Sweet Home 3D et Sweet Home 3D
Online — cf. `tools/mobile_compat_check/`, `npm install` dans ce dossier au
préalable). Absent : contrôle ignoré, sans planter.

### Génération à la demande, sans machine Linux/macOS locale (GitHub Actions)

Ce dépôt est un **template GitHub**. Pour générer sans rien installer
localement :

1. Bouton **Use this template** sur ce dépôt -> créer votre copie en
   **Private** (important : voir mise en garde ci-dessous).
2. Dans votre copie, `Settings → Secrets and variables → Actions` : créer le
   secret `SITE_LOCAL_TOML` = contenu d'un `site.local.toml` (comme
   `config/site.example.toml`, **sans** section `[tools]` — elle est
   ajoutée automatiquement par le workflow).
3. Onglet **Actions** : lancer une fois *Construire l'image CI*
   (`build-image.yml`), puis *Génération* (`generation.yml`) à chaque fois
   que vous voulez un plan.
4. Télécharger l'artefact `Plan 3D` depuis la page du run, en extraire
   `Plan 3D.sh3d`, l'ouvrir en local dans Sweet Home 3D (Windows/macOS/Linux).

**Mise en garde confidentialité** : ne créez ce secret et ne déclenchez ce
workflow que dans une copie **privée** — sur un dépôt public, logs de run et
artefacts sont visibles par n'importe quel compte GitHub, pas seulement les
collaborateurs. Même en privé, la sortie normale de `phase1_cadastre.py`
affiche en clair, dans les logs, la section cadastrale et les numéros de
parcelle — pensez à réduire la rétention par défaut
(`Settings → Actions → General → Artifact and log retention`, quelques jours
suffisent) et à ne jamais ajouter de collaborateur externe à une copie qui a
déjà tourné sans d'abord évaluer l'historique des runs (il resterait
visible pour ce nouveau collaborateur).

## Démarrage

Windows (`.\run.ps1`, ouverture/rendu uniquement — cf. Prérequis) :

```powershell
# 1. crée l'env conda `sitegeo` et un config/site.local.toml vierge, puis s'arrête
.\run.ps1

# 2. éditez config/site.local.toml : code INSEE, section, numéros de parcelles

# 3. lance le pipeline complet (menu interactif : Entree = toutes les etapes)
.\run.ps1

# 4. double-cliquez Plan 3D.sh3d
```

Linux/macOS (`./run.sh`, génération complète avec toit multi-pans) :

```bash
# 1. crée .venv/ et un config/site.local.toml vierge, puis s'arrête
./run.sh

# 2. éditez config/site.local.toml : code INSEE, section, numéros de parcelles

# 3. lance le pipeline complet (menu interactif : Entree = toutes les etapes)
./run.sh

# 4. ouvrez Plan 3D.sh3d dans Sweet Home 3D
```

Sans argument, `run.ps1`/`run.sh` proposent un menu (étapes à lancer, et choix
du site si plusieurs configs existent). En cas d'échec d'une étape, ils
proposent de réessayer / sauter / arrêter.

Autres usages :

```powershell
.\run.ps1 verif                 # contrôle seul (parcelles live, calage, topologie), sans menu
.\run.ps1 terrain bati          # certaines étapes seulement, sans menu
.\run.ps1 -Site autre-site.toml # utiliser une autre config sans passer par le menu
.\run.ps1 -Fresh                # recréer l'env conda
.\run.ps1 -NonInteractive       # jamais de prompt (toutes les étapes, site.local.toml,
                                 # arrêt immédiat si une étape échoue) - pour un script/hook
```

```bash
./run.sh verif                    # contrôle seul, sans menu
./run.sh terrain bati             # certaines étapes seulement, sans menu
./run.sh --site autre-site.toml   # utiliser une autre config sans passer par le menu
./run.sh --fresh                  # recréer .venv/
./run.sh --non-interactive        # jamais de prompt - pour un script/hook
```

Sans `run.ps1`/`run.sh` : `conda activate sitegeo` puis `python src\<script>.py`
(Windows), ou `.venv/bin/python src/<script>.py` (Linux/macOS). **Ne pas**
utiliser `py` (Python système) ni `conda run`.

## Arborescence

```
├── run.ps1              point d'entrée Windows (ouverture/rendu)
├── run.sh               point d'entrée Linux/macOS (génération complète)
├── Dockerfile            image CI (toolchain figé), publiée par build-image.yml
├── .github/workflows/
│   ├── build-image.yml  construit + publie l'image CI sur ghcr.io
│   └── generation.yml   lance le pipeline à la demande dans cette image
├── config/
│   ├── environment.yml       env conda `sitegeo` (Windows)
│   ├── requirements-venv.txt venv pip (Linux/macOS/Docker)
│   ├── site.example.toml     gabarit de config
│   └── site.local.toml       VOTRE parcelle (git-ignored, créé au 1er lancement)
├── src/                 le pipeline Python
├── java/                Conv.java (assemble le .sh3d) + RenderPhoto.java (rendu photo)
├── assets/              gabarits stables (home_template.xml, tree.obj/.mtl,
│                        arbaro_species/*.xml pour la variété des arbres)
├── docs/PIPELINE.md     détail de la génération du .sh3d + limitations
├── data/                toutes les sorties (git-ignored)
└── README.md  CLAUDE.md  LICENSE  NOTICE
```

| Script | Rôle |
|--------|------|
| `src/sitegeo.py` | module commun : chemins, config, accès IGN, `terrain_z_at`, primitives PyVista, écriture OBJ/MTL |
| `src/phase1_cadastre.py` | fond ortho + cadastre + parcelles ; **définit le repère plan** (`data/meta.json`) |
| `src/terrain.py` | terrain 3D solide (PyVista) + ortho drapée + grille d'ancrage |
| `src/bati.py` | BD TOPO -> bâtiments voisinage (prisme + toit) ; emprises 2D de la propriété |
| `src/vegetation.py` | arbres (maxima MNH) + haies taillées éventuelles |
| `src/courbes.py` | courbes de niveau 1 m (`gdal_contour`) |
| `src/build_home.py` | assemble `Plan 3D.sh3d` hors-ligne (voir `docs/PIPELINE.md`) |
| `src/verif.py` | contrôle lecture seule (`--overlay` : parcelles sur l'ortho ; `--render` : rendu photo headless du `.sh3d` ; `--mobile-compat` : compatibilité appli mobile / Sweet Home 3D Online, cf. `tools/mobile_compat_check/`) |
| `src/preview.py` | aperçus photo depuis chaque bâtiment de la propriété + vue d'ensemble (`data/verif/preview_*.png`), via `python src/preview.py [larg haut [low\|high]]` |
| `src/orbit_render.py` | panoramique circulaire MP4 (caméra fixe sur la parcelle propriété, 360° de yaw, `data/verif/orbit.mp4`), option du job CI *Rendu* — via `python src/orbit_render.py [larg haut [low\|high] [images] [secondes]]` (cf. `docs/PIPELINE.md`) |

Ordre : `phase1_cadastre -> terrain -> bati -> vegetation -> courbes -> build_home`.

## Repère plan Sweet Home 3D

Origine = coin **nord-ouest** de la bounding box (parcelles + marge). Axes
**X = est, Y = sud**, unité **centimètre**. Altitude `z = altitude_NGF - z_min`.
Les coordonnées Lambert-93 de l'origine sont calculées en Phase 1 et écrites dans
`data/meta.json` (git-ignored), réutilisées telles quelles par toutes les étapes.

## Licence

Code sous licence **MIT** (voir `LICENSE`). Ressources tierces et licences des
données : voir `NOTICE`. Les données IGN Géoplateforme sont diffusées sous
**Licence Ouverte / Etalab 2.0**.
