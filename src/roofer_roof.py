"""
roofer_roof.py : toit + mur des batiments reconstruits par l'outil externe
`roofer` (moteur 3DBAG/TU Delft, LoD2.2, GPLv3, non redistribue dans ce
depot -- appel CLI, aucun code copie/lie -- cf. CLAUDE.md section
"Dependance externe : roofer"). Methode principale du pipeline (remplace
roof_lidar.py, conserve dans le depot a titre de reference/comparaison --
roof_lidar.py, roofer_compare.py -- mais plus appele depuis bati.py).

Suppose un environnement Linux pour l'execution du pipeline de generation
(roofer n'a pas de build Windows officiel) -- Windows ne sert qu'a ouvrir/
rendre le .sh3d final dans Sweet Home 3D natif, cf. CLAUDE.md.

Pipeline :
  1. `run_roofer()` : UN SEUL appel CLI sur les dalles LiDAR HD IGN brutes
     (classes sol+batiment non filtrees, comme deja telechargees par
     `cg.lidar_points_l93`) + l'empreinte BD TOPO de TOUS les batiments a la
     fois (1 GeoPackage) -- sortie CityJSONSequence LoD2.2.
  2. `build_roof()` par batiment : consomme le `Solid` CityJSON TEL QUEL
     (aucune reconstruction geometrique propre -- ni regroupement de faces
     en pans, ni extrapolation de plan pour le mur). roofer fournit deja un
     solide ferme et valide, avec la semantique par face
     (`GroundSurface`/`WallSurface`/`RoofSurface`, un seul index de surface
     = un pan complet, verifie sur les 18 batiments de cette session : 0
     face de toit fragmentee, 0 arete ouverte dans le solide brut).
     Reproduit la pratique du projet officiel `3DBAG/3dbag-surfaces`, qui
     classe les faces par semantics au lieu de reconstruire un mur a part
     (cf. plan de cette session pour le detail des sources). Seul ajout :
     un decalage vertical RIGIDE (une seule translation, pas de
     reconstruction par sommet) pour ancrer le solide sous le maillage
     terrain, meme marge de securite (`base_cm`, deja calcule par
     `bati.py`) que les autres types de batiments du pipeline.

`run_roofer()` renvoie None (binaire absent, echec CLI, sortie vide) et
`build_roof()` renvoie None (pas de geometrie LoD2.2 pour ce batiment, pas
de semantics exploitables) -- dans les deux cas `bati.py` se replie sur le
toit pyramidal, jamais de batiment sans toit modelise.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pyvista as pv
from shapely.geometry import Polygon
from shapely.ops import unary_union

import sitegeo as cg

CLEAN_TOLERANCE_CM = 1e-2         # fusion des sommets dupliques entre faces adjacentes du Solid
ROOFER_TIMEOUT_S = 600

LIDAR_CLASS_DIVERS_BATI_IGN = 67  # classe IGN hors nomenclature ASPRS ("Divers - batis"),
                                   # invisible pour --bld-class de roofer (defaut 6)
LIDAR_CLASS_BATIMENT = 6

# Memes noms de colonne BD TOPO que l'exemple officiel IGN
# ignfab/roofer-with-ignf-datasets (scripts/run_workflow.sh, appel roofer) :
# --h-terrain-attribute altitude_minimale_sol --h-roof-attribute altitude_maximale_toit.
H_TERRAIN_FIELD = "altitude_minimale_sol"
H_ROOF_FIELD = "altitude_maximale_toit"


def find_roofer_bin() -> str | None:
    """Meme esprit que `cg.find_sweethome3d_jar` : None si absent, jamais
    d'exception -- l'appelant decide du repli (toit pyramidal)."""
    p = shutil.which("roofer") or str(Path.home() / ".local" / "bin" / "roofer")
    return p if Path(p).exists() else None


def roofer_gdal_data(bin_path: str) -> str | None:
    """Dossier `share/gdal` du bundle roofer (`bin/roofer` + `share/proj` +
    `share/gdal` cote a cote dans l'archive officielle, cf. Dockerfile),
    ou None si absent. PROJ se relocalise seul (`/proc/self/exe` + chemin
    relatif, verifie dans le binaire), mais GDAL n'a pas cet equivalent -- le
    binaire ne retrouverait alors que son chemin de build Conan (absent a
    l'execution). Ne JAMAIS positionner GDAL_DATA globalement (casserait le
    gdal_contour systeme utilise par courbes.py, qui trouve deja tout seul
    son propre GDAL_DATA) : uniquement pour ce sous-processus roofer. Publique
    (pas de prefixe `_`) : reutilisee telle quelle par roofer_compare.py."""
    share_gdal = Path(bin_path).resolve().parent.parent / "share" / "gdal"
    return str(share_gdal) if share_gdal.is_dir() else None


def prepare_out_dir(out_dir: Path) -> None:
    """Vide out_dir (sinon un .city.jsonl d'une execution precedente, sur une
    autre bbox, serait repris a tort par un glob() ulterieur) puis le
    recree. Peut lever OSError si rmtree n'a pas tout supprime (permissions,
    fichier tenu ouvert) -- a l'appelant de decider du repli (toit pyramidal
    ici ; SystemExit explicite cote roofer_compare.py, outil de diagnostic)."""
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)


def cleabs_for(rid: str, i: int, n_polys: int) -> str:
    """Identifiant cleabs pour le i-eme polygone d'un batiment (n_polys
    parties disjointes au total) : suffixe uniquement si MultiPolygon (sinon
    inchange, cas majoritaire). `write_footprint_gpkg` et l'appelant de
    `build_roof` (bati.py) DOIVENT utiliser le meme identifiant pour un meme
    polygone -- sinon toit duplique/mal place sur les batiments MultiPolygon
    (cf. issue #35)."""
    return rid if n_polys == 1 else f"{rid}_{i}"


def run_roofer(footprint_gpkg: Path, laz_paths: list[Path], out_dir: Path, *, log=print):
    """Appel CLI unique sur tous les batiments du footprint_gpkg (un
    GeoPackage EPSG:2154 avec une colonne 'cleabs'). Renvoie
    {"records": [...], "scale": [...], "translate": [...]} ou None."""
    bin_path = find_roofer_bin()
    if bin_path is None:
        log("  toit roofer : binaire introuvable (PATH / ~/.local/bin) -> repli pyramidal")
        return None
    if not laz_paths:
        log("  toit roofer : aucune dalle LiDAR HD -> repli pyramidal")
        return None
    try:
        prepare_out_dir(out_dir)
    except OSError as e:
        log(f"  toit roofer : dossier de sortie inutilisable ({type(e).__name__}: {e}) -> repli pyramidal")
        return None
    cmd = [bin_path, "--lod22",
           "--h-terrain-attribute", H_TERRAIN_FIELD, "--h-roof-attribute", H_ROOF_FIELD,
           *[str(p) for p in laz_paths], str(footprint_gpkg), str(out_dir)]
    env = os.environ.copy()
    gdal_data = roofer_gdal_data(bin_path)
    if gdal_data:
        env["GDAL_DATA"] = gdal_data
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=ROOFER_TIMEOUT_S, env=env)
    except Exception as e:                                          # noqa: BLE001
        log(f"  toit roofer : appel CLI echoue ({type(e).__name__}: {e}) -> repli pyramidal")
        return None
    if r.returncode != 0:
        log(f"  toit roofer : code retour {r.returncode} -> repli pyramidal\n{r.stderr[-500:]}")
        return None
    seq_files = list(out_dir.glob("*.city.jsonl"))
    if not seq_files:
        log("  toit roofer : aucune sortie .city.jsonl -> repli pyramidal")
        return None

    scale, translate = (1e-4, 1e-4, 1e-4), (0.0, 0.0, 0.0)
    records = []
    try:
        for line in seq_files[0].read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            t = rec.get("transform")
            if t is not None:
                scale, translate = t["scale"], t["translate"]
            if rec.get("CityObjects"):
                records.append(rec)
    except Exception as e:                                          # noqa: BLE001
        log(f"  toit roofer : sortie CityJSON illisible ({type(e).__name__}: {e}) -> repli pyramidal")
        return None
    if not records:
        log("  toit roofer : sortie CityJSON sans batiment -> repli pyramidal")
        return None
    log(f"  toit roofer : {len(records)} batiment(s) reconstruit(s)")
    return {"records": records, "scale": scale, "translate": translate}


