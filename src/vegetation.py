"""
vegetation.py — Phase 2 : arbres + haies depuis le MNH LIDAR HD.

  A. arbres  : maxima locaux du MNH (scipy.maximum_filter), h >= H_ARBRE, espaces
     d'au moins MIN_DIST, dans (parcelles + 8 m), hors emprises bati.
     + lisieres boisees larges -> ligne d'arbres dense le long du spine.
  B. haies taillees : vegetation basse allongee et etroite le long de la limite
     de propriete -> squelette (skimage) -> spine (networkx) -> PRISME OBJ vert
     mat ferme (winding correct, jamais de cull).

Toutes les elevations sont prises sur la SURFACE du maillage terrain
(`sitegeo.terrain_z_at`) -> les objets affleurent le sol visible.

Sorties dans data/ :
  mnh.tif
  vegetation_arbres.json   {place:[...], resize:[...]} apparie dans l'ordre
  haies.obj / haies.mtl    prismes verts fusionnes (+ haies_place.json)
"""
from __future__ import annotations

import json

import numpy as np

import sitegeo as cg

GEO = cg.GEO
MARGE = 30.0
H_ARBRE = 3.5          # m : cime = arbre
H_VEG = 1.5            # m : seuil vegetation
MIN_DIST = 4.5         # m entre cimes
LINE_SPACING = 5.0     # m entre arbres d'une lisiere
HEDGE_BUF_M = 15.0     # ceinture autour de la parcelle propriete

TREE_CAT = "OlaKristianHoff#tree"        # gabarit 600 x 640 x 800 cm
TREE_W0, TREE_D0, TREE_H0 = 600.0, 640.0, 800.0
COL_HAIE = (0.30, 0.44, 0.20)           # vert mat


def main() -> None:
    from scipy.ndimage import binary_closing, label as ndlabel, maximum_filter
    from skimage.morphology import skeletonize
    from rasterio.features import rasterize, shapes
    from shapely.geometry import LineString, Point, shape
    from shapely.ops import unary_union
    import pyvista as pv

    MNH, T, _, blob = cg.wms_raster("MNH_LIDAR", margin_m=MARGE, res_m=0.5)
    (GEO / "mnh.tif").write_bytes(blob)
    MNH = np.nan_to_num(MNH, nan=0.0)
    res = abs(T.a)

    def rc_l93(r, c):
        return T.c + (c + 0.5) * T.a, T.f + (r + 0.5) * T.e

    bati = json.loads((GEO / "bati.json").read_text(encoding="utf-8"))["batiments"]
    bati_l93 = unary_union([_ring_l93(ring) for b in bati for ring in b["rings_cm"]
                            if len(ring) >= 3])
    zone = cg.parcels_union_l93().buffer(8.0)
    poly_prop = cg.property_polygon_l93()
    bati_mask = rasterize([(bati_l93.buffer(2.0), 1)], out_shape=MNH.shape,
                          transform=T, fill=0).astype(bool)

    # ---------- A. ARBRES ----------
    win = max(3, int(round(MIN_DIST / res)) | 1)
    peaks = (maximum_filter(MNH, size=win) == MNH) & (MNH >= H_ARBRE) & ~bati_mask
    rr, cc = np.where(peaks)
    order = np.argsort(MNH[rr, cc])[::-1]

    trees, taken = [], []
    for r_, c_ in zip(rr[order], cc[order]):
        E, N = rc_l93(r_, c_)
        if not zone.contains(Point(E, N)):
            continue
        if any((E - te) ** 2 + (N - tn) ** 2 < MIN_DIST ** 2 for te, tn in taken):
            continue
        taken.append((E, N))
        x, y = cg.to_plan_cm(E, N)
        trees.append((float(x), float(y), cg.terrain_z_at(x, y), float(MNH[r_, c_])))

    # ---------- B. HAIES / LISIERES (ceinture de la parcelle propriete) ----------
    zmask = rasterize([(poly_prop.buffer(HEDGE_BUF_M), 1)], out_shape=MNH.shape,
                      transform=T, fill=0).astype(bool)
    veg = binary_closing((MNH >= H_VEG) & zmask & ~bati_mask, np.ones((3, 3)))
    lab, nlab = ndlabel(veg, np.ones((3, 3)))

    hedge_meshes, line_trees = [], []
    n_hedges = 0
    for k in range(1, nlab + 1):
        comp = lab == k
        if comp.sum() * res * res < 12:
            continue
        polys = [shape(gj).simplify(0.4) for gj, v in
                 shapes(comp.astype("uint8"), mask=comp, transform=T, connectivity=8)
                 if v == 1]
        poly = max(polys, key=lambda p: p.area)
        if poly.geom_type != "Polygon":
            continue
        rr2 = poly.minimum_rotated_rectangle.exterior.coords.xy
        seg = sorted(np.hypot(rr2[0][i + 1] - rr2[0][i], rr2[1][i + 1] - rr2[1][i])
                     for i in range(4))
        Wd, L = seg[0], seg[2]
        h_med = float(np.median(MNH[comp]))
        if L < 10 or L / max(Wd, 0.1) < 1.8:
            continue
        pr, pc = np.where(skeletonize(comp))
        line = (_spine(pr, pc, T) if len(pr) >= 2
                else LineString([poly.centroid, poly.centroid]))

        if Wd <= 4.0 and h_med < 4.0:
            # ---- haie taillee -> PRISME OBJ (suit le terrain via terrain_z_at) ----
            n_hedges += 1
            ring_l93 = list(line.buffer(max(Wd, 0.6) / 2, cap_style=2).exterior.coords)[:-1]
            ring_cm = [cg.to_plan_cm(E, N) for E, N in ring_l93]
            ring_cm = [(float(x), float(y)) for x, y in ring_cm]
            gz = [cg.terrain_z_at(x, y) for x, y in ring_cm]
            base, top = min(gz) - 5.0, max(gz) + h_med * 100.0
            hedge_meshes.append(cg.polygon_prism(ring_cm, base, top))
        else:
            # ---- lisiere boisee large -> ligne d'arbres ----
            d = 0.0
            while d <= line.length + 1e-6:
                p = line.interpolate(d)
                if not any((p.x - e) ** 2 + (p.y - n) ** 2 < MIN_DIST ** 2
                           for e, n in taken):
                    taken.append((p.x, p.y))
                    x, y = cg.to_plan_cm(p.x, p.y)
                    line_trees.append((float(x), float(y), cg.terrain_z_at(x, y),
                                       max(h_med, 3.0)))
                d += LINE_SPACING

    # ---------- ecriture ----------
    tplace, tresize = _tree_cmds(trees + line_trees)
    (GEO / "vegetation_arbres.json").write_text(json.dumps(
        {"place": {"commands": tplace}, "resize": tresize,
         "note": f"{len(trees)} arbres isoles + {len(line_trees)} arbres de lisiere"},
        indent=1), encoding="utf-8")

    if hedge_meshes:
        merged = (hedge_meshes[0] if len(hedge_meshes) == 1
                  else pv.MultiBlock(hedge_meshes).combine().extract_surface(
                      algorithm="dataset_surface").triangulate())
        cg.write_mtl(GEO / "haies.mtl", {"haie": {"Kd": COL_HAIE}})
        cg.write_obj(GEO / "haies.obj", merged, mtl_name="haie", mtl_file="haies.mtl",
                     group="haies")
        (GEO / "haies_place.json").write_text(
            json.dumps(cg.bbox_cm(merged), indent=2), encoding="utf-8")

    hs = sorted(round(h, 1) for *_, h in trees)
    print(f"arbres : {len(trees)} isoles + {len(line_trees)} lisiere  "
          f"(h {hs[0] if hs else 0}..{hs[-1] if hs else 0} m)")
    print(f"haies  : {n_hedges} prismes -> haies.obj" if hedge_meshes else "haies  : 0")
    print(">>> vegetation OK  ->  build_home.py")


