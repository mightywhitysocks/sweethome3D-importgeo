#!/usr/bin/env bash
# Bibliothèque sourcée par les autres hooks (pas un hook en soi — pas de
# shebang exécuté directement, pas de logique de lecture de stdin ici).
#
# Distinction à 4 états, pas 2 : un hook qui ne dit rien peut être (a) muet
# parce qu'il a bien examiné et n'a rien trouvé, (b) hors périmètre parce
# qu'il n'y avait rien d'applicable à examiner, ou (c) mort silencieusement
# (bug). Sans cette distinction, (a)/(b) et (c) sont indiscernables dans les
# logs alors que les tests restent verts — piège vécu sur des hooks
# comparables ailleurs.
#
#   alerte          : quelque chose a été trouvé et signalé à l'utilisateur.
#   muet            : examen effectué, rien à signaler (résultat réel).
#   hors-perimetre  : rien d'applicable à examiner (silence normal).
#   commande        : une commande slash a été invoquée (métrique d'usage).
#
# Contrat : ne fait jamais échouer l'appelant (avale toute erreur, renvoie
# toujours 0, n'écrit jamais sur stdout — seul le hook appelant parle à
# Claude Code). SITEGEO_USAGE_LOG permet de rediriger le journal en test
# sans polluer le vrai journal.

journaliser_usage() {
    local hook="$1"
    local etat="$2"
    local detail="${3:-}"
    {
        local log_file="${SITEGEO_USAGE_LOG:-$CLAUDE_PROJECT_DIR/.git/sitegeo-usage.log}"
        local horodatage
        horodatage="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        printf '%s\t%s\t%s\t%s\n' "$horodatage" "$hook" "$etat" "$detail" >> "$log_file" 2>/dev/null
    } || true
    return 0
}
