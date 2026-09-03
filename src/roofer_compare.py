"""
roofer_compare.py : comparaison ponctuelle entre roof_lidar.build_roof (module
maison) et l'outil externe roofer (moteur 3DBAG/TU Delft, LoD2.2,
https://github.com/3DBAG/roofer, GPLv3) sur le(s) batiment(s) "propriete".

OUTIL DE DIAGNOSTIC, PAS INTEGRE a run.ps1 / build_home.py -- aucune sortie
de ce script n'est consommee par le pipeline. Necessite le binaire `roofer`
installe separement (non redistribue dans ce depot, GPLv3 -- voir CLAUDE.md
section "Dependance externe optionnelle : roofer"), disponible sur le PATH
ou dans ~/.local/bin/roofer (installe par le script officiel
distribution/install.sh du depot 3DBAG/roofer).

Prerequis pipeline (comme bati.py) : phase1_cadastre.py et terrain.py deja
executes -- data/meta.json, data/terrain_grid.npz, data/terrain_stats.json
presents.

Usage :
    <venv ou conda sitegeo>/python src/roofer_compare.py
"""
from __future__ import annotations

import json
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

import roof_lidar
import roofer_roof
import sitegeo as cg

ROOFER_BIN = shutil.which("roofer") or str(Path.home() / ".local" / "bin" / "roofer")
OUT_DIR = cg.DATA / "roofer_compare"
CACHE_DIR = OUT_DIR / "_cache"


def _cached(name: str, compute):
    """Cache disque local a ce script (pickle, dans data/roofer_compare/_cache/,
    git-ignore comme le reste de data/) -- evite de retelecharger a chaque
    tentative les etapes reseau (WFS BDTOPO, APICARTO, WMS ortho) en cas de
    coupure transitoire du proxy en cours de test. N'affecte pas le pipeline
    principal (bati.py, etc.), qui n'importe pas cette fonction."""
    p = CACHE_DIR / f"{name}.pkl"
    if p.exists():
        print(f"  (cache) {name} <- {p}")
        return pickle.loads(p.read_bytes())
    result = compute()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p.write_bytes(pickle.dumps(result))
    return result


def _check_prereqs() -> None:
    missing = [f for f in ("meta.json", "terrain_grid.npz", "terrain_stats.json")
               if not (cg.DATA / f).exists()]
    if missing:
        raise SystemExit(
            f"prerequis manquants dans data/ : {', '.join(missing)} -- lancer "
            "d'abord `.\\run.ps1 phase1_cadastre terrain` (ou l'equivalent : "
            "phase1_cadastre.py puis terrain.py).")
    if not Path(ROOFER_BIN).exists():
        raise SystemExit(
            "binaire roofer introuvable -- installer via le script officiel "
            "distribution/install.sh de https://github.com/3DBAG/roofer "
            "(voir CLAUDE.md).")


def _property_buildings(prop_zone):
    """Meme filtre 'propriete' que bati.py : majorite de l'emprise sur la parcelle.
    `prop_zone` recu en parametre (plutot que recalcule ici) pour ne faire
    qu'un seul appel reseau APICARTO -- cf. cache dans main()."""
    import geopandas as gpd
    import pandas as pd

    g = cg.wfs_l93("BDTOPO_V3:batiment", count=300)
    rows = [row for _, row in g.iterrows()
           if row.geometry.intersection(prop_zone).area > 0.5 * row.geometry.area]
    if not rows:
        raise SystemExit("aucun batiment BD TOPO classe 'propriete' sur cette parcelle.")
    return gpd.GeoDataFrame(pd.DataFrame(rows), geometry="geometry", crs=g.crs)