def _remap67_path(src: Path) -> Path:
    """Chemin de la copie remappee (67 -> 6) d'une dalle brute, dans un
    sous-dossier dedie du cache LiDAR partage -- jamais le fichier source lui
    meme (cg.lidar_points_l93 le relit tel quel, classe 6 stricte, pour ses
    propres besoins)."""
    return cg.LIDAR_CACHE / "roofer_remap67to6" / src.name


def _remap67(src: Path, dst: Path) -> None:
    """Copie `src` -> `dst` (pur laspy/numpy, pas de dependance PDAL -- deja
    ecartee, cf. config/environment.yml) avec les points classes 67 (IGN
    "Divers - batis", hors nomenclature ASPRS) remappes en 6 (batiment
    ASPRS) : roofer ne regarde que --bld-class/--grnd-class (defaut 6/2), les
    points 67 lui sont sinon invisibles -- jusqu'a 55 % de l'emprise BD TOPO
    non couverte par les pans reconstruits, constate sur 18 batiments reels
    (cf. CLAUDE.md). Reproduit le remap PDAL `filters.assign` 67 -> 6
    documente par l'exemple officiel IGN ignfab/roofer-with-ignf-datasets.

    Les dalles LiDAR HD IGN sont distribuees au format COPC (`.copc.laz`,
    cf. CLAUDE.md issue #24) : `laspy` sait le LIRE mais refuse de le
    RE-ecrire tel quel (`NotImplementedError: Writing COPC is not
    supported`, constate sur une dalle reelle -- l'appelant (`lidar_tile_paths`)
    absorbe cette exception et fournit la dalle sans remap, mais ca annule
    silencieusement le remap sur TOUTE dalle COPC, systematiquement). Le
    format COPC vient de deux VLR/EVLR specifiques (l'index octree) que
    `laspy` ne sait pas reserialiser -- on les retire avant l'ecriture ; la
    copie remappee redevient une dalle LAZ classique (jamais relue en COPC,
    seul `cg.lidar_points_l93` lit le fichier source original)."""
    import laspy
    from laspy.vlrs.vlrlist import VLRList

    las = laspy.read(src)
    c = np.asarray(las.classification)
    mask = c == LIDAR_CLASS_DIVERS_BATI_IGN
    if mask.any():
        c = c.copy()
        c[mask] = LIDAR_CLASS_BATIMENT
        las.classification = c
    las.header.vlrs = VLRList(v for v in las.header.vlrs
                              if type(v).__name__ != "CopcInfoVlr")
    las.header.evlrs = VLRList(v for v in las.header.evlrs
                               if type(v).__name__ != "CopcHierarchyVlr")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".part")
    las.write(tmp)
    tmp.rename(dst)


