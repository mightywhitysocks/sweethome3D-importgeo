# `lidar_view` : inspecter le nuage de points LiDAR HD brut

Outil **autonome**, sans lien avec le pipeline principal :

- aucun `import sitegeo`, aucune dépendance à l'env conda `sitegeo` ;
- aucune dépendance à Java / Sweet Home 3D ;
- venv séparé, ses propres paquets (`requirements.txt`) ;
- ne touche jamais à `data/`, `Plan 3D.sh3d`, ni au `run.ps1` principal.

Répond à une question en amont du pipeline : **que contient réellement le
LiDAR HD** sur la parcelle, avant toute reconstruction géométrique (prismes,
toits pyramidaux, etc.) ?

## Le jeu de données (LiDAR HD, IGN)

Deux choses bien distinctes portent le même nom :

| | Contenu |
|---|---|
| **Le nuage de points classé** (le livrable « brut ») | Fichiers `.laz` (LAZ 1.4), découpés en dalles de 1 km × 1 km, ~10 points/m² en moyenne (souvent plus en zone bâtie). Chaque point a une classification IGN (étendue par rapport à l'ASPRS standard) : `2` sol, `3`/`4`/`5` végétation basse/moyenne/haute, `6` bâti, `9` eau, `17` pont, `64` sursol pérenne, parmi d'autres. Seule source qui donne la **forme réelle** d'un toit (pans, faîtage, cheminées) plutôt qu'une hauteur globale. |
| **Les produits dérivés, rasterisés** à partir de ce nuage | MNT (altitude du sol nu), MNS (altitude du point le plus haut : dessus des toits et de la canopée), MNH = MNS − MNT (hauteur du sursol). Diffusés en WMS `GetMap`, résolution 0,5 m. |

Licence Ouverte / Etalab, pas de clé API, diffusion via la Géoplateforme IGN
(`data.geopf.fr`).

## Ce que le pipeline principal en utilise déjà

| Couche | Utilisée par | Comment |
|---|---|---|
| `MNT_LIDAR` | `src/terrain.py` | Raster WMS 0,5 m → maillage terrain solide. |
| `MNH_LIDAR` | `src/vegetation.py` | Raster WMS 0,5 m → maxima locaux (arbres), zones (haies). |
| `MNS_LIDAR` | *(aucun script)* | Clé présente dans `sitegeo.LAYERS`, jamais consommée. |
| Nuage de points brut (`.laz`) | *(aucun script)* | Jamais téléchargé ni lu. |

Les bâtiments (`src/bati.py`) n'utilisent **pas** le LiDAR directement : ils
viennent de BD TOPO (WFS), avec une hauteur (`altitude_maximale_toit`) déjà
calculée par l'IGN à partir du LiDAR, puis un toit **pyramidal simplifié**
(apex au centroïde, cf. `docs/PIPELINE.md` limitation #6). Les bâtiments de
la propriété ne sont, eux, que des emprises 2D « à modéliser » (limitation
#9) : c'est précisément là que le nuage de points brut a de la valeur, car
lui seul donne la vraie géométrie de toiture (pente par pan, faîtage,
décrochés) plutôt qu'une approximation.

Cet outil sert à **voir** ce nuage avant d'aller plus loin (reconstruction
de toit, export vers un autre format, etc., non traité ici).

## Utilisation

```bash
cd tools/lidar_view
python3 -m venv .venv && source .venv/bin/activate      # ou l'équivalent Windows
pip install -r requirements.txt

# 1. localiser la dalle qui couvre la parcelle (E0 N0 E1 N1 en Lambert-93,
#    à lire dans data/meta.json ou config/site.local.toml, jamais à coder
#    en dur dans un fichier versionné)
python find_tile.py <E0> <N0> <E1> <N1>

# 2. si une URL de téléchargement est trouvée : la récupérer à la main
#    (repli obligatoire si find_tile.py ne trouve rien, cf. sa docstring)

# 3. visualiser (tout le fichier, ou filtré sur le bâti / une emprise)
python view_point_cloud.py DALLE.laz -o apercu.html
python view_point_cloud.py DALLE.laz --classes 6 --bbox <E0> <N0> <E1> <N1> -o bati.html
```

`apercu.html` est autonome (plotly.js embarqué) : double-clic, s'ouvre dans
n'importe quel navigateur, sans connexion.

## Limites connues

- **`find_tile.py` a été testé en conditions réelles** (bbox de test sur un
  lieu public, hors parcelle du projet) : `GetCapabilities` sur
  `data.geopf.fr` répond bien, et la découverte dynamique par nom trouve la
  couche du nuage brut, `IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle` (parmi
  d'autres couches candidates, MNT/MNS/MNH, metadata, que le filtre
  `LIDAR`/`DALLE` remonte aussi et qui restent affichées à titre
  informatif). Ses entités exposent bien un champ `url` : lien direct vers
  la dalle `.copc.laz`, plus `name` (identifiant de dalle) et
  `name_download`. `view_point_cloud.py` a chargé sans erreur une dalle
  réelle téléchargée via cette URL.

  Le seul ajustement nécessaire suite à ce test : `find_tile.py` interroge
  plusieurs couches candidates en séquence, et une erreur réseau transitoire
  sur l'une d'elles ne doit pas faire perdre les réponses déjà obtenues des
  autres. Désormais gérée (couche ignorée avec un message, la boucle
  continue). Repli toujours disponible si le catalogue venait à changer :
  téléchargement manuel depuis la page du jeu de données (onglet
  Téléchargement).
- **`view_point_cloud.py` est testé** (nuage synthétique : sol + toit à
  deux pans + arbre ; et une dalle LiDAR HD réelle téléchargée via
  `find_tile.py`) et fonctionne correctement (filtrage bbox/classes,
  sous-échantillonnage, export HTML).
- Aucune coordonnée, commune, section ni numéro de parcelle n'est écrite
  dans ces fichiers : à passer uniquement en argument de ligne de commande,
  lu depuis `data/` ou `config/site.local.toml` (tous deux git-ignored).