def _tree_cmds(pts):
    place, resize = [], []
    for x, y, elev, h in pts:
        f = min(max(h, 2.0), 25.0) * 100 / TREE_H0
        place.append({"action": "place_furniture", "params": {
            "catalogId": TREE_CAT, "x": round(x, 1), "y": round(y, 1),
            "elevation": round(max(0.0, elev), 1)}})
        resize.append({"width": round(TREE_W0 * f, 1), "depth": round(TREE_D0 * f, 1),
                       "height": round(TREE_H0 * f, 1)})
    return place, resize


def _spine(pr, pc, T):
    """Plus long chemin dans le graphe du squelette (networkx) -> LineString L93."""
    import networkx as nx
    from shapely.geometry import LineString

    nodes = set(zip(pr.tolist(), pc.tolist()))
    G = nx.Graph()
    for (r, c) in nodes:
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (dr or dc) and (r + dr, c + dc) in nodes:
                    G.add_edge((r, c), (r + dr, c + dc), weight=float(np.hypot(dr, dc)))
    if G.number_of_nodes() < 2:
        r, c = next(iter(nodes))
        p = (T.c + (c + .5) * T.a, T.f + (r + .5) * T.e)
        return LineString([p, p])
    comp = max(nx.connected_components(G), key=len)
    G = G.subgraph(comp)
    a = max(nx.single_source_dijkstra_path_length(G, next(iter(comp))).items(),
            key=lambda kv: kv[1])[0]
    lengths, paths = nx.single_source_dijkstra(G, a)
    b = max(lengths.items(), key=lambda kv: kv[1])[0]
    pts = [(T.c + (c + .5) * T.a, T.f + (r + .5) * T.e) for r, c in paths[b]]
    return LineString(pts).simplify(0.6)


def _ring_l93(ring_cm):
    from shapely.geometry import Polygon
    xs = np.array([p[0] for p in ring_cm])
    ys = np.array([p[1] for p in ring_cm])
    E, N = cg.plan_cm_to_l93(xs, ys)
    return Polygon(zip(E, N))


if __name__ == "__main__":
    main()
