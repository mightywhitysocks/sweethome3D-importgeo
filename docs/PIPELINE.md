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
un aperçu depuis chaque bâtiment de la propriété plus une vue d'ensemble aérienne
(`data/verif/preview_*.png`). `sitegeo.render_photo()` factorise compilation et
lancement, partagé par `verif.py --render` et `preview.py`.

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
6. **Toits pyramidaux simples** (apex au centroïde, pas de faîtage). Les
   bâtiments en L reçoivent un point central. Réglable via `ROOF_RISE_MAX` et
   les facteurs 0,22 / 0,45 de `bati.py`.
7. **Haies taillées** : détectées seulement si végétation basse (< 4 m) et
   étroite (< 4 m) le long de la limite. Une ceinture boisée est rendue en
   **ligne d'arbres** dense à la place.
8. **`matplotlib` interdit** dans l'env (crash DLL) ; **`pv.Plane()` casse**
   (même cause).
9. **Bâtiments de la propriété** : toit multi-pans reconstruit depuis le nuage
   LiDAR HD (`src/roof_lidar.py`, RANSAC + croissance de région + jonctions
   mesurées/analytiques + partition Voronoï + `coverage_simplify`), avec repli
   automatique sur le même toit pyramidal simple que le voisinage si la
   reconstruction n'est pas assez fiable (peu de points, aucun plan détecté,
   partition non close) — jamais de bâtiment propriété sans toit modélisé.
   Sortie : `data/bati_propriete.obj/.mtl` (absent si aucun bâtiment propriété
   trouvé), chargé par `build_home.py` comme le voisinage.
10. **Murs clairs sur-exposés** en lumière rasante (éclairage Sweet Home 3D, le
    matériau est correctement mat).
11. **`run.ps1` lui-même est Windows uniquement** (création de l'env conda,
    détection de chemins d'installation Sweet Home 3D). Les scripts `src/*.py`
    (dont `verif.py`) et le rendu photo headless n'en dépendent pas : ils
    tournent aussi dans un venv pip (`config/requirements-venv.txt`) + JDK,
    y compris en session Claude Code distante (conteneur Linux), cf.
    `CLAUDE.md` section Environnement.
