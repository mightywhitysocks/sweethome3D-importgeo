"""
vegetation.py : Phase 2, arbres + haies depuis le MNH LIDAR HD.

  A. arbres  : maxima locaux du MNH (scipy.maximum_filter), h >= H_ARBRE, espaces
     d'au moins MIN_DIST, sur toute l'emprise terrain (zone = META.bbox_l93,
     meme emprise que le bati voisinage), hors emprises bati.
     + lisieres boisees larges -> ligne d'arbres dense le long du spine.
  B. haies taillees : vegetation basse allongee et etroite, meme emprise
     que les arbres (pas seulement autour de la propriete) -> squelette
     (skimage) -> spine (networkx) -> PRISME OBJ vert mat ferme (winding
     correct, jamais de cull).

Toutes les elevations sont prises sur la SURFACE du maillage terrain
(`sitegeo.terrain_z_at`) -> les objets affleurent le sol visible.

Chaque arbre isole/de lisiere est en outre affecte a un archetype de
silhouette ("conifere"/"feuillu"/"arbuste", genere par `arbaro_tree.py`,
cf. issues #81/#82) via une heuristique grossiere (forme du houppier depuis
le MNH + teinte depuis l'ortho, `_classify_essence`) -- PAS une detection
d'essence reelle, cf. docstring de `arbaro_tree.py`. Si l'outil externe
arbaro est indisponible, `arbaro_tree.prepare_species_models` renvoie {} et
tous les arbres reutilisent le gabarit unique historique (`assets/tree.obj`,
comportement inchange) -- jamais de melange gabarit-historique/especes-
generees au sein d'un meme run.

Sorties dans data/ :
  mnh.tif
  vegetation_arbres.json   {place:[...], resize:[...]} apparie dans l'ordre
                           (resize[i]["model"] = cle espece x variante, ou
                           None -> gabarit unique historique, cf. build_home.py)
  haies.obj / haies.mtl    prismes verts fusionnes (+ haies_place.json)
"""
from __future__ import annotations

import json

import numpy as np

import arbaro_tree
import sitegeo as cg

GEO = cg.GEO
MARGE = 30.0
H_ARBRE = 3.5          # m : cime = arbre
H_VEG = 1.5            # m : seuil vegetation
MIN_DIST = 4.5         # m entre cimes
LINE_SPACING = 5.0     # m entre arbres d'une lisiere

TREE_W0, TREE_D0, TREE_H0 = 600.0, 640.0, 800.0   # gabarit historique (assets/tree.obj)
COL_HAIE = (0.30, 0.44, 0.20)           # vert mat

# ---- classification grossiere en archetype (cf. arbaro_tree.py) ----
SEUIL_ARBUSTE_M = 4.5     # h < ce seuil -> silhouette "arbuste" (pres de H_ARBRE)
SEUIL_STEEPNESS = 1.8     # h / rayon_houppier -- empirique (houppier etroit = conifere)
ORTHO_SAMPLE_M = 1.5      # rayon (m) d'echantillonnage ortho autour de la cime


