"""
bati.py : Phase 2, batiments BD TOPO.

WFS BDTOPO_V3:batiment -> Lambert-93 -> classe (par aire majoritaire) :
  - "propriete"  : la majorite de l'emprise est sur la parcelle propriete
  - "voisinage"  : le reste

Sorties dans data/ :
  bati.json                    tous les batiments (id, classe, hauteur, alt_*, mur, toit, rings_cm)
  bati_voisinage.obj / .mtl    prisme mur + toit pyramidal par batiment voisinage (PyVista),
                               1 OBJ multi-materiaux (mur / tuile / ardoise / fibro)
  bati_propriete.obj / .mtl    idem, pour les batiments de la propriete : toit multi-pans
                               extrapole du nuage LiDAR HD (roof_lidar.build_roof) quand
                               assez fiable, sinon repli sur le meme toit pyramidal que le
                               voisinage (jamais de batiment propriete sans toit modelise)
  bati_propriete_ref.json      emprises au sol 2D + etiquettes (commandes MCP), + hauteur de
                               reference de la camera de visite 3D (cf. build_home.py)
"""
from __future__ import annotations

import json

import numpy as np

import roof_lidar
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


def _pyramidal_mesh(poly, ring, haut, alt_toit, z_min):
    """Toit pyramidal simple (apex au centroide) : repli utilise pour le
    voisinage, et pour la propriete quand la reconstruction LiDAR echoue."""
    base = min(cg.terrain_z_at(x, y) for x, y in ring) - 3.0
    eave = base + (haut * 100 if haut else 400.0)
    w_m = min(poly.bounds[2] - poly.bounds[0], poly.bounds[3] - poly.bounds[1])
    # comble : hauteur BD TOPO si dispo, sinon 0,22 x petite dimension ;
    # borne a ~0,45 x petite dimension (pente <= ~45 deg) et ROOF_RISE_MAX
    rise = ((alt_toit - z_min) * 100 - eave) if alt_toit else w_m * 100 * 0.22
    rise = min(max(rise, 90.0), w_m * 100 * 0.45, ROOF_RISE_MAX)
    ridge = eave + rise
    return base, eave, cg.polygon_prism(ring, base, eave), cg.pyramid_roof(ring, eave, ridge)


