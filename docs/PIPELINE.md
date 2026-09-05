# `Plan 3D.sh3d` : plan d'exécution et limitations

## Pourquoi ce n'est pas trivial

Le format `.sh3d` est un ZIP qui **doit** contenir une entrée `Home` :
l'objet Java `com.eteks.sweethome3d.model.Home` **sérialisé**. Un `.sh3d` qui ne
contiendrait qu'un `Home.xml` est refusé au chargement. Python ne sait pas
produire cette sérialisation Java -> on passe par les propres classes de
Sweet Home 3D.

## Étape 1 : Python (`src/build_home.py`)

Assemble un ZIP intermédiaire `data/_home_raw.zip` :

1. Lit le gabarit neutre `assets/home_template.xml` (en-tête Sweet Home 3D :
   `<environment>`, `<compass>`, caméras, les **5 `<level>`** avec des UUID
   stables) et garde tout jusqu'à `</home>`.
2. Remplace la `<backgroundImage>` du niveau *Cadastre* : image `bg`, échelle
   calée sur `sh3d_payload.json` (0,8 x largeur, origine 0,0).
3. Réoriente le `<compass>` : longitude / latitude (radians) du **centroïde**
   de la bbox WGS84 du site ; l'orientation solaire est correcte sans qu'aucune
   coordonnée ne soit stockée dans le dépôt.
4. Positionne la caméra de visite 3D (observateur) sur le centroïde de la parcelle
   propriété, à hauteur d'œil (`+170 cm`) au-dessus du **sol le plus haut sous les
   bâtiments de la propriété** (`bati_propriete_ref.json[sol_bati_max_cm]`). Sweet
   Home 3D ne fait pas suivre le relief à la caméra. Repli sans bâti propriété :
   `z_max_terrain + 60 cm`.