def lidar_tile_paths(bbox_l93, margin_m: float = 5.0, *, log=print) -> list[Path]:
    """Dalles LAZ IGN couvrant bbox_l93+marge, classe 67 remappee en 6 (cf.
    `_remap67`) -- force le telechargement/cache (cg.lidar_points_l93, effet
    de bord) puis retrouve les chemins de dalles concernees via
    `cg.lidar_tile_index` (meme requete WFS, mise en cache disque -- cf.
    `cg._cached`), pour ne donner a roofer QUE les dalles pertinentes (pas
    tout data/lidar_cache/, qui peut contenir des dalles d'executions
    anterieures sur une autre zone). Le remap est lui-meme mis en cache
    disque (`_remap67_path`, jamais invalide automatiquement comme le reste
    de `data/`, cf. `rm -rf data/net_cache`/`data/lidar_cache` documente dans
    CLAUDE.md) -- pas refait a chaque run pour la meme dalle. Une dalle dont
    le remap echoue (lecture LAZ corrompue, backend LAZ absent) est fournie
    a roofer SANS remap plutot que d'etre ecartee -- degrade la couverture
    (repli pyramidal batiment par batiment cote appelant si besoin), jamais
    d'exception qui remonte."""
    cg.lidar_points_l93(bbox_l93, margin_m=margin_m)  # effet de bord : peuple le cache LAZ
    tiles = cg.lidar_tile_index(bbox_l93, margin_m=margin_m)
    paths = []
    for _, row in tiles.iterrows():
        if not row.get("url"):
            continue
        src = cg.LIDAR_CACHE / Path(row["url"]).name
        dst = _remap67_path(src)
        if not dst.exists():
            try:
                _remap67(src, dst)
            except Exception as e:                                     # noqa: BLE001
                log(f"  toit roofer : remap classe 67->6 echoue sur {src.name} "
                    f"({type(e).__name__}: {e}) -> dalle fournie sans remap")
                paths.append(src)
                continue
        paths.append(dst)
    return paths


