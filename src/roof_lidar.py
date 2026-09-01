"""
roof_lidar.py : reconstruction du toit multi-pans d'un batiment (la propriete)
depuis le nuage de points LiDAR HD, en cite d'extrapolation (hauteur, longueur,
angle de pente) plutot que le toit pyramidal simple utilise pour le voisinage.

Pipeline (valide iterativement sur un batiment reel avant portage ici) :
  1. RANSAC sequentiel : un plan par pan de toit.
  2. Affectation point -> pan par croissance de region (jamais un classement
     point-a-point global, qui deborde entre 2 pentes proches).
  3. Enveloppe convexe par pan (points reels).
  4. Aretes de jonction : mesurees sur les points-frontiere (SVD), avec repli
     geometrique (intersection analytique des 2 plans, ou construction a
     mi-chemin de 2 rebords) pour les jonctions trop courtes/instables, et
     recalage sur l'orthophoto pour les aretes a fort contraste.
  5. Polygone final par pan = enveloppe recoupee par ses aretes validees.
  6. Bloc 3D complet (murs hauteur variable + toit) sur le contour ENTIER du
     batiment (pas seulement l'emprise LiDAR) : diagramme de Voronoi (garanti
     sans trou/recouvrement) puis `coverage_simplify` (peu de sommets, sans
     desynchroniser les frontieres entre pans voisins).

Toute reconstruction non assez fiable (pas assez de points, aucun plan trouve,
solide final non ferme) renvoie None -- `bati.py` se replie alors sur le toit
pyramidal deja utilise pour le voisinage. Aucune coordonnee ni identifiant de
parcelle n'est en dur ici : tout vient des arguments de `build_roof`.
"""
from __future__ import annotations

import heapq

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from shapely import coverage_simplify, voronoi_polygons
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box
from shapely.ops import split, unary_union

import sitegeo as cg

# ---------- constantes : toutes generiques (bruit LiDAR HD, densite de
# points), aucune ne depend d'un batiment particulier. Chaque seuil a ete
# valide empiriquement (voir historique de calibration en commentaire). ----------
MIN_LIDAR_PTS = 200          # sous ce seuil, pas assez de points pour tenter une reconstruction
RANSAC_THRESH_M = 0.12       # bruit du capteur LiDAR HD (ordre de grandeur documente IGN)
RANSAC_ITERS = 800
MIN_INLIERS = 100            # cf. historique : 150 excluait des plans reels et coherents
MAX_PLANES_SAFETY = 20       # garde-fou anti-boucle infinie, pas une hypothese de forme de toit
K_NEIGH = 10
MAX_DIST_M = RANSAC_THRESH_M
FALLBACK_DIST_M = 0.3
MIN_PTS_PAN = 30
RESIDU_MAX_M = 0.7
MIN_CROSS_EDGES = 3
MIN_COMPONENT_PTS = 10       # cf. historique : un plancher a 3 laissait gagner des amas
                              # minuscules par hasard du ratio des valeurs singulieres
COVER_RADIUS_M = 1.0
SEG_BUFFER_M = 0.8
EAVE_TOL_M = 1.0
SHORT_EDGE_M = 2.0
PITCH_DIFF_MAX_DEG = 5.0
DIR_ANGLE_MAX_DEG = 20.0
ANALYTIC_TOL_M = 1.0
ORTHO_MULT = 10
ORTHO_SEARCH_PX = 20
ORTHO_SCORE_MIN = 100.0
BOUNDARY_SAMPLE_M = 0.3
COVERAGE_SIMPLIFY_TOL_M = 0.2
# 0.01 m2 (calibre sur un premier batiment teste) s'est revele trop strict sur
# un autre batiment reel : residu mesure 0.011-0.013 m2 (deja negligeable vis-
# a-vis de la surface au sol d'une maison), rejete a tort -> repli sur les
# ~140 sommets par pan du Voronoi brut au lieu des ~10-15 attendus. Remonte a
# 0.05 m2, toujours tres en dessous du seuil ou une degradation reelle apparait
# (mesure : gap franc des 0.3 m2 a partir d'une tolerance de simplification
# 0.7 m, cf. COVERAGE_SIMPLIFY_TOL_M) -- marge large sans risque identifie.
COVERAGE_SIMPLIFY_ACCEPT_M2 = 0.05


def build_roof(ring_cm, base_cm, eave_attr_cm, lidar_pts_cm, plan_origin_l93,
              ortho_arr, ortho_bbox_l93, *, log=print):
    """
    ring_cm : contour du batiment (liste [(x, y)], repere plan SH3D cm, sans
        point de fermeture) -- deja calcule par bati.py (`cg.to_plan_cm`).
    base_cm : altitude du sol (repere plan cm) -- meme valeur que le `base`
        deja calcule par bati.py pour le toit pyramidal.
    eave_attr_cm : altitude d'egout ATTENDUE (BD TOPO, `base + hauteur*100`)
        -- sert uniquement de point de vigilance (ecart signale, jamais
        corrige de force : le LiDAR est la source de verite pour la geometrie).
    lidar_pts_cm : ndarray (N, 3) points LiDAR classe batiment pres de ce
        contour, deja convertis en repere plan cm par l'appelant.
    plan_origin_l93 : (E0, N1) -- `cg.META.E0, cg.META.N1` -- pour retrouver
        les coordonnees L93 necessaires au recalage sur l'orthophoto (WMS
        travaille en L93).
    ortho_arr, ortho_bbox_l93 : ortho HR deja recuperee par l'appelant (memes
        arguments que `cg.roof_color_from_ortho`), pour la couleur de chaque
        pan (le recalage fin refait sa propre requete WMS ciblee, plus haute
        resolution, sur une petite zone).

    Renvoie une liste de (nom, pyvista.PolyData, cle_materiau) -- meme forme
    que les groupes 'mur'/'tuile'/'ardoise'/'fibro' de bati.py -- ou None si
    la reconstruction n'est pas assez fiable.
    """
    try:
        return _build_roof_impl(ring_cm, base_cm, eave_attr_cm, lidar_pts_cm,
                                plan_origin_l93, ortho_arr, ortho_bbox_l93, log)
    except Exception as e:                                       # noqa: BLE001
        log(f"  toit LiDAR : reconstruction echouee ({type(e).__name__}: {e}) -> repli pyramidal")
        return None


