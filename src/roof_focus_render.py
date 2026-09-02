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

from shapely.geometry import LineString, Point, Polygon

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


def _clear_position(cx, cy, dx, dy, radius, wanted, target_id, obstacle_polys, bounds):
    """Position camera (px, py, standoff, dx, dy) le long de (dx, dy), choisie
    parmi plusieurs angles candidats pour maximiser le degagement reel vis-a-
    vis des autres batiments -- pas juste eviter d'etre "dedans" un buffer
    fixe. Constate au rendu reel : un critere tout-ou-rien (buffer autour de
    chaque batiment) soit laissait un batiment proche dominer le premier plan
    (buffer trop petit), soit degradait tous les cadrages sans lien avec le
    probleme (buffer agrandi pour tous). A la place : score chaque angle par
    sa distance minimale reelle aux batiments (bruts, non bufferises), avec
    une forte penalite si le segment camera->cible en traverse un, et garde
    le meilleur -- jamais de rejet total, toujours le meilleur compromis
    trouve parmi les angles essayes."""
    others = [poly for oid, poly in obstacle_polys if oid != target_id]

    def score_dir(ddx, ddy):
        room = _max_standoff(cx, cy, ddx, ddy, bounds)
        standoff = min(wanted, max(room - EDGE_BUFFER_CM, radius * 1.2))
        px, py = cx + standoff * ddx, cy + standoff * ddy
        cam_pt = Point(px, py)
        min_dist = min((poly.distance(cam_pt) for poly in others), default=float("inf"))
        seg = LineString([(px, py), (cx, cy)])
        blocked = any(seg.intersects(poly) for poly in others)
        score = min_dist - (1.0e7 if blocked else 0.0)
        return score, px, py, standoff

    # plage volontairement limitee (pas au-dela de 40 deg) : un plus grand
    # ecart maximisait parfois la distance aux batiments proches mais finit
    # par regarder au-dela du bati cible, hors du cone de vue reel de la
    # camera (constate au rendu : bati cible absent du cadre malgre un yaw
    # recalcule vers son centroide -- l'angle etait trop excentre pour rester
    # coherent avec un cadrage "de face").
    base_angle = math.atan2(dy, dx)
    candidates = []
    for offset_deg in (0, 20, -20, 40, -40):
        a = base_angle + math.radians(offset_deg)
        ddx, ddy = math.cos(a), math.sin(a)
        score, px, py, standoff = score_dir(ddx, ddy)
        candidates.append((score, px, py, standoff, ddx, ddy))
    _, px, py, standoff, dx, dy = max(candidates, key=lambda c: c[0])
    return px, py, standoff, dx, dy


def _viewpoints():
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    tx, ty = prop["centroid_cm"] if prop else (0.0, 0.0)

    # obstacles = TOUS les batiments (voisinage compris, pas seulement
    # "propriete") -- un recul de camera reduit (cf. radius_eq ci-dessous)
    # peut la rapprocher d'un batiment voisin, au point de dominer le premier
    # plan meme sans etre exactement sur la ligne de visee (constate au rendu
    # reel). Polygones bruts (pas de buffer fixe) : _clear_position score
    # chaque angle candidat par sa distance REELLE aux batiments, un buffer
    # fixe s'est avere soit trop petit (bati proche pas detecte), soit trop
    # grand (degrade les cadrages sans lien avec le probleme).
    obstacles = [(bd["id"], Polygon(bd["rings_cm"][0]))
                for bd in bat if len(bd["rings_cm"]) == 1]
    xmin, ymin, xmax, ymax = _bounds()

    views = []
    for i, b in enumerate(props):
        cx, cy = b["centroid_cm"]
        radius = max((math.hypot(x - cx, y - cy) for ring in b["rings_cm"] for x, y in ring),
                     default=0.0)
        # rayon "equivalent" base sur l'aire (pas la diagonale au coin le plus
        # eloigne) pour le calcul du recul : un bati allonge/en L (ex. plan en L)
        # a un radius jusqu'a 2x plus grand que son etendue apparente reelle --
        # utiliser radius tel quel eloignerait la camera bien au-dela de ce qui
        # est necessaire pour cadrer le toit (constate : bati en L rendu minuscule
        # a l'ecran). radius reste utilise ci-dessous pour la detection de bord/
        # collision, ou le rayon max est le bon critere.
        area = sum(Polygon(ring).area for ring in b["rings_cm"])
        radius_eq = math.sqrt(area / math.pi) if area > 0 else radius
        # direction depuis le centre de parcelle vers le bati, prolongee au
        # dela du bati (cote exterieur) pour que la camera le voie de face ;
        # repliee vers l'interieur si ca sort du maillage terrain (bati pres
        # d'un bord de parcelle).
        away = math.hypot(cx - tx, cy - ty)
        if away < 1.0:
            dx, dy = 0.0, -1.0
        else:
            dx, dy = (cx - tx) / away, (cy - ty) / away
        wanted = radius_eq * (1.0 + STANDOFF_SCALE) + STANDOFF_MARGIN_CM
        room = _max_standoff(cx, cy, dx, dy, (xmin, ymin, xmax, ymax))
        if room < radius * 1.2:
            # bati trop pres du bord dans cette direction : on filme depuis
            # le cote interieur (vers le centre de la parcelle) a la place.
            dx, dy = -dx, -dy
        px, py, standoff, dx, dy = _clear_position(
            cx, cy, dx, dy, radius, wanted, b["id"], obstacles, (xmin, ymin, xmax, ymax))
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
