# Exploration du socle : rebaser sur l'existant plutôt que du développement maison

Objectif de cette note : évaluer si des projets IGN ou de l'écosystème LiDAR
open source peuvent remplacer du code maison du pipeline, pour réduire la
maintenance à long terme (suite à la bascule `roof_lidar.py` -> `roofer`).
Pistes évaluées : Potree/point-server/PointsTools (viewer derrière
visionneuse-lidarhd.ign.fr), cartes-ign-app, lidar-prod, myria3d, puis
approfondissement ciblé sur `ign-pdal-tools`, un remplaçant pour
`vegetation.py`, et Entwine/Potree upstream comme outil de QC.

**Conclusion générale : aucune des pistes ne remplace de code existant.** Le
socle actuel (LiDAR HD déjà classé à la source + `roofer` pour la géométrie +
`gdal_contour` pour les courbes) est déjà l'assemblage pertinent compte tenu
de l'échelle du projet (une parcelle, pas un jeu de données massif) et de la
contrainte d'environnement (venv pip Linux, pas de sudo garanti, pas de
conda côté session distante).

## Constat transverse : la classification LiDAR n'est pas un problème ouvert

`sitegeo.lidar_points_l93(classification=6)` filtre directement le champ
`classification` LAS des dalles LiDAR HD publiques. Ces dalles sont déjà
classifiées par la chaîne de production IGN (règles TerraScan + `myria3d` +
`lidar-prod` + arbitrage humain résiduel, cf. sources ci-dessous) *avant*
distribution sur le Géoplateforme. Conséquence : `myria3d` et `lidar-prod`
répondent à un problème déjà résolu en amont pour ce projet — les intégrer
ajouterait une dépendance PyTorch/PyTorch-Geometric (GPU recommandé, poids
de modèle, temps d'inférence) sans gain de nomenclature (le modèle
pré-entraîné public de `myria3d` est même plus pauvre que la classification
déjà distribuée). Sources : doc produit LiDAR HD IGN
(`data.geopf.fr/annexes/ressources/documentation/DC_LiDAR_HD_1-0.pdf`),
article *3D AI in the LiDAR HD Production Process* (LIDAR Magazine, 2024).

| Piste | Verdict | Raison en une ligne |
|---|---|---|
| Potree / point-server / PointsTools (forks `LIDAR-HD-IGN`, figés depuis 2022) | Écarté | Tuilage/viewer web (EPT/Entwine), aucune extraction géométrique ni classification. |
| cartes-ign-app | Écarté | Client carto mobile MapLibre/Capacitor sans backend, rien de portable en Python. |
| lidar-prod | Écarté | Post-traitement de correction *interne à la chaîne de production IGN*, sur nuage pas encore distribué. |
| myria3d | Écarté | Classification déjà faite en amont par IGN ; modèle public plus pauvre que la nomenclature distribuée. |
| ign-pdal-tools | Écarté (voir détail) | Ne télécharge aucun nuage LiDAR depuis le Géoplateforme — hors du besoin critique. |
| Entwine/Potree upstream (QC) | Écarté (voir détail) | Dépendance PDAL native non trivialement installable dans l'environnement du pipeline, pour un gain marginal. |
| Remplaçant `vegetation.py` | Aucun trouvé | Pas d'outil mûr, maintenu et gratuit qui fasse détection d'arbres individuels + haies à cette échelle. |

## Focus 1 — `ign-pdal-tools`

Dépôt officiel IGN (`github.com/IGNF/ign-pdal-tools`), licence MIT, activement
maintenu (release `v1.18.0`). Mapping fonction par fonction avec
`src/sitegeo.py` :