def main() -> None:
    from scipy.ndimage import binary_closing, label as ndlabel, maximum_filter
    from skimage.morphology import skeletonize
    from rasterio.features import rasterize, shapes
    from shapely.geometry import LineString, Point, box, shape
    from shapely.ops import unary_union
    import pyvista as pv

    MNH, T, _, blob = cg.wms_raster("MNH_LIDAR", margin_m=MARGE, res_m=0.5)
    (GEO / "mnh.tif").write_bytes(blob)
    MNH = np.nan_to_num(MNH, nan=0.0)
    res = abs(T.a)

    # especes generees (issue #82) : {} si arbaro indisponible -> gabarit
    # unique historique pour tous les arbres, cf. docstring de arbaro_tree.py.
    # L'ortho n'est telechargee que si des modeles sont disponibles (inutile
    # sinon, cf. _classify_essence).
    species_models = arbaro_tree.prepare_species_models(log=print)
    ortho_arr = ortho_bbox = None
    if species_models:
        ortho_arr, ortho_bbox = cg.wms_ortho_rgb(margin_m=MARGE)

    def rc_l93(r, c):
        return T.c + (c + 0.5) * T.a, T.f + (r + 0.5) * T.e

    def pick_model(r, c, h, E, N, x_cm, y_cm):
        if not species_models:
            return None
        H, W = MNH.shape
        r = min(max(r, 0), H - 1)
        c = min(max(c, 0), W - 1)
        crown_r = _crown_radius_m(MNH, r, c, h, res)
        rgb = _sample_ortho_rgb(ortho_arr, ortho_bbox, E, N)
        essence = _classify_essence(h, crown_r, rgb)
        variant = abs(hash((round(x_cm), round(y_cm)))) % arbaro_tree.N_VARIANTS
        return _resolve_model_key(species_models, essence, variant)

    bati = json.loads((GEO / "bati.json").read_text(encoding="utf-8"))["batiments"]
    bati_l93 = unary_union([_ring_l93(ring) for b in bati for ring in b["rings_cm"]
                            if len(ring) >= 3])
    # meme emprise que le bati voisinage (bati.py : cg.wfs_l93 sur META.bbox_wgs84,
    # equivalent a META.bbox_l93 ici) -- pas les seules parcelles listees dans
    # site.local.toml, sinon la vegetation modelisee en 3D (arbres ET haies,
    # meme traitement pour les deux) ne couvre qu'une fraction de ce que
    # montrent deja le fond ortho/terrain sur le reste de la bbox (issue #46).
    zone = box(*cg.META.bbox_l93)
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
        h = float(MNH[r_, c_])
        trees.append((float(x), float(y), cg.terrain_z_at(x, y), h,
                     pick_model(r_, c_, h, E, N, x, y)))

    # ---------- B. HAIES / LISIERES (meme emprise que les arbres, cf. zone) ----------
    zmask = rasterize([(zone, 1)], out_shape=MNH.shape,
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
                    h = max(h_med, 3.0)
                    r2, c2 = _rc_at(T, p.x, p.y)
                    line_trees.append((float(x), float(y), cg.terrain_z_at(x, y), h,
                                       pick_model(r2, c2, h, p.x, p.y, x, y)))
                d += LINE_SPACING

    # ---------- ecriture ----------
    tplace, tresize = _tree_cmds(trees + line_trees, species_models)
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

    hs = sorted(round(h, 1) for *_, h, _model in trees)
    print(f"arbres : {len(trees)} isoles + {len(line_trees)} lisiere  "
          f"(h {hs[0] if hs else 0}..{hs[-1] if hs else 0} m)")
    print(f"haies  : {n_hedges} prismes -> haies.obj" if hedge_meshes else "haies  : 0")
    print(">>> vegetation OK  ->  build_home.py")


def _tree_cmds(pts, species_models):
    """`model` (dans `resize`) = cle espece x variante (cf. arbaro_tree.py)
    ou None -> gabarit unique historique (TREE_W0/D0/H0, catalogId
    OlaKristianHoff#tree, cf. build_home.py)."""
    place, resize = [], []
    for x, y, elev, h, model_key in pts:
        dims = species_models.get(model_key) if model_key else None
        w0, d0, h0 = (dims["w0"], dims["d0"], dims["h0"]) if dims else (TREE_W0, TREE_D0, TREE_H0)
        f = min(max(h, 2.0), 25.0) * 100 / h0
        place.append({"action": "place_furniture", "params": {
            "x": round(x, 1), "y": round(y, 1),
            "elevation": round(max(0.0, elev), 1)}})
        resize.append({"width": round(w0 * f, 1), "depth": round(d0 * f, 1),
                       "height": round(h0 * f, 1), "model": model_key if dims else None})
    return place, resize


def _rc_at(T, E, N):
    """Inverse de `rc_l93` (main()) : ligne/colonne raster MNH au point L93
    (E, N)."""
    c = (E - T.c) / T.a - 0.5
    r = (N - T.f) / T.e - 0.5
    return int(round(r)), int(round(c))


def _crown_radius_m(MNH, r0, c0, h_peak, res):
    """Rayon (m) ou le MNH retombe sous la moitie de la hauteur du houppier,
    mesure par un balayage en croix (4 directions) autour du pic -- suffisant
    pour distinguer un houppier pointu (conifere) d'un houppier etale
    (feuillu), pas une segmentation de couronne complete. Cf.
    `_classify_essence`."""
    half = h_peak / 2.0
    win = max(1, int(round(15.0 / res)))
    H, W = MNH.shape
    rmax = 0.0
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        d = 0
        for k in range(1, win + 1):
            rr, cc = r0 + dr * k, c0 + dc * k
            if not (0 <= rr < H and 0 <= cc < W) or MNH[rr, cc] < half:
                break
            d = k
        rmax = max(rmax, d * res)
    return max(rmax, res)


def _sample_ortho_rgb(ortho_arr, ortho_bbox, E, N, radius_m=ORTHO_SAMPLE_M):
    """Mediane RGB de l'ortho dans un petit carre autour de (E, N) -- meme
    principe d'echantillonnage que `cg.roof_color_from_ortho`, mais valeur
    brute (pas de quantification en materiau de toiture)."""
    e0, n0, e1, n1 = ortho_bbox
    oh, ow, _ = ortho_arr.shape
    c0 = max(0, int((E - radius_m - e0) / (e1 - e0) * ow))
    c1 = min(ow, int((E + radius_m - e0) / (e1 - e0) * ow) + 1)
    r0 = max(0, int((n1 - (N + radius_m)) / (n1 - n0) * oh))
    r1 = min(oh, int((n1 - (N - radius_m)) / (n1 - n0) * oh) + 1)
    patch = ortho_arr[r0:r1, c0:c1].reshape(-1, 3).astype(float)
    if len(patch) == 0:
        return (100.0, 100.0, 100.0)
    r, g, b = np.median(patch, axis=0)
    return (float(r), float(g), float(b))


def _classify_essence(h, crown_r, rgb):
    """Heuristique grossiere a 2 indices (forme du houppier + teinte),
    faute d'outil open source de detection d'essence exploitable trouve en
    recherche documentaire (cf. issue #81 : vide constate apres recherche,
    pas une absence de recherche). Distingue seulement 3 archetypes de
    silhouette (conifere/feuillu/arbuste, cf. arbaro_tree.py) -- PAS une
    identification botanique. Non revalidee sur donnees reelles dans cette
    session (aucun site configure, confidentialite -- cf. CLAUDE.md)."""
    if h < SEUIL_ARBUSTE_M:
        return "arbuste"
    steepness = h / max(crown_r, 0.5)
    r, g, b = rgb
    greenness = g - (r + b) / 2.0
    luminosite = (r + g + b) / 3.0
    conifer_score = int(steepness > SEUIL_STEEPNESS) + int(greenness < 15.0 or luminosite < 70.0)
    return "conifere" if conifer_score >= 1 else "feuillu"


def _resolve_model_key(species_models, essence, variant):
    """Cle `species_models` pour (essence, variant), avec repli sur une
    autre variante de la MEME essence si celle-ci a echoue a la generation
    (cf. arbaro_tree.prepare_species_models), puis sur n'importe quelle
    essence disponible plutot que de planter -- jamais de KeyError."""
    for v in range(arbaro_tree.N_VARIANTS):
        key = f"{essence}_{(variant + v) % arbaro_tree.N_VARIANTS}"
        if key in species_models:
            return key
    for key in species_models:
        if key.startswith(essence + "_"):
            return key
    return next(iter(species_models))


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