def _complete_altitudes(alt_sol, alt_toit, haut):
    """Cascade de completion (toit manquant -> sol + hauteur ; sol manquant ->
    toit - hauteur), reproduisant -- avec les 3 seuls champs BD TOPO deja
    extraits par bati.py (pas les 4 colonnes min/max completes du script de
    reference) -- la logique documentee par l'exemple officiel IGN
    ignfab/roofer-with-ignf-datasets (scripts/set_building_attributes.sh).
    Renvoie (alt_sol, alt_toit), inchanges si `haut` ou les deux autres sont
    deja None (aucune reconstruction possible -- reste NULL dans le GPKG,
    ce que `--h-terrain-attribute`/`--h-roof-attribute` gerent nativement,
    cf. roofer --help-all)."""
    if alt_toit is None and alt_sol is not None and haut is not None:
        alt_toit = alt_sol + haut
    if alt_sol is None and alt_toit is not None and haut is not None:
        alt_sol = alt_toit - haut
    return alt_sol, alt_toit


def write_footprint_gpkg(prop_bldgs, path: Path) -> None:
    """GeoPackage EPSG:2154 des empreintes des batiments (colonne 'cleabs'),
    format d'entree attendu par roofer. `prop_bldgs` = la liste deja
    construite par bati.py : (polys, rings_cm, haut, alt_sol, alt_toit, rid).
    Un batiment MultiPolygon (parties disjointes) recoit un cleabs suffixe
    par polygone (cf. `cleabs_for`) -- sinon roofer produit un CityObject par
    polygone mais tous portant le meme cleabs, et `_find_roof_geometry` ne
    peut renvoyer que le premier trouve pour les parties suivantes (toit
    disjoint) -- cf. `build_roof`, appele avec le meme identifiant.

    Ecrit aussi `H_TERRAIN_FIELD`/`H_ROOF_FIELD` (altitudes BD TOPO,
    completees autant que possible par `_complete_altitudes`) : repli
    d'altitude que roofer utilise lui-meme (`--h-terrain-attribute`/
    `--h-roof-attribute`, cf. `run_roofer`) quand sa couverture LiDAR est
    insuffisante pour deriver l'altitude sol/toit d'un batiment depuis le
    nuage -- jamais une reconstruction geometrique cote projet, cf.
    CLAUDE.md."""
    import geopandas as gpd

    rows = []
    for polys, _rings, haut, alt_sol, alt_toit, rid in prop_bldgs:
        alt_sol_c, alt_toit_c = _complete_altitudes(alt_sol, alt_toit, haut)
        for i, poly in enumerate(polys):
            rows.append({"cleabs": cleabs_for(rid, i, len(polys)), "geometry": poly,
                         H_TERRAIN_FIELD: alt_sol_c, H_ROOF_FIELD: alt_toit_c})
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:2154")
    gdf.to_file(path, driver="GPKG")


def _to_real(v, scale, translate):
    return (v[0] * scale[0] + translate[0], v[1] * scale[1] + translate[1],
           v[2] * scale[2] + translate[2])


def _find_roof_geometry(records, cleabs):
    """`cleabs` est sur le Building PARENT ; la geometrie Solid LoD2.2 est
    sur son enfant BuildingPart -- jamais le meme objet CityJSON. Renvoie
    (geom, vertices_bruts_de_la_ligne) ou (None, None)."""
    for rec in records:
        objs = rec["CityObjects"]
        for oid, obj in objs.items():
            if obj.get("type") != "Building":
                continue
            if obj.get("attributes", {}).get("cleabs") != cleabs:
                continue
            candidates = [obj] + [objs[c] for c in (obj.get("children") or []) if c in objs]
            for cand in candidates:
                for geom in cand.get("geometry", []):
                    if geom.get("lod") == "2.2":
                        return geom, rec["vertices"]
    return None, None


