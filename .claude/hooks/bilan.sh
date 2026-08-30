#!/usr/bin/env bash
# Stop — jamais bloquant. N'utilise jamais `decision: "block"` : sur un hook
# Stop, ça forcerait Claude à continuer et créerait une boucle. Un simple
# rappel texte, au plus une fois par changement d'état (mémorisé dans
# .git/sitegeo-bilan), suffit.
#
# Rappelle, dans l'ordre de priorité :
#   1. le contrôle qualité (verif.py) n'a pas été rejoué depuis la dernière
#      édition de src/ (ou n'a jamais tourné, ou a échoué la dernière fois) ;
#   2. des commits existent localement mais n'ont pas été poussés ;
#   3. des modifications sont en attente (non commitées).

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$CLAUDE_PROJECT_DIR" || exit 0
# shellcheck source=./journal-usage.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/journal-usage.sh"

JALON="$CLAUDE_PROJECT_DIR/.git/sitegeo-qualite-ok"
ETAT_PRECEDENT="$CLAUDE_PROJECT_DIR/.git/sitegeo-bilan"

lignes=()

if [[ ! -f "$JALON" ]]; then
    lignes+=("le contrôle qualité (verif.py) n'a jamais été rejoué depuis le début de session")
elif [[ -d src ]]; then
    dernier_edit_src="$(find src -name '*.py' -newer "$JALON" 2>/dev/null | head -1)"
    [[ -n "$dernier_edit_src" ]] && lignes+=("src/ a été modifié depuis le dernier verif.py réussi — à rejouer avant de livrer")
fi

if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' &>/dev/null; then
    non_pousses="$(git log '@{u}..HEAD' --oneline 2>/dev/null | wc -l | tr -d ' ')"
    [[ "$non_pousses" -gt 0 ]] && lignes+=("$non_pousses commit(s) local(aux) non poussé(s)")
fi

if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
    lignes+=("des modifications ne sont pas commitées")
fi

if [[ ${#lignes[@]} -eq 0 ]]; then
    journaliser_usage "bilan" "muet" "rien à signaler"
    rm -f "$ETAT_PRECEDENT"
    exit 0
fi

etat_actuel="$(printf '%s\n' "${lignes[@]}" | md5sum | cut -d' ' -f1)"
if [[ -f "$ETAT_PRECEDENT" && "$(cat "$ETAT_PRECEDENT")" == "$etat_actuel" ]]; then
    journaliser_usage "bilan" "muet" "état inchangé depuis le dernier rappel"
    exit 0
fi
echo "$etat_actuel" > "$ETAT_PRECEDENT"

message="Avant de livrer :"
for l in "${lignes[@]}"; do
    message+=$'\n- '"$l"
done
echo "$message"
journaliser_usage "bilan" "alerte" "rappel affiché"
exit 0
