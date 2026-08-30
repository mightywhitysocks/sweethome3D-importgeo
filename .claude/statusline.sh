#!/usr/bin/env bash
# Ligne de statut : branche git · % de contexte utilisé · lignes modifiées
# cette session. Générique, sans lien avec ce projet en particulier —
# fonctionne pour n'importe quel dépôt Claude Code.
#
# Note : `disableAllHooks` désactive aussi cette ligne de statut (elle est
# elle-même injectée via le mécanisme de hooks).
#
# Pas de seuil de couleur sur le % de contexte, délibérément : à quel point
# un contexte chargé dégrade la qualité dépend fortement de la tâche en
# cours (une tâche répétitive tolère un contexte plus chargé qu'une tâche
# qui demande de tenir beaucoup de contraintes en tête à la fois) — un
# seuil de couleur fixe donnerait une fausse impression de précision.

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

entree="$(cat)"

branche="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')"
pourcentage_contexte="$(jq -r '.context_window.used_percentage // empty' <<< "$entree" 2>/dev/null || true)"
ajouts="$(jq -r '.cost.total_lines_added // 0' <<< "$entree" 2>/dev/null || echo 0)"
retraits="$(jq -r '.cost.total_lines_removed // 0' <<< "$entree" 2>/dev/null || echo 0)"

lignes=$((ajouts + retraits))

if [[ -n "$pourcentage_contexte" ]]; then
    printf '%s · ctx %s%% · %s l.\n' "$branche" "$pourcentage_contexte" "$lignes"
else
    printf '%s · %s l.\n' "$branche" "$lignes"
fi
