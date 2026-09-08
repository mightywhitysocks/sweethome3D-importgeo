# Journal technique : historique des investigations

Ce fichier porte le détail chronologique (essais, mesures, sessions
successives, pistes rejetées) qui alourdissait autrefois la section
`## Points durs` de `CLAUDE.md`. `CLAUDE.md` ne garde que l'état courant —
ce qu'il faut savoir *maintenant* pour travailler correctement sur le
pipeline ; ce fichier garde le *pourquoi historique* pour qui veut
comprendre comment on y est arrivé, ou éviter de rouvrir une piste déjà
explorée et écartée.

**Ce fichier n'est pas chargé par défaut** dans le contexte d'une session
Claude Code (contrairement à `CLAUDE.md`) — à consulter à la demande. Mêmes
règles de confidentialité que le reste du dépôt (cf. `CLAUDE.md`
§Confidentialité) : rien ici ne doit jamais nommer une commune, un code
INSEE, une section ou un numéro de parcelle.

## Plan 2D intérieur (validation)

Mécanisme (`interieur_init.py`/`fusion_interieur.py`, cf. `CLAUDE.md` §Points
durs pour la conception actuelle) **validé de bout en bout** dans une session
Claude Code distante (JDK + mirror `SweetHome3D.jar` du dépôt) sur une
fixture synthétique : 2 bâtiments (l'un multi-ring), murs joints
(`wallAtStart`) et meuble de catalogue ajoutés via l'API Java (simulant une
édition native réelle), y compris un cas de fichiers `interieur/*.sh3d`
dupliqués (ids source identiques) -- fusion puis relecture via
`HomeFileRecorder` : tous les niveaux, murs et meubles résolus au bon niveau
sans collision, contenu du meuble catalogue correctement copié/résolu.
**Pas encore validé sur un site réel** (pas de site configuré dans cette
session, confidentialité) : à reprendre au prochain run complet avec un vrai
bâtiment édité dans l'appli desktop.

### Repère absolu -> repère local par bâtiment (défaut constaté à l'usage, corrigé)

