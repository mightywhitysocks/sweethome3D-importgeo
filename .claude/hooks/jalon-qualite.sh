#!/usr/bin/env bash
# PostToolUse (matcher: Bash) — jamais bloquant.
#
# Repère l'exécution du contrôle qualité du projet (`src/verif.py` ou
# `.\run.ps1 verif`) et pose/retire un fichier jalon dans .git/ selon le
# succès ou l'échec, pour que bilan.sh (hook Stop) puisse dire si le
# contrôle a été rejoué depuis la dernière édition de src/.

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
# shellcheck source=./journal-usage.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/journal-usage.sh"

JALON="$CLAUDE_PROJECT_DIR/.git/sitegeo-qualite-ok"

entree="$(cat)"
commande="$(jq -r '.tool_input.command // empty' <<< "$entree" 2>/dev/null || true)"

if ! grep -qP '(verif\.py|run\.ps1\s+verif)\b' <<< "$commande"; then
    journaliser_usage "jalon-qualite" "hors-perimetre" "commande non liée à verif"
    exit 0
fi

# Schéma de tool_response non garanti d'un hook à l'autre : on regarde à la
# fois un éventuel exitCode explicite et, à défaut, des marqueurs textuels
# dans la sortie capturée par le harness.
sortie="$(jq -r '[.tool_response.stdout, .tool_response.output, .tool_response.stderr] | map(select(. != null)) | join("\n")' <<< "$entree" 2>/dev/null || true)"
code_sortie="$(jq -r '.tool_response.exitCode // .tool_response.exit_code // empty' <<< "$entree" 2>/dev/null || true)"

echec=0
if [[ -n "$code_sortie" && "$code_sortie" != "0" ]]; then
    echec=1
elif grep -qP 'Traceback \(most recent call last\)|^FAIL\b' <<< "$sortie"; then
    echec=1
fi

if [[ "$echec" -eq 1 ]]; then
    rm -f "$JALON"
    journaliser_usage "jalon-qualite" "alerte" "verif en echec"
else
    touch "$JALON"
    journaliser_usage "jalon-qualite" "muet" "verif en succes"
fi
exit 0
