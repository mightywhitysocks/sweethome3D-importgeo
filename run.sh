#!/usr/bin/env bash
# run.sh - enchaine le pipeline IGN -> Sweet Home 3D dans un venv pip
# (config/requirements-venv.txt). Equivalent Linux/macOS de run.ps1.
#
#   ./run.sh                       # sans argument : menus interactifs
#                                   #   (choix du site si plusieurs configs, choix des etapes)
#   ./run.sh verif                 # juste le controle (lecture seule), sans menu
#   ./run.sh terrain bati          # seulement ces etapes (dans l'ordre donne), sans menu
#   ./run.sh --fresh                # force la recreation de .venv depuis config/requirements-venv.txt
#   ./run.sh --site mon-site.toml   # utilise cette config au lieu de choisir dans un menu
#   ./run.sh --non-interactive      # jamais de prompt (comportement historique : toutes
#                                   #   les etapes, site.local.toml, arret immediat si une
#                                   #   etape echoue) - utile depuis un script/hook
#
# Cree .venv/ depuis config/requirements-venv.txt s'il est absent. Necessite
# aussi un JDK (java/javac) et gdal-bin (apt) / gdal (Homebrew) sur le PATH
# -- cf. README.md > Prerequis.
# Si une etape echoue en mode interactif, propose de reessayer / sauter / arreter.
# La parcelle cible se configure dans config/site.local.toml (git-ignored).
set -uo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

steps_args=()
fresh=0
site=""
non_interactive=0

while [ $# -gt 0 ]; do
  case "$1" in
    --fresh) fresh=1; shift ;;
    --site) [ $# -ge 2 ] || { echo "--site attend un chemin" >&2; exit 1; }; site="$2"; shift 2 ;;
    --non-interactive) non_interactive=1; shift ;;
    *) steps_args+=("$1"); shift ;;
  esac
done

# interactif seulement si on n'a pas coupe le prompt et qu'un terminal est bien attache
interactive=1
[ "$non_interactive" -eq 1 ] && interactive=0
[ -t 0 ] || interactive=0

# --- config de site (parcelle) ---
config_dir="$script_dir/config"
local_cfg="$config_dir/site.local.toml"
if [ -n "$site" ]; then
  [ -f "$site" ] || { echo "config --site introuvable : $site" >&2; exit 1; }
  export SITEGEO_CONFIG="$(cd "$(dirname "$site")" && pwd)/$(basename "$site")"
  echo ">> config site : $SITEGEO_CONFIG"
else
  sites=()
  while IFS= read -r -d '' f; do
    [ "$(basename "$f")" = "site.example.toml" ] && continue
    sites+=("$f")
  done < <(find "$config_dir" -maxdepth 1 -name '*.toml' -print0 | sort -z)

  if [ "${#sites[@]}" -eq 0 ]; then
    cp "$config_dir/site.example.toml" "$local_cfg"
    echo ""
    echo ">> 'config/site.local.toml' vient d'etre cree depuis le gabarit."
    echo ">> Renseignez votre parcelle (insee / section / parcels) puis relancez."
    exit 1
  elif [ "${#sites[@]}" -eq 1 ]; then
    export SITEGEO_CONFIG="${sites[0]}"
  elif [ "$interactive" -eq 1 ]; then
    echo ""
    echo "Plusieurs configs de site trouvees :"
    default_idx=0
    for i in "${!sites[@]}"; do
      n=$((i + 1))
      echo "  $n. $(basename "${sites[$i]}")"
      [ "$(basename "${sites[$i]}")" = "site.local.toml" ] && default_idx=$i
    done
    read -r -p "  -> numero (Entree = $((default_idx + 1))) : " reponse
    idx=$default_idx
    if [ -n "$reponse" ]; then
      if ! [[ "$reponse" =~ ^[0-9]+$ ]] || [ "$reponse" -lt 1 ] || [ "$reponse" -gt "${#sites[@]}" ]; then
        echo "choix de site invalide : $reponse" >&2; exit 1
      fi
      idx=$((reponse - 1))
    fi
    export SITEGEO_CONFIG="${sites[$idx]}"
    echo ">> config site : $SITEGEO_CONFIG"
  else
    # non interactif, plusieurs configs, aucune precisee -> comportement historique
    chosen=""
    for f in "${sites[@]}"; do
      [ "$(basename "$f")" = "site.local.toml" ] && chosen="$f" && break
    done
    [ -z "$chosen" ] && chosen="${sites[0]}"
    export SITEGEO_CONFIG="$chosen"
  fi
