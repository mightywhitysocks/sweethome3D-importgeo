# Génération de `Plan 3D.sh3d` — plan d'exécution et limitations

## Pourquoi ce n'est pas trivial

Le format `.sh3d` est un ZIP qui **doit** contenir une entrée `Home` :
l'objet Java `com.eteks.sweethome3d.model.Home` **sérialisé**. Un `.sh3d` qui ne
contiendrait qu'un `Home.xml` est refusé au chargement. Python ne sait pas
produire cette sérialisation Java → on passe par les propres classes de
Sweet Home 3D.

## Étape 1 — Python (`src/build_home.py`)

Assemble un ZIP intermédiaire `data/_home_raw.zip` :

1. Lit le gabarit neutre `assets/home_template.xml` (en-tête Sweet Home 3D :
   `<environment>`, `<compass>`, caméras, les **5 `<level>`** avec des UUID
   stables) et garde tout jusqu'à `</home>`.
2. Remplace la `<backgroundImage>` du niveau *Cadastre* : image `bg`, échelle
   calée sur `sh3d_payload.json` (0,8 × largeur, origine 0,0).
3. Réoriente le `<compass>` : longitude / latitude (radians) du **centroïde**
   de la bbox WGS84 du site — l'orientation solaire est correcte sans qu'aucune
   coordonnée ne soit stockée dans le dépôt.
4. Monte la caméra observateur de marche à `z_max + 60 cm` (elle ne plonge plus
   sous le terrain — Sweet Home 3D ne fait pas suivre le relief à la caméra).
5. Génère les `<pieceOfFurniture>` : terrain (`data/terrain.obj`), bâti voisinage
   (`data/bati_voisinage.obj`), haies si présentes, et ~1 arbre par entrée de
   `data/vegetation_arbres.json` (tous `model='tree/tree.obj'`, redimensionnés).
   Position / élévation depuis les `*_place.json` et la végétation JSON.
6. Génère les `<room>` : les parcelles (niveau Cadastre) et les emprises au sol
   des bâtiments de la propriété (niveau *Bâti propriété (à modéliser)*).
7. Écrit le ZIP : `Home.xml` + `bg` + dossiers modèles (`t/ b/ h/ tree/`, chaque
   OBJ avec son `.mtl` et sa texture) + une icône. Écrit aussi
   `data/home_source.xml` pour debug / diff.

## Étape 2 — Java (`java/Conv.java`)

1. `_prepare_java()` : copie `SweetHome3D.jar` dans `data/_jconv/` (une fois) et
   compile `Conv.java` (`javac`, en cache par mtime). Le `.jar` est auto-détecté
   (WindowsApps, Program Files) ou pris dans `[tools].sweethome3d_jar`.
2. `java -cp "<jar>;data/_jconv" com.eteks.sweethome3d.io.Conv _home_raw.zip "Plan 3D.sh3d"` :
   - `new HomeContentContext(zipFileUrl, null, true)` (URL fichier simple) ;
   - `HomeXMLHandler` + `handler.setContentContext(ctx)` (méthode package-private
     — d'où `Conv` compilé dans le package `com.eteks.sweethome3d.io` sur le
     classpath) ;
   - SAX-parse `Home.xml` du ZIP → `handler.getHome()` → objet `Home` avec les
     bons niveaux ;
   - `new HomeFileRecorder(9, false).writeHome(home, out)` → `.sh3d` avec `Home`
     sérialisé + `ContentDigests` + entrées modèles numérotées ;
   - relit sa propre sortie (`readHome`) et imprime la répartition par niveau.
3. `build_home.py` sauvegarde l'ancien `.sh3d` en `.sh3d.bak` et supprime
   `_home_raw.zip`.

**Résultat** : `Plan 3D.sh3d` (~2,3 Mo), double-cliquable, 5 calques —
Cadastre / Terrain / Bâti voisinage / Bâti propriété (à modéliser) / Végétation.

## Limitations connues

1. **JVM obligatoire** pour produire le `.sh3d` (`java` + `javac`). La JRE
   embarquée de Sweet Home 3D ne suffit pas (pas de `javac`).
2. **Plugin MCP Sweet Home 3D** : `load_home` / `get_state` / `save_home`
   mésaffichent l'affectation aux niveaux (tout sur un calque). Le fichier
   produit, lui, est correct (prouvé par la relecture `Conv` + l'ouverture
   native). Ne pas vérifier les calques via MCP.
3. **Caméra de visite** : Sweet Home 3D déplace la caméra observateur à altitude
   fixe sur son sol plat (`z = 0`), sans collision avec le terrain importé.
   Contournement : caméra montée à `z_max + 60 cm` ; elle « flotte » dans les
   zones basses. Ajuster avec Pg.Préc / Pg.Suiv en vue 3D.
4. **Ortho plafonnée à 20 cm/px** (résolution HR native IGN). Aspect un peu flou
   aux angles rasants (filtrage de texture du moteur).
5. **Maillage terrain sous-échantillonné à 2 m** (~43 k faces). `terrain_z_at`
   interpole cette grille pour que les objets affleurent la surface *visible* ;
   résidu de calage ~±cm.
6. **Toits pyramidaux simples** (apex au centroïde, pas de faîtage). Les
   bâtiments en L reçoivent un point central. Réglable via `ROOF_RISE_MAX` et
   les facteurs 0,22 / 0,45 de `bati.py`.
7. **Haies taillées** : détectées seulement si végétation basse (< 4 m) et
   étroite (< 4 m) le long de la limite. Une ceinture boisée est rendue en
   **ligne d'arbres** dense à la place.
8. **`matplotlib` interdit** dans l'env (crash DLL) ; **`pv.Plane()` casse**
   (même cause).
9. **Bâtiments de la propriété** = emprises au sol 2D (« à modéliser ») —
   modélisation fine ultérieure (topo + LIDAR + photos + plugin GenerateRoof).
10. **Murs clairs sur-exposés** en lumière rasante (éclairage Sweet Home 3D — le
    matériau est correctement mat).
11. **Windows uniquement** (`run.ps1`, chemins d'installation Sweet Home 3D).
