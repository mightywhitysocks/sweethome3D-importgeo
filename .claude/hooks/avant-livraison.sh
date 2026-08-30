#!/usr/bin/env bash
# PreToolUse — bloquant. Matcher (settings.json) : Bash |
# mcp__github__create_pull_request | mcp__github__update_pull_request |
# mcp__github__merge_pull_request.
#
# Mécanise 3 règles déjà énoncées en prose dans CLAUDE.md, qu'un humain
# pressé oublie plus facilement qu'un hook :
#   1. Confidentialité (règle n°1 du projet) : jamais de commune / code
#      INSEE / section / numéro de parcelle / coordonnées dans un commit,
#      un push ou une PR.
#   2. Jamais de push direct sur `main`.
#   3. Jamais `--force` ni `git merge` / fusion de PR par Claude sans accord.
#
# Design deny/ask : on ne "deny" que ce qui n'est jamais légitime. Un commit
# de confidentialité est ambigu à 100% (le projet n'a aucune raison légitime
# d'en avoir un) -> deny direct plutôt qu'ask, contrairement à un usage plus
# général où on réserverait deny aux cas sans aucune exception possible.
#
# Limite connue : les motifs de confidentialité sont dérivés des valeurs
# trouvées localement (config/site.local.toml, data/meta.json) — jamais
# codés en dur ici. Si ni l'un ni l'autre n'existe encore (tout début de
# pipeline), ce hook n'a rien à vérifier et laisse passer : le grep manuel
# de CLAUDE.md reste la dernière ligne de défense, et le workflow CI
# `confidentialite` fait un backstop plus générique côté PR.

set -euo pipefail
export LANG=C.UTF-8 LC_ALL=C.UTF-8

CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
# shellcheck source=./journal-usage.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/journal-usage.sh"
# shellcheck source=./confidentialite.sh
source "$CLAUDE_PROJECT_DIR/.claude/hooks/confidentialite.sh"

entree="$(cat)"
outil="$(jq -r '.tool_name // empty' <<< "$entree" 2>/dev/null || true)"

deny() {
    local raison="$1"
    jq -n --arg raison "$raison" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "deny",
            permissionDecisionReason: $raison
        }
    }'
    journaliser_usage "avant-livraison" "alerte" "$raison"
    exit 0
}

verifier_confidentialite() {
    local contenu="$1"
    if contient_fuite_confidentielle "$contenu"; then
        deny "Confidentialité (CLAUDE.md §Confidentialité) : le contenu vérifié contient une valeur de parcelle (commune/section/numéro/coordonnées) trouvée dans config/site.local.toml ou data/meta.json. Ces données ne doivent jamais apparaître dans un commit, un push ou une PR."
    fi
    return 0
}

if [[ "$outil" == "Bash" ]]; then
    commande="$(jq -r '.tool_input.command // empty' <<< "$entree" 2>/dev/null || true)"

    if grep -qP '(^|[;&|]\s*)git\s+merge\b' <<< "$commande"; then
        deny "git merge est interdit (CLAUDE.md §git) : jamais de fusion sans l'accord explicite de l'utilisateur."
    fi

    if grep -qP '(^|[;&|]\s*)git\s+push\b' <<< "$commande"; then
        if grep -qP '(--force\b|-f\b|--force-with-lease\b)' <<< "$commande"; then
            deny "git push --force est interdit (CLAUDE.md §git)."
        fi
        branche_courante="$(git -C "$CLAUDE_PROJECT_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
        if grep -qP '\bmain\b' <<< "$commande" \
           || { [[ "$branche_courante" == "main" ]] && ! grep -qP '\S+\s+\S+:\S+|\S+\s+refs/' <<< "$commande"; }; then
            deny "Push direct sur main interdit (CLAUDE.md §git) : passer par une PR."
        fi
        # Défense en profondeur : recontrôle les commits sur le point d'être
        # poussés, en plus du contrôle fait à git commit. Best-effort : si
        # origin/main n'est pas connu localement, on ne bloque pas dessus.
        base="$(git -C "$CLAUDE_PROJECT_DIR" merge-base HEAD origin/main 2>/dev/null || true)"
        if [[ -n "$base" ]]; then
            diff_a_pousser="$(git -C "$CLAUDE_PROJECT_DIR" diff "$base"..HEAD -- . ':!data' 2>/dev/null || true)"
            verifier_confidentialite "$diff_a_pousser"
        fi
    fi

    if grep -qP '(^|[;&|]\s*)git\s+commit\b' <<< "$commande"; then
        diff_index="$(git -C "$CLAUDE_PROJECT_DIR" diff --cached -- . ':!data' 2>/dev/null || true)"
        verifier_confidentialite "$diff_index"
        # Le message de commit (-m "...") n'apparaît pas dans le diff.
        message="$(grep -oP -- '-m\s+"\K[^"]*' <<< "$commande" || true)"
        [[ -n "$message" ]] && verifier_confidentialite "$message"
    fi
elif [[ "$outil" == "mcp__github__merge_pull_request" ]]; then
    deny "Fusion de PR par Claude interdite (CLAUDE.md §git) : jamais de merge sans l'accord explicite de l'utilisateur."
elif [[ "$outil" == "mcp__github__create_pull_request" || "$outil" == "mcp__github__update_pull_request" ]]; then
    titre="$(jq -r '.tool_input.title // empty' <<< "$entree" 2>/dev/null || true)"
    corps="$(jq -r '.tool_input.body // empty' <<< "$entree" 2>/dev/null || true)"
    verifier_confidentialite "$titre"$'\n'"$corps"
fi

journaliser_usage "avant-livraison" "muet" "$outil"
exit 0
