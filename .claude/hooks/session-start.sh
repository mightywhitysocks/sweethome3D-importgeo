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
        additionalContext: "Session distante : `.\\run.ps1` lui-meme (creation de l'\''env conda sitegeo, detection de chemins Windows) ne s'\''execute pas ici. MAIS le JDK + SweetHome3D.jar + SunFlow (java/Conv.java, java/RenderPhoto.java, rendu photo headless via xvfb-run) fonctionnent dans ce conteneur (JDK deja present ; SweetHome3D.jar + jars de rendu recuperables depuis l'\''archive Linux officielle) et ont ete valides de bout en bout ici (build_home.py -> .sh3d -> rendu SunFlow reel). Un venv pip (`pip install -r config/requirements-venv.txt`, git-suivi) remplace l'\''env conda pour lancer les scripts src/*.py directement, verif.py compris (valide de bout en bout : seul echec observe = data/*.json absent quand le pipeline n'\''a pas encore tourne, non bloquant) ; seul gdal_contour.exe (courbes.py) reste indisponible (binaire GDAL Windows), sans bloquer build_home.py. Detail complet : CLAUDE.md section Environnement. Lecture/edition du code OK dans tous les cas."
    }
}'
exit 0