# --------------------------------------------------------------------------- #
# Implementation (leve une exception -> None cote appelant en cas d'echec)
# --------------------------------------------------------------------------- #
def _build_roof_impl(ring_cm, base_cm, eave_attr_cm, lidar_pts_cm, plan_origin_l93,
                     ortho_arr, ortho_bbox_l93, log):
    E0, N1 = plan_origin_l93
    ring_m = np.asarray(ring_cm, dtype=np.float64) / 100.0
    base_m = base_cm / 100.0
    eave_attr_m = eave_attr_cm / 100.0
    footprint = Polygon(ring_m)
    pts = np.asarray(lidar_pts_cm, dtype=np.float64) / 100.0
    if len(pts) < MIN_LIDAR_PTS:
        log(f"  toit LiDAR : {len(pts)} points (< {MIN_LIDAR_PTS}) -> repli pyramidal")
        return None
    inside = np.array([footprint.buffer(1.5).contains(Point(x, y)) for x, y in pts[:, :2]])
    pts = pts[inside]
    if len(pts) < MIN_LIDAR_PTS:
        log(f"  toit LiDAR : {len(pts)} points dans l'emprise -> repli pyramidal")
        return None

    planes = _ransac_planes(pts)
    if not planes:
        log("  toit LiDAR : aucun plan RANSAC -> repli pyramidal")
        return None

    labels, pan_points = _grow_regions(pts, planes)
    active = sorted(pan_points)
    if not active:
        log("  toit LiDAR : aucun pan retenu -> repli pyramidal")
        return None

    info, hulls = _pan_hulls(pan_points, planes)
    active = [pid for pid in active if pid in hulls]
    if not active:
        return None

    def plane_z_at(pid, x, y):
        n_, d_ = planes[pid]["normal"], planes[pid]["d"]
        return -(n_[0] * x + n_[1] * y + d_) / n_[2]

    edge_fits, free_edges = _junction_edges(
        pts, labels, active, hulls, pan_points, info, plane_z_at, eave_attr_m, log)
    _geometric_ridges(edge_fits, free_edges, info, log)
    _ortho_recalage(edge_fits, E0, N1, log)
    _analytic_replace(edge_fits, planes, pts, labels, log)

    polys = _cut_pans(active, hulls, pan_points, edge_fits, info, log)
    full_polys = _full_footprint(active, polys, footprint, log)
    if full_polys is None:
        return None

    return _mesh_groups(active, full_polys, plane_z_at, base_m, plan_origin_l93,
                        ortho_arr, ortho_bbox_l93, log)


# ---------- 1. RANSAC : un plan par pan de toit. ---------- #
def _fit_plane_ransac(P, rng, thresh=RANSAC_THRESH_M, iters=RANSAC_ITERS, min_inliers=MIN_INLIERS):
    n = len(P)
    if n < min_inliers:
        return None
    best = None
    for _ in range(iters):
        idx = rng.choice(n, 3, replace=False)
        p0, p1, p2 = P[idx]
        normal = np.cross(p1 - p0, p2 - p0)
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal = normal / norm
        if abs(normal[2]) < 0.5:          # rejette les plans quasi verticaux (murs)
            continue
        d = -normal.dot(p0)
        dist = np.abs(P @ normal + d)
        inl = dist < thresh
        if best is None or inl.sum() > best[2].sum():
            best = (normal, d, inl)
    if best is None or best[2].sum() < min_inliers:
        return None
    inl = best[2]
    centroid = P[inl].mean(axis=0)
    _, _, vh = np.linalg.svd(P[inl] - centroid)
    normal = vh[2]
    if normal[2] < 0:
        normal = -normal
    d = -normal.dot(centroid)
    dist = np.abs(P @ normal + d)
    return normal, d, dist < thresh


def _ransac_planes(pts):
    planes, remaining, rng = [], pts.copy(), np.random.default_rng(0)
    while len(remaining) > MIN_INLIERS and len(planes) < MAX_PLANES_SAFETY:
        res = _fit_plane_ransac(remaining, rng)
        if res is None:
            break
        normal, d, inl = res
        planes.append({"normal": normal, "d": d})
        remaining = remaining[~inl]
    return planes


