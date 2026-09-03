"""
preview.py : apercus photo depuis les batiments de la propriete (post-build).

Rend `Plan 3D.sh3d` depuis plusieurs points de vue via le moteur SunFlow de Sweet
Home 3D (comme "Creer photo") : un apercu par batiment de la propriete (camera au
centre de l'emprise, hauteur d'oeil, visant le centre de la parcelle) + une vue
d'ensemble. Sorties : `data/verif/preview_*.png`.

Optionnel : ne fait rien si le JDK ou les jars de rendu manquent
(cf. sitegeo.render_photo). Prerequis : le pipeline a tourne (`./run.sh`,
cf. CLAUDE.md section Environnement).

  python src/preview.py             # 1024x640, qualite rapide
  python src/preview.py 1280 800    # taille au choix
  python src/preview.py 1280 800 high
"""
from __future__ import annotations

import json
import math
import sys

from shapely.geometry import Point, Polygon

import sitegeo as cg

CAM_UP_CM = 250.0        # camera au-dessus du sol (vue "1er etage", moins rasante)
PITCH = 0.28             # legere plongee -> moins de terrain en lumiere rasante
STANDOFF_STEP_CM = 300.0
STANDOFF_MAX_CM = 4000.0  # garde-fou : au-dela, on rend quand meme (mieux qu'une boucle infinie)


def _viewpoints():
    """[(label, (x, y, z, yaw, pitch)), ...] en repere plan SH3D (cm / rad)."""
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    tx, ty = prop["centroid_cm"] if prop else (0.0, 0.0)

    # tous les batiments propriete ont maintenant un vrai mur/toit modelise
    # (toit LiDAR ou repli pyramidal, cf. bati.py) : une camera doit eviter
    # TOUTES leurs emprises, pas seulement la sienne -- des batiments proches
    # (ex. dependances cote a cote) font qu'un simple ecart au rayon de son
    # propre contour retombe pile dans le voisin (constate en conditions
    # reelles : rendu noir persistant sur un batiment tant que seule sa
    # propre emprise etait prise en compte).
    footprints = [Polygon(b["rings_cm"][0]) for b in props if len(b["rings_cm"]) == 1]

    views = []
    for i, b in enumerate(props):
        cx, cy = b["centroid_cm"]
        yaw = math.atan2(tx - cx, ty - cy)          # vise le centre de la parcelle
        radius = max((math.hypot(x - cx, y - cy) for ring in b["rings_cm"] for x, y in ring),
                     default=0.0)
        standoff = radius + 100.0
        cap = radius + STANDOFF_MAX_CM
        while True:
            s = min(standoff, cap)
            px, py = cx + s * math.sin(yaw), cy + s * math.cos(yaw)
            # garde-fou : au plafond, on rend quand meme avec le point clampe
            # (jamais un point rejete a un recul moindre) -- mieux qu'une
            # boucle infinie si tous les points candidats tombent dans
            # l'emprise d'un batiment.
            if s >= cap or not any(fp.contains(Point(px, py)) for fp in footprints):
                break
            standoff += STANDOFF_STEP_CM
        z = cg.terrain_z_at(px, py) + CAM_UP_CM
        views.append((f"bati{i}_{b['id'][-4:]}", (px, py, z, yaw, PITCH)))
    if props:
        # vue d'ensemble : aerienne au-dessus du barycentre des batiments de la
        # propriete (l'ortho drapee se lit bien vue de haut, mal a hauteur d'oeil).
        bx = sum(b["centroid_cm"][0] for b in props) / len(props)
        by = sum(b["centroid_cm"][1] for b in props) / len(props)
        views.append(("ensemble", (bx, by + 1500.0,
                                   cg.terrain_z_at(bx, by) + 3500.0, 0.0, 1.0)))
    return views


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    quality = sys.argv[3] if len(sys.argv) > 3 else "low"

    views = _viewpoints()
    if not views:
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json ; lancer bati.py.")

    done = []
    for label, cam in views:
        out = cg.render_photo(cg.VERIF / f"preview_{label}.png",
                              camera=cam, size=(w, h), quality=quality)
        print(f"  {label:16} -> {('OK  ' + out.name) if out else 'indisponible / echec'}")
        if out:
            done.append(out)
    print(f"\n>>> {len(done)}/{len(views)} apercus -> {cg.VERIF}")
    if not done:
        raise SystemExit(1)


if __name__ == "__main__":
    main()