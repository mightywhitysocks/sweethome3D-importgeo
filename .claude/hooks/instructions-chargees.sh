#!/usr/bin/env bash
# InstructionsLoaded — journalise, horodaté, ce qui a réellement été chargé
# en contexte (CLAUDE.md, .claude/rules/*.md à portée de fichiers, etc.),
# pour transformer un mécanisme autrement opaque en historique consultable
# (utile pour /point, et pour diagnostiquer un rappel qui ne se recharge
# pas après une compaction). Capé à 400 lignes dès que le fichier dépasse
# 500, pour ne jamais grossir indéfiniment.

set -uo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
LOG="$CLAUDE_PROJECT_DIR/.git/sitegeo-instructions.log"

entree="$(cat)"
horodatage="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '%s\t%s\n' "$horodatage" "$entree" >> "$LOG" 2>/dev/null || true

if [[ -f "$LOG" ]]; then
    n="$(wc -l < "$LOG" 2>/dev/null || echo 0)"
    if [[ "$n" -gt 500 ]]; then
        tail -n 400 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
    fi
fi
exit 0
