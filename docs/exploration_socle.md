# Exploration du socle : rebaser sur l'existant plutôt que du développement maison

Objectif de cette note : évaluer si des projets IGN ou de l'écosystème LiDAR
open source peuvent remplacer du code maison du pipeline, pour réduire la
maintenance à long terme (suite à la bascule `roof_lidar.py` -> `roofer`).
Pistes évaluées : Potree/point-server/PointsTools (viewer derrière
visionneuse-lidarhd.ign.fr), cartes-ign-app, lidar-prod, myria3d, puis
approfondissement ciblé sur `ign-pdal-tools`, un remplaçant pour
`vegetation.py`, Entwine/Potree upstream comme outil de QC, puis, sur les
zones de code maison restant hors LiDAR/végétation : écrire le `.sh3d` sans
bridge Java, un client cadastre officiel, et un générateur de terrain 3D
existant.

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
| `sh3d.py` / `python-javaobj` (écrire le `.sh3d` sans JVM) | Écarté (voir détail) | Le premier ne fait que lire ; le second sait écrire du Java sérialisé générique mais pas le graphe d'objets `Home` réel. |
| Client Python officiel pour le cadastre (`phase1_cadastre.py`) | Aucun trouvé | Aucun wrapper maintenu au-delà du WFS brut ; la doc officielle recommande elle-même `requests` nu. |
| Génération terrain (`terrain.py`) par un outil DEM->mesh existant | Écarté (voir détail) | Outils trouvés visent l'impression 3D ou le tuilage massif, aucun ne fait le drapage UV + volume fermé dans un repère plan cm arbitraire. |

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

## Focus 4 — écrire le `.sh3d` sans bridge Java (`build_home.py` / `java/Conv.java`)

Le point dur le plus lourd du pipeline (cf. `docs/PIPELINE.md`) : le loader
Sweet Home 3D exige une entrée `Home` **sérialisée au format binaire Java**
(`ObjectOutputStream`), que Python ne sait pas produire nativement — d'où le
détour actuel par une JVM (`javac` + `java` sur `Conv.java`, qui appelle les
vraies classes `com.eteks.sweethome3d.io.HomeFileRecorder` du `.jar`
propriétaire). Question : existe-t-il un moyen de produire ce flux binaire
directement en Python, sans JVM ?

- **`Salamek/sh3d.py`** (PyPI `sh3d.py`, LGPL-3.0, actif — dernière version
  0.2.2 en juin 2025) : parseur Python pur du format `.sh3d`, capable de
  décoder **aussi bien** `Home.xml` que l'entrée binaire `Home` (options
  `HomeSource.XML` / `HomeSource.JavaObject`). Confirme que le format binaire
  est décodable hors JVM. Mais c'est un lecteur seul — aucune fonction
  d'écriture n'est exposée ni documentée.
- **`tcalmant/python-javaobj`** (Apache-2.0, actif, 84 étoiles) : la brique
  générique dont dépend probablement ce type de lecteur — son implémentation
  `v3` sait à la fois lire **et écrire** (`dump()`/`dumps()`) le format
  Java Object Serialization en pur Python. Ce n'est donc pas la sérialisation
  binaire elle-même qui bloque : l'obstacle est ailleurs.
- **L'obstacle réel** : `python-javaobj` sérialise des objets Python déjà
  construits pour ressembler à des beans Java (mêmes champs, mêmes types) —
  il ne connaît rien de la classe `com.eteks.sweethome3d.model.Home` ni de
  ses dizaines de classes associées (`Wall`, `Room`, `HomePieceOfFurniture`,
  `Level`, `Camera`, …), dont beaucoup implémentent des méthodes
  `writeObject`/`readObject` personnalisées (pas la sérialisation par défaut
  champ-à-champ) pour gérer la compatibilité de version entre releases de
  Sweet Home 3D. Reproduire ça à la main reviendrait à ré-implémenter et
  maintenir, en Python, un décalque du modèle de données interne de Sweet
  Home 3D — recalé à chaque montée de version de l'appli — soit une dette
  largement supérieure au bridge Java actuel, qui lui délègue cette
  correctness aux vraies classes upstream quelle que soit la version du
  `.jar` détectée.

