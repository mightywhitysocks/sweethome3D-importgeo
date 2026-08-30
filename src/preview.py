"""
preview.py — apercus photo depuis les batiments de la propriete (post-build).

Rend `Plan 3D.sh3d` depuis plusieurs points de vue via le moteur SunFlow de Sweet
Home 3D (comme "Creer photo") : un apercu par batiment de la propriete (camera au
centre de l'emprise, hauteur d'oeil, visant le centre de la parcelle) + une vue
d'ensemble. Sorties : `data/verif/preview_*.png`.

Optionnel : ne fait rien si le JDK ou les jars de rendu manquent
(cf. sitegeo.render_photo). Prerequis : le pipeline a tourne (`.\run.ps1`).

  python src/preview.py             # 1024x640, qualite rapide
  python src/preview.py 1280 800    # taille au choix
  python src/preview.py 1280 800 high
"""
from __future__ import annotations

import json
import math
import sys

import sitegeo as cg

CAM_UP_CM = 250.0        # camera au-dessus du sol (vue "1er etage", moins rasante)
PITCH = 0.28             # legere plongee -> moins de terrain en lumiere rasante


def _viewpoints():
    """[(label, (x, y, z, yaw, pitch)), ...] en repere plan SH3D (cm / rad)."""
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    tx, ty = prop["centroid_cm"] if prop else (0.0, 0.0)

    views = []
    for i, b in enumerate(props):
        cx, cy = b["centroid_cm"]
        z = cg.terrain_z_at(cx, cy) + CAM_UP_CM
        yaw = math.atan2(tx - cx, ty - cy)          # vise le centre de la parcelle
        views.append((f"bati{i}_{b['id'][-4:]}", (cx, cy, z, yaw, PITCH)))
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
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json — lancer bati.py.")

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