Défaut remonté par l'utilisateur en ouvrant un `interieur/<id>.sh3d` généré
avec le repère absolu d'origine : la pièce-repère de l'emprise n'apparaissait
pas dans le plan 2D à l'ouverture (visible en 3D seulement, un clic-droit
"Sélectionner l'objet" en 3D la faisait apparaître en 2D avec bord/nom/
surface). Cause réelle, identifiée en creusant plutôt qu'en corrigeant à
l'aveugle une hypothèse de transparence de `floorColor` d'abord envisagée :
le bâtiment était positionné à des dizaines de mètres de l'origine du
fichier (repère absolu du site), largement hors du cadrage 2D par défaut à
l'ouverture -- la pièce existait mais n'était simplement pas dans la zone
visible tant qu'on n'avait pas zoomé/recentré (ou sélectionné l'objet, qui
recentre la vue). Second défaut, lié : le bâtiment apparaissait aussi en
biais par rapport à la grille du plan 2D (repère absolu orienté sur la trame
Lambert-93/site, sans rapport avec l'orientation réelle du bâtiment),
gênant pour tracer des murs (magnétisme/grille peu utile sur un bâtiment en
biais).

Corrigé par un repère LOCAL par bâtiment (`interieur_init.py::_local_frame`,
rectangle englobant minimal via `shapely.oriented_envelope`, cf. `CLAUDE.md`
§Points durs pour la conception retenue). Schéma XML des éléments à
transformer (`<point>` imbriqué, `xStart`/`yStart`/`xEnd`/`yEnd`, `x`/`y`,
`angle`/`areaAngle`/`nameAngle` en radians) **vérifié empiriquement** avant
d'écrire `fusion_interieur.py::_apply_transform`, plutôt que supposé -- même
méthode que le reste de ce mécanisme : petit programme Java jetable (JDK +
`SweetHome3D.jar` déjà présents dans la session), export XML réel via
`HomeXMLExporter` d'un `Home` construit avec un `Polyline`/`Label`/`Room`
d'angles connus (ex. `angle='0.7853982'` pour un angle réglé à 45°,
confirmant l'unité radian).

**Validé de bout en bout** sur une fixture synthétique dans cette session :
une emprise rectangulaire tournée de 25° par rapport aux axes absolus ->
`_local_frame` produit un contour local axé sur la grille (proche de
l'origine) ; un mur, un meuble de catalogue (avec un `angle` local non nul),
une `<polyline>`, un `<label>` (avec `angle`) et une `<dimensionLine>`
ajoutés dans le fichier intérieur (simulant une édition native réelle) ;
fusion dans un `Plan 3D.sh3d` minimal puis relecture du résultat via
`HomeFileRecorder` -- coordonnées et angles absolus reconstruits comparés au
calcul direct de la transformation inverse (recalculée indépendamment en
Python) : concordance exacte aux arrondis près, pour chaque type d'élément.
Vérifié aussi : la pièce-repère de l'emprise est bien absente du fichier
fusionné, et un `interieur/<id>.sh3d` sans `interieur/<id>.transform.json`
(simulant un fichier créé par une version antérieure du script, en repère
absolu) fusionne toujours correctement (repli sur la transformation
identité, coordonnées/angles inchangés).

## Dépendance externe : `roofer`

### Bug confirmé (roofer 1.1.0-beta.1), n'affecte QUE `roofer_compare.py`

(attributs CityJSON `rf_h_*`, pas la géométrie du `Solid` que consomme
`roofer_roof.py`) : `rf_h_ground` est exposé relatif à
`transform.translate[2]` (translation Z interne du CityJSON, pour la
compression des coordonnées), PAS en NGF absolu -- contrairement à
`rf_h_roof_min/max/50p/70p`, qui eux le sont bien. Confirmé empiriquement en
comparant le nuage rogné par roofer lui-même (`--crop-output`) : le Z réel
des points sol retombe à quelques cm de
`rf_h_ground + transform.translate[2]`. Écarté : bug connu "garbage value
avec plusieurs pointclouds en entrée" (déjà corrigé en v1.0.0-beta.6, testé
ici avec 1 seule dalle -- résultat identique). `rf_h_roof_ridge` (hauteur
relative au sol) était déjà correct tel quel ; seul `rf_h_ground` manquait
ce recalage. Correctif appliqué dans `_roofer_metrics` (`roofer_compare.py`) :
lire `transform.translate[2]` sur la ligne de métadonnées du `.city.jsonl`
et l'ajouter à `rf_h_ground`.

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

### Couverture LiDAR/BD TOPO incomplète en entrée de `roofer` (issues #22, #23)

Diagnostic d'origine (comparaison emprise BD TOPO vs union des pans
reconstruits, 18 bâtiments) : écarts systémiques, jusqu'à 55 % de l'emprise
non couverte sur certains bâtiments. Deux causes racines, alignées sur
l'exemple officiel IGN
[`ignfab/roofer-with-ignf-datasets`](https://github.com/ignfab/roofer-with-ignf-datasets)
(Docker-first, PDAL) et sur `roofer --help-all` -- corrigées en préparant
l'entrée dans un format que `roofer` sait déjà consommer (paramètres CLI
existants), jamais par une reconstruction géométrique ou un calcul
d'altitude côté projet : cf. `CLAUDE.md` pour le mécanisme retenu
(`_remap67`, attributs `--h-terrain-attribute`/`--h-roof-attribute`).

Validé mécaniquement (tests unitaires ciblés : remap sur une dalle LAS
synthétique avec points classés 67, cascade `_complete_altitudes` sur les 4
combinaisons de valeurs manquantes, écriture GPKG des deux colonnes) dans
une session Claude Code distante. **Pas encore revalidé sur données
réelles** (pas de site configuré dans cette session, confidentialité) :
reprendre la comparaison emprise BD TOPO vs pans reconstruits sur le même
jeu de 18 bâtiments qui a servi au diagnostic d'origine, lors d'un prochain
run complet sur le site.

### Un polygone BD TOPO peut englober une structure du camp opposé (diagnostic)

