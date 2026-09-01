"""
roof_focus_render.py : rendus aeriens obliques centres sur chaque batiment de la
propriete, cadres pour bien lire la toiture (angle plus eleve/plus rapproche que
preview.py qui vise des vues "1er etage"). Sorties : data/verif/roof_*.png.

  python src/roof_focus_render.py             # 1280x800, qualite rapide
  python src/roof_focus_render.py 1600 1000 high
"""
from __future__ import annotations

import json
import math
import sys

from shapely.geometry import Point, Polygon

import sitegeo as cg

CAM_UP_ROOF_CM = 900.0      # camera au-dessus de l'apex du toit
STANDOFF_MARGIN_CM = 1300.0
STANDOFF_SCALE = 1.1        # standoff proportionnel a l'etendue du bati (cadrage large constant)
STANDOFF_STEP_CM = 300.0
EDGE_BUFFER_CM = 200.0       # marge de securite a l'interieur du maillage terrain


def _bounds():
    """(xmin, ymin, xmax, ymax) approx du maillage terrain, repere plan cm."""
    e0, n0, e1, n1 = cg.META.bbox_l93
    w_cm = (e1 - e0) * 100.0
    h_cm = (n1 - n0) * 100.0
    m_cm = cg.META.marge_m * 100.0 - EDGE_BUFFER_CM
    return -m_cm, -m_cm, w_cm + m_cm, h_cm + m_cm


def _max_standoff(cx, cy, dx, dy, bounds):
    """Plus grand t >= 0 tel que (cx+t*dx, cy+t*dy) reste dans `bounds`."""
    xmin, ymin, xmax, ymax = bounds
    t = float("inf")
    if dx > 1e-9:
        t = min(t, (xmax - cx) / dx)
    elif dx < -1e-9:
        t = min(t, (xmin - cx) / dx)
    if dy > 1e-9:
        t = min(t, (ymax - cy) / dy)
    elif dy < -1e-9:
        t = min(t, (ymin - cy) / dy)
    return max(t, 0.0)


def _viewpoints():
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    tx, ty = prop["centroid_cm"] if prop else (0.0, 0.0)

    footprints = [Polygon(b["rings_cm"][0]) for b in props if len(b["rings_cm"]) == 1]
    xmin, ymin, xmax, ymax = _bounds()

    views = []
    for i, b in enumerate(props):
        cx, cy = b["centroid_cm"]
        radius = max((math.hypot(x - cx, y - cy) for ring in b["rings_cm"] for x, y in ring),
                     default=0.0)
        # direction depuis le centre de parcelle vers le bati, prolongee au
        # dela du bati (cote exterieur) pour que la camera le voie de face ;
        # repliee vers l'interieur si ca sort du maillage terrain (bati pres
        # d'un bord de parcelle).
        away = math.hypot(cx - tx, cy - ty)
        if away < 1.0:
            dx, dy = 0.0, -1.0
        else:
            dx, dy = (cx - tx) / away, (cy - ty) / away
        wanted = radius * (1.0 + STANDOFF_SCALE) + STANDOFF_MARGIN_CM
        room = _max_standoff(cx, cy, dx, dy, (xmin, ymin, xmax, ymax))
        if room < radius * 1.2:
            # bati trop pres du bord dans cette direction : on filme depuis
            # le cote interieur (vers le centre de la parcelle) a la place.
            dx, dy = -dx, -dy
            room = _max_standoff(cx, cy, dx, dy, (xmin, ymin, xmax, ymax))
        standoff = min(wanted, max(room - EDGE_BUFFER_CM, radius * 1.2))
        px, py = cx + standoff * dx, cy + standoff * dy
        tries = 0
        while any(fp.contains(Point(px, py)) for fp in footprints) and tries < 60:
            standoff += STANDOFF_STEP_CM
            px, py = cx + standoff * dx, cy + standoff * dy
            tries += 1
        yaw = math.atan2(px - cx, py - cy)   # la camera regarde vers le bati
        apex_cm = (b["hauteur"] or 4.0) * 100.0
        z = cg.terrain_z_at(px, py) + apex_cm + CAM_UP_ROOF_CM
        # pitch calcule geometriquement (pas une constante) : vise un point a
        # mi-hauteur du toit, quelle que soit la distance reelle de la camera
        # (recul variable pres des bords de parcelle) -> toit toujours cadre.
        aim_z = cg.terrain_z_at(cx, cy) + apex_cm * 0.55
        horiz = math.hypot(px - cx, py - cy)
        pitch = math.atan2(z - aim_z, max(horiz, 1.0))
        views.append((f"roof{i}_{b['id'][-4:]}", (px, py, z, yaw, pitch)))

    if props:
        bx = sum(b["centroid_cm"][0] for b in props) / len(props)
        by = sum(b["centroid_cm"][1] for b in props) / len(props)
        spread = max((math.hypot(b["centroid_cm"][0] - bx, b["centroid_cm"][1] - by)
                     for b in props), default=0.0)
        e_standoff = min(spread * 0.35 + 1700.0, _max_standoff(bx, by, 0.0, 1.0, (xmin, ymin, xmax, ymax)) - EDGE_BUFFER_CM)
        ey = by + e_standoff
        ez = cg.terrain_z_at(bx, ey) + 1250.0
        aim_z = cg.terrain_z_at(bx, by) + 300.0
        e_pitch = math.atan2(ez - aim_z, max(e_standoff, 1.0))
        views.append(("roof_ensemble", (bx, ey, ez, 0.0, e_pitch)))
    return views


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1280
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    quality = sys.argv[3] if len(sys.argv) > 3 else "low"

    views = _viewpoints()
    if not views:
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json ; lancer bati.py.")

    done = []
    for label, cam in views:
        out = cg.render_photo(cg.VERIF / f"{label}.png",
                              camera=cam, size=(w, h), quality=quality)
        print(f"  {label:16} -> {('OK  ' + out.name) if out else 'indisponible / echec'}")
        if out:
            done.append(out)
    print(f"\n>>> {len(done)}/{len(views)} rendus -> {cg.VERIF}")
    if not done:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