5. Génère les `<pieceOfFurniture>` : terrain (`data/terrain.obj`), bâti voisinage
   (`data/bati_voisinage.obj`), bâti propriété si présent (`data/bati_propriete.obj`,
   cf. limitation #9), haies si présentes, et ~1 arbre par entrée de
   `data/vegetation_arbres.json` (tous `model='tree/tree.obj'`, redimensionnés).
   Position / élévation depuis les `*_place.json` et la végétation JSON. Haies +
   arbres sont rassemblés dans un seul `<furnitureGroup>` (niveau *Végétation*) :
   `x`/`y`/`width`/`depth`/`height` du groupe sont calculés par SH3D
   (`HomeFurnitureGroup`) depuis la boîte englobante des enfants, pas besoin de
   les fournir.
6. Génère les `<room>` : les parcelles (niveau Cadastre) et les emprises au sol
   des bâtiments de la propriété (niveau *Bâti propriété*, plancher invisible :
   la géométrie 3D vient de `bati_propriete.obj`, cette pièce ne sert qu'aux
   étiquettes/repères 2D).
7. Écrit le ZIP : `Home.xml` + `bg` + dossiers modèles (`t/ b/ p/ h/ tree/`, chaque
   OBJ avec son `.mtl` et sa texture) + une icône. Écrit aussi
   `data/home_source.xml` pour debug / diff.

## Étape 2 : Java (`java/Conv.java`)

1. `_prepare_java()` : copie `SweetHome3D.jar` dans `data/_jconv/` (une fois) et
   compile `Conv.java` (`javac`, en cache par mtime). Le `.jar` est auto-détecté
   (WindowsApps, Program Files) ou pris dans `[tools].sweethome3d_jar`.
2. `java -cp "<jar>;data/_jconv" com.eteks.sweethome3d.io.Conv _home_raw.zip "Plan 3D.sh3d"` :
   - `new HomeContentContext(zipFileUrl, null, true)` (URL fichier simple) ;
   - `HomeXMLHandler` + `handler.setContentContext(ctx)` (méthode package-private
     ; d'où `Conv` compilé dans le package `com.eteks.sweethome3d.io` sur le
     classpath) ;
   - SAX-parse `Home.xml` du ZIP -> `handler.getHome()` -> objet `Home` avec les
     bons niveaux ;
   - `new HomeFileRecorder(9, false).writeHome(home, out)` -> `.sh3d` avec `Home`
     sérialisé + `ContentDigests` + entrées modèles numérotées ;
   - relit sa propre sortie (`readHome`) et imprime la répartition par niveau.
3. `build_home.py` sauvegarde l'ancien `.sh3d` en `.sh3d.bak` et supprime
   `_home_raw.zip`.

**Résultat** : `Plan 3D.sh3d` (~2,3 Mo), double-cliquable, 5 calques :
Cadastre / Terrain / Bâti voisinage / Bâti propriété / Végétation.

## Étape 3 (optionnelle) : rendu photo headless (`verif.py --render`, `preview.py`)

`java/RenderPhoto.java` (`com.eteks.sweethome3d.utilities.RenderPhoto`) rend
`Plan 3D.sh3d` en PNG hors-ligne via le moteur SunFlow de Sweet Home 3D
(`com.eteks.sweethome3d.j3d.PhotoRenderer`, qualité 3/4, même brique que
« Créer photo » dans l'appli). Sortie : `data/verif/render_photo.png`. Sert de
smoke-test visuel (textures, calques, géométrie) sans ouvrir l'appli.
`RenderPhoto` accepte un point de vue optionnel `x y z yaw pitch` (repère plan,
cm / rad) et `-Drender.quality=low|high`. `python src/preview.py` s'en sert pour
trois vues d'ensemble aériennes de la parcelle -- large, rapprochée, latérale
(`data/verif/preview_ensemble_*.png`), cf. limitation #12 pour le détail et
les vues par bâtiment (désactivées). `sitegeo.render_photo()` factorise
compilation et lancement, partagé par `verif.py --render` et `preview.py`.
`python src/roof_focus_render.py [larg haut [low|high]]` réutilise la même
brique pour un cadrage manuel distinct, non lancé par `run.sh`/`run.ps1` : un
rendu oblique par bâtiment propriété, plus rapproché/plus incliné que
`preview.py`, pour lire spécifiquement la géométrie du toit reconstruit par
`roofer` (`data/verif/roof_*.png`) -- outil de diagnostic ponctuel, à invoquer
à la main après `bati.py`.

`python src/orbit_render.py [larg haut [low|high] [images]]` assemble en MP4
(`data/verif/orbit.mp4`, via `ffmpeg` en sous-processus) une séquence de
rendus au même cadrage que `ensemble_large` (`preview._ensemble_camera`),
yaw réparti sur 360° -- une animation faisant le tour de la parcelle. Option
du job CI *Rendu* (`.github/workflows/render.yml`, entrée `animation`),
jamais lancé par `run.sh`/`run.ps1` (coût : un rendu SunFlow complet par
image). Un tour complet balaie nécessairement tous les azimuts, y compris
ceux où le bug directionnel de la limitation #12/issue #65 peut dégrader une
image : chaque image tente d'abord le même repli en yaw que `preview.py`
(`DEGRADED_RETRY_MAX_OFFSET_DEG`), puis à défaut est remplacée par un GEL de
la dernière image bonne (jamais de saut de montage ni d'image quasi vide
publiée dans la boucle -- la durée et le nombre d'images restent constants,
contrairement au simple abandon utilisé par `preview.py` pour une vue
isolée). Échoue explicitement (`SystemExit`) si `ffmpeg` est absent, si le
rendu lui-même est indisponible, ou si les 360° balayés ne produisent aucune
image exploitable.

- Cette classe **n'existe pas** dans `SweetHome3D.jar` (contrairement à ce que
  suggère la doc communautaire du même nom) : c'est un petit helper source,
  adapté de `com.eteks.sweethome3d.utilities.ConsolePhotoGenerator`
  (Emmanuel Puybaret / eTeks, GPLv2), compilé comme `Conv.java`.
- Jars additionnels au-delà de `SweetHome3D.jar` : `sunflow-*.jar`,
  `j3dcore.jar`, `j3dutils.jar`, `vecmath.jar`, `batik-svgpathparser-*.jar`,
  dans le `lib/` de Sweet Home 3D (recherche **récursive** : le build Microsoft
  Store range Java3D dans `lib/java3d-*/`). Réglable via `[tools].render_libs_dir`
  (sinon le `lib/` du `.jar` détecté, lui-même trouvé via `Get-AppxPackage` pour
  une install Store). Absents/incomplets -> étape ignorée proprement, n'affecte
  pas le code retour de `verif.py`.
- **Sous Linux, `xvfb-run` est nécessaire** même avec `-Dj3d.rend=noop`
  (pipeline GPU désactivé) : Java3D interroge quand même un
  `GraphicsEnvironment` au démarrage et lève `HeadlessException` sans display
  réel ou virtuel. `verif.py` l'utilise automatiquement si trouvé sur le
  `PATH` ; sous Windows ce n'est pas nécessaire.
- Distinct du **plugin MCP Sweet Home 3D** (pilote une instance GUI déjà
  ouverte, affichage des calques pas fiable, cf. limitation #2 ci-dessous) et
  du rendu interactif soigné (GUI + plugin `AdvancedSettingsPhotoRendering` +
  GPU, qui restera toujours de meilleure qualité) : ceci est un rendu rapide,
  réglages par défaut, pour vérification automatisée seulement.

## Limitations connues

1. **JVM obligatoire** pour produire le `.sh3d` (`java` + `javac`). La JRE
   embarquée de Sweet Home 3D ne suffit pas (pas de `javac`).
2. **Plugin MCP Sweet Home 3D** : `load_home` / `get_state` / `save_home`
   mésaffichent l'affectation aux niveaux (tout sur un calque). Le fichier
   produit, lui, est correct (prouvé par la relecture `Conv` + l'ouverture
   native). Ne pas vérifier les calques via MCP.
3. **Caméra de visite** : Sweet Home 3D déplace la caméra observateur à altitude
   fixe, sans collision avec le terrain importé. Contournement : caméra posée sur
   la parcelle propriété, à hauteur d'œil au-dessus du sol le plus haut de ses
   bâtiments (cf. étape 4). Elle « flotte » là où le terrain descend sous ce
   niveau ; ajuster avec Pg.Préc / Pg.Suiv en vue 3D.
4. **Ortho plafonnée à 20 cm/px** (résolution HR native IGN). Aspect un peu flou
   aux angles rasants (filtrage de texture du moteur).
5. **Maillage terrain sous-échantillonné à 2 m** (~43 k faces). `terrain_z_at`
   interpole cette grille pour que les objets affleurent la surface *visible* ;
   résidu de calage de l'ordre du cm.
6. **Toits pyramidaux simples** (apex au centroïde, pas de faîtage) : repli
   utilisé par bâtiment quand `roofer` n'est pas disponible/exploitable
   (cf. limitation #9). Les bâtiments en L reçoivent un point central.
   Réglable via `ROOF_RISE_MAX` et les facteurs 0,22 / 0,45 de `bati.py`.
7. **Haies taillées** : détectées seulement si végétation basse (< 4 m) et
   étroite (< 4 m) le long de la limite. Une ceinture boisée est rendue en
   **ligne d'arbres** dense à la place.
8. **`matplotlib` interdit** dans l'env (crash DLL) ; **`pv.Plane()` casse**
   (même cause).
9. **Tous les bâtiments** (propriété et voisinage) : toit + mur multi-pans
   reconstruits par l'outil externe `roofer` (`src/roofer_roof.py`, moteur
   3DBAG/TU Delft, LoD2.2, GPLv3 — cf. CLAUDE.md "Dépendance externe :
   roofer"), consommé tel quel (aucune reconstruction géométrique propre),
   avec repli automatique sur un toit pyramidal simple par bâtiment si
   `roofer` est absent/échoue ou si un bâtiment n'a pas de géométrie LoD2.2
   exploitable — jamais de bâtiment sans toit modélisé. Suppose un
   environnement Linux (pas de build Windows officiel de `roofer`, cf.
   CLAUDE.md section Environnement). Ancien `src/roof_lidar.py` (RANSAC +
   croissance de région) conservé dans le dépôt pour référence/comparaison
   (`src/roofer_compare.py`), plus utilisé par le pipeline. Sorties :
   `data/bati_propriete.obj/.mtl` et `data/bati_voisinage.obj/.mtl`,
   chargées par `build_home.py`.
10. **Murs clairs sur-exposés** en lumière rasante (éclairage Sweet Home 3D, le
    matériau est correctement mat).
11. **`run.ps1` lui-même est Windows uniquement** (création de l'env conda,
    détection de chemins d'installation Sweet Home 3D). Les scripts `src/*.py`
    (dont `verif.py`) et le rendu photo headless n'en dépendent pas : ils
    tournent aussi dans un venv pip (`config/requirements-venv.txt`) + JDK,
    y compris en session Claude Code distante (conteneur Linux), cf.
    `CLAUDE.md` section Environnement.
12. **`preview.py` : vues caméra par bâtiment désactivées ; le rendu SunFlow
    peut aussi dégrader une vue d'ensemble selon l'azimut.** Un plafond de
    standoff (18 m) avait d'abord été tenté comme repli défensif pour les
    vues par bâtiment, mais s'est révélé insuffisant : même à cette distance
    courte, avec un cadrage géométriquement correct (yaw = azimut
    caméra→bâtiment vérifié par calcul direct, écart nul), le rendu SunFlow
    reste par endroits quasi vide (ciel/sol seul) sans obstacle ni relief
    pouvant l'expliquer — comportement non documenté du moteur de rendu
    SunFlow/`PhotoRenderer` (jar tiers, pas de source correspondant
    exactement au binaire utilisé). **Le même bug touche aussi la vue
    d'ensemble** selon l'azimut caméra, indépendamment du FOV : reproduit sur
    une scène synthétique dédiée (dalle + cube isolés, sans variable de
    matériau/couleur/relief) à plusieurs valeurs de FOV, et sur les deux
    moteurs de rendu embarqués (`PhotoRenderer`/SunFlow et
    `YafarayRenderer`, deux codebases indépendantes) — écarte une cause liée
    au soleil, au terrain, à la végétation, à un bâtiment voisin, au winding
    du maillage ou à un FOV mal transmis ; cause exacte non identifiée
    (moteurs tiers, boîte noire). `preview.py` filtre donc automatiquement
    (`_looks_degraded`, seuil empirique sur la fraction de pixels quasi
    blancs) toute vue rendue et écarte celles qui ressortent quasi vides,
    plutôt que de supposer qu'un angle validé sur un site le reste sur un
    autre.
    **FOV corrigé séparément** : `FOV_RENDER_CORRECTION = 4.0` (un facteur de
    correction appliqué au FOV transmis au renderer) reposait sur une mesure
    non re-vérifiée d'une session antérieure ; décompilation du
    `PhotoRenderer`/`YafarayRenderer`/`PinholeLens` réellement chargés et
    mesure directe sur un rendu réel confirment que `fieldOfView` est
    transmis et appliqué tel quel, sans facteur caché. Constante supprimée ;
    `DEFAULT_FOV` recalibré à 2.0 rad (grand-angle) pour rester sous le
    plafond de standoff (`_terrain_max_standoff`) sur le site de test — même
    valeur réelle que l'ancien code transmettait par accident, donc mêmes
    rendus déjà validés visuellement. Un re-balayage complet des azimuts sur
    la vue d'ensemble du site de test, avec ce FOV corrigé, ne reproduit plus
    aucune vue dégradée (auparavant, +90° dégradait à distance/pitch
    identiques à la vue large) : le grand-angle semble réduire, sur ce site
    et à ce cadrage, la probabilité pratique de tomber dans une zone
    d'azimut sensible — sans que cela change le diagnostic du bug lui-même
    (confirmé indépendant du FOV sur la scène synthétique). `_looks_degraded`
    reste donc actif comme filet de sécurité, pas retiré.
    **Scène synthétique enrichie (repère d'axes coloré, sol en damier, cube à
    6 couleurs par face)** : la disparition reste totale, jamais partielle
    (pas de face manquante isolée -- écarte un problème de culling de face
    unique/normale). Le sol en damier, lui, reste net et correctement projeté
    en perspective à tous les azimuts testés (aucun warp de texture) : seuls
    les petits objets compacts proches de l'origine (repère d'axes, cube)
    disparaissent, jamais la grande dalle qui les entoure. Testé aussi en
    plaçant le repère et le cube sur le **même niveau SH3D** que le sol
    (`level='Terrain'` au lieu de `'Bati propriete'`) : la disparition
    persiste à l'identique -- écarte une cause liée à la structure multi-
    niveaux du `Home` (les 5 niveaux du projet partagent tous `elevation=0`,
    seul `elevationIndex` diffère). La cause reste donc localisée à la façon
    dont un objet (`pieceOfFurniture`) individuel, de petite emprise, est
    transformé/inclus dans la scène exportée à certains azimuts caméra --
    pas une question de niveau, de matériau ou de texture.
    **Distance et taille de l'objet écartées, FOV/pitch confirmés comme
    facteurs réels (session ultérieure, cf. issue #65)** : contrairement à
    la conclusion précédente (FOV testé à seulement 3 valeurs isolées, sans
    effet constaté), un balayage continu montre que FOV (0.5-3.0 rad) et
    pitch (0.0-1.0 rad) déplacent bel et bien les bandes d'azimut mortes,
    par paliers -- le motif ne fait pas que grandir/rétrécir, il **tourne**
    autour du cercle des azimuts jusqu'à une inversion complète en régime
    extrême (FOV=3.0 rad, pitch=1.0 rad, hors usage réel du pipeline). À
    l'inverse, la distance caméra-cible (×10 testé) et la taille de l'objet
    (×16 testé) n'ont strictement aucun effet -- motif de visibilité
    identique bit à bit sur toute la plage testée dans chaque cas. La cause
    ne dépend donc d'aucune propriété relative objet↔caméra, uniquement de
    l'orientation caméra absolue dans le repère du monde (yaw, modulé par
    FOV et pitch) -- un calcul de matrice de vue/frustum plus probable
    qu'un problème de bounding-volume par objet.
    **Levier exploité côté `preview.py` (session ultérieure)** : comme
    distance et taille n'ont aucun effet, `main()` ne fait plus que filtrer
    puis abandonner une vue dégradée -- sur rendu quasi vide, elle retente
    désormais la MÊME vue (même marge/pitch/FOV, donc même cadrage voulu) à
    quelques azimuts voisins (`_offset_sweep(ANGLE_STEP_DEG,
    DEGRADED_RETRY_MAX_OFFSET_DEG)`, ±30° par défaut, 15° de pas) avant de
    l'écarter pour de bon. Portée volontairement bornée (pas un balayage
    360°, coûteux en rendu CI) et **non validée sur un cas réel dégradé** :
    les bandes mortes mesurées sur la scène synthétique font ~100° de large,
    un azimut retombant au milieu d'une bande aussi large resterait hors de
    portée de ce repli à ±30°. `SUSPECT_YAW_BANDS_DEG` (mesurée à une seule
    config FOV/pitch) n'est PAS utilisée pour orienter ce repli -- le
    croisement FOV×pitch ci-dessus montre que ces bandes tournent avec la
    config, une table figée mesurée ailleurs risquerait de désavantager un
    azimut en réalité sûr. Cf. `## Écarts assumés` ci-dessous.

## Écarts assumés

1 écart assumé à ce jour.

| # | Limite concernée | Contexte | Choix assumé |
|---|---|---|---|
| 1 | #12 (vues caméra de `preview.py`) | Investigation ciblée (calibration du soleil, du maillage terrain, de la végétation, de la proximité des bâtiments voisins, du winding/volume signé du maillage terrain, de la structure multi-niveaux du `Home`, de la distance caméra-cible, de la taille de l'objet) : toutes les hypothèses de ce type infirmées, y compris après correction du bug FOV séparé (`FOV_RENDER_CORRECTION` supprimé) -- reproduit à l'identique sur une scène synthétique dédiée (enrichie d'un repère d'axes coloré, d'un sol en damier et d'un cube à 6 couleurs par face pour affiner le diagnostic), sur deux moteurs de rendu indépendants (SunFlow et YafaRay), et que l'objet touché soit sur le même niveau SH3D que le sol ou un niveau différent. En revanche, **FOV et pitch ont un effet réel et mesurable** (déplacent/tournent les bandes d'azimut mortes, jusqu'à inversion en régime extrême) -- la cause ne dépend donc que de l'orientation caméra absolue (yaw × FOV × pitch), jamais d'une propriété de l'objet visé ou de sa distance à la caméra. Caractérisation affinée : la disparition est totale (jamais une seule face), et touche spécifiquement les objets compacts proches de l'origine -- jamais la grande dalle de sol qui les entoure, qui reste nette et correctement projetée à tous les azimuts testés. Sur le site de test réel, le passage au FOV corrigé (grand-angle, 2.0 rad) explique désormais mécaniquement pourquoi un re-balayage complet des azimuts ne reproduit plus la dégradation observée auparavant à yaw=+90° -- effet FOV confirmé, plus une hypothèse. Aucune règle générale n'explique quels azimuts/FOV/pitch/sites restent sûrs, la cause exacte reste dans les moteurs de rendu tiers (boîte noire). | `_viewpoints()` ne génère plus que des vues d'ensemble de la parcelle (large, rapprochée, latérale), jamais les vues par bâtiment (code conservé dans `preview.py` pour référence/reprise future, plus appelé). En complément, `main()` filtre chaque rendu (`_looks_degraded`) ; sur rendu dégradé, retente la même vue à quelques azimuts voisins (`DEGRADED_RETRY_MAX_OFFSET_DEG`, ±30° bornés, non validé sur un cas réel) avant de l'écarter silencieusement -- le pipeline reste donc fiable même si un azimut donné se révèle mauvais sur un site futur, y compris avec le FOV corrigé. |

Le compromis retenu privilégie l'absence d'une vue à une vue ponctuellement
vide ou inexploitable, sur toutes les vues caméra (pas seulement celles par
bâtiment) : mieux vaut publier 1 ou 2 vues d'ensemble fiables que 3 dont une
inutilisable sans que rien ne le signale. Le repli en azimut ne change pas ce
compromis (le filet de sécurité reste `_looks_degraded`), il réduit
seulement, à cadrage identique, la probabilité d'avoir à s'y résoudre.