Constaté sur le site réel : un bâtiment classé `"propriete"` avait 33,7 % de
son aire qui débordait en réalité sur une parcelle voisine (points LiDAR
classés bâtiment confirmés dans la zone de débordement, aucun autre polygone
BD TOPO ne couvrant cette zone -- ce n'est pas un défaut de la règle de
classification par aire majoritaire, mais une fusion du polygone source
lui-même par la vectorisation automatique IGN à grande échelle) ;
symétriquement, un bâtiment classé `"voisinage"` avait 26 % de son aire qui
débordait sur la parcelle propriété. Sans correction, ce polygone gonflé se
propage tel quel à toute la chaîne : l'empreinte donnée à `roofer`
(reconstruction 3D qui semble alors "fusionner" les deux structures),
`bati_propriete.obj`/`bati_voisinage.obj`, et la pièce visible
"Emprise `<id>`" (aire gonflée). Fix décrit dans `CLAUDE.md` (intersection/
différence avec `prop_zone` dans `bati.py`).

Réserve honnête, toujours d'actualité : ce fix corrige à coup sûr
l'emprise/l'aire (calcul Python déterministe) et très probablement
l'essentiel de la fusion visuelle du toit, mais rien ne garantit à 100 % le
comportement interne de `roofer` (boîte noire externe, GPLv3) pour
l'ajustement des pans de toit tout près de cette nouvelle limite.

### Décision actée (issue #25) : `roof_lidar.py`/`roofer_compare.py` restent dans le dépôt

