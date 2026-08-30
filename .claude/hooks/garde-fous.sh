#!/usr/bin/env bash
# PostToolUse (matcher: Edit|Write) — jamais bloquant, uniquement conseil.
#
# Deux familles d'alerte sur le fichier qui vient d'être écrit :
#   1. Pièges d'environnement documentés dans CLAUDE.md §Environnement
#      (matplotlib/pyvista) — pour les rattraper au moment de l'écriture,
#      avant qu'ils ne cassent l'exécution sur la machine Windows/conda.
#   2. Fuite de confidentialité précoce (même détection que
#      avant-livraison.sh) — pour la signaler dès l'édition plutôt qu'au
#      commit, où elle est plus coûteuse à défaire.
#
# Utilise journaliser_usage() avec ses 3 états utiles ici : "alerte" (trouvé
# et signalé), "muet" (fichier examiné, rien à signaler), "hors-perimetre"
# (type de fichier non concerné par ces contrôles).

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
# shellcheck source=./journal-usage.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/journal-usage.sh"
# shellcheck source=./confidentialite.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/confidentialite.sh"

entree="$(cat)"
fichier="$(jq -r '.tool_input.file_path // empty' <<< "$entree" 2>/dev/null || true)"

if [[ -z "$fichier" || ! -f "$fichier" ]]; then
    journaliser_usage "garde-fous" "hors-perimetre" "fichier introuvable ou absent de tool_input"
    exit 0
fi

contenu="$(cat "$fichier" 2>/dev/null || true)"
alertes=()

if [[ "$fichier" == *.py ]]; then
    grep -qP '^\s*(import\s+matplotlib|from\s+matplotlib)' <<< "$contenu" \
        && alertes+=("matplotlib est interdit dans l'env conda sitegeo (crash DLL Windows, exit -1066598273) — voir CLAUDE.md §Environnement.")
    grep -qP '\bpyvista\.plotting\b|\bPlotter\s*\(' <<< "$contenu" \
        && alertes+=("pyvista.plotting / Plotter(...) sont à éviter (même piège que matplotlib) — voir CLAUDE.md §Environnement.")
    grep -qP '\.plot\s*\(' <<< "$contenu" \
        && alertes+=(".plot(...) est à éviter dans cet env — préférer PIL pour les aperçus (CLAUDE.md §Environnement).")
    grep -qP '\bpv\.Plane\s*\(' <<< "$contenu" \
        && alertes+=("pv.Plane() casse (même cause que matplotlib) — utiliser extrusion + capping comme dans solidify().")
    grep -qP '\bconda\s+run\b' <<< "$contenu" \
        && alertes+=("conda run casse le multi-lignes — appeler <conda>\\envs\\sitegeo\\python.exe directement (CLAUDE.md §Environnement).")
fi

if contient_fuite_confidentielle "$contenu"; then
    alertes+=("Ce fichier contient une valeur de parcelle (commune/section/numéro/coordonnées) trouvée dans config/site.local.toml ou data/meta.json — à retirer avant tout commit (CLAUDE.md §Confidentialité).")
fi

if [[ ${#alertes[@]} -eq 0 ]]; then
    journaliser_usage "garde-fous" "muet" "$fichier"
    exit 0
fi

message="Garde-fous sur $fichier :"
for a in "${alertes[@]}"; do
    message+=$'\n- '"$a"
done

jq -n --arg msg "$message" '{
    hookSpecificOutput: {
        hookEventName: "PostToolUse",
        additionalContext: $msg
    }
}'
journaliser_usage "garde-fous" "alerte" "$fichier"
exit 0
