# `Plan 3D.sh3d` : plan d'exécution et limitations

## Pourquoi ce n'est pas trivial

Le format `.sh3d` est un ZIP qui **doit** contenir une entrée `Home` :
l'objet Java `com.eteks.sweethome3d.model.Home` **sérialisé**. Un `.sh3d` qui
ne contiendrait qu'un `Home.xml` est refusé au chargement. Python ne sait pas
produire cette sérialisation Java, d'où le passage par les propres classes de
Sweet Home 3D.

## Étape 1 : Python (`src/build_home.py`)

Assemble un ZIP intermédiaire `data/_home_raw.zip` :

1. Lit le gabarit neutre `assets/home_template.xml` (en-tête Sweet Home 3D :
   `<environment>`, `<compass>`, caméras, les **5 `<level>`** avec des UUID
   stables) et garde tout jusqu'à `</home>`.
2. Remplace la `<backgroundImage>` du niveau *Cadastre* : image `bg`, échelle
   calée sur `sh3d_payload.json` (0,8 x largeur, origine 0,0).
3. Réoriente le `<compass>` : longitude/latitude (radians) du **centroïde** de
   la bbox WGS84 du site. L'orientation solaire est correcte sans qu'aucune
   coordonnée ne soit stockée dans le dépôt.
4. Positionne la caméra de visite 3D (observateur) sur le centroïde de la
   parcelle propriété, à hauteur d'œil (`+170 cm`) au-dessus du **sol le plus
   haut sous les bâtiments de la propriété**
   (`bati_propriete_ref.json[sol_bati_max_cm]`). Sweet Home 3D ne fait pas
   suivre le relief à la caméra. Repli sans bâti propriété :
   `z_max_terrain + 60 cm`.