fi

# --- venv ---
venv_dir="$script_dir/.venv"
venv_py="$venv_dir/bin/python"
if [ "$fresh" -eq 1 ] && [ -d "$venv_dir" ]; then
  echo ">> suppression de .venv"
  rm -rf "$venv_dir"
fi
if [ ! -x "$venv_py" ]; then
  echo ">> creation de .venv depuis config/requirements-venv.txt (long...)"
  python3 -m venv "$venv_dir" || { echo "echec de la creation de .venv (python3 >= 3.12 requis)." >&2; exit 1; }
  "$venv_py" -m pip install --quiet --upgrade pip || { echo "echec de la mise a jour de pip." >&2; exit 1; }
  "$venv_py" -m pip install -r "$config_dir/requirements-venv.txt" || { echo "echec de l'installation de config/requirements-venv.txt." >&2; exit 1; }
fi

# --- etapes ---
all=(phase1_cadastre terrain bati vegetation courbes build_home)
if [ "${#steps_args[@]}" -eq 0 ]; then
  if [ "$interactive" -eq 1 ]; then
    echo ""
    echo "Etapes disponibles :"
    for i in "${!all[@]}"; do
      echo "  $((i + 1)). ${all[$i]}"
    done
    read -r -p "  -> numeros separes par des virgules (Entree = toutes ; 'verif' = controle seul) : " reponse
    if [ -z "$reponse" ]; then
      run=("${all[@]}")
    elif [ "$reponse" = "verif" ]; then
      run=(verif)
    else
      run=()
      IFS=',' read -r -a nums <<< "$reponse"
      for n in "${nums[@]}"; do
        n="$(echo "$n" | tr -d '[:space:]')"
        [ -z "$n" ] && continue
        if ! [[ "$n" =~ ^[0-9]+$ ]] || [ "$n" -lt 1 ] || [ "$n" -gt "${#all[@]}" ]; then
          echo "choix d'etape invalide : $n" >&2; exit 1
        fi
        run+=("${all[$((n - 1))]}")
      done
      [ "${#run[@]}" -eq 0 ] && { echo "aucune etape selectionnee" >&2; exit 1; }
    fi
  else
    run=("${all[@]}")
  fi
elif [ "${#steps_args[@]}" -eq 1 ] && [ "${steps_args[0]}" = "verif" ]; then
  run=(verif)
else
  run=()
  for s in "${steps_args[@]}"; do
    run+=("${s%.py}")
  done
fi

for s in "${run[@]}"; do
  script="$script_dir/src/$s.py"
  [ -f "$script" ] || { echo "script inconnu : src/$s.py" >&2; exit 1; }
  rejoue=1
  while [ "$rejoue" -eq 1 ]; do
    rejoue=0
    echo ""
    echo "=== $s.py ==="
    "$venv_py" "$script"
    code=$?
    [ "$code" -eq 0 ] && break
    if [ "$interactive" -eq 0 ]; then
      echo "$s.py a echoue (code $code)" >&2
      exit "$code"
    fi
    echo ""
    echo "!! $s.py a echoue (code $code)"
    while true; do
      read -r -p "  -> (r)eessayer / (s)auter / (a)rreter [r] : " choix
      choix="$(echo "${choix:-r}" | tr '[:upper:]' '[:lower:]')"
      case "$choix" in
        r) rejoue=1; break ;;
        s) break ;;
        a) echo "$s.py a echoue (code $code) - arret demande" >&2; exit "$code" ;;
      esac
    done
  done
done
echo ""
echo ">> termine."
