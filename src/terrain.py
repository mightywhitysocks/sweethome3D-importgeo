"""
terrain.py — Phase 2 : terrain 3D solide depuis le MNT LIDAR HD.

Un SEUL objet terrain sur toute l'emprise (la limite de propriete est deja
tracee par les pieces cadastre). Geometrie 100 % PyVista (`extrude` + `capping`
+ `compute_normals(auto_orient_normals=True)`).

Source : MNT LIDAR HD 0,5 m (repli RGE ALTI 1 m), clip sur bbox parcelles + marge.
Sous-echantillonnage a STEP m. Repere plan SH3D (x=est, y=sud, cm ; z = alt - z_min).

Sorties dans data/ :
  mnt.tif             raster MNT conserve (courbes.py)
  terrain_stats.json  z_min/z_max NGF, denivele  (lu via sitegeo.META.z_min)
  terrain_grid.npz    grille EXACTE du maillage -> sitegeo.terrain_z_at (ancrage des objets)
  terrain.obj / .mtl  volume ferme + UV ortho
  terrain_drape.jpg   ortho HR drapee (20 cm/px natif IGN)
  terrain_place.json  bbox de l'OBJ (x/y/width/depth/height/elevation)
  terrain_preview.png apercu ombrage (PIL — matplotlib interdit)
"""
from __future__ import annotations

import json

import numpy as np

import sitegeo as cg

GEO = cg.GEO
MARGE = 25.0
STEP = 2.0                  # m entre sommets du maillage
DEPTH_CM = 800.0           # profondeur d'extrusion (fond ondulé sous la scene)
COL_HERBE = (0.49, 0.55, 0.34)      # fallback plat si la texture manque


def main() -> None:
    # --- MNT (repli RGE ALTI) ---
    try:
        A, T, _, blob = cg.wms_raster("MNT_LIDAR", margin_m=MARGE, res_m=0.5)
        src = "MNT LIDAR HD 0.5m"
    except Exception as e:                                        # noqa: BLE001
        print("MNT LIDAR indisponible ->", e, "; repli RGE ALTI")
        A, T, _, blob = cg.wms_raster("RGEALTI", margin_m=MARGE, res_m=1.0)
        src = "RGE ALTI 1m"
    (GEO / "mnt.tif").write_bytes(blob)
    A = cg.fill_nan_nearest(A)
    H, W = A.shape

    # --- sous-echantillonnage regulier ---
    px = max(1, int(round(STEP / abs(T.a))))
    rows = np.arange(0, H, px)
    cols = np.arange(0, W, px)
    Zs = A[np.ix_(rows, cols)]
    Es = np.array([T.c + (c + 0.5) * T.a for c in cols])
    Ns = np.array([T.f + (r + 0.5) * T.e for r in rows])          # T.e < 0
    EE, NN = np.meshgrid(Es, Ns)

    z_min, z_max = float(Zs.min()), float(Zs.max())
    (GEO / "terrain_stats.json").write_text(json.dumps({
        "source": src, "step_m": STEP, "grid": [len(cols), len(rows)],
        "z_min_ngf": z_min, "z_max_ngf": z_max,
        "denivele_m": round(z_max - z_min, 2),
        "note": "z plan = altitude - z_min_ngf.",
    }, indent=2), encoding="utf-8")

    # --- grille du maillage en repere plan cm, axes ASCENDANTS (pour terrain_z_at) ---
    x_cm = np.sort(cg.to_plan_cm(Es, Ns[0])[0])                   # x croit avec E
    y_row = cg.to_plan_cm(Es[0], Ns)[1]                           # y croit quand N decroit
    order = np.argsort(y_row)
    y_cm = y_row[order]
    z_cm = ((Zs - z_min) * 100.0)[order, :]                       # [ny, nx] reordonne
    np.savez_compressed(GEO / "terrain_grid.npz", x_cm=x_cm, y_cm=y_cm, z_cm=z_cm)
    print(f"MNT {src} : grille {len(cols)}x{len(rows)}  "
          f"altitude {z_min:.2f}..{z_max:.2f} m NGF  (denivele {z_max - z_min:.2f} m)")

    # --- surface -> volume ferme (PyVista) ---
    surf = cg.grid_surface(EE, NN, Zs)                            # PolyData, repere plan cm
    solid = cg.solidify(surf, depth_cm=DEPTH_CM)

    # emprise plan (UV de la texture drapee)
    xr, yr = cg.to_plan_cm(EE.ravel(), NN.ravel())
    drape = (float(xr.min()), float(yr.min()), float(xr.max()), float(yr.max()))

    # --- ortho drapee sur l'emprise exacte du maillage ---
    obb = (float(EE.min()) - abs(T.a) / 2, float(NN.min()) - abs(T.e) / 2,
           float(EE.max()) + abs(T.a) / 2, float(NN.max()) + abs(T.e) / 2)
    has_texture = False
    try:
        ortho, _ = cg.wms_ortho_rgb(mult=5, bbox_l93=obb, max_px=4096)   # 20 cm/px natif
        from PIL import Image, ImageEnhance
        img = Image.fromarray(ortho)
        img = ImageEnhance.Contrast(img).enhance(1.10)
        img = ImageEnhance.Color(img).enhance(1.18)
        img.save(GEO / "terrain_drape.jpg", quality=95, subsampling=0)
        has_texture = True
        print(f"terrain_drape.jpg {ortho.shape[1]}x{ortho.shape[0]}")
    except Exception as e:                                        # noqa: BLE001
        print("ortho drapee indisponible ->", e)

    # Kd blanc quand une texture est appliquee : sinon le chargeur OBJ (mode
    # MODULATE) multiplie chaque pixel de la texture par Kd, ce qui assombrit
    # et desature l'ortho (rendu "terne"). COL_HERBE ne sert alors que de
    # repli quand la texture est indisponible.
    mat = {"Kd": (1.0, 1.0, 1.0) if has_texture else COL_HERBE}
    if has_texture:
        mat["map_Kd"] = "terrain_drape.jpg"
    cg.write_mtl(GEO / "terrain.mtl", {"terrain": mat})
    cg.write_obj(GEO / "terrain.obj", solid, mtl_name="terrain", mtl_file="terrain.mtl",
                 drape_bbox_cm=drape, group="terrain")
    (GEO / "terrain_place.json").write_text(
        json.dumps(cg.bbox_cm(solid), indent=2), encoding="utf-8")
    print(f"  terrain.obj : {solid.n_points} sommets, {solid.n_cells} faces, "
          f"open_edges={solid.n_open_edges}")

    _preview(A, T, z_min, z_max)
    print(">>> terrain OK  ->  bati.py")


def _preview(A, T, z_min, z_max) -> None:
    from PIL import Image
    zn = np.clip((A - z_min) / max(z_max - z_min, 1e-6), 0, 1)
    ramp = np.array([[70, 110, 60], [140, 165, 75], [200, 180, 115],
                     [175, 135, 95], [240, 240, 240]], float)
    pos = np.linspace(0, 1, len(ramp))
    rgb = np.stack([np.interp(zn, pos, ramp[:, k]) for k in range(3)], -1)
    gy, gx = np.gradient(A, abs(T.a))
    sh = np.clip(0.6 + (-gx - gy) / (np.hypot(gx, gy).mean() + 1e-6) * 0.18,
                 0.25, 1.15)[..., None]
    Image.fromarray(np.clip(rgb * sh, 0, 255).astype("uint8")).save(
        cg.GEO / "terrain_preview.png")


if __name__ == "__main__":
    main()