5. Génère les `<pieceOfFurniture>` :
   - terrain (`data/terrain.obj`) ;
   - bâti voisinage (`data/bati_voisinage.obj`) ;
   - bâti propriété si présent (`data/bati_propriete.obj`, cf. limitation #9) ;
   - haies si présentes ;
   - environ 1 arbre par entrée de `data/vegetation_arbres.json`,
     redimensionné selon la hauteur mesurée. `model='tree/<espèce>_<variante>.obj'`
     (silhouette conifère/feuillu/arbuste générée par `arbaro_tree.py`, cf.
     issue #82) si l'outil externe `arbaro` était disponible à la génération,
     sinon `model='tree/tree.obj'` (gabarit unique historique) pour tous les
     arbres.

   Position et élévation lues depuis les `*_place.json` et la végétation JSON.
   Haies et arbres sont rassemblés dans un seul `<furnitureGroup>` (niveau
   *Végétation*) : `x`/`y`/`width`/`depth`/`height` du groupe sont calculés
   par SH3D (`HomeFurnitureGroup`) depuis la boîte englobante des enfants, pas
   besoin de les fournir.
6. Génère les `<room>` :
   - les parcelles (niveau *Cadastre*) ;
   - les emprises au sol des bâtiments de la propriété (niveau *Bâti
     propriété*, plancher invisible : la géométrie 3D vient de
     `bati_propriete.obj`, cette pièce ne sert qu'aux étiquettes/repères 2D) ;
   - pour chacun de ces bâtiments, une seconde pièce **visible** ("Emprise
     `<id>`") sur un niveau dédié. Raison : un `<room>` SH3D n'a pas
     d'élévation propre (seulement celle de son niveau), et un niveau unique
     partagé clipperait certains bâtiments dans le maillage terrain sur un
     site en pente (écart constaté : jusqu'à ~2,5 m de sol entre deux
     bâtiments propriété du même site). Élévation du niveau = point de
     terrain le plus haut sous l'emprise du bâtiment
     (`bati_propriete_ref.json[footprints[].sol_max_cm]`, calculé par
     `bati.py`) + `FOOTPRINT_CLEARANCE_CM` (3 cm), jamais clippée, quitte à
     légèrement flotter au-dessus du terrain sur les coins bas d'une emprise
     en pente.
7. Écrit le ZIP : `Home.xml` + `bg` + dossiers modèles (`t/ b/ p/ h/ tree/`,
   chaque OBJ avec son `.mtl` et sa texture) + une icône. Écrit aussi
   `data/home_source.xml` pour debug/diff.

## Étape 2 : Java (`java/Conv.java`)

1. `_prepare_java()` : copie `SweetHome3D.jar` dans `data/_jconv/` (une fois)
   et compile `Conv.java` (`javac`, en cache par mtime). Le `.jar` est
   auto-détecté (WindowsApps, Program Files) ou pris dans
   `[tools].sweethome3d_jar`.
2. `java -cp "<jar>;data/_jconv" com.eteks.sweethome3d.io.Conv _home_raw.zip "Plan 3D.sh3d"` :
   - `new HomeContentContext(zipFileUrl, null, true)` (URL fichier simple) ;
   - `HomeXMLHandler` + `handler.setContentContext(ctx)` (méthode
     package-private, d'où `Conv` compilé dans le package
     `com.eteks.sweethome3d.io` sur le classpath) ;
   - SAX-parse `Home.xml` du ZIP → `handler.getHome()` → objet `Home` avec les
     bons niveaux ;
   - `new HomeFileRecorder(9, false).writeHome(home, out)` → `.sh3d` avec
     `Home` sérialisé + `ContentDigests` + entrées modèles numérotées ;
   - relit sa propre sortie (`readHome`) et imprime la répartition par
     niveau.
3. `build_home.py` sauvegarde l'ancien `.sh3d` en `.sh3d.bak` et supprime
   `_home_raw.zip`.

**Résultat** : `Plan 3D.sh3d` (~2,3 Mo), double-cliquable, 5 calques fixes
(Cadastre / Terrain / Bâti voisinage / Bâti propriété / Végétation) + un
calque *Emprise `<id>`* par bâtiment propriété (cf. point 6 ci-dessus).

## Plan 2D intérieur (optionnel, séparé du pipeline principal)

`interieur_init.py`/`fusion_interieur.py` (détail complet dans `CLAUDE.md` >
Points durs) permettent de dessiner à la main, dans l'appli Sweet Home 3D
native, le plan intérieur d'un bâtiment (pièces, cloisons, mobilier), absent
du pipeline de génération extérieur qui n'a aucune source IGN pour
l'agencement intérieur réel.

1. `interieur_init.py` (après `phase1_cadastre`/`terrain`/`bati.py`) crée
   `interieur/<id>.sh3d`, un fichier par bâtiment propriété (par
   emprise/ring), un niveau par étage BD TOPO, un `<room>` guide par niveau
   reproduisant l'emprise exacte. **Repère LOCAL propre à chaque bâtiment**
   (pas le repère absolu du site) : l'emprise est ramenée près de l'origine
   du fichier et alignée sur son rectangle englobant minimal, pour rester
   visible et pratique à l'édition dans l'appli native (murs sur la grille).
   La transformation (rotation + translation) est écrite une seule fois dans
   `interieur/<id>.transform.json`, à côté du `.sh3d`. Ne réécrit jamais un
   fichier déjà présent.
2. Édition manuelle dans l'appli Sweet Home 3D native (murs, pièces,
   mobilier).
3. `fusion_interieur.py`, à la main, ponctuellement : lit chaque
   `interieur/<id>.sh3d` (son entrée `Home.xml`, écrite par le même
   `Conv.java` que ci-dessus grâce à `preferXmlEntry=true`) et son
   `interieur/<id>.transform.json` (repli sur la transformation identité si
   absent), retient les éléments portés par un niveau (`room`/`wall`/
   `pieceOfFurniture`/`furnitureGroup`/`dimensionLine`/`polyline`/`label`,
   à l'exclusion de la pièce-repère de l'emprise, reconnue par son nom),
   leur applique la transformation inverse repère local → absolu, réattribue
   à chaque niveau un id frais et un `elevationIndex` continu après celui de
   `Plan 3D.sh3d`, copie les éventuelles entrées de contenu (modèles/icônes
   de mobilier) référencées sous un préfixe par bâtiment, puis réinjecte le
   tout dans le `Home.xml` de `Plan 3D.sh3d` et repasse par `Conv.java` →
   **nouveau fichier** `Plan 3D (avec interieur).sh3d`. Ne modifie jamais
   `Plan 3D.sh3d` lui-même.

> [!NOTE]
> **Limite connue, non couverte.** Un mur qui référencerait
> (`wallAtStart`/`wallAtEnd`) un mur d'un autre fichier `interieur/*.sh3d`
> casserait la fusion (identifiants de murs non résolubles au-delà de leur
> propre fichier). Ne devrait pas se produire en usage normal de l'appli
> (chaque bâtiment a son propre fichier indépendant), mais n'est ni détecté
> ni signalé explicitement si cela arrivait.

## Étape 3 (optionnelle) : rendu photo headless (`verif.py --render`, `preview.py`)

`java/RenderPhoto.java` (`com.eteks.sweethome3d.utilities.RenderPhoto`) rend
`Plan 3D.sh3d` en PNG hors-ligne via le moteur SunFlow de Sweet Home 3D
(`com.eteks.sweethome3d.j3d.PhotoRenderer`, qualité 3/4, même brique que
« Créer photo » dans l'appli). Sortie : `data/verif/render_photo.png`. Sert
de smoke-test visuel (textures, calques, géométrie) sans ouvrir l'appli.

`RenderPhoto` accepte un point de vue optionnel `x y z yaw pitch` (repère
plan, cm/rad) et `-Drender.quality=low|high`.

| Script | Rôle |
|---|---|
| `python src/preview.py` | Trois vues d'ensemble aériennes de la parcelle (large, rapprochée, latérale, `data/verif/preview_ensemble_*.png`). Vues par bâtiment désactivées, cf. limitation #12. |
| `python src/roof_focus_render.py [larg haut [low\|high]]` | Rendu oblique par bâtiment propriété pour lire la géométrie du toit reconstruit par `roofer` (`data/verif/roof_*.png`). Diagnostic ponctuel, à invoquer à la main après `bati.py`. |
| `python src/orbit_render.py [larg haut [low\|high] [images] [secondes]]` | Panoramique circulaire MP4 (`data/verif/orbit.mp4`, via `ffmpeg`). |

`sitegeo.render_photo()` factorise compilation et lancement du renderer,
partagé par `verif.py --render` et `preview.py`.

### `orbit_render.py` : détails

- Caméra **fixe** (`cg.walk_camera_xyz()`, le même point que la caméra de
  visite 3D du `.sh3d` : centroïde de la parcelle propriété, hauteur d'œil
  au-dessus du sol le plus haut sous ses bâtiments), seul le yaw tourne sur
  360°. C'est un **panoramique circulaire** (la caméra pivote sur
  elle-même), pas un travelling autour de la parcelle : la position ne
  bouge jamais.
- Option du job CI *Rendu* (`.github/workflows/render.yml`, entrées
  `animation`/`orbit_frames`/`orbit_seconds`), jamais lancé par
  `run.sh`/`run.ps1` (coût : un rendu SunFlow complet par image).
- Pitch/FOV fixes (`PANO_PITCH` ≈ 0,135 rad, `PANO_FOV` ≈ 1,0996 rad), même
  convention que l'`observerCamera` du gabarit (quasi horizontale, FOV
  observateur standard Sweet Home 3D, plutôt que le grand-angle plongeant
  des vues d'ensemble `preview.py`). Plage déjà testée pour le bug
  directionnel (issue #65, point 15) : le filet de sécurité (repli + gel,
  ci-dessous) reste actif quelle que soit la position exacte des zones
  mortes à ce pitch/FOV.
- Vitesse de rotation découplée du nombre d'images (`images`, seul poste de
  coût) via une durée de tour explicite (`secondes`, 10 s par défaut). L'entrée
  ffmpeg est consommée à `images/secondes` im/s puis ré-échantillonnée
  (filtre `fps=`) à 30 im/s de sortie par duplication d'image, **pas**
  d'interpolation de mouvement : la rotation reste « par à-coups », juste
  plus lente. Un mouvement réellement fluide demanderait soit beaucoup plus
  d'images (coût linéaire, un rendu SunFlow complet chacune), soit `ffmpeg
  minterpolate` (pas de rendu supplémentaire, mais risque de « warping » non
  testé entre deux azimuts très différents) : ni l'un ni l'autre n'est
  activé pour l'instant.
- Un tour complet balaie nécessairement tous les azimuts, y compris ceux où
  le bug directionnel de la limitation #12/issue #65 peut dégrader une
  image. Chaque image tente d'abord le même repli en yaw que `preview.py`
  (`DEGRADED_RETRY_MAX_OFFSET_DEG`), puis à défaut est remplacée par un
  **gel de la dernière image bonne** (jamais de saut de montage ni d'image
  quasi vide publiée dans la boucle, contrairement au simple abandon utilisé
  par `preview.py` pour une vue isolée). Échoue explicitement (`SystemExit`)
  si `ffmpeg` est absent, si le rendu lui-même est indisponible, ou si les
  360° balayés ne produisent aucune image exploitable.

### `RenderPhoto` : précisions

- Cette classe **n'existe pas** dans `SweetHome3D.jar` (contrairement à ce
  que suggère la doc communautaire du même nom) : c'est un petit helper
  source, adapté de `com.eteks.sweethome3d.utilities.ConsolePhotoGenerator`
  (Emmanuel Puybaret / eTeks, GPLv2), compilé comme `Conv.java`.
- Jars additionnels au-delà de `SweetHome3D.jar` : `sunflow-*.jar`,
  `j3dcore.jar`, `j3dutils.jar`, `vecmath.jar`, `batik-svgpathparser-*.jar`,
  dans le `lib/` de Sweet Home 3D (recherche **récursive** : le build
  Microsoft Store range Java3D dans `lib/java3d-*/`). Réglable via
  `[tools].render_libs_dir` (sinon le `lib/` du `.jar` détecté, lui-même
  trouvé via `Get-AppxPackage` pour une install Store). Absents/incomplets :
  étape ignorée proprement, n'affecte pas le code retour de `verif.py`.
- **Sous Linux, `xvfb-run` est nécessaire** même avec `-Dj3d.rend=noop`
  (pipeline GPU désactivé) : Java3D interroge quand même un
  `GraphicsEnvironment` au démarrage et lève `HeadlessException` sans
  display réel ou virtuel. `verif.py` l'utilise automatiquement si trouvé
  sur le `PATH` ; sous Windows ce n'est pas nécessaire.
- Distinct du **plugin MCP Sweet Home 3D** (pilote une instance GUI déjà
  ouverte, affichage des calques pas fiable, cf. limitation #2) et du rendu
  interactif soigné (GUI + plugin `AdvancedSettingsPhotoRendering` + GPU,
  qui restera toujours de meilleure qualité) : ceci est un rendu rapide,
  réglages par défaut, pour vérification automatisée seulement.

## Limitations connues

1. **JVM obligatoire** pour produire le `.sh3d` (`java` + `javac`). La JRE
   embarquée de Sweet Home 3D ne suffit pas (pas de `javac`).
2. **Plugin MCP Sweet Home 3D** : `load_home`/`get_state`/`save_home`
   mésaffichent l'affectation aux niveaux (tout sur un calque). Le fichier
   produit, lui, est correct (prouvé par la relecture `Conv` + l'ouverture
   native). Ne pas vérifier les calques via MCP.
3. **Caméra de visite** : Sweet Home 3D déplace la caméra observateur à
   altitude fixe, sans collision avec le terrain importé. Contournement :
   caméra posée sur la parcelle propriété, à hauteur d'œil au-dessus du sol
   le plus haut de ses bâtiments (cf. étape 1, point 4). Elle « flotte » là
   où le terrain descend sous ce niveau ; ajuster avec Pg.Préc/Pg.Suiv en
   vue 3D.
4. **Ortho plafonnée à 20 cm/px** (résolution HR native IGN). Aspect un peu
   flou aux angles rasants (filtrage de texture du moteur).
5. **Maillage terrain sous-échantillonné à 2 m** (~43 k faces).
   `terrain_z_at` interpole cette grille pour que les objets affleurent la
   surface *visible* ; résidu de calage de l'ordre du cm.
6. **Toits pyramidaux simples** (apex au centroïde, pas de faîtage) : repli
   utilisé par bâtiment quand `roofer` n'est pas disponible/exploitable
   (cf. limitation #9). Les bâtiments en L reçoivent un point central.
   Réglable via `ROOF_RISE_MAX` et les facteurs 0,22/0,45 de `bati.py`.
7. **Haies taillées** : détectées seulement si végétation basse (< 4 m) et
   étroite (< 4 m) le long de la limite. Une ceinture boisée est rendue en
   **ligne d'arbres** dense à la place.
8. **`matplotlib` interdit** dans l'env conda Windows (crash DLL) ;
   **`pv.Plane()` casse** (même cause).
9. **Tous les bâtiments** (propriété et voisinage) : toit + mur multi-pans
   reconstruits par l'outil externe `roofer` (`src/roofer_roof.py`, moteur
   3DBAG/TU Delft, LoD2.2, GPLv3, cf. `CLAUDE.md` > « Dépendance externe :
   roofer »), consommé tel quel (aucune reconstruction géométrique propre),
   avec repli automatique sur un toit pyramidal simple par bâtiment si
   `roofer` est absent/échoue ou si un bâtiment n'a pas de géométrie LoD2.2
   exploitable. Jamais de bâtiment sans toit modélisé. Suppose un
   environnement Linux (pas de build Windows officiel de `roofer`, cf.
   `CLAUDE.md` > Environnement). Ancien `src/roof_lidar.py` (RANSAC +
   croissance de région) conservé dans le dépôt pour référence/comparaison
   (`src/roofer_compare.py`), plus utilisé par le pipeline. Sorties :
   `data/bati_propriete.obj/.mtl` et `data/bati_voisinage.obj/.mtl`,
   chargées par `build_home.py`.
10. **Murs clairs sur-exposés** en lumière rasante (éclairage Sweet Home 3D,
    le matériau est correctement mat).
11. **`run.ps1` lui-même est Windows uniquement** (création de l'env conda,
    détection de chemins d'installation Sweet Home 3D). Les scripts
    `src/*.py` (dont `verif.py`) et le rendu photo headless n'en dépendent
    pas : ils tournent aussi dans un venv pip
    (`config/requirements-venv.txt`) + JDK, y compris en session Claude Code
    distante (conteneur Linux), cf. `CLAUDE.md` > Environnement.
12. **`preview.py` : vues caméra par bâtiment désactivées ; le rendu SunFlow
    peut aussi dégrader une vue d'ensemble selon l'azimut.** Détail complet
    ci-dessous.
13. **Compatibilité appli mobile / Sweet Home 3D Online.** Détail complet
    ci-dessous.

### Limitation #12 : dégradation de rendu selon l'azimut caméra

Un plafond de standoff (18 m) avait d'abord été tenté comme repli défensif
pour les vues par bâtiment, mais s'est révélé insuffisant : même à cette
distance courte, avec un cadrage géométriquement correct (yaw = azimut
caméra→bâtiment vérifié par calcul direct, écart nul), le rendu SunFlow
reste par endroits quasi vide (ciel/sol seul) sans obstacle ni relief
pouvant l'expliquer. Comportement non documenté du moteur de rendu
SunFlow/`PhotoRenderer` (jar tiers, pas de source correspondant exactement
au binaire utilisé).

**Portée du bug.** Touche aussi la vue d'ensemble selon l'azimut caméra,
indépendamment du FOV : reproduit sur une scène synthétique dédiée (dalle +
cube isolés, sans variable de matériau/couleur/relief) à plusieurs valeurs
de FOV, et sur les deux moteurs de rendu embarqués (`PhotoRenderer`/SunFlow
et `YafarayRenderer`, deux codebases indépendantes). Écarte une cause liée
au soleil, au terrain, à la végétation, à un bâtiment voisin, au winding du
maillage ou à un FOV mal transmis. Cause exacte non identifiée (moteurs
tiers, boîte noire). `preview.py` filtre donc automatiquement
(`_looks_degraded`, seuil empirique sur la fraction de pixels quasi blancs)
toute vue rendue et écarte celles qui ressortent quasi vides, plutôt que de
supposer qu'un angle validé sur un site le reste sur un autre.

**FOV corrigé séparément.** `FOV_RENDER_CORRECTION = 4.0` (un facteur de
correction appliqué au FOV transmis au renderer) reposait sur une mesure non
re-vérifiée d'une session antérieure. Décompilation du
`PhotoRenderer`/`YafarayRenderer`/`PinholeLens` réellement chargés et mesure
directe sur un rendu réel confirment que `fieldOfView` est transmis et
appliqué tel quel, sans facteur caché. Constante supprimée ; `DEFAULT_FOV`
recalibré à 2.0 rad (grand-angle) pour rester sous le plafond de standoff
(`_terrain_max_standoff`) sur le site de test, même valeur réelle que
l'ancien code transmettait par accident, donc mêmes rendus déjà validés
visuellement. Un re-balayage complet des azimuts sur la vue d'ensemble du
site de test, avec ce FOV corrigé, ne reproduit plus aucune vue dégradée
(auparavant, +90° dégradait à distance/pitch identiques à la vue large) : le
grand-angle semble réduire, sur ce site et à ce cadrage, la probabilité
pratique de tomber dans une zone d'azimut sensible, sans que cela change le
diagnostic du bug lui-même (confirmé indépendant du FOV sur la scène
synthétique). `_looks_degraded` reste donc actif comme filet de sécurité,
pas retiré.

**Caractérisation affinée (scène synthétique enrichie : repère d'axes
coloré, sol en damier, cube à 6 couleurs par face).** La disparition reste
totale, jamais partielle (pas de face manquante isolée, ce qui écarte un
problème de culling de face unique/normale). Le sol en damier, lui, reste
net et correctement projeté en perspective à tous les azimuts testés (aucun
warp de texture) : seuls les petits objets compacts proches de l'origine
(repère d'axes, cube) disparaissent, jamais la grande dalle qui les entoure.
Testé aussi en plaçant le repère et le cube sur le **même niveau SH3D** que
le sol (`level='Terrain'` au lieu de `'Bati propriete'`) : la disparition
persiste à l'identique, ce qui écarte une cause liée à la structure
multi-niveaux du `Home` (les 5 niveaux du projet partagent tous
`elevation=0`, seul `elevationIndex` diffère). La cause reste donc localisée
à la façon dont un objet (`pieceOfFurniture`) individuel, de petite emprise,
est transformé/inclus dans la scène exportée à certains azimuts caméra, pas
une question de niveau, de matériau ou de texture.

**Distance et taille de l'objet écartées, FOV/pitch confirmés comme facteurs
réels (cf. issue #65).** Contrairement à une conclusion antérieure (FOV
testé à seulement 3 valeurs isolées, sans effet constaté), un balayage
continu montre que FOV (0,5-3,0 rad) et pitch (0,0-1,0 rad) déplacent bel et
bien les bandes d'azimut mortes, par paliers. Le motif ne fait pas que
grandir/rétrécir, il **tourne** autour du cercle des azimuts jusqu'à une
inversion complète en régime extrême (FOV=3,0 rad, pitch=1,0 rad, hors usage
réel du pipeline). À l'inverse, la distance caméra-cible (×10 testé) et la
taille de l'objet (×16 testé) n'ont strictement aucun effet : motif de
visibilité identique bit à bit sur toute la plage testée dans chaque cas. La
cause ne dépend donc d'aucune propriété relative objet↔caméra, uniquement de
l'orientation caméra absolue dans le repère du monde (yaw, modulé par FOV et
pitch), un calcul de matrice de vue/frustum plus probable qu'un problème de
bounding-volume par objet.

**Levier exploité côté `preview.py`.** Comme distance et taille n'ont aucun
effet, `main()` ne se contente plus de filtrer puis abandonner une vue
dégradée : sur rendu quasi vide, elle retente désormais la même vue (même
marge/pitch/FOV, donc même cadrage voulu) à quelques azimuts voisins
(`_offset_sweep(ANGLE_STEP_DEG, DEGRADED_RETRY_MAX_OFFSET_DEG)`, ±30° par
défaut, 15° de pas) avant de l'écarter pour de bon. Portée volontairement
bornée (pas un balayage 360°, coûteux en rendu CI) et **non validée sur un
cas réel dégradé** : les bandes mortes mesurées sur la scène synthétique
font ~100° de large, un azimut retombant au milieu d'une bande aussi large
resterait hors de portée de ce repli à ±30°. `SUSPECT_YAW_BANDS_DEG` (mesurée
à une seule config FOV/pitch) n'est **pas** utilisée pour orienter ce repli :
le croisement FOV × pitch ci-dessus montre que ces bandes tournent avec la
config, une table figée mesurée ailleurs risquerait de désavantager un
azimut en réalité sûr. Cf. [Écarts assumés](#écarts-assumés) ci-dessous.

### Limitation #13 : compatibilité appli mobile / Sweet Home 3D Online

Le loader du moteur JS partagé par l'appli mobile et Sweet Home 3D Online
(`SweetHome3DJS`, transpilé Java→JS via JSweet) ne sait pas lire l'entrée
`Home` sérialisée Java qu'exige le desktop, seulement une entrée XML
`Home.xml`. `java/Conv.java` écrit désormais les deux
(`HomeFileRecorder(..., preferXmlEntry=true)`, cf. `CLAUDE.md` > Points
durs) : un seul `.sh3d` reste ouvrable sur le desktop (entrée `Home`) et sur
mobile/Online (entrée `Home.xml`, chemins de modèles déjà corrects car
écrite par `HomeXMLExporter`, intégré à `SweetHome3D.jar`).

Vérifié de bout en bout sur un plan synthétique
(`tools/mobile_compat_check/`, chargement réel dans Chromium headless via le
même moteur JS officiel). Pas encore vérifié sur un vrai `Plan 3D.sh3d`
(poids géométrique réel : terrain, toits `roofer`, arbres `arbaro`) faute de
site configuré lors de l'écriture de ce correctif. `verif.py
--mobile-compat` automatise ce contrôle à chaque génération (optionnel,
ignoré si Node.js est absent).

**Visibilité niveau/groupe sur l'appli mobile réelle** (testée sur Android,
version non consignée). Question distincte du chargement ci-dessus : une
fois le plan ouvert, quel contrôle de visibilité reste disponible sur
mobile ? Vérifié à la main avec le fixture synthétique de
`tools/mobile_compat_check/` (3 niveaux + un `furnitureGroup`) sur l'appli
mobile officielle (pas le viewer JS headless ci-dessus, qui ne partage pas
forcément la même interface) :

| Action | Résultat |
|---|---|
| Masquer un groupe de mobilier entier (case « Visible » dans la liste du mobilier, colonne `VISIBLE` déjà prévue dans `assets/home_template.xml`) | Fonctionne sur mobile. |
| Masquer un niveau entier | Ne fonctionne pas sur mobile : aucune bascule équivalente au raccourci desktop `Ctrl+Maj+H` n'est accessible dans l'interface mobile. |
| Masquer un élément individuel à l'intérieur d'un groupe (sans le dégrouper) | Impossible sur toute plateforme, desktop compris : décision volontaire du développeur ([forum officiel](https://www.sweethome3d.com/support/forum/viewthread_thread,6334)) pour éviter de compliquer la gestion de la taille/altitude d'un groupe partiellement visible. Pas une limitation mobile spécifique. |

**Conséquence pour ce projet** : un contenu qu'on veut pouvoir masquer à la
demande sur mobile doit vivre dans un groupe de mobilier, jamais reposer sur
le seul découpage en niveaux. Cadastre / Terrain / Bâti voisinage /
Végétation / « Emprise `<id>` » ne sont aujourd'hui **pas** masquables
individuellement sur mobile.

## Écarts assumés

1 écart assumé à ce jour.

| # | Limite concernée | Contexte | Choix assumé |
|---|---|---|---|
| 1 | #12 (vues caméra de `preview.py`) | Investigation ciblée (calibration du soleil, du maillage terrain, de la végétation, de la proximité des bâtiments voisins, du winding/volume signé du maillage terrain, de la structure multi-niveaux du `Home`, de la distance caméra-cible, de la taille de l'objet) : toutes les hypothèses de ce type infirmées, y compris après correction du bug FOV séparé (`FOV_RENDER_CORRECTION` supprimé), reproduit à l'identique sur une scène synthétique dédiée, sur deux moteurs de rendu indépendants (SunFlow et YafaRay), quel que soit le niveau SH3D de l'objet touché. **FOV et pitch ont un effet réel et mesurable** (déplacent/tournent les bandes d'azimut mortes, jusqu'à inversion en régime extrême) : la cause ne dépend donc que de l'orientation caméra absolue (yaw × FOV × pitch), jamais d'une propriété de l'objet visé ou de sa distance à la caméra. Sur le site de test réel, le passage au FOV corrigé (grand-angle, 2,0 rad) explique désormais mécaniquement pourquoi un re-balayage complet des azimuts ne reproduit plus la dégradation observée auparavant à yaw=+90°. Aucune règle générale n'explique quels azimuts/FOV/pitch/sites restent sûrs ; la cause exacte reste dans les moteurs de rendu tiers (boîte noire). | `_viewpoints()` ne génère plus que des vues d'ensemble de la parcelle (large, rapprochée, latérale), jamais les vues par bâtiment (code conservé dans `preview.py` pour référence/reprise future, plus appelé). En complément, `main()` filtre chaque rendu (`_looks_degraded`) ; sur rendu dégradé, retente la même vue à quelques azimuts voisins (`DEGRADED_RETRY_MAX_OFFSET_DEG`, ±30° bornés, non validé sur un cas réel) avant de l'écarter silencieusement. |

**Compromis retenu** : privilégier l'absence d'une vue à une vue
ponctuellement vide ou inexploitable, sur toutes les vues caméra (pas
seulement celles par bâtiment). Mieux vaut publier 1 ou 2 vues d'ensemble
fiables que 3 dont une inutilisable sans que rien ne le signale. Le repli en
azimut ne change pas ce compromis (le filet de sécurité reste
`_looks_degraded`) : il réduit seulement, à cadrage identique, la
probabilité d'avoir à s'y résoudre.
