# `mobile_compat_check` : verifier qu'un `.sh3d` s'ouvre sur l'appli mobile

Outil **autonome**, sans lien avec le pipeline principal (meme principe que
`tools/lidar_view/`) :

- aucun `import sitegeo` ;
- ses propres dependances (`package.json` Node) ;
- ne touche jamais a `data/`, `Plan 3D.sh3d`, ni a `run.sh`/`run.ps1` ;
- utilise le JDK et le `SweetHome3D.jar` deja requis par le pipeline
  principal (cf. `README.md` racine), rien de plus a installer cote Java.

## Pourquoi

L'appli mobile Sweet Home 3D (eTeks, Google Play / App Store) et
**Sweet Home 3D Online** partagent le meme moteur JS, `SweetHome3DJS`
(transpile depuis le code Java via **JSweet**). Ce moteur sait **parser du
XML** (`Home.xml`, via un `HomeXMLHandler` transpile) mais ne sait **pas
deserialiser l'entree Java `Home`** (`ObjectInputStream`, sans equivalent
JS) que `java/Conv.java` ecrit seule dans `Plan 3D.sh3d` via
`HomeFileRecorder`. Confirme empiriquement avec cet outil : un `.sh3d` sans
entree `Home.xml` echoue au chargement cote moteur mobile avec l'erreur
`No Home.xml entry`, alors qu'il s'ouvre normalement sur le desktop.

**Correctif applique dans `java/Conv.java`** : `HomeFileRecorder(9, false,
null, false, true, false)` (`preferXmlEntry=true`) fait ecrire, EN PLUS de
l'entree `Home` serialisee (seule lue par le desktop), une entree
`Home.xml` (via `HomeXMLExporter`, integre a `SweetHome3D.jar` -- pas une
reconstruction maison, donc les chemins de modeles renumerotes par
`ContentDigests` sont deja corrects). Sans impact sur le desktop : il
continue de lire l'entree `Home` en priorite. Un seul fichier `.sh3d`
reste donc compatible desktop **et** mobile/Online, sans dupliquer aucun
contenu.

## Ce que verifie cet outil

Charge un `.sh3d` dans le **vrai moteur JS officiel eTeks**
(`lib/sweethome3djsviewer/lib/*.min.js`, embarque par le paquet npm
`@node-projects/sweethome3d-webcomponent`, GPL-2.0 -- meme licence que
`arbaro`, appele ici en sous-processus/page web isolee, aucun code lie
dans le depot) via Chromium headless (Playwright), et rapporte
succes/echec explicite (erreurs console + exceptions JS non catchees +
capture d'ecran).

## Utilisation

```bash
cd tools/mobile_compat_check
npm install

# 1. construit fixture.sh3d (plan synthetique commite dans fixture/,
#    aucune donnee geographique reelle -- cube + pyramide + 3 niveaux +
#    furnitureGroup + room + image de fond) :
python3 build_fixture.py --sh3d-jar /chemin/vers/SweetHome3D.jar

# 2. verifie le chargement cote moteur mobile :
node check.mjs _build/fixture.sh3d --screenshot _build/fixture.png

# 3. sur le vrai plan genere par le pipeline (jamais commite) :
node check.mjs "../../Plan 3D.sh3d"
```

`SweetHome3D.jar` n'est pas fourni par ce depot : cf. `README.md` racine
(prerequis JDK + Sweet Home 3D installe), ou recuperer l'archive Linux
officielle `SweetHome3D-<version>-linux-x64.tgz` depuis SourceForge
(`lib/SweetHome3D.jar`) -- meme source que documentee dans `CLAUDE.md`
section Environnement pour une session Claude Code distante.

## Limites connues

- **Format verifie de bout en bout** (fixture synthetique : niveaux
  multiples, `furnitureGroup`, modeles OBJ/MTL personnalises
  multi-materiaux avec la convention `.mtl` du projet -- `Ka 0`/`Ks 0`/
  `Ns 1`/`illum 1`, `backgroundImage`, `room`) : chargement propre, zero
  erreur, rendu visuellement coherent (capture d'ecran).
- **Pas encore verifie sur le vrai `Plan 3D.sh3d`** d'un site reel (pas de
  site configure dans la session qui a ecrit cet outil, confidentialite) :
  le poids geometrique cumule reel (terrain ~43k faces, toits `roofer`
  multi-batiments, jusqu'a ~76 arbres `arbaro`) n'a pas ete teste sur ce
  moteur -- performance/fluidite sur mobile restent a observer sur un run
  complet (`node check.mjs "Plan 3D.sh3d"` depuis ce dossier).
- Ce test verifie le **chargement**, pas l'identite visuelle exacte au
  pixel pres avec le rendu desktop (Java3D) ni avec l'appli mobile native
  elle-meme (webview/moteur natif potentiellement legerement different du
  Chromium utilise ici) -- une verification manuelle sur un vrai appareil
  reste la validation ultime, non substituable.