**Verdict : ne pas remplacer le bridge Java.** Le fondement technique du
blocage (sérialisation Java binaire) est contournable en pur Python, mais le
vrai coût — modéliser fidèlement et maintenir le graphe de classes Sweet
Home 3D — resterait entier et deviendrait une charge de maintenance propre au
projet, à l'exact inverse de l'objectif de cette exploration.

## Focus 5 — client Python pour le cadastre (`phase1_cadastre.py`)

`phase1_cadastre.py` interroge directement le WFS IGN via
`cg.parcels_l93()` (requêtes HTTP maison). Recherche d'un client officiel ou
communautaire mûr qui réduirait ce code :

- **`IGNF/apicarto`** (dépôt GitHub officiel) : c'est l'implémentation de
  l'API elle-même (JavaScript, service derrière `apicarto.ign.fr`), pas une
  bibliothèque cliente à installer côté consommateur.
- **Guide officiel `data.gouv.fr`** ("Manipuler les données du cadastre") :
  recommande explicitement `requests` pour des appels ponctuels et `httpx`
  asynchrone pour du batch — aucun client Python dédié n'est mentionné ni
  requis.
- Aucun autre wrapper Python maintenu trouvé pour l'API Carto module
  cadastre (les projets Python "cadastre" identifiés sur GitHub visent
  d'autres pays — Russie, Italie, Espagne — ou d'autres formats, ex. export
  OSM du Plan Cadastral Informatisé, hors sujet ici).

**Verdict : garder le code maison.** L'écosystème officiel recommande
lui-même l'appel HTTP direct ; il n'y a pas de dette à réduire ici, la
fonction `parcels_l93()` fait déjà ce que la documentation IGN suggère de
faire.

## Focus 6 — génération du terrain (`terrain.py`) par un outil DEM->mesh existant

`terrain.py` transforme un MNT LIDAR HD en volume fermé texturé (grille
régulière -> `cg.grid_surface` + `cg.solidify` PyVista, UV drapées sur
l'ortho, écrit en OBJ dans le repère plan cm du projet). Outils candidats
identifiés pour remplacer cette étape :

| Outil | Écarté pourquoi |
|---|---|
| `tin-terrain` (HERE Maps) | Pensé pour du tuilage de terrain à l'échelle d'un territoire (sorties tuile par tuile, format `quantized-mesh`) ; pas de notion de volume fermé ni de drapage UV sur une orthophoto propre au projet. |
| `TouchTerrain`, `dem2stl`, `phstl`, DEMto3D (QGIS) | Toute la famille "impression 3D" : sortie STL non texturée, souvent non fermée dans le sens attendu ici (fermeture pour l'impression, pas pour un rendu texturé), aucune gestion de repère plan local en cm. |
| `DTM2MESH` | Portage DTM -> Collada via OpenCV, mais projet isolé/peu maintenu, sans drapage UV sur une ortho externe ni sortie OBJ directe. |

Aucun de ces outils ne couvre le vrai besoin : un maillage **dans le repère
plan cm propre à ce projet** (pas WGS84/Web Mercator), avec **drapage UV**
exact sur l'ortho IGN déjà téléchargée par `phase1_cadastre.py`, en **volume
fermé** utilisable tel quel par le loader OBJ de Sweet Home 3D. C'est un
besoin de glue spécifique au pipeline, pas un problème géométrique générique
— le cœur géométrique (`grid_surface`/`solidify`, une quinzaine de lignes
PyVista) est déjà minimal.

**Verdict : garder le code maison**, même conclusion que pour `vegetation.py` :
pas de dette technique à réduire, aucun outil mûr ne fait ce drapage
spécifique.

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
- `pypi.org/project/sh3d.py/`, `github.com/Salamek/sh3d.py` (lecteur `.sh3d`)
- `github.com/tcalmant/python-javaobj` (sérialisation Java générique lire/écrire)
- `github.com/IGNF/apicarto`, guide `data.gouv.fr` "Manipuler les données du
  cadastre" (`guides.data.gouv.fr/guides/reutiliser-des-donnees/autour-du-cadastre`)
- `github.com/heremaps/tin-terrain`,
  `github.com/ChHarding/TouchTerrain_for_CAGEO`, `github.com/cvr/dem2stl`,
  `github.com/anoved/phstl`, `github.com/jonathanlurie/DTM2MESH`