def _solid_faces(geom, verts_int, scale, translate):
    """Faces du Solid AVEC leur semantique d'origine (`GroundSurface`/
    `WallSurface`/`RoofSurface`, index de surface = id de pan pour un
    toit -- roofer emet deja un pan = une face, jamais fragmente, verifie
    sur les 18 batiments de cette session). Renvoie None si le Solid n'a
    pas de semantics (repli pyramidal cote appelant -- pas de mecanisme de
    reconstruction ici pour compenser une sortie roofer degradee)."""
    sem = geom.get("semantics")
    if not sem:
        return None
    surfaces = sem["surfaces"]
    is_solid = geom["type"] == "Solid"
    faces_group = geom["boundaries"][0] if is_solid else geom["boundaries"]
    values = sem["values"][0] if is_solid else sem["values"]
    faces = []
    for face, sidx in zip(faces_group, values):
        if sidx is None:
            continue
        surf = surfaces[sidx]
        ring = face[0]  # anneau exterieur ; trous ignores (rares sur un toit/mur)
        pts = [_to_real(verts_int[vi], scale, translate) for vi in ring]
        faces.append({"type": surf["type"], "surface_index": sidx, "pts": pts})
    return faces


def build_roof(roofer_data, cleabs, ring_cm, base_cm, plan_origin_l93, z_min,
               ortho_arr, ortho_bbox_l93, *, log=print):
    """Liste de (nom, pyvista.PolyData, cle_materiau), ou None (roofer
    absent/echec, aucune geometrie/semantics exploitable pour ce batiment
    precis) -- l'appelant (bati.py) se replie alors sur le toit pyramidal."""
    try:
        return _build_roof_impl(roofer_data, cleabs, ring_cm, base_cm, plan_origin_l93,
                                z_min, ortho_arr, ortho_bbox_l93, log)
    except Exception as e:                                          # noqa: BLE001
        log(f"  toit roofer : construction echouee ({type(e).__name__}: {e}) -> repli pyramidal")
        return None