def _lidar_tile_paths(bbox_l93, margin_m: float = 5.0) -> list[Path]:
    """Force le telechargement/cache (cg.lidar_points_l93, classe batiment) puis
    retrouve les chemins de dalles concernees par la MEME requete WFS -- pour ne
    donner a roofer QUE les dalles pertinentes, jamais tout data/lidar_cache/
    (qui peut contenir des dalles d'executions anterieures sur une autre zone).
    Dalles LAZ elles-memes deja mises en cache disque par cg.lidar_points_l93
    (data/lidar_cache/) ; seule la requete WFS d'index est mise en cache ici."""
    def _fetch():
        import geopandas as gpd

        cg.lidar_points_l93(bbox_l93, margin_m=margin_m)  # effet de bord : peuple le cache LAZ
        e0, n0, e1, n1 = bbox_l93
        pe0, pn0, pe1, pn1 = e0 - margin_m, n0 - margin_m, e1 + margin_m, n1 + margin_m
        u = (f"{cg.WFS_URL}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
             f"&TYPENAMES={cg.LIDAR_TILE_INDEX}&SRSNAME=urn:ogc:def:crs:EPSG::2154"
             f"&BBOX={pe0},{pn0},{pe1},{pn1},urn:ogc:def:crs:EPSG::2154"
             f"&OUTPUTFORMAT=application/json")
        tiles = gpd.read_file(u)
        return [cg.LIDAR_CACHE / Path(row["url"]).name
                for _, row in tiles.iterrows() if row.get("url")]

    return _cached("lidar_tile_paths", _fetch)


def _run_roofer(footprint_gpkg: Path, laz_paths: list[Path], out_dir: Path):
    # memes garde-fous que roofer_roof.run_roofer (pipeline principal) : dossier
    # de sortie vide avant l'appel (sinon un .city.jsonl d'une comparaison
    # precedente, sur une autre bbox, serait repris a tort par le glob() plus
    # bas) et GDAL_DATA du bundle roofer (sinon le binaire ne retrouve pas ses
    # donnees GDAL a l'execution -- cf. roofer_roof._roofer_gdal_data).
    shutil.rmtree(out_dir, ignore_errors=True)
    try:
        out_dir.mkdir(parents=True)
    except OSError as e:
        # rmtree ignore_errors=True peut laisser out_dir non vide (permissions,
        # fichier tenu ouvert) -> mkdir() sans exist_ok leverait FileExistsError.
        raise SystemExit(f"dossier de sortie roofer inutilisable : {out_dir} ({e})")
    cmd = [ROOFER_BIN, "--lod22", *[str(p) for p in laz_paths], str(footprint_gpkg), str(out_dir)]
    env = os.environ.copy()
    gdal_data = roofer_roof._roofer_gdal_data(ROOFER_BIN)
    if gdal_data:
        env["GDAL_DATA"] = gdal_data
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit(f"roofer a echoue (code {r.returncode})")
    seq_files = list(out_dir.glob("*.city.jsonl"))
    if not seq_files:
        raise SystemExit("roofer n'a produit aucun fichier .city.jsonl")
    objects: dict = {}
    translate_z = 0.0
    for line in seq_files[0].read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        objects.update(rec.get("CityObjects", {}))
        t = rec.get("transform", {}).get("translate")
        if t is not None:
            translate_z = t[2]
    return objects, translate_z


def _roofer_metrics(objects: dict, translate_z: float) -> list[dict]:
    """
    BUG CONFIRME (roofer 1.1.0-beta.1, cf. CLAUDE.md) : `rf_h_ground` est
    expose relatif a la translation Z interne du CityJSON
    (`transform.translate[2]`), alors que `rf_h_roof_min/max/50p/70p` sont en
    NGF absolu -- incoherence propre a cet attribut. Verifie ici en
    reajoutant `translate_z` : le resultat retombe a quelques cm du minimum
    reel des points sol (`--crop-output` sur le nuage rogne par roofer
    lui-meme). `rf_h_roof_ridge` (hauteur relative au sol) etait deja
    correct tel quel, ce n'est que `rf_h_ground` qui manquait ce recalage.
    """
    rows = []
    for oid, obj in objects.items():
        attrs = obj.get("attributes")
        if not attrs or "rf_roof_planes" not in attrs:
            continue
        h_ground = attrs.get("rf_h_ground")
        rows.append({
            "id": oid, "cleabs": attrs.get("cleabs"),
            "pans": attrs.get("rf_roof_planes"), "faitages": attrs.get("rf_ridgelines"),
            "h_faitage_m": attrs.get("rf_h_roof_ridge"),
            "h_ground_m": (h_ground + translate_z) if h_ground is not None else None,
            "h_roof_max_m": attrs.get("rf_h_roof_max"), "rmse_m": attrs.get("rf_rmse_lod22"),
            "type": attrs.get("rf_roof_type"), "succes": attrs.get("rf_success"),
        })
    return rows


