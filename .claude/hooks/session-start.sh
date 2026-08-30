#!/usr/bin/env bash
# SessionStart — volontairement minimal ici, contrairement à un bootstrap
# lourd d'environnement : ce pipeline cible une machine Windows avec un env
# conda `sitegeo` et un JDK pour java/Conv.java (voir CLAUDE.md
# §Environnement) — rien de tout ça ne tourne dans une session Claude Code
# distante (conteneur Linux éphémère). Le seul rôle de ce hook est d'éviter
# la confusion : signaler que le pipeline lui-même (`.\run.ps1`) n'est pas
# exécutable ici, sans empêcher la lecture/l'édition du code.

set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
    exit 0
fi

jq -n '{
    hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: "Session distante : le pipeline (.\\run.ps1, conda sitegeo, JDK) cible une machine Windows locale et ne s'\''exécute pas dans ce conteneur. Lecture/édition du code OK ; `.\\run.ps1` et `verif.py` ne peuvent pas être lancés ici."
    }
}'
exit 0
