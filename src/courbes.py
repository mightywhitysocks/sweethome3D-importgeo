"""
courbes.py : courbes de niveau depuis data/mnt.tif (LIDAR HD), via gdal_contour.
Sortie : data/courbes.geojson (equidistance 1 m) + data/courbes.png.
"""
from __future__ import annotations

import json
import os
import subprocess

import sitegeo as cg          # noqa: E402  (regle GDAL_DATA/PROJ_LIB en premier)

import numpy as np
import rasterio
from PIL import Image, ImageDraw

GEO = cg.GEO
ENV = cg.ENV_ROOT
EQUI = 1.0


def main() -> None:
    gj = GEO / "courbes.geojson"
    if gj.exists():
        gj.unlink()
    subprocess.run(
        [str(ENV / "Library" / "bin" / "gdal_contour.exe"),
         "-a", "alt", "-i", str(EQUI), "-f", "GeoJSON",
         str(GEO / "mnt.tif"), str(gj)],
        check=True, env={**os.environ,
                         "GDAL_DATA": str(ENV / "Library/share/gdal"),
                         "PROJ_LIB": str(ENV / "Library/share/proj"),
                         "PATH": str(ENV / "Library/bin")})

    feats = json.loads(gj.read_text(encoding="utf-8"))["features"]
    alts = sorted({round(f["properties"]["alt"]) for f in feats})
    print(f"{len(feats)} courbes, equidistance {EQUI} m, altitudes {alts}")

    with rasterio.open(GEO / "mnt.tif") as r:
        Z = r.read(1).astype(float)
        T = r.transform
        H, W = Z.shape
    Z[Z < -9000] = np.nan
    g = ((Z - np.nanmin(Z)) / (np.nanmax(Z) - np.nanmin(Z)) * 200 + 30).astype("uint8")
    img = Image.fromarray(np.stack([g, g, g], -1)).convert("RGB")
    d = ImageDraw.Draw(img)
    for f in feats:
        geom = f["geometry"]
        parts = (geom["coordinates"] if geom["type"] == "MultiLineString"
                 else [geom["coordinates"]])
        maitresse = round(f["properties"]["alt"]) % 5 == 0
        for part in parts:
            px = [((E - T.c) / T.a, (N - T.f) / T.e) for E, N, *_ in part]
            d.line(px, fill=(210, 50, 30) if maitresse else (110, 110, 110),
                   width=2 if maitresse else 1)
    img.resize((W * 3, H * 3), Image.LANCZOS).save(GEO / "courbes.png")
    print("courbes.png")


if __name__ == "__main__":
    main()
