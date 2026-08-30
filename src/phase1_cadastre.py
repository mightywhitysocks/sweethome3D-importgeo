"""
phase1_cadastre.py : Phase 1, fond de plan cadastral cale.

DEFINIT le repere plan SH3D (origine = coin NO de la bbox parcelles + marge ;
X=est, Y=sud, cm) et l'ecrit dans data/meta.json, reutilise ensuite par tout le
pipeline via sitegeo.META. La parcelle vient de config/site.local.toml.

Produit dans data/ :
  fond_cadastre_ortho.png   ortho HR + PARCELLAIRE_EXPRESS (limites/bati/numeros IGN)
  ortho.tif                 ortho seule, GeoTIFF
  sh3d_payload.json         parcelles en cm + metadonnees fond
  meta.json                 origine Lambert-93 + bbox (bootstrap du repere)
docs/notice_calage.md       les 3 nombres a taper dans l'assistant SH3D
"""
from __future__ import annotations

import io
import json

from pyproj import Transformer
from shapely.ops import unary_union

import sitegeo as cg

GEO = cg.GEO
MARGE_M = cg.MARGE_M
MPP = 0.20
MAX_PX = 4000
TO_WGS = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def main() -> None:
    gdf = cg.parcels_l93()                      # EPSG:2154, colonnes dont 'contenance'
    for _, p in gdf.iterrows():
        a, c = p.geometry.area, int(p["contenance"])
        print(f"{cg.SECTION} {p['numero']}: aire={a:8.1f}  contenance={c:6d}  "
              f"ecart={abs(a - c) / c * 100:.2f}%  "
              f"{'OK' if abs(a - c) / c < 0.01 else '!! ECART'}")

    union = unary_union(list(gdf.geometry))
    minx, miny, maxx, maxy = union.bounds
    e0, n1 = minx - MARGE_M, maxy + MARGE_M     # origine plan (X=0, Y=0) = coin NO
    e1, n0 = maxx + MARGE_M, miny - MARGE_M
    width_m, height_m = e1 - e0, n1 - n0

    to_cm = lambda x, y: [round((x - e0) * 100, 1), round((n1 - y) * 100, 1)]

    def rings_cm(geom):
        polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        return [[to_cm(x, y) for x, y in poly.exterior.coords[:-1]] for poly in polys]

    w_px = min(MAX_PX, max(1, round(width_m / MPP)))
    h_px = min(MAX_PX, max(1, round(height_m / MPP)))
    bbox = (e0, n0, e1, n1)

    (GEO / "fond_cadastre_ortho.png").write_bytes(cg.wms_getmap(
        ["ORTHO", "CADASTRE"], bbox, size=(w_px, h_px), fmt="image/png"))
    tif = cg.wms_getmap("ORTHO", bbox, size=(w_px, h_px), fmt="image/geotiff")
    (GEO / "ortho.tif").write_bytes(tif)

    import rasterio
    with rasterio.open(io.BytesIO(tif)) as ds:
        b = ds.bounds
        bbox_reelle = [b.left, b.bottom, b.right, b.top]
    print(f"fond : {w_px}x{h_px} px  {width_m:.2f} x {height_m:.2f} m")

    payload = {
        "insee": cg.INSEE, "section": cg.SECTION, "origin_l93": [e0, n1],
        "unit": "cm", "axes": "X=est, Y=sud",
        "parcels": [{
            "numero": p["numero"],
            "is_property": bool(p["is_property"]),
            "contenance_m2": int(p["contenance"]),
            "area_calc_m2": round(p.geometry.area, 1),
            "rings_cm": rings_cm(p.geometry),
            "centroid_cm": to_cm(p.geometry.centroid.x, p.geometry.centroid.y),
        } for _, p in gdf.iterrows()],
        "fond": {"png": "fond_cadastre_ortho.png",
                 "width_m": round(width_m, 4), "height_m": round(height_m, 4),
                 "width_px": w_px, "height_px": h_px,
                 "scale_cm_per_px": round(width_m * 100 / w_px, 6),
                 "bbox_l93": bbox_reelle},
    }
    (GEO / "sh3d_payload.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lon0, lat0 = TO_WGS.transform(e0, n0)
    lon1, lat1 = TO_WGS.transform(e1, n1)
    (GEO / "meta.json").write_text(json.dumps({
        "insee": cg.INSEE, "section": cg.SECTION, "numeros": list(cg.NUMEROS),
        "property_numero": cg.PROPERTY_NUMERO, "crs_projete": "EPSG:2154",
        "origin_l93": [e0, n1], "bbox_l93": [e0, n0, e1, n1],
        "bbox_wgs84": [min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1)],
        "marge_m": MARGE_M,
        "note": "Origine plan SH3D = coin NO bbox. X=est, Y=sud, cm. "
                "Reutiliser origin_l93 tel quel en Phase 2.",
    }, indent=2), encoding="utf-8")

    L_defaut = 0.8 * width_m
    cg.DOCS.mkdir(parents=True, exist_ok=True)
    (cg.DOCS / "notice_calage.md").write_text(f"""# Poser le fond de plan dans Sweet Home 3D : valeurs a TAPER (ne rien cliquer)

Image : `data/fond_cadastre_ortho.png`  ({w_px} x {h_px} px)
Emprise reelle : **{width_m:.2f} m** x **{height_m:.2f} m**.

## Menu : Plan -> Importer une image de fond

1. **Choisir l'image** : `{GEO / 'fond_cadastre_ortho.png'}`
2. **Echelle** : NE PAS deplacer la ligne bleue. « Longueur de la ligne dessinee (m) » :
   > **{L_defaut:.2f}**   (= 0,8 x {width_m:.2f} ; echelle {width_m * 100 / w_px:.5f} cm/px)
3. **Origine** : NE PAS cliquer. X = 0 , Y = 0.
4. Continuer / Terminer.

## Ensuite
- `python src/verif.py` relit le `.sh3d` et confirme echelle < 0,05 % et origine < 5 cm.
""", encoding="utf-8")

    print(f"\n>>> Import SH3D : longueur ligne = {L_defaut:.2f} m , origine X=0 Y=0")


if __name__ == "__main__":
    main()