def _build_roof_impl(roofer_data, cleabs, ring_cm, base_cm, plan_origin_l93,
                     z_min, ortho_arr, ortho_bbox_l93, log):
    if roofer_data is None:
        return None
    geom, verts_int = _find_roof_geometry(roofer_data["records"], cleabs)
    if geom is None:
        log("  toit roofer : aucune geometrie LoD2.2 pour ce batiment -> repli pyramidal")
        return None
    faces = _solid_faces(geom, verts_int, roofer_data["scale"], roofer_data["translate"])
    if not faces:
        log("  toit roofer : solide sans semantics exploitables -> repli pyramidal")
        return None

    E0, N1 = plan_origin_l93

    def to_plan_cm(pt):
        x_l93, y_l93, z_ngf = pt
        return ((x_l93 - E0) * 100.0, (N1 - y_l93) * 100.0, (z_ngf - z_min) * 100.0)

    for f in faces:
        f["pts_cm"] = [to_plan_cm(p) for p in f["pts"]]

    # decalage vertical RIGIDE (une seule translation) : ancre le solide sous
    # le maillage terrain, meme marge de securite (base_cm, deja calcule par
    # bati.py) que les autres types de batiments -- ne modifie pas la forme
    # du solide, seulement sa position.
    z_solid_min_cm = min(p[2] for f in faces for p in f["pts_cm"])
    dz = base_cm - z_solid_min_cm

    # --- un seul maillage pour tout le Solid, TRIANGULE DES LA CONSTRUCTION
    # par eventail-centroide (ajoute le centroide de chaque face, relie a
    # chacune de ses aretes -- couvre par construction tout polygone simple,
    # convexe ou non, quelle que soit sa forme). PREFERE a un N-gon +
    # `.triangulate()` global : constate sur un batiment reel (8 pans) que
    # VTK laisse un petit trou quadrilatere au milieu d'un pan a 11 sommets
    # de forme tres etiree (repli tardif de reconstruction, plausible sur un
    # pan complexe) -- l'eventail-centroide ne peut pas laisser de trou : il
    # ne cree que des triangles (centroide, sommet_i, sommet_i+1), un par
    # arete du polygone d'origine, jamais de diagonale interne susceptible
    # de mal se comporter sur une forme non convexe.
    all_pts, faces_flat, roles = [], [], []
    for f in faces:
        pts = [(x, y, z + dz) for x, y, z in f["pts_cm"]]
        n_ = len(pts)
        cx = sum(p[0] for p in pts) / n_
        cy = sum(p[1] for p in pts) / n_
        cz = sum(p[2] for p in pts) / n_
        base_i = len(all_pts)
        all_pts.extend(pts)
        all_pts.append((cx, cy, cz))
        centroid_i = base_i + n_
        role = f["type"] if f["type"] != "RoofSurface" else f"roof_{f['surface_index']}"
        for k in range(n_):
            faces_flat += [3, base_i + k, base_i + (k + 1) % n_, centroid_i]
            roles.append(role)

    mesh = pv.PolyData(np.array(all_pts), faces=np.hstack(faces_flat))
    mesh.cell_data["role"] = np.array(roles)
    mesh = mesh.clean(tolerance=CLEAN_TOLERANCE_CM)
    mesh = mesh.compute_normals(auto_orient_normals=True, consistent_normals=True,
                                non_manifold_traversal=False)

    wall_mask = np.isin(mesh.cell_data["role"], ["GroundSurface", "WallSurface"])
    if not wall_mask.any():
        # semantics avec RoofSurface mais sans GroundSurface/WallSurface (sortie
        # roofer atypique) : jamais un toit flottant sans mur -- meme traitement
        # d'echec que "aucun pan de toit exploitable" plus bas.
        log("  toit roofer : solide sans mur (GroundSurface/WallSurface) -> repli pyramidal")
        return None
    groups = [("bati_mur", mesh.extract_cells(wall_mask).extract_surface(algorithm="dataset_surface"), "mur")]

    roof_faces_by_idx: dict[int, list] = {}
    for f in faces:
        if f["type"] == "RoofSurface":
            roof_faces_by_idx.setdefault(f["surface_index"], []).append(f)

    # Un seul materiau pour TOUT le toit du batiment (pas un echantillonnage
    # independant par pan) : un pan individuel peut etre mal classe (ombre
    # portee, pan etroit/en biais, bord de toit qui mord sur le mur ou le
    # sol dans le bbox echantillonne par cg.roof_color_from_ortho) --
    # constate au rendu reel : plusieurs pans d'un meme toit repartis sur
    # 2 materiaux differents alors qu'il s'agit visiblement du meme
    # revetement. Vote pondere par l'AIRE reelle de chaque pan (pas un
    # simple comptage de pans) : un grand pan mal classe ne doit pas etre
    # neutralise par plusieurs petits pans bien classes, et inversement.
    pans = []
    for sidx, pan_faces in roof_faces_by_idx.items():
        role = f"roof_{sidx}"
        pan_mask = mesh.cell_data["role"] == role
        if not pan_mask.any():
            continue
        pan_mesh = mesh.extract_cells(pan_mask).extract_surface(algorithm="dataset_surface")
        # aire du pan en L93 pour la couleur -- union de toutes ses faces
        # (normalement une seule, roofer emet un pan = une face, mais on ne
        # suppose pas cette garantie ici)
        poly_l93 = unary_union([Polygon([(x, y) for x, y, _z in pf["pts"]]) for pf in pan_faces])
        rc = cg.roof_color_from_ortho(poly_l93, ortho_arr, ortho_bbox_l93)
        key = cg.ROOF_COLOR_KEY.get(tuple(rc), "ardoise")
        pans.append((sidx, pan_mesh, poly_l93.area, key))

    if not pans:
        log("  toit roofer : aucun pan de toit exploitable -> repli pyramidal")
        return None

    area_par_materiau: dict[str, float] = {}
    for _sidx, _mesh, aire, key in pans:
        area_par_materiau[key] = area_par_materiau.get(key, 0.0) + aire
    materiau_toit = max(area_par_materiau, key=area_par_materiau.get)

    for sidx, pan_mesh, _aire, _key in pans:
        groups.append((f"bati_toit_{sidx}", pan_mesh, materiau_toit))

    return groups