| `sitegeo.py` | Couverture `ign-pdal-tools` |
|---|---|
| `lidar_tile_index` (WFS dalles LiDAR HD) | **Non couvert** — aucun équivalent. |
| `lidar_points_l93` (téléchargement HTTP LAZ + cache + filtre classification) | **Non couvert** pour le téléchargement/cache. `las_clip.las_crop` pourrait faire le clip bbox, mais seulement sur un LAZ déjà présent sur disque — pas de gain net (il faut alors installer PDAL et écrire un fichier intermédiaire au lieu d'un filtrage numpy in-memory). |
| `_cached` (cache pickle générique WFS/WMS) | Non couvert, spécifique au projet. |
| `wms_getmap` / `wms_raster` | **Couvert et amélioré** par `download_image()` : retry natif (`@retry(times=9, delay=5, factor=2)`, absent côté `sitegeo` pour le raster) + pavage GDAL automatique au-delà d'une taille max, alors que `wms_getmap` plafonne juste la résolution sans paver. |
| `wms_ortho_rgb` | Couvert pour la partie téléchargement ortho seule (sortie GeoTIFF à relire au lieu d'un `ndarray` direct). |
| `roof_color_from_ortho` | Non couvert — logique métier propre au projet. |

**Verdict chiffré** : ~40 lignes éliminables sur les ~185 lignes réseau/raster
de `sitegeo.py` (~5-6 % du fichier), concentrées sur `wms_getmap`/`wms_raster`
— un gain réel mais mineur (retry + pavage, reproductible en une dizaine de
lignes maison avec `tenacity`). Le cœur du besoin — trouver et télécharger
les dalles LiDAR HD avec cache disque indéfini (`lidar_tile_index` +
`lidar_points_l93`, ~59 lignes, la partie la plus spécifique et la plus
sensible du module) — **n'a aucun remplacement** dans `ign-pdal-tools`, qui
suppose toujours des LAZ déjà présents sur disque. Coût d'intégration : une
dépendance PDAL native (lib C++, pas un simple `pip install`), à l'opposé de
l'approche actuelle 100 % `laspy`/`numpy`. **Gain insuffisant pour justifier
le risque** — ne pas intégrer.

## Focus 2 — remplaçant pour `vegetation.py`

Fonctionnement actuel : détection d'arbres par maxima locaux (`maximum_filter`
sur le MNH WMS IGN, seuils `H_ARBRE=3.5 m`/`MIN_DIST=4.5 m`, rayon de houppier
non mesuré — dérivé du gabarit catalogue) ; haies par fermeture morphologique +
composantes connexes + squelettisation + réduction en ligne de crête
(Dijkstra), avec bifurcation haie taillée (prisme fermé) / lisière boisée
(alignement d'arbres).

Alternatives évaluées et écartées :

- **`lidR`** (R, mûr et maintenu) : son algorithme par défaut (`itd_lmf`,
  Local Maximum Filter à fenêtre variable) est **le même principe** que le
  `maximum_filter` maison — un portage n'apporterait pas de méthode
  supérieure, seulement un changement de langage.
- **`pyfor`**, **`PyCrown`** : portages Python de méthodes façon `lidR`,
  tous deux **abandonnés** (`pyfor` : dernière release 2019 ; `PyCrown` :
  dépôt archivé en lecture seule depuis octobre 2021).
- **WhiteboxTools** : `IndividualTreeDetection`/`LidarSegmentation` existent
  mais sont réservés à l'extension payante (500 $/an) — le noyau open
  source ne les inclut pas. Disqualifié sur le critère gratuit.
- **PDAL `filters.litree`** : dans le cœur PDAL, mais nécessite PDAL natif
  (pas un simple `pip install`) et fonctionne sur nuage de points brut, pas
  sur le MNH WMS déjà utilisé — changerait l'entrée du pipeline pour un gain
  incertain (sortie = `TreeID` par point, encore à post-traiter en position
  + houppier).
- **BD TOPO IGN, thème végétation** : couche "Zone de végétation" =
  polygones génériques (millésimes hétérogènes 2004-2015 selon départements),
  pas d'arbre individuel géolocalisé. Couche "Haie" (Dispositif de Suivi des
  Bocages) donne des axes linéaires nationaux mais sans hauteur/largeur
  exploitable pour un prisme 3D, et sans garantie de précision à l'échelle
  d'une parcelle. "Arbre isolé" = POI restreint aux arbres remarquables
  nommés, pas une couverture générale.
- **FRACTAL / PureForest** (IGN) : classification sémantique par point ou
  par patch 50×50 m — pas de détection d'individus, ne répondent pas au
  besoin.

**Verdict : garder le code maison, ce n'est pas une dette technique.** Aucune
option mûre, maintenue et simplement installable ne couvre le besoin exact
(détection d'arbres individuels + haies avec forme 3D exploitable pour un
rendu résidentiel). Le traitement des haies (ligne de crête + prisme) est en
outre propre au rendu Sweet Home 3D, absent par nature de toute boîte à
outils forestière professionnelle.

## Focus 3 — Entwine/Potree upstream comme outil de QC visuel

Question distincte de l'écart initial sur les forks IGN figés : les projets
d'origine (`connormanning/entwine`, `potree/potree`, tous deux mûrs et
activement maintenus, licences LGPL-2.1/BSD) auraient-ils un intérêt comme
utilitaire optionnel d'inspection visuelle du nuage LiDAR brut dans un
navigateur (en complément de `preview.py` et du rendu SunFlow) ?

