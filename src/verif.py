"""
verif.py — controle complet du pipeline (lecture seule).

  1. Parcelles : API Carto (live) vs sh3d_payload.json (contenance, aire, 1er sommet)
  2. Topologie : pas de recouvrement, emprise dans la bbox du fond
  3. Fond : georeferencement de data/ortho.tif (CRS L93, bbox, resolution)
  4. Repere : origin_l93 == coin NO bbox, marge
  5. .sh3d : niveau 'Cadastre', pieces parcelle, image de fond
  6. Calage <backgroundImage> : echelle < 0,05 % et origine < 5 cm
  7. (option --overlay) data/verif/verif_overlay.png : parcelles sur l'ortho
  8. (option --render) data/verif/render_photo.png : rendu photo headless (SunFlow),
     smoke-test visuel du .sh3d — voir _render_photo() et java/RenderPhoto.java.
     Optionnel : ignore si les jars de rendu ([tools].render_libs_dir) sont absents,
     n'affecte pas le code retour de verif.py.

Sortie : rapport + code retour 0 (OK) / 1 (echec).
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from math import hypot
from pathlib import Path

import sitegeo as cg          # noqa: E402  (regle GDAL_DATA/PROJ_LIB en premier)

import rasterio
from PIL import Image
from shapely.geometry import Point
from shapely.ops import unary_union

GEO = cg.GEO
SH3D = cg.HOME_SH3D
_OK = [True]


def check(label, cond, detail=""):
    _OK[0] &= bool(cond)
    print(f"  [{'OK ' if cond else 'ECHEC'}] {label}" + (f"  -- {detail}" if detail else ""))


def _bg_from_xml(xml):
    m = re.search(r"<backgroundImage\b[^>]*>", xml)
    if not m:
        return None
    F = ("scaleDistance scaleDistanceXStart scaleDistanceYStart scaleDistanceXEnd "
         "scaleDistanceYEnd xOrigin yOrigin").split()
    return {k: float(re.search(k + r"='([-\d.eE]+)'", m.group(0)).group(1))
            for k in F if re.search(k + r"='", m.group(0))}


def _bg_from_serialized(blob):
    import javaobj.v2 as javaobj
    F = ("scaleDistance scaleDistanceXStart scaleDistanceYStart scaleDistanceXEnd "
         "scaleDistanceYEnd xOrigin yOrigin").split()

    def walk(o, seen):
        if id(o) in seen:
            return None
        seen.add(id(o))
        fd = getattr(o, "field_data", None)
        if isinstance(fd, dict):
            flat = {}
            for fields in fd.values():
                if isinstance(fields, dict):
                    for jf, val in fields.items():
                        flat[getattr(jf, "name", str(jf))] = val
            if "scaleDistance" in flat and "xOrigin" in flat:
                return {k: float(flat[k]) for k in F if k in flat}
            for v in flat.values():
                if (r := walk(v, seen)):
                    return r
        for v in (getattr(o, "array_data", None) or
                  (o if isinstance(o, (list, tuple)) else [])):
            if (r := walk(v, seen)):
                return r
        return None

    return walk(javaobj.loads(blob), set())


def main() -> None:
    payload = json.loads((GEO / "sh3d_payload.json").read_text(encoding="utf-8"))
    fond = payload["fond"]
    e0, n0, e1, n1 = cg.META.bbox_l93
    E0, N1 = cg.META.E0, cg.META.N1

    print("\n=== 1. Parcelles : API Carto (live) vs payload ===")
    live = cg.parcels_l93()
    geoms = {}
    for _, p in live.iterrows():
        num = p["numero"]
        pc = next(x for x in payload["parcels"] if x["numero"] == num)
        geoms[num] = p.geometry
        cont = int(p["contenance"])
        check(f"{cg.SECTION} {num} contenance", cont == pc["contenance_m2"], f"{cont} m2")
        check(f"{cg.SECTION} {num} aire recalculee (<0.5 m2)",
              abs(p.geometry.area - pc["area_calc_m2"]) < 0.5,
              f"{p.geometry.area:.1f} vs {pc['area_calc_m2']:.1f}")
        check(f"{cg.SECTION} {num} ecart aire/contenance < 1%",
              abs(p.geometry.area - cont) / cont < 0.01,
              f"{abs(p.geometry.area - cont) / cont * 100:.2f}%")
        r0 = pc["rings_cm"][0][0]
        d = p.geometry.boundary.distance(Point(E0 + r0[0] / 100, N1 - r0[1] / 100))
        check(f"{cg.SECTION} {num} 1er sommet sur le contour (<0.05 m)", d < 0.05, f"{d * 100:.1f} cm")

    print("\n=== 2. Topologie ===")
    union = unary_union(list(geoms.values()))
    somme = sum(g.area for g in geoms.values())
    check("pas de recouvrement (<1 m2)", abs(somme - union.area) < 1.0,
          f"delta {somme - union.area:.2f} m2")
    b = union.bounds
    check("emprise dans la bbox du fond",
          b[0] >= e0 - 0.01 and b[1] >= n0 - 0.01 and b[2] <= e1 + 0.01 and b[3] <= n1 + 0.01)

    print("\n=== 3. Fond : georeferencement (ortho.tif) ===")
    with rasterio.open(GEO / "ortho.tif") as ds:
        bb = ds.bounds
        wkt = ds.crs.to_wkt() if ds.crs else ""
        check("CRS = Lambert-93",
              all(s in wkt for s in ['"central_meridian",3', '"false_easting",700000',
                                     '"false_northing",6600000']),
              "params L93")
        check("bbox ortho.tif == bbox meta (<0.5 m)",
              max(abs(bb.left - e0), abs(bb.bottom - n0),
                  abs(bb.right - e1), abs(bb.top - n1)) < 0.5)
        check("resolution ~0.20 m/px", 0.18 < (bb.right - bb.left) / ds.width < 0.22)
        arr = ds.read(1)
        check("image non uniforme", arr.min() != arr.max())

    print("\n=== 4. Coherence repere ===")
    check("origin_l93 == coin NO bbox", abs(E0 - e0) < 1e-6 and abs(N1 - n1) < 1e-6)
    check(f"marge meta == {cg.MARGE_M} m", cg.META.marge_m == cg.MARGE_M)

    if not SH3D.exists():
        print("\n(.sh3d absent — etapes 5/6 sautees)")
    else:
        print("\n=== 5. .sh3d ===")
        with zipfile.ZipFile(SH3D) as z:
            names = z.namelist()
            check("image de fond presente", any(n.isdigit() for n in names))
            raw = (z.read("Home.xml").decode("utf-8", "replace") if "Home.xml" in names
                   else z.read("Home").decode("latin-1", "replace"))
            check("niveau 'Cadastre' present", "Cadastre" in raw)
            for num in cg.NUMEROS:
                check(f"piece '{cg.SECTION} {num}' presente",
                      f"{cg.SECTION} {num}" in raw)

            print("\n=== 6. Calage <backgroundImage> ===")
            bg = (_bg_from_xml(z.read("Home.xml").decode("utf-8", "replace"))
                  if "Home.xml" in names else None)
            if bg is None and "Home" in names:
                bg = _bg_from_serialized(z.read("Home"))
            # l'image de fond = la plus grosse entree a nom purement numerique
            digit = [i for i in z.infolist() if i.filename.isdigit()]
            img_name = max(digit, key=lambda i: i.file_size).filename if digit else None
            if not bg or img_name is None:
                check("<backgroundImage> lisible", False, "import non fait/sauvegarde")
            else:
                img_w = Image.open(io.BytesIO(z.read(img_name))).size[0]
                line_px = hypot(bg["scaleDistanceXEnd"] - bg["scaleDistanceXStart"],
                                bg["scaleDistanceYEnd"] - bg["scaleDistanceYStart"])
                s_act = bg["scaleDistance"] / line_px
                s_vou = fond["width_m"] * 100 / img_w
                ecart = (s_act - s_vou) / s_vou * 100
                xo, yo = bg.get("xOrigin", 0.0), bg.get("yOrigin", 0.0)
                check("echelle < 0,05 %", abs(ecart) < 0.05, f"{ecart:+.4f} %")
                check("origine X < 5 cm", abs(xo) < 5, f"{xo:.1f} cm")
                check("origine Y < 5 cm", abs(yo) < 5, f"{yo:.1f} cm")
                if abs(ecart) >= 0.05:
                    print(f"    -> retaper longueur ligne : {s_vou * line_px / 100:.3f} m")

    if "--overlay" in sys.argv:
        _overlay(payload)

    if "--render" in sys.argv:
        _render_photo()

    print("\n=== RESULTAT ===", "TOUT OK" if _OK[0] else ">>> ECHEC <<<")
    sys.exit(0 if _OK[0] else 1)


def _overlay(payload) -> None:
    from PIL import ImageDraw
    src = GEO / "fond_cadastre_ortho.png"
    img = Image.open(src).convert("RGB")
    W, H = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    sx = W / (payload["fond"]["width_m"] * 100.0)
    sy = H / (payload["fond"]["height_m"] * 100.0)
    for p in payload["parcels"]:
        prop = p["is_property"]
        outline = (27, 122, 61, 255) if prop else (60, 60, 60, 230)
        for ring in p["rings_cm"]:
            draw.polygon([(x * sx, y * sy) for x, y in ring], outline=outline,
                         width=5 if prop else 3)
        cx, cy = p["centroid_cm"]
        draw.text((cx * sx, cy * sy), f"{cg.SECTION} {p['numero']}", fill=outline,
                  anchor="mm")
    cg.VERIF.mkdir(parents=True, exist_ok=True)
    img.save(cg.VERIF / "verif_overlay.png")
    print("verif_overlay.png", img.size)


# --- rendu photo headless (SunFlow), smoke-test visuel optionnel du .sh3d ---
# Distinct du plugin MCP Sweet Home 3D (pilote une instance GUI deja ouverte,
# affichage des calques pas fiable) et du rendu interactif soigne (GUI + plugin
# AdvancedSettingsPhotoRendering + GPU) : ceci est un rendu rapide qualite 3/4,
# reglages par defaut, juste pour confirmer visuellement que le .sh3d produit
# est correct (textures, calques, geometrie) sans machine Windows.
_RENDER_JARS = ("sunflow", "j3dcore", "j3dutils", "vecmath", "batik-svgpathparser")


def _render_photo() -> None:
    print("\n=== 8. Rendu photo headless (optionnel) ===")
    if not SH3D.exists():
        print("  (.sh3d absent — rendu ignore)")
        return

    libs_dir = (Path(cg.RENDER_LIBS_DIR) if cg.RENDER_LIBS_DIR else None)
    if libs_dir is None:
        jar_default = cg.find_sweethome3d_jar(required=False)
        libs_dir = jar_default.parent if jar_default else None
    if libs_dir is None or not libs_dir.is_dir():
        print("  jars de rendu introuvables — renseignez [tools].render_libs_dir "
              "dans site.local.toml (dossier lib/ de Sweet Home 3D) -> ignore.")
        return

    jars = {}
    for stem in _RENDER_JARS:
        hits = sorted(libs_dir.rglob(f"{stem}*.jar"))
        if hits:
            jars[stem] = hits[-1]
    missing = [s for s in _RENDER_JARS if s not in jars]
    if missing:
        print(f"  jars manquants dans {libs_dir} : {missing} -> ignore.")
        return

    jar = cg.find_sweethome3d_jar(required=False)
    if jar is None:
        print("  SweetHome3D.jar introuvable -> ignore.")
        return

    jconv = cg.DATA / "_jconv"
    jconv.mkdir(parents=True, exist_ok=True)
    cls = jconv / "com" / "eteks" / "sweethome3d" / "utilities" / "RenderPhoto.class"
    src = cg.JAVA / "RenderPhoto.java"
    if not cls.exists() or cls.stat().st_mtime < src.stat().st_mtime:
        r = subprocess.run(
            ["javac", "-cp", f"{jar}{os.pathsep}{jars['sunflow']}", "-d", str(jconv), str(src)],
            capture_output=True, text=True)
        if not cls.exists():
            print("  javac a echoue ->", (r.stderr or r.stdout).strip()[:500])
            return

    cp = os.pathsep.join(str(p) for p in
                          [jconv, jar, jars["sunflow"], jars["j3dcore"], jars["vecmath"],
                           jars["j3dutils"], jars["batik-svgpathparser"]])
    cg.VERIF.mkdir(parents=True, exist_ok=True)
    out_png = cg.VERIF / "render_photo.png"
    cmd = ["java", "-Dj3d.rend=noop", "-cp", cp,
           "com.eteks.sweethome3d.utilities.RenderPhoto", str(SH3D), str(out_png)]
    if shutil.which("xvfb-run"):          # Linux : Java3D exige un display meme en noop
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24"] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True)
    print("  " + (r.stdout.strip() or r.stderr.strip()[:500]).replace("\n", "\n  "))
    if r.returncode != 0 or not out_png.exists():
        print("  rendu echoue (voir ci-dessus) -> ignore.")
        return
    print(f"  {out_png} ({out_png.stat().st_size // 1024} Ko)")


if __name__ == "__main__":
    main()
