#!/usr/bin/env bash
# SessionStart — volontairement minimal ici, contrairement à un bootstrap
# lourd d'environnement. Distinction importante (retrouvée empiriquement
# une fois avant d'être documentée ici, cf. CLAUDE.md §Environnement) :
# `.\run.ps1` lui-même (env conda `sitegeo`, détection de chemins Windows)
# ne tourne pas dans une session distante (conteneur Linux éphémère), MAIS
# le JDK + SweetHome3D.jar + SunFlow (java/Conv.java, java/RenderPhoto.java,
# rendu photo headless via xvfb-run) fonctionnent bien ici et ont été
# validés de bout en bout. Le rôle de ce hook est d'éviter la confusion
# inverse (croire que RIEN ne tourne ici) sans empêcher la lecture/l'édition
# du code.

set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
    exit 0
fi

jq -n '{
    hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: "Session distante : `.\\run.ps1` lui-meme (creation de l'\''env conda sitegeo, detection de chemins Windows) ne s'\''execute pas ici. MAIS le JDK + SweetHome3D.jar + SunFlow (java/Conv.java, java/RenderPhoto.java, rendu photo headless via xvfb-run) fonctionnent dans ce conteneur (JDK deja present ; SweetHome3D.jar + jars de rendu recuperables depuis l'\''archive Linux officielle) et ont ete valides de bout en bout ici (build_home.py -> .sh3d -> rendu SunFlow reel). `./run.sh` (ou un venv pip manuel, `pip install -r config/requirements-venv.txt`, git-suivi) remplace l'\''env conda pour lancer les scripts src/*.py directement, verif.py compris, courbes.py y compris depuis que gdal_contour est detecte via shutil.which (gdal-bin apt) plutot qu'\''un chemin conda Windows en dur. requirements-venv.txt exige maintenant Python >=3.12 (harmonise avec environment.yml, Python 3.14 recommande) : si le python3 par defaut de ce conteneur est reste a 3.11, prevoir un python3.12+ explicite. Detail complet : CLAUDE.md section Environnement. Lecture/edition du code OK dans tous les cas."
    }
}'
exit 0