- `entwine build` produit un dossier EPT statique, servable par un simple
  serveur HTTP statique + une page Potree — pas de backend applicatif requis
  une fois le build fait.
- Mais **Entwine dépend de PDAL en tant que bibliothèque C++**, installable
  officiellement via `conda-forge` ; pas de binaire statique précompilé
  documenté. Sans conda et sans sudo (contrainte de l'environnement Linux du
  pipeline), l'installation n'est pas triviale — même obstacle que pour
  `ign-pdal-tools`.
- Alternative plus légère envisagée : le format **COPC** (fichier LAZ unique
  streamable par requêtes HTTP range, sans étape de tuilage), via `untwine`
  ou `pdal writers.copc` — mais ces deux voies dépendent aussi de PDAL natif,
  donc même obstacle d'installation.
- À l'échelle du projet (une dalle par site, quelques hectares), Entwine est
  par ailleurs un outil pensé pour des jeux de données massifs
  (villes/régions) — disproportionné pour l'usage visé.

**Verdict : ne pas ajouter cet utilitaire.** Le coût d'installation (PDAL
natif, non garanti dans l'environnement de session distante) dépasse le gain
par rapport à l'existant (`preview.py` en 2D, rendu SunFlow pour le contrôle
qualité final).

## Point encore ouvert : `roof_lidar.py` / `roofer_compare.py`

Seul reliquat de développement spécifique identifié par l'audit interne :
`roof_lidar.py` (RANSAC + croissance de région + Voronoi, seuils empiriques)
est déjà hors du chemin de production (`bati.py` appelle `roofer`), mais
conservé en fichier mort avec `roofer_compare.py` pour comparaison
ponctuelle. Décision distincte de cette exploration, à trancher séparément :
purger ces deux fichiers (cohérent avec l'objectif d'arrêter le
développement spécifique), ou assumer explicitement leur rôle de filet de
comparaison avec une échéance de décision.

## Sources principales

- Doc produit LiDAR HD IGN (classification) :
  `data.geopf.fr/annexes/ressources/documentation/DC_LiDAR_HD_1-0.pdf`
- `ignf.github.io/cartes.gouv.fr-documentation/.../nuages-points-lidar-hd/`
- *3D AI in the LiDAR HD Production Process*, LIDAR Magazine, 2024
- `github.com/IGNF/myria3d`, `github.com/IGNF/lidar-prod`,
  `github.com/IGNF/ign-pdal-tools`, `github.com/IGNF/cartes-ign-app`
- `github.com/LIDAR-HD-IGN/{potree,point-server,PointsTools}` (forks figés)
- `github.com/connormanning/entwine`, `github.com/potree/potree`, `copc.io`
- `github.com/r-lidar/lidR`, `github.com/brycefrank/pyfor` (abandonné),
  `github.com/manaakiwhenua/pycrown` (archivé), `github.com/jblindsay/whitebox-tools`
- Comparatif couches végétation BD TOPO :
  `geoservices.ign.fr/sites/default/files/2021-07/Comparatif_Vegetation.pdf`