# ---------- 2. affectation point -> pan par croissance de region. ---------- #
def _grow_regions(pts, planes):
    tree = cKDTree(pts[:, :2])
    _, nn_idx = tree.query(pts[:, :2], k=K_NEIGH + 1)

    def score(j, normal, d):
        return abs(pts[j] @ normal + d)

    labels = np.full(len(pts), -1, dtype=int)
    regions = {}
    for pid, pl in enumerate(planes):
        dists = np.abs(pts @ pl["normal"] + pl["d"])
        seed = int(np.argmin(dists))
        labels[seed] = pid
        regions[pid] = {"normal": pl["normal"], "d": pl["d"], "pts_idx": [seed],
                        "last_refit": 1, "heap": []}
        for k in nn_idx[seed][1:]:
            if labels[k] == -1:
                heapq.heappush(regions[pid]["heap"], (score(k, pl["normal"], pl["d"]), int(k)))

    active_pids = set(regions)
    while active_pids:
        next_active = set()
        for pid in sorted(active_pids):
            rs = regions[pid]
            heap = rs["heap"]
            while heap:
                _, j = heapq.heappop(heap)
                if labels[j] != -1:
                    continue
                dist = score(j, rs["normal"], rs["d"])
                if dist <= MAX_DIST_M:
                    labels[j] = pid
                    rs["pts_idx"].append(j)
                    interval = max(5, len(rs["pts_idx"]) // 10)
                    if len(rs["pts_idx"]) - rs["last_refit"] >= interval:
                        P = pts[rs["pts_idx"]]
                        c = P.mean(axis=0)
                        _, _, vh = np.linalg.svd(P - c)
                        n_ = vh[2]
                        n_ = n_ if n_[2] > 0 else -n_
                        rs["normal"], rs["d"] = n_, -n_.dot(c)
                        rs["last_refit"] = len(rs["pts_idx"])
                    for k in nn_idx[j][1:]:
                        if labels[k] == -1:
                            heapq.heappush(heap, (score(k, rs["normal"], rs["d"]), int(k)))
                break
            if heap:
                next_active.add(pid)
        active_pids = next_active

    # mop-up restreint : ne comble que la bande non affectee la ou au plus 2
    # regions sont candidates parmi les voisins deja affectes.
    changed = True
    while changed:
        changed = False
        for j in np.where(labels == -1)[0]:
            neighbor_labels = {int(labels[k]) for k in nn_idx[j][1:] if labels[k] != -1}
            if not neighbor_labels or len(neighbor_labels) > 2:
                continue
            best_pid, best_dist = None, FALLBACK_DIST_M
            for pid in neighbor_labels:
                d = score(j, regions[pid]["normal"], regions[pid]["d"])
                if d < best_dist:
                    best_pid, best_dist = pid, d
            if best_pid is not None:
                labels[j] = best_pid
                regions[best_pid]["pts_idx"].append(j)
                changed = True

    pan_points = {}
    for pid in range(len(planes)):
        sel = labels == pid
        if sel.sum() >= MIN_PTS_PAN:
            pan_points[pid] = pts[sel]
    return labels, pan_points


# ---------- 4. enveloppe convexe par pan (points reels). ---------- #
def _pan_hulls(pan_points, planes):
    info, hulls = {}, {}
    for pid, P in pan_points.items():
        xs, ys, zs = P[:, 0], P[:, 1], P[:, 2]
        hull = MultiPoint(P[:, :2]).convex_hull
        if hull.geom_type != "Polygon":
            continue
        pl = planes[pid]
        pente = np.degrees(np.arccos(abs(pl["normal"][2])))
        info[pid] = {"pente_deg": float(pente), "z_moyen": float(zs.mean()),
                    "aire_m2": float(hull.area), "centroid": (float(xs.mean()), float(ys.mean()))}
        hulls[pid] = hull.simplify(0.15, preserve_topology=True)
    return info, hulls


# ---------- 5. aretes de jonction (mesurees, SVD, repli coin en L). ---------- #
def _fit_line_svd(P2d):
    mx, my = P2d[:, 0].mean(), P2d[:, 1].mean()
    _, _, vh = np.linalg.svd(P2d - [mx, my])
    dirv = vh[0]
    along = (P2d[:, 0] - mx) * dirv[0] + (P2d[:, 1] - my) * dirv[1]
    across = (P2d[:, 0] - mx) * (-dirv[1]) + (P2d[:, 1] - my) * dirv[0]
    p0 = (mx + along.min() * dirv[0], my + along.min() * dirv[1])
    p1 = (mx + along.max() * dirv[0], my + along.max() * dirv[1])
    return {"mx": mx, "my": my, "dirv": dirv, "p0": p0, "p1": p1,
            "longueur_m": float(along.max() - along.min()), "n_pts": len(P2d),
            "residu_max_m": float(np.abs(across).max())}


def _most_linear_component(P2d, radius=0.3):
    """Isole, parmi les composantes connexes, celle la plus proche d'une
    ligne unique -- sert a nettoyer un coin a 3 pans. MIN_COMPONENT_PTS est
    CRITIQUE : sans plancher de taille, un amas de 3-5 points gagne par pur
    hasard du ratio des valeurs singulieres, devant un amas bien plus grand
    et geometriquement reel (verifie iterativement avant ce portage)."""
    if len(P2d) < 4:
        return None
    tree = cKDTree(P2d)
    pairs = tree.query_pairs(radius, output_type="ndarray")
    if len(pairs) == 0:
        return None
    row = np.concatenate([pairs[:, 0], pairs[:, 1]])
    col = np.concatenate([pairs[:, 1], pairs[:, 0]])
    graph = coo_matrix((np.ones(len(row)), (row, col)), shape=(len(P2d), len(P2d)))
    n_comp, comp = connected_components(graph, directed=False)
    if n_comp <= 1:
        return None
    best, best_ratio = None, -1.0
    for c in range(n_comp):
        sub = P2d[comp == c]
        if len(sub) < MIN_COMPONENT_PTS:
            continue
        _, s, _ = np.linalg.svd(sub - sub.mean(axis=0))
        ratio = s[0] / (s[1] + 1e-9)
        if ratio > best_ratio:
            best_ratio, best = ratio, sub
    return best


def _boundary_pair(pts, labels, nn_idx, a, b):
    idx_a = np.where(labels == a)[0]
    idx_b = np.where(labels == b)[0]
    set_a, set_b = set(idx_a.tolist()), set(idx_b.tolist())
    near_a = [i for i in idx_a if set_b.intersection(nn_idx[i][1:])]
    near_b = [i for i in idx_b if set_a.intersection(nn_idx[i][1:])]
    n_edges = (sum(len(set_b.intersection(nn_idx[i][1:])) for i in idx_a) +
              sum(len(set_a.intersection(nn_idx[i][1:])) for i in idx_b))
    return near_a, near_b, n_edges


def _junction_edges(pts, labels, active, hulls, pan_points, info, plane_z_at, eave_attr_m, log):
    tree_pts = cKDTree(pts[:, :2])
    _, nn_idx = tree_pts.query(pts[:, :2], k=K_NEIGH + 1)

    edge_fits = {}
    for i, a in enumerate(active):
        for b in active[i + 1:]:
            near_a, near_b, n_edges = _boundary_pair(pts, labels, nn_idx, a, b)
            if n_edges < MIN_CROSS_EDGES or len(near_a) + len(near_b) < 2:
                continue
            combined = pts[near_a + near_b][:, :2]
            fit = _fit_line_svd(combined)
            if fit["residu_max_m"] > RESIDU_MAX_M:
                sub = _most_linear_component(combined)
                if sub is not None and len(sub) >= 2:
                    refit = _fit_line_svd(sub)
                    if refit["residu_max_m"] < fit["residu_max_m"]:
                        fit = refit
            fit["fiable"] = fit["residu_max_m"] <= RESIDU_MAX_M
            edge_fits[(a, b)] = fit

    # aretes libres (faitage sans pan oppose / egout), pour le repli 5ter.
    free_edges = []
    for pid in active:
        others = [o for o in active if o != pid]
        other_xy = np.vstack([pan_points[o][:, :2] for o in others]) if others else np.empty((0, 2))
        tree_other = cKDTree(other_xy) if len(other_xy) else None
        coords = list(hulls[pid].exterior.coords[:-1])
        n = len(coords)
        covered = []
        for k in range(n):
            p0, p1 = coords[k], coords[(k + 1) % n]
            mid = ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
            d = tree_other.query(mid)[0] if tree_other is not None else np.inf
            covered.append(d <= COVER_RADIUS_M)
        if all(covered):
            continue
        if not any(covered):
            # pan isole (aucun autre pan a proximite sur tout son pourtour,
            # ex. un petit batiment annexe a un seul pan) : tout le contour
            # est un unique run libre, pas besoin d'ancrer sur un point
            # "couvert" -- il n'en existe aucun ici.
            runs = [list(range(n))]
        else:
            start = next(k for k in range(n) if covered[k])
            order = [(start + k) % n for k in range(n)]
            runs, cur = [], []
            for idx in order:
                if not covered[idx]:
                    cur.append(idx)
                elif cur:
                    runs.append(cur); cur = []
            if cur:
                runs.append(cur)
        for run in runs:
            run_coords = [coords[k] for k in run] + [coords[(run[-1] + 1) % n]]
            for fit in _merge_free_run(pid, run_coords, pan_points):
                fit["fiable"] = fit["residu_max_m"] <= RESIDU_MAX_M
                z0, z1 = plane_z_at(pid, *fit["p0"]), plane_z_at(pid, *fit["p1"])
                z_line = (z0 + z1) / 2
                side = "bas" if z_line <= info[pid]["z_moyen"] else "haut"
                entry = {"pid": pid, "side": side, "longueur_m": fit["longueur_m"],
                        "residu_max_m": fit["residu_max_m"], "fiable": fit["fiable"],
                        "p0": [fit["p0"][0], fit["p0"][1], z0], "p1": [fit["p1"][0], fit["p1"][1], z1]}
                if side == "bas" and abs(z_line - eave_attr_m) > EAVE_TOL_M:
                    log(f"  pan {pid+1} (bas) : ecart BD TOPO {abs(z_line - eave_attr_m):.2f} m "
                        f"(LiDAR peu fiable a l'egout)")
                free_edges.append(entry)
    return edge_fits, free_edges


def _points_near_polyline(pan_points, pid, poly_coords, buffer_m=SEG_BUFFER_M):
    buf = LineString(poly_coords).buffer(buffer_m)
    P = pan_points[pid][:, :2]
    sel = np.array([buf.contains(Point(x, y)) for x, y in P])
    return P[sel]


def _merge_free_run(pid, run_coords, pan_points):
    """Fusionne prudemment les segments consecutifs d'un run : etend une
    chaine tant que le residu de la droite fusionnee reste sous le seuil."""
    def fit_or_none(coords):
        P = _points_near_polyline(pan_points, pid, coords)
        return _fit_line_svd(P) if len(P) >= 4 else None

    n_seg = len(run_coords) - 1
    results, start = [], 0
    while start < n_seg:
        end = start + 1
        best = fit_or_none(run_coords[start:end + 1])
        while end < n_seg:
            candidate = fit_or_none(run_coords[start:end + 2])
            if candidate is not None and candidate["residu_max_m"] <= RESIDU_MAX_M:
                end += 1
                best = candidate
            else:
                break
        if best is not None:
            results.append(best)
        start = end
    return results


# ---------- 5ter. repli geometrique pour un faitage mesure trop court entre
#     2 pans quasi paralleles. ---------- #
def _geometric_ridges(edge_fits, free_edges, info, log):
    def best_free_edge(pid):
        cands = [fe for fe in free_edges if fe["pid"] == pid and fe["fiable"]]
        return max(cands, key=lambda fe: fe["longueur_m"]) if cands else None

    for (a, b), fit in list(edge_fits.items()):
        if fit["longueur_m"] >= SHORT_EDGE_M:
            continue
        if abs(info[a]["pente_deg"] - info[b]["pente_deg"]) > PITCH_DIFF_MAX_DEG:
            continue
        fa, fb = best_free_edge(a), best_free_edge(b)
        if fa is None or fb is None:
            continue
        pa0, pa1 = np.array(fa["p0"][:2]), np.array(fa["p1"][:2])
        pb0, pb1 = np.array(fb["p0"][:2]), np.array(fb["p1"][:2])
        dir_a = (pa1 - pa0) / np.linalg.norm(pa1 - pa0)
        dir_b = (pb1 - pb0) / np.linalg.norm(pb1 - pb0)
        if dir_b @ dir_a < 0:
            pb0, pb1, dir_b = pb1, pb0, -dir_b
        angle_deg = np.degrees(np.arccos(np.clip(dir_a @ dir_b, -1.0, 1.0)))
        if angle_deg > DIR_ANGLE_MAX_DEG:
            continue
        dirv = (dir_a + dir_b) / np.linalg.norm(dir_a + dir_b)
        center = (pa0 + pa1 + pb0 + pb1) / 4
        mx, my = float(center[0]), float(center[1])
        proj = lambda p: (p[0] - mx) * dirv[0] + (p[1] - my) * dirv[1]
        ra = sorted([proj(pa0), proj(pa1)])
        rb = sorted([proj(pb0), proj(pb1)])
        lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
        if hi <= lo:
            lo, hi = min(ra[0], rb[0]), max(ra[1], rb[1])
        edge_fits[(a, b)] = {
            "mx": mx, "my": my, "dirv": dirv,
            "p0": (mx + lo * dirv[0], my + lo * dirv[1]), "p1": (mx + hi * dirv[0], my + hi * dirv[1]),
            "longueur_m": float(hi - lo), "fiable": True, "residu_max_m": fit["residu_max_m"],
            "methode": "geometrique"}


# ---------- 5quater. recalage automatique sur l'orthophoto. ---------- #
def _ortho_recalage(edge_fits, E0, N1, log):
    if not edge_fits:
        return
    xs = [c for fit in edge_fits.values() for c in (fit["p0"][0], fit["p1"][0])]
    ys = [c for fit in edge_fits.values() for c in (fit["p0"][1], fit["p1"][1])]
    pad = 4.0
    o_minx, o_maxx = min(xs) - pad, max(xs) + pad
    o_miny, o_maxy = min(ys) - pad, max(ys) + pad
    bbox_l93 = (E0 + o_minx, N1 - o_maxy, E0 + o_maxx, N1 - o_miny)
    try:
        ortho_rgb, _ = cg.wms_ortho_rgb(mult=ORTHO_MULT, bbox_l93=bbox_l93)
    except Exception as e:                                        # noqa: BLE001
        log(f"  recalage ortho indisponible ({e}) -- aretes mesurees conservees telles quelles")
        return
    from scipy import ndimage
    ortho_gray = ortho_rgb.mean(axis=2)
    ortho_grad = np.hypot(ndimage.sobel(ortho_gray, axis=1), ndimage.sobel(ortho_gray, axis=0))

    def to_px(x, y):
        return ((x - o_minx) * ORTHO_MULT, (o_maxy - y) * ORTHO_MULT)

    def sample(px, py):
        ix, iy = int(round(px)), int(round(py))
        if 0 <= iy < ortho_grad.shape[0] and 0 <= ix < ortho_grad.shape[1]:
            return ortho_grad[iy, ix]
        return 0.0

    for (a, b), fit in list(edge_fits.items()):
        p0, p1 = np.array(fit["p0"]), np.array(fit["p1"])
        length = np.linalg.norm(p1 - p0)
        if length < 0.5:
            continue
        dirv = (p1 - p0) / length
        normal = np.array([-dirv[1], dirv[0]])
        ts = np.linspace(0.15, 0.85, 12)
        offs = list(range(-ORTHO_SEARCH_PX, ORTHO_SEARCH_PX + 1))
        profile = [np.mean([sample(*to_px(*(p0 + t * (p1 - p0) + (o / ORTHO_MULT) * normal)))
                            for t in ts]) for o in offs]
        i_best = int(np.argmax(profile))
        convergent = 0 < i_best < len(offs) - 1
        if not convergent or profile[i_best] < ORTHO_SCORE_MIN:
            continue
        offset_m = offs[i_best] / ORTHO_MULT
        mx, my, dv = fit["mx"], fit["my"], fit["dirv"]
        nx, ny = -dv[1], dv[0]
        new_fit = dict(fit)
        new_fit["mx"], new_fit["my"] = mx + offset_m * nx, my + offset_m * ny
        new_fit["p0"] = (fit["p0"][0] + offset_m * nx, fit["p0"][1] + offset_m * ny)
        new_fit["p1"] = (fit["p1"][0] + offset_m * nx, fit["p1"][1] + offset_m * ny)
        new_fit["methode"] = fit.get("methode", "mesure") + "+ortho"
        edge_fits[(a, b)] = new_fit


# ---------- 5quinquies. remplacement par la droite ANALYTIQUE (intersection
#     pure des 2 plans deja connus) quand elle est justifiee. ---------- #
def _analytic_replace(edge_fits, planes, pts, labels, log):
    tree_pts = cKDTree(pts[:, :2])
    _, nn_idx = tree_pts.query(pts[:, :2], k=K_NEIGH + 1)

    for (a, b), fit in list(edge_fits.items()):
        na, da = planes[a]["normal"], planes[a]["d"]
        nb, db = planes[b]["normal"], planes[b]["d"]
        A = nb[2] * na[0] - na[2] * nb[0]
        B = nb[2] * na[1] - na[2] * nb[1]
        C = nb[2] * da - na[2] * db
        norm = np.hypot(A, B)
        if norm < 1e-6:
            continue
        A, B, C = A / norm, B / norm, C / norm
        near_a, near_b, n_edges = _boundary_pair(pts, labels, nn_idx, a, b)
        if n_edges < MIN_CROSS_EDGES or len(near_a) + len(near_b) < 2:
            continue
        combined = pts[near_a + near_b][:, :2]
        residual = A * combined[:, 0] + B * combined[:, 1] + C
        residu_max = float(np.abs(residual).max())
        if residu_max > ANALYTIC_TOL_M:
            continue
        dirv = np.array([-B, A])
        p0_line = np.array([-A * C, -B * C])
        centroid = combined.mean(axis=0)
        mx, my = (p0_line + np.dot(centroid - p0_line, dirv) * dirv).tolist()
        along = (combined[:, 0] - mx) * dirv[0] + (combined[:, 1] - my) * dirv[1]
        edge_fits[(a, b)] = {
            "mx": mx, "my": my, "dirv": dirv,
            "p0": (mx + along.min() * dirv[0], my + along.min() * dirv[1]),
            "p1": (mx + along.max() * dirv[0], my + along.max() * dirv[1]),
            "longueur_m": float(along.max() - along.min()), "residu_max_m": residu_max,
            "fiable": True, "methode": "analytique"}


# ---------- 6. polygone final par pan = enveloppe recoupee par ses aretes. ---------- #
def _polygon_pieces(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def _largest_polygon(geom):
    pieces = _polygon_pieces(geom)
    return max(pieces, key=lambda g: g.area) if pieces else geom


def _pan_majority_sign(pan_points, pid, mx, my, nx, ny):
    P = pan_points[pid][:, :2]
    signs = np.sign((P[:, 0] - mx) * nx + (P[:, 1] - my) * ny)
    s = np.sign(signs.sum())
    return s if s != 0 else 1.0


def _local_halfplane(pan_points, pid, fit, extent=80.0):
    mx, my, dirv = fit["mx"], fit["my"], fit["dirv"]
    nx, ny = -dirv[1], dirv[0]
    line_half = extent * 3
    a_pt = (mx - dirv[0] * line_half, my - dirv[1] * line_half)
    b_pt = (mx + dirv[0] * line_half, my + dirv[1] * line_half)
    line = LineString([a_pt, b_pt])
    big = box(mx - extent, my - extent, mx + extent, my + extent)
    pieces = split(big, line)
    self_sign = _pan_majority_sign(pan_points, pid, mx, my, nx, ny)
    for piece in pieces.geoms:
        rep = piece.representative_point()
        if np.sign((rep.x - mx) * nx + (rep.y - my) * ny) == self_sign:
            return piece
    return big


def _edge_separates(pan_points, a, b, fit):
    mx, my, dirv = fit["mx"], fit["my"], fit["dirv"]
    nx, ny = -dirv[1], dirv[0]
    return (_pan_majority_sign(pan_points, a, mx, my, nx, ny) !=
            _pan_majority_sign(pan_points, b, mx, my, nx, ny))


def _nearest_centroid_split(info, a, b, region):
    ca = np.array(info[a]["centroid"])
    cb = np.array(info[b]["centroid"])
    d = cb - ca
    norm = np.linalg.norm(d)
    if norm < 1e-9:
        return region, Polygon()
    d = d / norm
    mid = (ca + cb) / 2
    n = np.array([-d[1], d[0]])
    ext = 200.0
    line = LineString([mid - n * ext, mid + n * ext])
    pieces = split(region, line)
    side_a, side_b = [], []
    for piece in _polygon_pieces(pieces) or [region]:
        rep = piece.representative_point()
        side = (rep.x - mid[0]) * d[0] + (rep.y - mid[1]) * d[1]
        (side_a if side < 0 else side_b).append(piece)
    return (unary_union(side_a) if side_a else Polygon(),
            unary_union(side_b) if side_b else Polygon())


def _cut_pans(active, hulls, pan_points, edge_fits, info, log):
    edge_fits_cut = {k: v for k, v in edge_fits.items()
                    if not v.get("methode", "mesure").startswith("geometrique")
                    and _edge_separates(pan_points, k[0], k[1], v)}
    polys = {}
    for pid in active:
        poly = hulls[pid]
        for (a, b), fit in edge_fits_cut.items():
            if pid not in (a, b):
                continue
            poly = _largest_polygon(poly.intersection(_local_halfplane(pan_points, pid, fit)))
        polys[pid] = poly

    for i, a in enumerate(active):
        for b in active[i + 1:]:
            pa, pb = polys[a], polys[b]
            inter = pa.intersection(pb)
            if inter.is_empty or inter.area <= 1e-9:
                continue
            test_pa = _largest_polygon(pa.difference(inter))
            test_pb = _largest_polygon(pb.difference(inter))
            a_clean = len(test_pa.interiors) == 0
            b_clean = len(test_pb.interiors) == 0
            if b_clean and not a_clean:
                fixed_a, fixed_b = pa, test_pb
            elif a_clean and not b_clean:
                fixed_a, fixed_b = test_pa, pb
            else:
                piece_a, piece_b = _nearest_centroid_split(info, a, b, inter)
                fixed_a = _largest_polygon(pa.difference(piece_b)) if not piece_b.is_empty else pa
                fixed_b = _largest_polygon(pb.difference(piece_a)) if not piece_a.is_empty else pb
            if not fixed_a.is_empty and fixed_a.geom_type == "Polygon" and len(fixed_a.interiors) == 0:
                polys[a] = fixed_a
            if not fixed_b.is_empty and fixed_b.geom_type == "Polygon" and len(fixed_b.interiors) == 0:
                polys[b] = fixed_b
    return polys


# ---------- 7. bloc 3D complet sur le contour ENTIER (Voronoi + coverage_simplify). ---------- #
def _full_footprint(active, polys, footprint_poly, log):
    full_polys = {pid: _largest_polygon(polys[pid].intersection(footprint_poly)) for pid in active}

    remainder = footprint_poly.difference(unary_union(list(full_polys.values())))
    if remainder.area > 1e-9:
        seed_pts, seed_pid = [], []
        for pid in active:
            eb = polys[pid].exterior
            n_samples = max(8, int(eb.length / BOUNDARY_SAMPLE_M))
            for t in np.linspace(0.0, eb.length, n_samples, endpoint=False):
                p = eb.interpolate(t)
                seed_pts.append((p.x, p.y))
                seed_pid.append(pid)
        envelope = footprint_poly.buffer(5.0)
        cells = voronoi_polygons(MultiPoint(seed_pts), extend_to=envelope, ordered=True)
        remainder_pieces = {pid: [] for pid in active}
        for pid, cell in zip(seed_pid, cells.geoms):
            piece = cell.intersection(remainder)
            if not piece.is_empty:
                remainder_pieces[pid].append(piece)
        for pid in active:
            if remainder_pieces[pid]:
                full_polys[pid] = unary_union([full_polys[pid]] + remainder_pieces[pid])

    # Recouvrement AVANT la decoupe exclusive ci-dessous : mesure la
    # fiabilite REELLE de la partition. Un recouvrement massif entre 2 pans
    # (ex. ~4 m2) signifie qu'ils n'ont aucune relation etablie (aucune
    # arete de jonction detectee entre eux) -- leur forcer une frontiere
    # arbitraire produit un contour en dents de scie sans rapport avec le
    # vrai toit (constate au rendu reel : bien pire qu'un repli pyramidal
    # honnete). Il faut le mesurer ICI : le passage d'exclusivite plus bas
    # ecrase PAR CONSTRUCTION tout recouvrement, y compris ceux qui auraient
    # du faire echouer la reconstruction (cf. `raw_overlap` dans le controle
    # de fiabilite final).
    raw_overlap = sum(full_polys[active[i]].intersection(full_polys[active[j]]).area
                      for i in range(len(active)) for j in range(i + 1, len(active)))

    # Chaque pan doit ensuite rester un sous-ensemble EXCLUSIF du contour,
    # ne serait-ce que pour le residu geometrique bien plus modeste laisse
    # par le remplissage du "remainder" ci-dessus (cellule Voronoi etendue a
    # une enveloppe bufferisee de 5 m, pas au contour exact -- peut deborder
    # du vrai contour ou empieter legerement sur un pan voisin, de l'ordre
    # du dixieme de m2, constate invisible sur le papier mais visible au
    # rendu reel en fin de mur/pan surnumeraire). Passage final deterministe
    # (ordre de `active`) : retranche a chaque pan ce qu'un pan precedent a
    # deja revendique. Necessaire pour un maillage propre, mais n'annule pas
    # le diagnostic `raw_overlap` ci-dessus.
    assigned_so_far = Polygon()
    for pid in active:
        full_polys[pid] = _largest_polygon(
            full_polys[pid].intersection(footprint_poly).difference(assigned_so_far))
        assigned_so_far = unary_union([assigned_so_far, full_polys[pid]])

    union_all = unary_union(list(full_polys.values()))
    gap = footprint_poly.difference(union_all)
    if gap.area > 1e-6:
        for gp in _polygon_pieces(gap):
            if gp.area < 1e-9:
                continue
            candidates = sorted(active, key=lambda pid: full_polys[pid].distance(gp))
            chosen, merged = None, None
            for pid in candidates:
                if full_polys[pid].distance(gp) > 0.05:
                    break
                m = unary_union([full_polys[pid], gp])
                if m.geom_type == "Polygon":
                    chosen, merged = pid, m
                    break
            if chosen is not None:
                full_polys[chosen] = merged

    overlap_total = sum(full_polys[active[i]].intersection(full_polys[active[j]]).area
                        for i in range(len(active)) for j in range(i + 1, len(active)))
    union_all = unary_union(list(full_polys.values()))
    gap = footprint_poly.difference(union_all).area

    simplified = coverage_simplify(
        [full_polys[pid] for pid in active], COVERAGE_SIMPLIFY_TOL_M, simplify_boundary=True)
    candidate = dict(zip(active, simplified))
    cand_overlap = sum(candidate[active[i]].intersection(candidate[active[j]]).area
                       for i in range(len(active)) for j in range(i + 1, len(active)))
    cand_union = unary_union(list(candidate.values()))
    cand_gap = footprint_poly.difference(cand_union).area
    cand_frag = any(p.geom_type != "Polygon" or p.is_empty for p in candidate.values())
    if cand_overlap < COVERAGE_SIMPLIFY_ACCEPT_M2 and cand_gap < COVERAGE_SIMPLIFY_ACCEPT_M2 and not cand_frag:
        n_before = sum(len(full_polys[pid].exterior.coords) - 1 for pid in active)
        full_polys = candidate
        overlap_total, gap = cand_overlap, cand_gap
        n_after = sum(len(full_polys[pid].exterior.coords) - 1 for pid in active)
        log(f"  toit LiDAR : coverage_simplify applique ({n_before} -> {n_after} sommets, "
            f"trou {cand_gap:.4f} m2, chevauchement {cand_overlap:.4f} m2)")
    else:
        log(f"  toit LiDAR : coverage_simplify rejete (trou {cand_gap:.4f} m2, "
            f"chevauchement {cand_overlap:.4f} m2, fragmente={cand_frag}) -- "
            f"partition Voronoi brute conservee")

    final_cover = unary_union(list(full_polys.values())).area
    if (abs(final_cover - footprint_poly.area) > 0.5 or overlap_total > 0.5 or gap > 0.5
            or raw_overlap > 0.5):
        log(f"  toit LiDAR : partition non fiable (couverture {final_cover:.1f}/"
            f"{footprint_poly.area:.1f} m2, recouvrement {overlap_total:.2f} m2, "
            f"recouvrement brut {raw_overlap:.2f} m2, trou {gap:.2f} m2) -> repli pyramidal")
        return None
    if any(p.geom_type != "Polygon" or p.is_empty for p in full_polys.values()):
        log("  toit LiDAR : au moins un pan vide/fragmente -> repli pyramidal")
        return None
    return full_polys


# ---------- 7bis. maillage PyVista : murs (hauteur variable) + toit. ---------- #
PAN_SOLIDIFY_DEPTH_CM = 60.0   # epaisseur cachee sous chaque pan, cf. cg.solidify (terrain :
                               # 800 cm ; ici juste assez pour rester sous le pan, jamais visible
                               # depuis l'exterieur ni traverser un mur/pan oppose).
HIDDEN_CAP_MARGIN_CM = 2.0     # abaisse le capot HAUT du mur sous le pan qui le recouvre (meme
                               # plan par construction -- cf. `_mesh_groups`) pour eviter le
                               # z-fighting quand un pan couvre 100% du capot d'un seul tenant.


def _mesh_groups(active, full_polys, plane_z_at, base_m, plan_origin_l93,
                 ortho_arr, ortho_bbox_l93, log):
    """
    Construit des SOLIDES FERMES separes (meme convention que bati.py pour le
    voisinage : `cg.polygon_prism` + `cg.pyramid_roof`, jamais une simple
    surface ouverte) -- une surface ouverte n'a pas de cote "exterieur" bien
    defini pour `compute_normals(auto_orient_normals=True)`, qui suppose un
    volume clos (risque de faces cullees selon l'angle, cf. limitation deja
    documentee dans docs/PIPELINE.md pour les toits pyramidaux). Le mur
    (hauteur variable) est ferme par un plancher + un capot HAUT non plan
    (suit le pan juste au-dessus, meme principe que le plancher fictif du
    prototype de validation) ; chaque pan de toit est ferme par extrusion
    verticale cachee (`cg.solidify`), qui chevauche invisiblement ce capot
    (memes materiaux 100% mats, cf. `cg.write_mtl`) -- exactement le motif
    deja utilise par `pyramid_roof` avec le capot du prisme mur.
    """
    import pyvista as pv
    from shapely.geometry import Point as ShPoint

    E0, N1 = plan_origin_l93

    def owning_pan(x, y):
        pt = ShPoint(x, y)
        return min(active, key=lambda pid: full_polys[pid].distance(pt))

    def to_l93(x_m, y_m):
        return E0 + x_m, N1 - y_m

    footprint_ring = list(unary_union(list(full_polys.values())).exterior.coords[:-1])
    n_ring = len(footprint_ring)
    base_cm = base_m * 100.0
    wall_top_cm = [(x * 100.0, y * 100.0, plane_z_at(owning_pan(x, y), x, y) * 100.0)
                  for x, y in footprint_ring]

    verts, tris = [], []

    def add_vert(x, y, z):
        verts.append((x, y, z))
        return len(verts) - 1

    floor_idx = [add_vert(x * 100.0, y * 100.0, base_cm) for x, y in footprint_ring]
    wall_top_idx = [add_vert(*p) for p in wall_top_cm]
    for i in range(n_ring):
        j = (i + 1) % n_ring
        a_, b_, c_, d_ = floor_idx[i], floor_idx[j], wall_top_idx[j], wall_top_idx[i]
        tris += [(a_, b_, c_), (a_, c_, d_)]
    side_faces = np.hstack([[3] + list(t) for t in tris])
    side_mesh = pv.PolyData(np.array(verts), faces=side_faces)

    # capots : plancher + un capot HAUT non plan qui suit le contour (couvre
    # le vide sous les pans, invisible sous leur extrusion -- cf. docstring),
    # pour que le mur soit un solide FERME comme le reste du depot. Le
    # contour du batiment (kink, angles rentrants) n'est pas garanti convexe
    # -- polygone N-gon + `.triangulate()` (meme motif que `cg.polygon_prism`),
    # jamais un fan depuis le sommet 0 : des qu'un contour est concave, un fan
    # produit des triangles hors du polygone (constate au rendu reel : gash/
    # trou triangulaire dans le toit et pan blanc flottant non colore).
    verts_a = np.array(verts)
    floor_cap = pv.PolyData(verts_a[floor_idx],
                            faces=np.hstack([[n_ring] + list(range(n_ring))])).triangulate()
    # le capot HAUT est cense etre entierement cache sous le pan (meme plan,
    # cf. `owning_pan`/`plane_z_at` ci-dessus) -- mais un pan et son capot
    # triangules independamment ne sont PAS coincidents triangle a triangle
    # meme sur un plan identique, d'ou du z-fighting visible au rendu reel
    # (liseret blanc scintillant sur un pan a 1 seul plan, ou le capot
    # recouvre 100% de sa surface). On abaisse le capot d'une marge fixe pour
    # qu'il passe strictement sous le pan partout, jamais a egalite.
    top_cap_pts = verts_a[wall_top_idx].copy()
    top_cap_pts[:, 2] -= HIDDEN_CAP_MARGIN_CM
    top_cap = pv.PolyData(top_cap_pts,
                          faces=np.hstack([[n_ring] + list(range(n_ring - 1, -1, -1))])).triangulate()
    wall_mesh = (side_mesh + floor_cap + top_cap).clean()
    wall_mesh = wall_mesh.compute_normals(auto_orient_normals=True, consistent_normals=True,
                                          non_manifold_traversal=False)

    groups = [("bati_propriete_mur", wall_mesh, "mur")]
    for pid, poly in full_polys.items():
        coords = list(poly.exterior.coords[:-1])
        n_ = len(coords)
        if n_ < 3:
            continue
        pts_cm = np.array([[x * 100.0, y * 100.0, plane_z_at(pid, x, y) * 100.0] for x, y in coords])
        # polygone N-gon + `.triangulate()` (meme motif que `cg.polygon_prism`,
        # jamais un fan depuis le sommet 0) : un pan issu de la partition
        # Voronoi + `coverage_simplify` n'est pas garanti convexe.
        pan_surf = pv.PolyData(pts_cm, faces=np.hstack([[n_] + list(range(n_))])).triangulate()
        pan_mesh = cg.solidify(pan_surf, depth_cm=PAN_SOLIDIFY_DEPTH_CM)
        poly_l93 = Polygon([to_l93(x, y) for x, y in coords])
        rc = cg.roof_color_from_ortho(poly_l93, ortho_arr, ortho_bbox_l93)
        key = {(139, 58, 43): "tuile", (62, 66, 72): "ardoise",
              (120, 124, 130): "fibro"}.get(tuple(rc), "ardoise")
        groups.append((f"bati_propriete_toit_{pid}", pan_mesh, key))
    return groups
