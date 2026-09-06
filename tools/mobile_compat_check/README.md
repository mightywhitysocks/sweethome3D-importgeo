# `mobile_compat_check` : vérifier qu'un `.sh3d` s'ouvre sur l'appli mobile

Outil **autonome**, sans lien avec le pipeline principal (même principe que
`tools/lidar_view/`) :

- aucun `import sitegeo` ;
- ses propres dépendances (`package.json` Node) ;
- ne touche jamais à `data/`, `Plan 3D.sh3d`, ni à `run.sh`/`run.ps1` ;
- utilise le JDK et le `SweetHome3D.jar` déjà requis par le pipeline
  principal (cf. `README.md` racine), rien de plus à installer côté Java.

## Pourquoi

L'appli mobile Sweet Home 3D (eTeks, Google Play / App Store) et
**Sweet Home 3D Online** partagent le même moteur JS, `SweetHome3DJS`
(transpilé depuis le code Java via **JSweet**). Ce moteur sait **parser du
XML** (`Home.xml`, via un `HomeXMLHandler` transpilé) mais ne sait **pas
désérialiser l'entrée Java `Home`** (`ObjectInputStream`, sans équivalent
JS) que `java/Conv.java` écrit seule dans `Plan 3D.sh3d` via
`HomeFileRecorder`.

Confirmé empiriquement avec cet outil : un `.sh3d` sans entrée `Home.xml`
échoue au chargement côté moteur mobile avec l'erreur `No Home.xml entry`,
alors qu'il s'ouvre normalement sur le desktop.

**Correctif appliqué dans `java/Conv.java`** : `HomeFileRecorder(9, false,
null, false, true, false)` (`preferXmlEntry=true`) fait écrire, en plus de
l'entrée `Home` sérialisée (seule lue par le desktop), une entrée
`Home.xml` (via `HomeXMLExporter`, intégré à `SweetHome3D.jar`, pas une
reconstruction maison : les chemins de modèles renumérotés par
`ContentDigests` sont donc déjà corrects). Sans impact sur le desktop : il
continue de lire l'entrée `Home` en priorité. Un seul fichier `.sh3d` reste
donc compatible desktop **et** mobile/Online, sans dupliquer aucun contenu.

## Ce que vérifie cet outil

Charge un `.sh3d` dans le **vrai moteur JS officiel eTeks**
(`lib/sweethome3djsviewer/lib/*.min.js`, embarqué par le paquet npm
`@node-projects/sweethome3d-webcomponent`, GPL-2.0, même licence que
`arbaro`, appelé ici en sous-processus/page web isolée, aucun code lié dans
le dépôt) via Chromium headless (Playwright), et rapporte succès/échec
explicite (erreurs console + exceptions JS non catchées + capture d'écran).

## Utilisation

```bash
cd tools/mobile_compat_check
npm install

# 1. construit fixture.sh3d (plan synthétique commité dans fixture/,
#    aucune donnée géographique réelle : cube + pyramide + 3 niveaux +
#    furnitureGroup + room + image de fond) :
python3 build_fixture.py --sh3d-jar /chemin/vers/SweetHome3D.jar

# 2. vérifie le chargement côté moteur mobile :
node check.mjs _build/fixture.sh3d --screenshot _build/fixture.png

# 3. sur le vrai plan généré par le pipeline (jamais commité) :
node check.mjs "../../Plan 3D.sh3d"
```

`SweetHome3D.jar` n'est pas fourni par ce dépôt. Voir `README.md` racine
(prérequis JDK + Sweet Home 3D installé), ou récupérer l'archive Linux
officielle `SweetHome3D-<version>-linux-x64.tgz` depuis SourceForge
(`lib/SweetHome3D.jar`), même source que documentée dans `CLAUDE.md` >
Environnement pour une session Claude Code distante.

## Limites connues

- **Format vérifié de bout en bout** (fixture synthétique : niveaux
  multiples, `furnitureGroup`, modèles OBJ/MTL personnalisés
  multi-matériaux avec la convention `.mtl` du projet : `Ka 0`/`Ks 0`/
  `Ns 1`/`illum 1`, `backgroundImage`, `room`) : chargement propre, zéro
  erreur, rendu visuellement cohérent (capture d'écran).
- **Pas encore vérifié sur le vrai `Plan 3D.sh3d`** d'un site réel (pas de
  site configuré dans la session qui a écrit cet outil, confidentialité) :
  le poids géométrique cumulé réel (terrain ~43k faces, toits `roofer`
  multi-bâtiments, jusqu'à ~76 arbres `arbaro`) n'a pas été testé sur ce
  moteur. Performance/fluidité sur mobile restent à observer sur un run
  complet (`node check.mjs "Plan 3D.sh3d"` depuis ce dossier).
- Ce test vérifie le **chargement**, pas l'identité visuelle exacte au
  pixel près avec le rendu desktop (Java3D) ni avec l'appli mobile native
  elle-même (webview/moteur natif potentiellement légèrement différent du
  Chromium utilisé ici) : une vérification manuelle sur un vrai appareil
  reste la validation ultime, non substituable.
