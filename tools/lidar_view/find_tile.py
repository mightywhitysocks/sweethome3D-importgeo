"""
find_tile.py : aide a localiser la/les dalle(s) du nuage de points LiDAR HD
brut couvrant une emprise Lambert-93 donnee.

Outil autonome, decouple du pipeline principal (aucun `import sitegeo`,
aucune dependance a l'env conda `sitegeo`). Utilise le meme serveur WFS que
src/sitegeo.py (data.geopf.fr), deja connu pour repondre a ce type de
requetes dans ce depot -- mais le nom exact de la couche d'index des dalles
LiDAR HD n'est PAS fige en dur ici : ce script l'interroge dynamiquement via
GetCapabilities pour eviter de coder une reference qui casserait si IGN la
renomme.

Si aucune couche n'est trouvee automatiquement (catalogue different de ce
qui a ete observe lors de l'ecriture de ce script), repli manuel : ouvrir la
page du jeu de donnees LiDAR HD, onglet Telechargement, reperer a l'oeil la
dalle 1 km x 1 km qui couvre l'emprise et la telecharger a la main -- puis
donner son chemin local a view_point_cloud.py avec --laz.

Usage :
    python find_tile.py E0 N0 E1 N1        (Lambert-93, metres, EPSG:2154)

Ne jamais passer une emprise codee en dur dans un fichier versionne : lire
les coordonnees depuis data/ (git-ignore) ou config/site.local.toml au
moment de l'appel, en ligne de commande uniquement.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import requests

WFS_URL = "https://data.geopf.fr/wfs/ows"
TIMEOUT_S = 30


def list_lidar_layers() -> list[str]:
    r = requests.get(WFS_URL, params={
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities",
    }, timeout=TIMEOUT_S)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    names = {n.text for n in root.iter() if n.tag.endswith("Name") and n.text}
    return sorted(n for n in names if "LIDAR" in n.upper() or "DALLE" in n.upper())


def query_bbox(layer: str, bbox_l93: tuple[float, float, float, float]) -> dict:
    e0, n0, e1, n1 = bbox_l93
    r = requests.get(WFS_URL, params={
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": layer, "SRSNAME": "EPSG:2154",
        "BBOX": f"{e0},{n0},{e1},{n1},EPSG:2154",
        "OUTPUTFORMAT": "application/json",
    }, timeout=TIMEOUT_S * 2)
    r.raise_for_status()
    return r.json()


def main() -> None:
    if len(sys.argv) != 5:
        raise SystemExit(__doc__)
    bbox = tuple(float(a) for a in sys.argv[1:5])

    layers = list_lidar_layers()
    if not layers:
        raise SystemExit(
            "Aucune couche WFS contenant 'LIDAR'/'DALLE' trouvee via GetCapabilities "
            f"sur {WFS_URL}.\n"
            "Repli manuel : page du jeu de donnees -> onglet Telechargement -> "
            "reperer la dalle 1 km x 1 km sur l'emprise -> la telecharger a la main, "
            "puis passer son chemin a view_point_cloud.py avec --laz.")

    print("couches candidates :", layers)
    any_hit = False
    for layer in layers:
        try:
            data = query_bbox(layer, bbox)
        except requests.RequestException as exc:
            # Le catalogue expose plusieurs couches candidates (MNT/MNS/MNH,
            # metadata, dalle du nuage brut...) interrogees en sequence : un
            # incident reseau transitoire sur l'une d'elles ne doit pas faire
            # perdre les reponses deja obtenues des autres.
            print(f"\n{layer} : requete echouee ({exc}), couche ignoree")
            continue
        feats = data.get("features", [])
        print(f"\n{layer} : {len(feats)} entite(s) sur l'emprise")
        for f in feats:
            print(" ", f.get("properties", {}))
            any_hit = True

    if not any_hit:
        print(
            "\nAucune entite retournee : verifier l'emprise (Lambert-93, EPSG:2154) "
            "ou basculer sur le repli manuel decrit dans le docstring.")


if __name__ == "__main__":
    main()