def _roof_lidar_metrics(ring, base, eave_attr, lidar_pts_cm, plan_origin_l93,
                        ortho, obb, z_min) -> dict:
    groups = roof_lidar.build_roof(ring, base, eave_attr, lidar_pts_cm,
                                   plan_origin_l93, ortho, obb)
    if groups is None:
        return {"pans": 0, "succes": False}
    toit_meshes = [m for name, m, _ in groups if "toit" in name]
    z_max_cm = max(m.bounds[5] for m in toit_meshes if m.n_points)
    return {"pans": len(toit_meshes), "h_faitage_m": z_min + z_max_cm / 100.0, "succes": True}


def main() -> None:
    _check_prereqs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    prop_zone = _cached("property_polygon", cg.property_polygon_l93)
    bbox = prop_zone.bounds
    gdf = _cached("property_buildings", lambda: _property_buildings(prop_zone))
    footprint_gpkg = OUT_DIR / "footprint.gpkg"
    gdf[["cleabs", "geometry"]].to_file(footprint_gpkg, driver="GPKG")

    laz_paths = _lidar_tile_paths(bbox)
    if not laz_paths:
        raise SystemExit("aucune dalle LiDAR HD ne couvre cette parcelle.")

    objects, translate_z = _run_roofer(footprint_gpkg, laz_paths, OUT_DIR / "roofer_output")
    roofer_rows = _roofer_metrics(objects, translate_z)

    z_min = cg.META.z_min
    plan_origin_l93 = (cg.META.E0, cg.META.N1)
    ortho, obb = _cached("ortho", lambda: cg.wms_ortho_rgb(mult=4))
    raw = _cached("lidar_raw", lambda: cg.lidar_points_l93(bbox, margin_m=5.0))
    xc, yc = cg.to_plan_cm(raw[:, 0], raw[:, 1])
    lidar_pts_cm = np.column_stack([xc, yc, (raw[:, 2] - z_min) * 100.0])

    print(f"\n{'cleabs':<16} {'roofer (pans / altitude toit / hauteur / type)':<58} "
          f"{'roof_lidar.py (pans / altitude max toit)'}")
    for _, row in gdf.iterrows():
        cleabs = row["cleabs"]
        geom = row.geometry
        # meme decoupe que bati.py : un batiment BD TOPO peut etre un
        # MultiPolygon (plusieurs emprises disjointes sous le meme cleabs).
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for poly in polys:
            xs, ys = poly.exterior.coords.xy
            xc2, yc2 = cg.to_plan_cm(np.array(xs[:-1]), np.array(ys[:-1]))
            ring = [[round(float(a), 1), round(float(b), 1)] for a, b in zip(xc2, yc2)]
            base = min(cg.terrain_z_at(x, y) for x, y in ring) - 3.0
            eave_attr = base + 400.0  # meme valeur par defaut que _pyramidal_mesh si hauteur BD TOPO absente

            rl = _roof_lidar_metrics(ring, base, eave_attr, lidar_pts_cm,
                                     plan_origin_l93, ortho, obb, z_min)
            rf = next((r for r in roofer_rows if r["cleabs"] == cleabs), None)
            if rf is None:
                rf_s = "non trouve dans la sortie roofer"
            elif rf["h_roof_max_m"] is None:
                rf_s = f"{rf['pans']} pans, altitude toit non calculee, {rf['type']}"
            else:
                # rf_h_ground corrige (cf. _roofer_metrics) ; rf_h_roof_ridge
                # (hauteur relative au sol) etait deja fiable tel quel.
                h_txt = (f"{rf['h_faitage_m']:.2f} m" if rf["h_faitage_m"] is not None
                        else "hauteur non calculee")
                rf_s = f"{rf['pans']} pans, {rf['h_roof_max_m']:.2f} m NGF, {h_txt}, {rf['type']}"
            rl_s = (f"{rl['pans']} pans, {rl['h_faitage_m']:.2f} m NGF" if rl["succes"]
                    else "echec -> repli pyramidal")
            print(f"{cleabs:<16} {rf_s:<48} {rl_s}")

    print(f"\nsortie roofer complete (CityJSONSeq) dans {OUT_DIR / 'roofer_output'}")


if __name__ == "__main__":
    main()
