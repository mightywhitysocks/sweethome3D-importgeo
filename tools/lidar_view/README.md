# `lidar_view` : inspecter le nuage de points LiDAR HD brut

Outil **autonome**, sans lien avec le pipeline principal :

- aucun `import sitegeo`, aucune dependance a l'env conda `sitegeo` ;
- aucune dependance a Java / Sweet Home 3D ;
- venv separe, ses propres paquets (`requirements.txt`) ;
- ne touche jamais a `data/`, `Plan 3D.sh3d`, ni au `run.ps1` principal.

Sert a repondre a une question en amont du pipeline : **que contient
reellement le LiDAR HD** sur la parcelle, avant toute reconstruction
geometrique (prismes, toits pyramidaux, etc.) ?

## Le jeu de donnees (LiDAR HD, IGN)

Deux choses bien distinctes portent le meme nom :

- **Le nuage de points classe** (le livrable "brut") : fichiers `.laz`
  (LAZ 1.4), decoupes en dalles de 1 km x 1 km, ~10 points/m² en moyenne
  (souvent plus en zone bâtie). Chaque point a une classification IGN
  (etendue par rapport a l'ASPRS standard) : `2` sol, `3/4/5` vegetation
  basse/moyenne/haute, `6` bati, `9` eau, `17` pont, `64` sursol perenne,
  parmi d'autres. C'est la seule source qui donne la **forme reelle** d'un
  toit (pans, faitage, cheminees) plutot qu'une hauteur globale.
- **Les produits derives, rasterises** a partir de ce nuage : MNT (altitude
  du sol nu), MNS (altitude du point le plus haut : dessus des toits et de
  la canopee), MNH = MNS - MNT (hauteur du sursol). Diffuses en WMS
  `GetMap`, resolution 0.5 m.

Licence Ouverte / Etalab, pas de cle API, diffusion via la Geoplateforme IGN
(`data.geopf.fr`).

## Ce que le pipeline principal en utilise deja

| Couche | Utilisee par | Comment |
| --- | --- | --- |
| `MNT_LIDAR` | `src/terrain.py` | raster WMS 0.5 m -> maillage terrain solide |
| `MNH_LIDAR` | `src/vegetation.py` | raster WMS 0.5 m -> maxima locaux (arbres), zones (haies) |
| `MNS_LIDAR` | *(aucun script)* | cle presente dans `sitegeo.LAYERS`, jamais consommee |
| nuage de points brut (`.laz`) | *(aucun script)* | jamais telecharge ni lu |

Les batiments (`src/bati.py`) n'utilisent **pas** le LiDAR directement : ils
viennent de BD TOPO (WFS), avec une hauteur (`altitude_maximale_toit`) deja
calculee par l'IGN a partir du LiDAR, puis un toit **pyramidal simplifie**
(apex au centroide -- cf. `docs/PIPELINE.md` limitation #6). Les batiments de
la propriete ne sont, eux, que des emprises 2D "a modeliser" (limitation
#9) : c'est precisement la que le nuage de points brut a de la valeur, car
lui seul donne la vraie geometrie de toiture (pente par pan, faitage,
decrochés) plutot qu'une approximation.

Cet outil sert a **voir** ce nuage avant d'aller plus loin (reconstruction
de toit, export vers un autre format, etc. -- non traite ici).

## Utilisation

```bash
cd tools/lidar_view
python3 -m venv .venv && source .venv/bin/activate      # ou l'equivalent Windows
pip install -r requirements.txt

# 1. localiser la dalle qui couvre la parcelle (E0 N0 E1 N1 en Lambert-93,
#    a lire dans data/meta.json ou config/site.local.toml -- jamais a coder
#    en dur dans un fichier versionne)
python find_tile.py <E0> <N0> <E1> <N1>

# 2. si une URL de telechargement est trouvee : la recuperer a la main
#    (repli obligatoire si find_tile.py ne trouve rien, cf. sa docstring)

# 3. visualiser (tout le fichier, ou filtre sur le bati / une emprise)
python view_point_cloud.py DALLE.laz -o apercu.html
python view_point_cloud.py DALLE.laz --classes 6 --bbox <E0> <N0> <E1> <N1> -o bati.html
```

`apercu.html` est autonome (plotly.js embarque) : double-clic, s'ouvre dans
n'importe quel navigateur, sans connexion.

## Limites connues

- **`find_tile.py` a ete teste en conditions reelles** (bbox de test sur un
  lieu public, hors parcelle du projet) : `GetCapabilities` sur
  `data.geopf.fr` repond bien, et la decouverte dynamique par nom trouve
  la couche du nuage brut, `IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle` (parmi
  d'autres couches candidates -- MNT/MNS/MNH, metadata -- que le filtre
  `LIDAR`/`DALLE` remonte aussi et qui restent affichees a titre
  informatif). Ses entites exposent bien un champ `url` : lien direct vers
  la dalle `.copc.laz`, plus `name` (identifiant de dalle) et
  `name_download`. `view_point_cloud.py` a charge sans erreur une dalle
  reelle telechargee via cette URL. Le seul ajustement necessaire suite a
  ce test : `find_tile.py` interroge plusieurs couches candidates en
  sequence, et une erreur reseau transitoire sur l'une d'elles ne doit pas
  faire perdre les reponses deja obtenues des autres -- desormais geree
  (couche ignoree avec un message, la boucle continue). Repli toujours
  disponible si le catalogue venait a changer : telechargement manuel
  depuis la page du jeu de donnees (onglet Telechargement).
- **`view_point_cloud.py` est teste** (nuage synthetique : sol + toit a
  deux pans + arbre ; et une dalle LiDAR HD reelle telechargee via
  `find_tile.py`) et fonctionne correctement (filtrage bbox/classes,
  sous-echantillonnage, export HTML).
- Aucune coordonnee, commune, section ni numero de parcelle n'est ecrite
  dans ces fichiers : a passer uniquement en argument de ligne de commande,
  lu depuis `data/` ou `config/site.local.toml` (tous deux git-ignored).
