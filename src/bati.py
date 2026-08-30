"""
bati.py — Phase 2 : batiments BD TOPO.

WFS BDTOPO_V3:batiment -> Lambert-93 -> classe (par aire majoritaire) :
  - "propriete"  : la majorite de l'emprise est sur la parcelle propriete
  - "voisinage"  : le reste

Sorties dans data/ :
  bati.json                    tous les batiments (id, classe, hauteur, alt_*, mur, toit, rings_cm)
  bati_voisinage.obj / .mtl    prisme mur + toit pyramidal par batiment voisinage (PyVista),
                               1 OBJ multi-materiaux (mur / tuile / ardoise / fibro)
  bati_propriete_ref.json      emprises au sol 2D + etiquettes (commandes MCP) — modelisation
                               fine ulterieure via le plugin GenerateRoof
"""
from __future__ import annotations

import json

import numpy as np

import sitegeo as cg

GEO = cg.GEO
ROOF_RISE_MAX = 350.0        # cm : hauteur de comble max
COL_MUR = (0.79, 0.74, 0.65)
ROOF_MTL = {"tuile": (0.545, 0.227, 0.169), "ardoise": (0.243, 0.259, 0.282),
            "fibro": (0.471, 0.486, 0.510)}
_ROOF_KEY = {(139, 58, 43): "tuile", (62, 66, 72): "ardoise", (120, 124, 130): "fibro"}


def _fnum(v):
    try:
        f = float(str(v).replace(",", "."))
        return None if f != f else f          # None si NaN
    except (TypeError, ValueError):
        return None


def main() -> None:
    g = cg.wfs_l93("BDTOPO_V3:batiment", count=300)
    prop_zone = cg.property_polygon_l93()               # PROPRIETE = parcelle property_parcel
    ortho, obb = cg.wms_ortho_rgb(mult=4)
    z_min = cg.META.z_min

    bat, groups, n_vois = [], {"mur": []}, 0
    for _, row in g.iterrows():
        geom = row.geometry
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        # PROPRIETE seulement si la MAJORITE de l'emprise est sur la parcelle propriete
        # (sinon un batiment d'une parcelle voisine qui longe la limite serait mal classe).
        on020 = geom.intersection(prop_zone).area
        classe = "propriete" if on020 > 0.5 * geom.area else "voisinage"
        haut = _fnum(row.get("hauteur"))
        alt_sol = _fnum(row.get("altitude_minimale_sol"))
        alt_toit = _fnum(row.get("altitude_maximale_toit"))
        rid = row.get("cleabs") or f"b{len(bat)}"

        rings_cm = []
        for poly in polys:
            xs, ys = poly.exterior.coords.xy
            xc, yc = cg.to_plan_cm(np.array(xs[:-1]), np.array(ys[:-1]))
            rings_cm.append([[round(float(a), 1), round(float(b), 1)]
                             for a, b in zip(xc, yc)])
        cx, cy = cg.to_plan_cm(geom.centroid.x, geom.centroid.y)
        bat.append({
            "id": rid, "classe": classe, "hauteur": haut,
            "alt_sol": alt_sol, "alt_toit": alt_toit,
            "etages": row.get("nombre_d_etages"),
            "mur": row.get("materiaux_des_murs"),
            "toit": row.get("materiaux_de_la_toiture"),
            "nature": row.get("nature"),
            "rings_cm": rings_cm,
            "centroid_cm": [round(float(cx), 1), round(float(cy), 1)],
        })
        if classe != "voisinage":
            continue

        for poly, ring in zip(polys, rings_cm):
            if poly.area < 4 or len(ring) < 3:
                continue
            n_vois += 1
            # base = point le plus bas de l'emprise SUR LA SURFACE du maillage terrain
            # (3 cm d'ancrage) ; sur une pente le terrain recouvre le bas du mur amont.
            base = min(cg.terrain_z_at(x, y) for x, y in ring) - 3.0
            eave = base + (haut * 100 if haut else 400.0)
            w_m = min(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1])
            # comble : hauteur LIDAR si dispo, sinon 0,22 x petite dimension ;
            # borne a ~0,45 x petite dimension (pente <= ~45 deg) et ROOF_RISE_MAX
            rise = ((alt_toit - z_min) * 100 - eave) if alt_toit else w_m * 100 * 0.22
            rise = min(max(rise, 90.0), w_m * 100 * 0.45, ROOF_RISE_MAX)
            ridge = eave + rise
            groups["mur"].append(cg.polygon_prism(ring, base, eave))
            rc = cg.roof_color_from_ortho(poly, ortho, obb)
            key = _ROOF_KEY.get(tuple(rc), "ardoise")
            groups.setdefault(key, []).append(cg.pyramid_roof(ring, eave, ridge))

    (GEO / "bati.json").write_text(json.dumps(
        {"z_min_ngf": z_min, "batiments": bat}, indent=1), encoding="utf-8")
    npr = sum(b["classe"] == "propriete" for b in bat)
    print(f"{len(bat)} batiments : {npr} propriete, {len(bat) - npr} voisinage "
          f"({n_vois} emprises voisinage modelisees)")

    # --- OBJ voisinage multi-materiaux ---
    import pyvista as pv
    obj_groups = []
    for mtl, meshes in groups.items():
        if not meshes:
            continue
        merged = meshes[0] if len(meshes) == 1 else pv.MultiBlock(meshes).combine()
        obj_groups.append((f"bati_{mtl}", merged.extract_surface(
            algorithm="dataset_surface").triangulate(), mtl))
    cg.write_mtl(GEO / "bati_voisinage.mtl",
                 {"mur": {"Kd": COL_MUR},
                  **{k: {"Kd": v} for k, v in ROOF_MTL.items()}})
    cg.write_obj_groups(GEO / "bati_voisinage.obj", obj_groups,
                        mtl_file="bati_voisinage.mtl")
    place = cg.bbox_cm(pv.MultiBlock([m for _, m, _ in obj_groups]).combine())
    (GEO / "bati_place.json").write_text(json.dumps(place, indent=2), encoding="utf-8")
    print(f"bati_voisinage.obj : {sum(m.n_points for _, m, _ in obj_groups)} sommets, "
          f"materiaux {[mt for _, _, mt in obj_groups]}")

    _propriete_ref([b for b in bat if b["classe"] == "propriete"])
    print(">>> bati OK  ->  vegetation.py")


def _propriete_ref(props) -> None:
    cmds = []
    for b in props:
        for ring in b["rings_cm"]:
            cmds.append({"action": "create_room_polygon", "params": {
                "points": [{"x": x, "y": y} for x, y in ring],
                "name": f"bati propriete {b['id'][-4:]}",
                "floorVisible": False, "ceilingVisible": False, "areaVisible": False,
                "floorColor": "#B0A48F"}})
        pts = [p for r in b["rings_cm"] for p in r]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        txt = f"bati {b['id'][-4:]}\\nh {b['hauteur']} m"
        if b["etages"]:
            txt += f" | {b['etages']} niv"
        if b["alt_toit"]:
            txt += f"\\ntoit {b['alt_toit']} m NGF"
        cmds.append({"action": "add_label", "params": {
            "text": txt, "x": round(cx, 1), "y": round(cy, 1),
            "fontSize": 45, "color": "#6D5F4B"}})
    (GEO / "bati_propriete_ref.json").write_text(
        json.dumps({"commands": cmds}), encoding="utf-8")
    print(f"bati_propriete_ref.json : {len(cmds)} cmds ({len(props)} batiments propriete)")


if __name__ == "__main__":
    main()