def main() -> None:
    g = cg.wfs_l93("BDTOPO_V3:batiment", count=300)
    prop_zone = cg.property_polygon_l93()               # PROPRIETE = parcelle property_parcel
    ortho, obb = cg.wms_ortho_rgb(mult=4)
    z_min = cg.META.z_min

    bat, groups, groups_prop, n_vois, n_prop_lidar, n_prop_pyr = [], {"mur": []}, {"mur": []}, 0, 0, 0
    prop_bldgs = []
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

        if classe == "propriete":
            prop_bldgs.append((polys, rings_cm, haut, alt_sol, alt_toit))
            continue

        for poly, ring in zip(polys, rings_cm):
            if poly.area < 4 or len(ring) < 3:
                continue
            n_vois += 1
            base, eave, mur_mesh, toit_mesh = _pyramidal_mesh(poly, ring, haut, alt_toit, z_min)
            groups["mur"].append(mur_mesh)
            rc = cg.roof_color_from_ortho(poly, ortho, obb)
            key = _ROOF_KEY.get(tuple(rc), "ardoise")
            groups.setdefault(key, []).append(toit_mesh)

    # --- batiments de la propriete : LiDAR HD si assez fiable, sinon pyramidal ---
    plan_origin_l93 = (cg.META.E0, cg.META.N1)
    prop_lidar_pts_cm = None
    if prop_bldgs:
        pe0, pn0, pe1, pn1 = prop_zone.bounds
        raw = cg.lidar_points_l93((pe0, pn0, pe1, pn1), margin_m=5.0)
        if len(raw):
            xc, yc = cg.to_plan_cm(raw[:, 0], raw[:, 1])
            prop_lidar_pts_cm = np.column_stack([xc, yc, (raw[:, 2] - z_min) * 100.0])
        print(f"toit propriete : {len(raw) if len(raw) else 0} points LiDAR HD (classe bati)")

    for polys, rings_cm, haut, alt_sol, alt_toit in prop_bldgs:
        for poly, ring in zip(polys, rings_cm):
            if poly.area < 4 or len(ring) < 3:
                continue
            base = min(cg.terrain_z_at(x, y) for x, y in ring) - 3.0
            eave_attr = base + (haut * 100 if haut else 400.0)
            mesh_groups = None
            if prop_lidar_pts_cm is not None and len(prop_lidar_pts_cm):
                mesh_groups = roof_lidar.build_roof(
                    ring, base, eave_attr, prop_lidar_pts_cm, plan_origin_l93, ortho, obb)
            if mesh_groups is not None:
                n_prop_lidar += 1
                for name, mesh, mtl in mesh_groups:
                    groups_prop.setdefault(mtl, []).append(mesh)
            else:
                n_prop_pyr += 1
                _, _, mur_mesh, toit_mesh = _pyramidal_mesh(poly, ring, haut, alt_toit, z_min)
                groups_prop["mur"].append(mur_mesh)
                rc = cg.roof_color_from_ortho(poly, ortho, obb)
                key = _ROOF_KEY.get(tuple(rc), "ardoise")
                groups_prop.setdefault(key, []).append(toit_mesh)

    (GEO / "bati.json").write_text(json.dumps(
        {"z_min_ngf": z_min, "batiments": bat}, indent=1), encoding="utf-8")
    npr = sum(b["classe"] == "propriete" for b in bat)
    print(f"{len(bat)} batiments : {npr} propriete, {len(bat) - npr} voisinage "
          f"({n_vois} emprises voisinage modelisees)")
    if npr:
        print(f"toit propriete : {n_prop_lidar} en LiDAR HD multi-pans, "
              f"{n_prop_pyr} en repli pyramidal")

    # --- OBJ voisinage multi-materiaux ---
    import pyvista as pv

    def _write_obj_multimat(groups, stem, place_name=None):
        obj_groups = []
        for mtl, meshes in groups.items():
            if not meshes:
                continue
            merged = meshes[0] if len(meshes) == 1 else pv.MultiBlock(meshes).combine()
            obj_groups.append((f"{stem}_{mtl}", merged.extract_surface(
                algorithm="dataset_surface").triangulate(), mtl))
        if not obj_groups:
            return None
        cg.write_mtl(GEO / f"{stem}.mtl",
                     {"mur": {"Kd": COL_MUR}, **{k: {"Kd": v} for k, v in ROOF_MTL.items()}})
        cg.write_obj_groups(GEO / f"{stem}.obj", obj_groups, mtl_file=f"{stem}.mtl")
        place = cg.bbox_cm(pv.MultiBlock([m for _, m, _ in obj_groups]).combine())
        if place_name:
            (GEO / place_name).write_text(json.dumps(place, indent=2), encoding="utf-8")
        print(f"{stem}.obj : {sum(m.n_points for _, m, _ in obj_groups)} sommets, "
              f"materiaux {[mt for _, _, mt in obj_groups]}")
        return place

    _write_obj_multimat(groups, "bati_voisinage", "bati_place.json")
    if any(groups_prop.values()):
        _write_obj_multimat(groups_prop, "bati_propriete", "bati_propriete_place.json")

    _propriete_ref([b for b in bat if b["classe"] == "propriete"])
    print(">>> bati OK  ->  vegetation.py")


def _propriete_ref(props) -> None:
    cmds = []
    # sol le plus haut sous les emprises des batiments de la propriete (repere plan,
    # cm) -> hauteur de reference de la camera de visite 3D (cf. build_home.py).
    sol_max = max((cg.terrain_z_at(x, y)
                   for b in props for ring in b["rings_cm"] for x, y in ring),
                  default=0.0)
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
        json.dumps({"sol_bati_max_cm": round(sol_max, 1), "commands": cmds}),
        encoding="utf-8")
    print(f"bati_propriete_ref.json : {len(cmds)} cmds ({len(props)} batiments propriete)")


if __name__ == "__main__":
    main()
