#!/usr/bin/env bash
# UserPromptSubmit — jamais bloquant. Classe l'intention du prompt et
# renvoie, au maximum, un pointeur vers la commande slash ou la section de
# CLAUDE.md pertinente. Règle de conception : des pointeurs, jamais du
# contenu (4 lignes max au total) ; silence complet si rien ne correspond ;
# le premier motif qui matche gagne, pas d'empilement.
#
# Lit le champ `.prompt` du JSON stdin (et pas `.user_input`, qui n'existe
# pas dans ce schéma — un hook resté silencieux des semaines pour cette
# raison ailleurs est le genre d'erreur que ce commentaire sert à éviter).

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
# shellcheck source=./journal-usage.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/journal-usage.sh"

entree="$(cat)"
prompt="$(jq -r '.prompt // empty' <<< "$entree" 2>/dev/null || true)"

if [[ -z "$prompt" ]]; then
    journaliser_usage "antiseche" "hors-perimetre" "prompt vide"
    exit 0
fi

pointeur=""

if grep -qiP '\b(livre|livrer|pousse|pousser|committe|commit|merge cette pr|push)\b' <<< "$prompt"; then
    pointeur="Pense à /pousser pour le rituel complet (contrôles -> commit -> push -> PR)."
elif grep -qiP "\b(v[ée]rifie|v[ée]rification|contr[ôo]le|teste|ça marche encore)\b" <<< "$prompt"; then
    pointeur="Pense à /qualite pour le contrôle lecture seule (verif.py + confidentialité)."
elif grep -qiP '\b(r[ée]capitule|reprends|o[uù] on en [ée]tait|r[ée]sume la session|passation)\b' <<< "$prompt"; then
    pointeur="Pense à /point pour une note de passation structurée avant de couper le contexte."
elif grep -qiP "\b([ée]cart|on assume que|on choisit de ne pas|limite connue|d[ée]viation)\b" <<< "$prompt"; then
    pointeur="Pense à /ecart pour journaliser la déviation dans docs/PIPELINE.md."
elif grep -qiP '\b(commune|insee|parcelle|coordonn[ée]es)\b' <<< "$prompt"; then
    pointeur="Rappel confidentialité : voir CLAUDE.md §Confidentialité avant tout commit."
elif grep -qiP '\b(matplotlib|pyvista|plotter|conda run)\b' <<< "$prompt"; then
    pointeur="Voir CLAUDE.md §Environnement pour les pièges connus (matplotlib/pyvista/conda run)."
fi

if [[ -z "$pointeur" ]]; then
    journaliser_usage "antiseche" "muet" "aucun motif reconnu"
    exit 0
fi

jq -n --arg ctx "$pointeur" '{
    hookSpecificOutput: {
        hookEventName: "UserPromptSubmit",
        additionalContext: $ctx
    }
}'
journaliser_usage "antiseche" "alerte" "$pointeur"
exit 0
