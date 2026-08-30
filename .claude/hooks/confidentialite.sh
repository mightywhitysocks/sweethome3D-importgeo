#!/usr/bin/env bash
# Bibliothèque sourcée par avant-livraison.sh (bloquant) et garde-fous.sh
# (conseil). Dérive dynamiquement les valeurs confidentielles à surveiller
# à partir de ce qui existe réellement en local — jamais de commune/INSEE
# codé en dur dans ces scripts, qui sont eux-mêmes versionnés et publics.
#
# Sources, dans l'ordre où elles deviennent disponibles pendant le pipeline :
#   - config/site.local.toml (git-ignored, dès que l'utilisateur configure un site)
#   - data/meta.json (git-ignored, écrit par phase1_cadastre.py)

extraire_motifs_confidentiels() {
    local motifs=()
    local toml="${CLAUDE_PROJECT_DIR}/config/site.local.toml"
    local meta="${CLAUDE_PROJECT_DIR}/data/meta.json"

    if [[ -f "$toml" ]]; then
        local v
        v="$(grep -oP '^\s*insee\s*=\s*"\K[^"]+' "$toml" 2>/dev/null || true)"
        [[ -n "$v" && "$v" != "00000" ]] && motifs+=("$v")
        v="$(grep -oP '^\s*section\s*=\s*"\K[^"]+' "$toml" 2>/dev/null || true)"
        [[ -n "$v" && "$v" != "AA" ]] && motifs+=("$v")
        v="$(grep -oP '^\s*site_name\s*=\s*"\K[^"]+' "$toml" 2>/dev/null || true)"
        [[ -n "$v" && "$v" != "Mon terrain" ]] && motifs+=("$v")
        while IFS= read -r p; do
            [[ -n "$p" && "$p" != "0001" ]] && motifs+=("$p")
        done < <(grep -oP '^\s*(parcels|property_parcel)\s*=.*' "$toml" 2>/dev/null \
                 | grep -oP '"\K[0-9A-Za-z]+' || true)
    fi

    if [[ -f "$meta" ]]; then
        local v
        v="$(grep -oP '"insee"\s*:\s*"\K[^"]+' "$meta" 2>/dev/null || true)"
        [[ -n "$v" ]] && motifs+=("$v")
        v="$(grep -oP '"section"\s*:\s*"\K[^"]+' "$meta" 2>/dev/null || true)"
        [[ -n "$v" ]] && motifs+=("$v")
        v="$(grep -oP '"property_numero"\s*:\s*"\K[^"]+' "$meta" 2>/dev/null || true)"
        [[ -n "$v" ]] && motifs+=("$v")
        while IFS= read -r p; do
            [[ -n "$p" ]] && motifs+=("$p")
        done < <(grep -oP '"numeros"\s*:\s*\[\K[^]]+' "$meta" 2>/dev/null \
                 | grep -oP '"\K[0-9A-Za-z]+' || true)
    fi

    printf '%s\n' "${motifs[@]-}" | sed '/^$/d' | sort -u
}

# Renvoie 0 (et n'affiche rien) si $1 ne contient aucun motif confidentiel
# connu localement ; renvoie 1 sinon. Silencieux quand aucun motif n'est
# disponible (rien à vérifier pour l'instant).
contient_fuite_confidentielle() {
    local contenu="$1"
    local motifs
    motifs="$(extraire_motifs_confidentiels)"
    [[ -z "$motifs" ]] && return 1
    local motif_regex
    motif_regex="$(paste -sd'|' <<< "$motifs")"
    grep -qiE "$motif_regex" <<< "$contenu"
}
