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
suppose désormais un **environnement Linux** : `bati.py` appelle l'outil
externe `roofer` (toit multi-pans), qui n'a pas de build Windows officiel
(cf. CLAUDE.md section Environnement). Sans lui, `bati.py` se replie
silencieusement sur un toit pyramidal simple pour tous les bâtiments, sans
planter — donc sans avertissement visible si vous ne le remarquez pas.

- **Windows + PowerShell + Anaconda/Miniconda** : sert à **ouvrir/rendre**
  `Plan 3D.sh3d` dans l'application Sweet Home 3D native, pas à lancer le
  pipeline de génération complet.
- **Linux (ou WSL2/Docker)** + un venv pip (`config/requirements-venv.txt`)
  + `roofer` installé (script officiel du dépôt `roofer`, licence GPLv3, cf.
  CLAUDE.md) : pour lancer le pipeline de génération avec toit multi-pans.
- Un **JDK** (`java` et `javac` sur le `PATH`), p.ex. Oracle JDK 21 — requis
  dans les deux cas (assemblage/relecture du `.sh3d`, rendu photo headless).
- **Sweet Home 3D** installé (le pipeline lit son `SweetHome3D.jar`).

## Démarrage

```powershell
# 1. crée l'env conda `sitegeo` et un config/site.local.toml vierge, puis s'arrête
.\run.ps1

# 2. éditez config/site.local.toml : code INSEE, section, numéros de parcelles

# 3. lance le pipeline complet (menu interactif : Entree = toutes les etapes)
.\run.ps1

# 4. double-cliquez Plan 3D.sh3d
```

Sans argument, `run.ps1` propose un menu (étapes à lancer, et choix du site si
plusieurs `config\*.toml` existent). En cas d'échec d'une étape, il propose de
réessayer / sauter / arrêter.

Autres usages :

```powershell
.\run.ps1 verif                 # contrôle seul (parcelles live, calage, topologie), sans menu
.\run.ps1 terrain bati          # certaines étapes seulement, sans menu
.\run.ps1 -Site autre-site.toml # utiliser une autre config sans passer par le menu
.\run.ps1 -Fresh                # recréer l'env conda
.\run.ps1 -NonInteractive       # jamais de prompt (toutes les étapes, site.local.toml,
                                 # arrêt immédiat si une étape échoue) - pour un script/hook
```

Sans `run.ps1` : `conda activate sitegeo` puis `python src\<script>.py`.
**Ne pas** utiliser `py` (Python système) ni `conda run`.

## Arborescence

```
├── run.ps1              point d'entrée
├── config/
│   ├── environment.yml  env conda `sitegeo`
│   ├── site.example.toml  gabarit de config
│   └── site.local.toml  VOTRE parcelle (git-ignored, créé au 1er lancement)
├── src/                 le pipeline Python
├── java/                Conv.java (assemble le .sh3d) + RenderPhoto.java (rendu photo)
├── assets/              gabarits stables (home_template.xml, tree.obj/.mtl)
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
| `src/verif.py` | contrôle lecture seule (`--overlay` : parcelles sur l'ortho ; `--render` : rendu photo headless du `.sh3d`) |
| `src/preview.py` | aperçus photo depuis chaque bâtiment de la propriété + vue d'ensemble (`data/verif/preview_*.png`), via `python src/preview.py [larg haut [low\|high]]` |

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