Comme filet de comparaison, pas de purge pour l'instant. Les deux fixes de
couverture `roofer` ci-dessus sont désormais appliqués (remap classe 67,
attributs d'altitude), mais -- comme noté ci-dessus -- pas encore revalidés
sur données réelles faute de site configuré dans la session qui les a
écrits. Tant que cette revalidation (même jeu de 18 bâtiments que le
diagnostic d'origine) n'a pas eu lieu, purger le filet de comparaison
serait prématuré : revisiter cette décision une fois la revalidation faite.

### Investigué et écarté pour l'instant (issue #24) : crop LiDAR streamé (COPC)

En remplacement du téléchargement de dalle entière. Les dalles LiDAR HD IGN
sont bien diffusées au format COPC (`.copc.laz`, confirmé en inspectant
`ignfab/roofer-with-ignf-datasets` : `readers.copc` PDAL ciblé sur la même
colonne `url` que celle que `cg.lidar_tile_index` lit déjà) -- un crop
spatial est donc structurellement possible côté serveur. Mais :

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

**Décision : ne pas engager ce travail maintenant.** À reconsidérer
seulement si les erreurs réseau redeviennent un blocage récurrent réel (pas
seulement théorique) en usage normal du pipeline.

## Dépendance externe optionnelle : `arbaro` (variété des arbres)

### Bug SweetHome3D confirmé sur données réelles (run CI `generation.yml` #16), corrigé

`HomeContentContext.lookupContent` (bibliothèque SweetHome3D, appelée par
`HomeXMLHandler`/`Conv.java` lors de la conversion `Home.xml` -> `.sh3d`)
cache le `Content` résolu par le PREMIER SEGMENT du chemin `model=`, pas le
chemin complet -- confirmé par reproduction minimale isolée (faire varier
tour à tour name/creator/catalogId/icon/elevation/niveau/ordre de lecture
ne change rien, seul le premier segment du chemin importe). Conséquence
concrète : tant que tous les arbres écrivaient `model='tree/{model_key}.obj'`
(même premier segment `tree/` pour toutes les variantes), TOUS les arbres du
`.sh3d` final héritaient du Content du PREMIER arbre résolu -- silhouette
identique partout (vérifié par rendu SunFlow HIGH ciblé sur des arbres de
hauteurs très différentes, même maillage exact sur les 76 arbres du site
réel) malgré un calcul et un embarquement corrects en amont (7 fichiers OBJ
distincts bien présents dans le `.sh3d`, jamais utilisés). Corrigé dans
`build_home.py` : chaque modèle espèce x variante écrit désormais dans son
PROPRE dossier de premier niveau (`{model_key}/{model_key}.obj` + `.mtl`
dupliqué dans ce même dossier, plus de partage inter-variantes) au lieu d'un
dossier `tree/` commun -- vérifié par reproduction minimale (7 modèles, 7
objets `Content` distincts après le fix, contre 1 seul avant), **et
confirmé sur le run CI réel suivant** (`generation.yml` #17 +
`render.yml` #18, après merge du fix) : les 76 arbres du site réel portent
bien chacun leur propre modèle espèce x variante (vérifié par lecture
directe du `Home` du `.sh3d` produit).

### Feuillage "conifère" quasi invisible au rendu, corrigé

En inspectant les images réelles de `render.yml` #18, des arbres
apparaissent réduits à un squelette tronc/branches nu, sans feuillage --
confirmé (pas supposé) être lié à l'archétype "conifère" par rendu
comparatif ciblé (même `.sh3d`, même caméra/distance/qualité, espèces
différentes côte à côte) : mesure de l'aire des quads du groupe `leaves`
par fichier OBJ, aiguilles du conifère ~20x plus petites en surface que
feuillu/arbuste (cohérent avec `LeafScale`/`LeafScaleX` 0.10/0.2 contre
0.20/0.8 et 0.22/0.8) -- sous le seuil d'échantillonnage SunFlow (qualité
`low`, défaut de `render.yml`) à distance de caméra normale. Effet
d'échelle de l'arbre exclu comme explication unique (testé : un grand
conifère, 10,8 m, montre un feuillage tout aussi clairsemé qu'un petit,
5,1 m, à taille apparente égalisée) ; hypothèses mémoire JVM et géométrie
corrompue également écartées (cf. `ModelManager.loadModel` source réelle :
aucun `Error`/`OutOfMemoryError` intercepté, seulement des exceptions de
format ; aucune face dégénérée mesurée dans les 7 fichiers OBJ). Corrigé
dans `assets/arbaro_species/conifere.xml` (`LeafScale` 0.10->0.18,
`LeafScaleX` 0.2->0.35, nombre de faces quasi inchangé) -- validé par rendu
comparatif avant/après (même seed, même distance) dans une session Claude
Code distante : feuillage nettement plus couvrant, silhouette "aiguilles"
toujours plus fine que feuillu/arbuste. **Revalidé de bout en bout sur le
site réel** (`render.yml` #19, après merge du fix) : même arbre comparé
avant/après sur les images réelles -- squelette nu au run #18, feuillage
clairsemé mais visible au run #19.

### Densité de branches insuffisante pour les 3 archétypes, étudiée sur sources documentaires

Même après le fix LeafScale ci-dessus, utilisateur juge le conifère pas
assez dense. Étude systématique des 3 presets (`assets/arbaro_species/*.xml`)
contre des sources réelles du même algorithme plutôt qu'un réglage à l'œil :

- Article original **Weber & Penn, "Creation and Rendering of Realistic
  Trees", SIGGRAPH 1995** (PDF récupéré et parsé par cette session, `pypdf`
  -- `pdftoppm`/poppler indisponible) : annexe "Parameter List" donne les
  valeurs complètes pour 4 espèces réelles (Quaking Aspen, Black Tupelo,
  Weeping Willow, CA Black Oak). Quaking Aspen ET Black Tupelo s'accordent
  sur `1Branches=50` (contre 28 dans notre `feuillu.xml` d'origine). Table 2
  du même article (nombre de triangles par niveau selon la distance de vue,
  sur un Quaking Aspen) : les branches de niveau 2 tombent à 0 triangle
  au-delà de 30 m, alors que le niveau 1 et les feuilles restent
  significatifs bien plus loin -- justifie de rester sur `Levels=2` pour les
  3 archétypes plutôt que de chercher à reproduire la structure à 3-4
  niveaux des espèces réelles.
- Presets communautaires du même algorithme, `arbaro/trees/*.xml` (clone
  depuis le commit du `Dockerfile` dans une session Claude Code distante) :
  `tamarack.xml` (conifère réel, `1Branches=75`, contre 30 dans notre preset
  d'origine) ; `desert_bush.xml` (arbuste/buisson réel, `1Branches=9` mais
  compensé par un niveau 2 à 40 branches).
- **Essai rejeté** : ajouter un niveau 2 allégé (conifère, `Levels=3`,
  `2Branches=12`, `CurveRes` réduit à 1-2) pour se rapprocher de la
  structure réelle à plusieurs niveaux : 48139 faces pour un seul arbre (le
  nombre de feuilles se multiplie par `1Branches x 2Branches`, pas leur
  somme) -- confirme le problème déjà documenté plus haut pour le preset de
  démo standard arbaro, et cohérent avec la Table 2 ci-dessus (niveau 2
  inutile à distance de rendu normale).
- **Corrigé** : `1Branches` relevé à la valeur réelle exacte pour
  `conifere.xml` (30->75, `tamarack.xml`) et `feuillu.xml` (28->50, Quaking
  Aspen/Black Tupelo). `arbuste.xml` **inchangé** (`1Branches=22`) : copier
  littéralement le `9` de `desert_bush.xml` rendrait l'arbuste MOINS dense
  sans le niveau 2 compensatoire qu'on n'ajoute pas -- déviation délibérée
  de la source pour cet archétype, arbuste déjà jugé visuellement adéquat
  dans tous les rendus de cette session. Validé par rendu comparatif
  avant/après (même seed, même distance, les 5 configurations côte à côte)
  ET par un rendu complet des 76 arbres du site réel avec les nouveaux
  modèles substitués (`ContentDigests` du `.sh3d` recalculé normalement par
  le pipeline réel, contourné uniquement pour ce test ponctuel sur un
  fichier déjà généré) : 13,7 s contre environ 11 s avant (qualité low,
  même caméra), écart négligeable, aucun artefact ni fouillis visuel
  constaté. **Pas encore revalidé sur le site réel** à ce stade (pas de
  site configuré dans cette session) : à reprendre lors d'un prochain run
  complet.

### Revalidée sur le site réel (`generation.yml` #19, post-merge du fix ci-dessus) : le conifère reste jugé insuffisamment dense — investigation approfondie, conclusion inattendue

Méthode corrigée par rapport à une comparaison antérieure jugée à tort
"sans effet" (portait très probablement sur un arbuste, jamais retouché,
pas un conifère -- 54 % des 76 arbres du site sont des arbustes) : caméra
`ensemble_rapprochee` recalculée EXACTEMENT depuis les données réelles du
run (`preview._ensemble_camera` sur `data/bati.json`/`sh3d_payload.json`/
`terrain_grid.npz`), positions des 76 arbres extraites du `.sh3d` réel par
un outil Java (`HomeFileRecorder`), projection pinhole pour identifier une
grappe de VRAIS conifères dans le rendu CI réel. Validation croisée : un
rendu local avec cette caméra reconstruite reproduit un compte de pixels de
feuillage identique au pixel près au rendu CI réel (652 px de feuillage
sombre dans les deux cas) -- la reconstruction de caméra est exacte, pas
approximative.

- Fix `1Branches` 30->75 ci-dessus : effet réel mesuré sur cette grappe
  (+8,8 % de pixels de feuillage sombre) -- pas nul comme la comparaison
  antérieure le laissait croire à tort, mais modeste.
- Qualité SunFlow `high` au lieu de `low` (même caméra/scène) : +14 % de
  pixels de feuillage seulement, silhouette toujours clairsemée -- écarte
  le sous-échantillonnage `low` comme cause principale.
- `Levels=3` rééquilibré testé (`1Branches=75`, `2Branches=8`,
  `Leaves=10`/brindille au lieu de 70/branche -- corrige un défaut
  méthodologique de l'essai rejeté ci-dessus, qui n'avait pas réduit
  `Leaves` en ajoutant un niveau, d'où l'explosion à 48139 faces) : 8581
  faces (moins cher que l'actuel) mais rendu quasi identique (649 px vs
  652) -- les brindilles ne comblent pas les trous perçus.
- `1Branches=150` testé (x2 de la valeur sourcée `tamarack.xml`,
  `Levels=2` inchangé, 25423 faces contre 12739, faces de feuillage x3,4
  car chaque branche ajoutée porte aussi son quota `Leaves=70`) : **655 px
  de feuillage contre 652 avant -- effet quasi nul**, malgré un
  quasi-doublement de la géométrie. Patch vérifié présent dans le `.sh3d`
  de test (25423 faces confirmées dans l'entrée zip) : pas un bug de
  patch, un vrai plafond.
- **Constat** : trois leviers structurellement très différents (qualité de
  rendu, structure de branches à `Levels=2` inchangé, niveau de
  ramification supplémentaire) produisent tous un effet quasi nul sur le
  rendu CI réel à qualité `low`/distance normale. Le plafond perçu n'est
  donc PAS un problème de configuration arbaro (paramètres déjà au niveau
  ou au-dessus de toutes les références documentaires trouvées), mais très
  probablement un plafond d'échantillonnage SunFlow à cette
  qualité/distance : une fois qu'un minimum de géométrie remplit
  l'enveloppe du houppier à l'écran, ajouter des branches/feuilles derrière
  des pixels déjà verts ne change rien à un comptage par pixel (SunFlow
  n'échantillonne pas assez de rayons par pixel à qualité `low` pour
  distinguer une superposition dense d'une clairsemée).
- **Comparaison au houppier réel (ortho IGN, site réel)**, demandée
  explicitement par l'utilisateur pour trancher si le rendu clairsemé
  correspond à une réalité botanique du site ou à un manque du modèle : sur
  9 conifères réels confiants (hauteur MNH >= 8,5 m, rayon de houppier
  4-6 m), coefficient de variation de la luminosité dans le disque du
  houppier (mesure de solidité/uniformité, insensible à l'exposition --
  une mesure par seuil de couleur absolu s'est avérée non robuste aux
  variations d'exposition de la mosaïque ortho) médian = 0,21 (plage
  0,18-0,28), soit une "solidité" 1/(1+CV) ~ 0,83 -- **les vrais conifères
  du site apparaissent bien comme des houppiers pleins/opaques vus du
  dessus, pas clairsemés**. Confirme que le rendu clairsemé du modèle
  arbaro est un écart réel par rapport à la réalité du site, pas une
  caractéristique botanique attendue -- mais n'aide pas à le corriger,
  puisque la cause identifiée (plafond d'échantillonnage SunFlow, pas la
  configuration arbaro) n'est pas adressable côté paramètres de l'espèce.
- **À date, aucun levier côté configuration arbaro (`1Branches`, `Levels`,
  qualité de rendu jusqu'à `high`) ne résout ce plafond.** Pistes restantes
  non testées à ce stade : augmenter `LeafScale`/`LeafScaleX` très au-delà
  des valeurs botaniques réelles (feuilles artificiellement plus grandes
  pour dépasser le seuil d'échantillonnage, coût : écart au réalisme déjà
  documenté comme hors du cadre "source" de cette section) ; ou une
  qualité de rendu encore supérieure à `high` si `PhotoRenderer`/SunFlow
  l'expose. Aucune des deux n'a été décidée à ce stade.

### Revalidation confirmée sans changement, puis levier LeafScale non botanique choisi par l'utilisateur et validé — corrige le plafond

Un nouveau run réel (`generation.yml` #20 -> `render.yml` #21, commit du
merge ci-dessus, aucun changement de code) a été revalidé avec la même
méthode (caméra recalculée, même grappe de conifères) : 652 px de
feuillage, identique au pixel près à la mesure précédente -- confirme
qu'aucune régression ni amélioration n'était attendue, et que la mesure est
reproductible d'un run à l'autre (le seul écart entre les deux fichiers
PNG, 2 octets, est du bruit d'échantillonnage SunFlow, pas un changement de
contenu).

Face au choix explicite de l'utilisateur ("LeafScale non-botanique" plutôt
que qualité de rendu supérieure), plusieurs paliers testés sur le même
conifère patché dans le `.sh3d` réel (même caméra/grappe de référence),
`LeafScale`/`LeafScaleX` relevées ensemble en conservant le rapport
largeur/longueur d'origine (silhouette "aiguille" préservée, pas une dérive
vers une forme en losange) :

- 0.18/0.35 (valeur PR#86, référence) : 652 px.
- 0.35/0.7 (x2) : 678 px (+4 %).
- 0.6/1.2 (x3,3) : 705 px (+8 %).
- 1.0/2.0 (x5,5) : 724 px (+11 %) -- gain net et visible en inspection
  directe du rendu (silhouette nettement plus pleine sur les arbres
  patchés), sans artefact (pas de blocs/losanges visibles).
- 1.6/3.2 (x8,9) : 727 px (+11,5 %) -- plateau atteint, gain marginal
  supplémentaire négligeable.

**Valeur retenue : `LeafScale`=1.0, `LeafScaleX`=2.0** (le point juste avant
le plateau, pas la valeur maximale testée). Contrairement à `1Branches`
(qui ajoute de la géométrie, coût en faces/temps de rendu), `LeafScale` ne
change que la taille des quads de feuillage déjà existants (`Leaves`=70
inchangé) : **aucun coût supplémentaire de faces ni de temps de rendu**
(12739 faces/arbre, identique à avant). **Déviation délibérément non
botanique**, assumée et documentée comme telle : ~2,9x plus grand que la
référence réelle `tamarack.xml` (0.15/0.35) et ~5,5x la valeur précédente
de ce projet (0.18/0.35, elle-même déjà au-dessus du réel pour corriger le
sous-échantillonnage) -- ne pas reprendre cette valeur comme référence
botanique Weber & Penn si ce fichier sert de modèle ailleurs. Choisie
explicitement par l'utilisateur en connaissance de cause, après avoir
constaté qu'aucun levier source (branches, niveaux, qualité de rendu) ne
fonctionnait.

### Revalidée sur un run complet réel (`generation.yml` #21 -> `render.yml` #22) : gain confirmé et meilleur que prévu

1112 px de feuillage sur la grappe de référence (contre 652 avant, et 724
sur le patch-test partiel qui ne modifiait qu'un seul des 3 modèles
conifère présents dans cette grappe) -- un run complet régénère les 3
variantes (`conifere_0/1/2`) avec la nouvelle valeur, pas une seule, d'où
un gain supérieur à l'extrapolation du patch-test. Inspection visuelle
directe (grappe ET scène complète) : tous les conifères du site affichent
désormais une silhouette pleine et reconnaissable (forme de sapin
classique), sans artefact (pas de bloc ni de losange), cohérents entre eux
et avec le reste de la végétation (feuillu/arbuste inchangés). Fix
définitivement confirmé de bout en bout, plus seulement sur un `.sh3d`
patché. **État courant retenu** (à ne pas régresser sans relire ce
journal) : `conifere.xml` avec `LeafScale`=1.0/`LeafScaleX`=2.0,
`1Branches`=75 ; `feuillu.xml` avec `1Branches`=50 ; `arbuste.xml`
inchangé (`1Branches`=22).

## Compatibilité `Plan 3D.sh3d` avec l'appli mobile / Sweet Home 3D Online

**Validé de bout en bout** (`tools/mobile_compat_check/`, outil autonome sur
le modèle de `tools/lidar_view/`) : un plan synthétique commité (`fixture/`,
cube + pyramide + 3 niveaux + `furnitureGroup` + `room` + `backgroundImage`,
aucune donnée géographique réelle) est assemblé en `.sh3d` réel via le même
`java/Conv.java` (`build_fixture.py`, JDK + `SweetHome3D.jar` -- non
fournis par le dépôt), puis chargé dans Chromium headless (Playwright) via
le vrai moteur JS eTeks (`check.mjs`) : chargement propre (zéro erreur),
rendu visuellement cohérent (capture d'écran).

**Pas encore validé sur un vrai `Plan 3D.sh3d`** d'un site réel (pas de
site configuré dans la session qui a écrit ce correctif, confidentialité) :
le poids géométrique cumulé réel (terrain ~43k faces, toits `roofer`
multi-bâtiments, jusqu'à ~76 arbres `arbaro`) n'a pas été testé sur ce
moteur -- performance/fluidité sur mobile restent à observer sur un run
complet (`node tools/mobile_compat_check/check.mjs "Plan 3D.sh3d"`, ou
`verif.py --mobile-compat`).

Mise à jour ultérieure : l'image CI embarque désormais Node.js +
`node_modules`/Chromium (cf. `Dockerfile`), et `generation.yml` appelle
`verif.py --mobile-compat` sur chaque run -- `docker build` (`npx
playwright install --with-deps chromium`) réussit bien, mais le premier
vrai run de `generation.yml` (génération #32) a échoué au LANCEMENT de
Chromium, pas à l'installation : `browserType.launch: Executable doesn't
exist at /github/home/.cache/ms-playwright/chromium_headless_shell-*`.
Cause : `generation.yml` utilise un job `container:` -- le runner force
`HOME=/github/home` au RUNTIME du conteneur, indépendamment du `HOME`
(`/root`, aucun `USER` dans le `Dockerfile`) utilisé pendant `docker
build`, où les navigateurs avaient été installés sous `/root/.cache/
ms-playwright/`. Corrigé en fixant `PLAYWRIGHT_BROWSERS_PATH` à un chemin
absolu hors de `$HOME` (`ENV` Docker, donc appliqué au conteneur peu
importe que le runner réécrive `HOME`) -- pas encore reconfirmé par un run
CI après ce fix, ni sur un `Plan 3D.sh3d` de site réel au poids
géométrique complet (cf. `CLAUDE.md` §Environnement pour l'état du run CI
le plus récent).
