"""
sitegeo.py — module commun du pipeline IGN -> Sweet Home 3D.

Genere un plan 3D georeference d'une parcelle cadastrale francaise a partir des
donnees publiques IGN Geoplateforme. Concentre tout ce qui etait recopie dans
les scripts :
  - le repere plan SH3D (origine Lambert-93, X=est, Y=sud, cm) et ses conversions
  - l'acces aux donnees IGN Geoplateforme : WMS (owslib) + WFS / API Carto (geopandas)
  - l'altitude de la SURFACE du maillage terrain (`terrain_z_at`) pour poser les objets
  - la couleur de toiture depuis l'ortho
  - les primitives PyVista (surface -> solide, prisme, toit) et l'ecriture OBJ + .mtl

La parcelle cible (INSEE, section, numeros) vient de `config/site.local.toml`
(git-ignored). Aucune donnee de site n'est codee en dur ici.

Aucun `main`. Importe par phase1_cadastre / terrain / bati / vegetation / courbes /
verif / build_home.

Env conda `sitegeo` (appeler le .exe directement) : pyvista, geopandas, owslib,
rasterio, shapely, scipy, scikit-image, networkx, pyproj, gdal, Pillow, javaobj-py3.
NE PAS installer matplotlib (crash DLL) -> ne jamais toucher pyvista.plotting / Plotter.
"""
from __future__ import annotations

import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- #
# Arborescence du depot
# --------------------------------------------------------------------------- #
PKG = Path(__file__).resolve().parent                 # <racine>/src/
ROOT = PKG.parent                                     # <racine>/
ASSETS = ROOT / "assets"
DATA = ROOT / "data"
DOCS = ROOT / "docs"
JAVA = ROOT / "java"
VERIF = DATA / "verif"
HOME_SH3D = ROOT / "Plan 3D.sh3d"                     # livrable
for _d in (DATA, VERIF):
    _d.mkdir(parents=True, exist_ok=True)

GEO = DATA          # compat : ancien nom, pointe desormais sur data/


# --------------------------------------------------------------------------- #
# Configuration utilisateur : config/site.local.toml (git-ignored)
# --------------------------------------------------------------------------- #
def _load_site() -> dict:
    p = Path(os.environ.get("SITEGEO_CONFIG") or ROOT / "config" / "site.local.toml")
    if not p.exists():
        ex = ROOT / "config" / "site.example.toml"
        dst = ROOT / "config" / "site.local.toml"
        try:
            if ex.exists() and not dst.exists():
                shutil.copy(ex, dst)
        except OSError:
            pass
        raise SystemExit(
            f"Config absente : {p}\n"
            f"  '{dst}' vient d'etre cree depuis le gabarit — renseignez votre "
            f"parcelle (insee / section / parcels) puis relancez.")
    return tomllib.loads(p.read_text(encoding="utf-8"))


SITE = _load_site()
INSEE = str(SITE["parcelle"]["insee"])
SECTION = str(SITE["parcelle"]["section"])
NUMEROS = tuple(str(n) for n in SITE["parcelle"]["parcels"])
PROPERTY_NUMERO = str(SITE["parcelle"]["property_parcel"])
MARGE_M = float(SITE.get("emprise", {}).get("margin_m", 10.0))
SITE_NAME = str(SITE.get("labels", {}).get("site_name", "Terrain"))
SH3D_JAR_CFG = str(SITE.get("tools", {}).get("sweethome3d_jar", "")).strip()
RENDER_LIBS_DIR = str(SITE.get("tools", {}).get("render_libs_dir", "")).strip()

WMS_URL = "https://data.geopf.fr/wms-r/wms"
WFS_URL = "https://data.geopf.fr/wfs/ows"
APICARTO = "https://apicarto.ign.fr/api/cadastre/parcelle"

# une seule table de couches WMS (data.geopf.fr : PAS de WCS, tout en WMS GetMap
# FORMAT=image/geotiff float32, EPSG:2154)
LAYERS = {
    "MNT_LIDAR": "IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    "MNH_LIDAR": "IGNF_LIDAR-HD_MNH_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93",
    "RGEALTI":   "RGEALTI-MNT_PYR-ZIP_FXX_LAMB93_WMS",
    "ORTHO":     "HR.ORTHOIMAGERY.ORTHOPHOTOS",
    "CADASTRE":  "CADASTRALPARCELS.PARCELLAIRE_EXPRESS",
}   # MNS dispo si besoin : IGNF_LIDAR-HD_MNS_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93

# emplacements de SweetHome3D.jar pour l'installeur classique. L'install Microsoft
# Store (MSIX) est trouvee via _msix_sh3d_jars() : C:\Program Files\WindowsApps
# n'est pas listable (ACL), on y accede par Get-AppxPackage.
JAR_GLOBS = (
    r"C:\Program Files\Sweet Home 3D\lib\SweetHome3D.jar",
    r"C:\Program Files (x86)\Sweet Home 3D\lib\SweetHome3D.jar",
)


def _msix_sh3d_jars() -> list[Path]:
    """SweetHome3D.jar d'une install Microsoft Store : InstallLocation via
    Get-AppxPackage (WindowsApps n'est pas enumerable) puis chemins connus."""
    if os.name != "nt":
        return []
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-AppxPackage *SweetHome3D*).InstallLocation"],
            capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return []
    out: list[Path] = []
    for line in r.stdout.splitlines():
        loc = line.strip()
        if not loc:
            continue
        for rel in ("lib/SweetHome3D.jar", "Sweet Home 3D/lib/SweetHome3D.jar"):
            p = Path(loc) / rel
            if p.exists():
                out.append(p)
    return out


def find_sweethome3d_jar(*, required: bool = True) -> Path | None:
    """
    Localise SweetHome3D.jar : [tools].sweethome3d_jar, sinon l'installeur
    classique, sinon l'install Microsoft Store. `required=False` -> None si
    introuvable (au lieu de lever) ; utilise par les etapes optionnelles (rendu).
    """
    if SH3D_JAR_CFG:
        p = Path(SH3D_JAR_CFG)
        if p.exists():
            return p
        if required:
            raise SystemExit(f"[tools].sweethome3d_jar introuvable : {p}")
        return None
    for pat in JAR_GLOBS:
        hits = sorted(glob.glob(pat, recursive=True))
        if hits:
            return Path(hits[-1])
    msix = _msix_sh3d_jars()
    if msix:
        return msix[-1]
    if required:
        raise SystemExit(
            "SweetHome3D.jar introuvable — renseignez [tools].sweethome3d_jar dans "
            "config/site.local.toml (chemin absolu du .jar de Sweet Home 3D).")
    return None


RENDER_JAR_STEMS = ("sunflow", "j3dcore", "j3dutils", "vecmath", "batik-svgpathparser")


def find_render_jars() -> dict | None:
    """Jars additionnels du rendu photo headless : [tools].render_libs_dir, sinon
    le lib/ du SweetHome3D.jar detecte (recherche RECURSIVE : le build Microsoft
    Store range Java3D dans lib/java3d-*/). {stem: Path} complet, ou None si
    dossier absent ou jars incomplets."""
    d = Path(RENDER_LIBS_DIR) if RENDER_LIBS_DIR else None
    if d is None:
        jar = find_sweethome3d_jar(required=False)
        d = jar.parent if jar else None
    if d is None or not d.is_dir():
        return None
    jars: dict = {}
    for stem in RENDER_JAR_STEMS:
        hits = sorted(d.rglob(f"{stem}*.jar"))
        if hits:
            jars[stem] = hits[-1]
    return jars if len(jars) == len(RENDER_JAR_STEMS) else None


def render_photo(out_png, *, camera=None, size=(1024, 768), quality=None,
                 sh3d=None, log=print):
    """
    Rendu photo headless d'un .sh3d via java/RenderPhoto.java (moteur SunFlow de
    Sweet Home 3D). `camera` = (x, y, z, yaw, pitch[, fov]) repere plan (cm / rad)
    ou None (camera enregistree). `quality` = "low" | "high" | None (celle du .sh3d).
    Renvoie le Path du PNG, ou None si indisponible (jars / JDK absents, echec) ;
    `log` recoit une ligne d'explication en cas d'echec.
    """
    sh3d = Path(sh3d) if sh3d else HOME_SH3D
    out_png = Path(out_png)
    if not sh3d.exists():
        log("  (.sh3d absent -> rendu ignore)")
        return None
    jar = find_sweethome3d_jar(required=False)
    jars = find_render_jars()
    if jar is None:
        log("  SweetHome3D.jar introuvable -> rendu ignore.")
        return None
    if jars is None:
        log("  jars de rendu introuvables/incomplets ([tools].render_libs_dir) -> ignore.")
        return None
    jconv = DATA / "_jconv"
    jconv.mkdir(parents=True, exist_ok=True)
    cls = jconv / "com" / "eteks" / "sweethome3d" / "utilities" / "RenderPhoto.class"
    src = JAVA / "RenderPhoto.java"
    if not cls.exists() or cls.stat().st_mtime < src.stat().st_mtime:
        r = subprocess.run(
            ["javac", "-cp", f"{jar}{os.pathsep}{jars['sunflow']}", "-d", str(jconv),
             str(src)], capture_output=True, text=True)
        if not cls.exists():
            log("  javac RenderPhoto a echoue ->", (r.stderr or r.stdout).strip()[:400])
            return None
    cp = os.pathsep.join(str(p) for p in
                         (jconv, jar, jars["sunflow"], jars["j3dcore"],
                          jars["vecmath"], jars["j3dutils"], jars["batik-svgpathparser"]))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["java", "-Dj3d.rend=noop"]
    if quality:
        cmd.append(f"-Drender.quality={quality}")
    cmd += ["-cp", cp, "com.eteks.sweethome3d.utilities.RenderPhoto",
            str(sh3d), str(out_png), str(size[0]), str(size[1])]
    if camera is not None:
        cmd += [f"{v:.5f}" for v in camera]
    if shutil.which("xvfb-run"):        # Linux : Java3D exige un display meme en noop
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 1280x1024x24"] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not out_png.exists():
        log("  rendu echoue ->", (r.stdout or r.stderr).strip()[:400])
        return None
    return out_png


# GDAL trouve ses ressources meme sous conda (sinon warnings gdalvrt.xsd / proj)
ENV_ROOT = Path(os.environ.get("CONDA_PREFIX") or sys.prefix)
_ENV_ROOT = ENV_ROOT          # compat
os.environ.setdefault("GDAL_DATA", str(ENV_ROOT / "Library" / "share" / "gdal"))
os.environ.setdefault("PROJ_LIB", str(ENV_ROOT / "Library" / "share" / "proj"))


# --------------------------------------------------------------------------- #
# Repere plan SH3D
# --------------------------------------------------------------------------- #
class _Meta:
    """data/meta.json (produit par phase1_cadastre.py) + z_min du terrain si dispo."""

    def __init__(self) -> None:
        m = json.loads((DATA / "meta.json").read_text(encoding="utf-8"))
        self.insee = m["insee"]
        self.section = m["section"]
        self.numeros = tuple(m["numeros"])
        self.property_numero = m["property_numero"]
        self.E0, self.N1 = m["origin_l93"]              # coin NO de la bbox = plan (0, 0)
        self.bbox_l93 = tuple(m["bbox_l93"])            # (e0, n0, e1, n1)
        self.bbox_wgs84 = tuple(m["bbox_wgs84"])        # (lon0, lat0, lon1, lat1)
        self.marge_m = m.get("marge_m", 10.0)

    @property
    def z_min(self) -> float:
        """Altitude NGF de reference (z_plan = alt - z_min). terrain_stats.json."""
        f = DATA / "terrain_stats.json"
        if f.exists():
            return float(json.loads(f.read_text(encoding="utf-8"))["z_min_ngf"])
        raise FileNotFoundError("terrain_stats.json absent — lancer terrain.py d'abord")


class _MetaLazy:
    """Proxy paresseux : `data/meta.json` n'existe pas au 1er run (phase1 ne l'a pas
    encore ecrit) alors que phase1_cadastre importe deja ce module."""

    _inst: _Meta | None = None

    def __getattr__(self, name):
        if _MetaLazy._inst is None:
            _MetaLazy._inst = _Meta()
        return getattr(_MetaLazy._inst, name)


META = _MetaLazy()


def to_plan_cm(E, N):
    """Lambert-93 (m) -> repere plan SH3D (cm) : x vers l'est, y vers le sud."""
    x = (np.asarray(E) - META.E0) * 100.0
    y = (META.N1 - np.asarray(N)) * 100.0
    return x, y


def plan_cm_to_l93(x, y):
    """repere plan SH3D (cm) -> Lambert-93 (m)."""
    E = META.E0 + np.asarray(x) / 100.0
    N = META.N1 - np.asarray(y) / 100.0
    return E, N


# --------------------------------------------------------------------------- #
# Vecteurs : parcelles (API Carto) et couches BD TOPO (WFS) via geopandas
# --------------------------------------------------------------------------- #
def parcels_l93(numeros=NUMEROS):
    """GeoDataFrame EPSG:2154 des parcelles demandees (colonne 'numero')."""
    import geopandas as gpd
    import pandas as pd

    rows = []
    for num in numeros:
        u = (f"{APICARTO}?code_insee={INSEE}&section={SECTION}"
             f"&numero={num}&source_ign=PCI")
        g = gpd.read_file(u)
        if len(g) != 1:
            raise SystemExit(f"{SECTION} {num}: {len(g)} feature(s) (attendu 1)")
        g = g.to_crs(2154)
        g["numero"] = num
        g["is_property"] = num == PROPERTY_NUMERO
        rows.append(g)
    return gpd.GeoDataFrame(pd.concat(rows, ignore_index=True), crs="EPSG:2154")


def parcels_union_l93(numeros=NUMEROS):
    """Polygone (shapely) union des parcelles demandees, EPSG:2154 (emprise cadastre)."""
    from shapely.ops import unary_union
    return unary_union(list(parcels_l93(numeros).geometry))


def property_polygon_l93():
    """
    La PROPRIETE = la seule parcelle `property_parcel` de la config. Les autres
    numeros de `parcels` sont des voisins contigus (emprise cadastre / abords).
    """
    return parcels_union_l93((PROPERTY_NUMERO,))


def wfs_l93(typename: str, count: int = 500):
    """GeoDataFrame EPSG:2154 d'une couche WFS sur la bbox du projet."""
    import geopandas as gpd

    lon0, lat0, lon1, lat1 = META.bbox_wgs84
    u = (f"{WFS_URL}?SERVICE=WFS&VERSION=2.0.0&REQUEST=GetFeature"
         f"&TYPENAMES={typename}&SRSNAME=urn:ogc:def:crs:EPSG::4326"
         f"&BBOX={lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326"
         f"&OUTPUTFORMAT=application/json&COUNT={count}")
    return gpd.read_file(u).to_crs(2154)


# --------------------------------------------------------------------------- #
# Raster : WMS GetMap (owslib) -> bytes GeoTIFF, + ouverture rasterio
# --------------------------------------------------------------------------- #
def _bbox_with_margin(margin_m: float):
    e0, n0, e1, n1 = META.bbox_l93
    return (e0 - margin_m, n0 - margin_m, e1 + margin_m, n1 + margin_m)


def _resolve_layers(layers):
    """str cle | str brute | liste de cles/brutes  ->  liste de noms de couches."""
    if isinstance(layers, str):
        layers = [layers]
    return [LAYERS.get(x, x) for x in layers]


def wms_getmap(layers, bbox_l93, res_m: float = 0.5,
               fmt: str = "image/geotiff", max_px: int = 4000,
               size: tuple | None = None) -> bytes:
    """
    WMS 1.3.0 GetMap, EPSG:2154, sur `bbox_l93` = (e0, n0, e1, n1).
    `layers` : une cle de LAYERS, un nom brut, ou une liste (composite).
    `res_m` = taille de pixel visee (m) — ou `size=(w, h)` explicite.
    """
    from owslib.wms import WebMapService

    e0, n0, e1, n1 = bbox_l93
    if size is None:
        w = min(max_px, max(1, int(round((e1 - e0) / res_m))))
        h = min(max_px, max(1, int(round((n1 - n0) / res_m))))
    else:
        w, h = size
    wms = WebMapService(WMS_URL, version="1.3.0")
    r = wms.getmap(layers=_resolve_layers(layers), srs="EPSG:2154",
                   bbox=(e0, n0, e1, n1), size=(w, h), format=fmt,
                   transparent=False)
    return r.read()


def wms_raster(layer_key: str, margin_m: float = 25.0, res_m: float = 0.5):
    """
    Recupere une couche raster sur (bbox projet + marge) et renvoie
    (array float, rasterio_transform, bbox_l93).  NaN pour les no-data.
    """
    import rasterio

    bbox = _bbox_with_margin(margin_m)
    blob = wms_getmap(layer_key, bbox, res_m=res_m, fmt="image/geotiff")
    with rasterio.open(io.BytesIO(blob)) as ds:
        A = ds.read(1).astype(float)
        T = ds.transform
    A[A < -9000] = np.nan
    return A, T, bbox, blob


def wms_ortho_rgb(margin_m: float = 25.0, mult: int = 4, max_px: int = 4000,
                  bbox_l93=None):
    """Ortho HR en RGB (H, W, 3) uint8 + bbox_l93. `mult` px/m."""
    from PIL import Image

    bbox = tuple(bbox_l93) if bbox_l93 is not None else _bbox_with_margin(margin_m)
    e0, n0, e1, n1 = bbox
    w = min(max_px, int((e1 - e0) * mult))
    h = min(max_px, int((n1 - n0) * mult))
    from owslib.wms import WebMapService
    wms = WebMapService(WMS_URL, version="1.3.0")
    r = wms.getmap(layers=[LAYERS["ORTHO"]], srs="EPSG:2154",
                   bbox=(e0, n0, e1, n1), size=(w, h), format="image/png")
    arr = np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB"))
    return arr, bbox


def fill_nan_nearest(A: np.ndarray) -> np.ndarray:
    """Comble les NaN d'un raster par plus proche voisin (scipy)."""
    if not np.isnan(A).any():
        return A
    from scipy.ndimage import distance_transform_edt
    idx = distance_transform_edt(np.isnan(A), return_distances=False,
                                 return_indices=True)
    return A[tuple(idx)]


# --------------------------------------------------------------------------- #
# Altitude de la surface du maillage terrain
#   terrain.py ecrit `terrain_grid.npz` = la grille EXACTE qu'il triangule.
#   Poser un objet a `terrain_z_at(x, y)` le fait affleurer le mesh visible
#   (le MNT brut 0,5 m ne suffit pas : le mesh est sous-echantillonne).
# --------------------------------------------------------------------------- #
class _TerrainSurface:
    def __init__(self) -> None:
        from scipy.interpolate import RegularGridInterpolator
        d = np.load(DATA / "terrain_grid.npz")
        self._f = RegularGridInterpolator(
            (d["y_cm"], d["x_cm"]), d["z_cm"],
            bounds_error=False, fill_value=None)          # extrapole aux bords

    def z_at(self, x_cm, y_cm) -> float:
        return float(self._f((y_cm, x_cm)))


_TERRAIN = None


def terrain_z_at(x_cm, y_cm) -> float:
    """Hauteur (repere plan, cm) de la surface du terrain au point (x_cm, y_cm)."""
    global _TERRAIN
    if _TERRAIN is None:
        _TERRAIN = _TerrainSurface()
    return _TERRAIN.z_at(x_cm, y_cm)


# --------------------------------------------------------------------------- #
# Couleur de toiture depuis l'ortho
#   SH3D delave fort les tons moyens au rendu -> renvoyer des couleurs franches
#   et sombres (tuile brique / ardoise / fibro).
# --------------------------------------------------------------------------- #
def roof_color_from_ortho(poly_l93, ortho_arr, ortho_bbox) -> tuple[int, int, int]:
    e0, n0, e1, n1 = ortho_bbox
    oh, ow, _ = ortho_arr.shape
    minx, miny, maxx, maxy = poly_l93.bounds
    c0 = max(0, int((minx - e0) / (e1 - e0) * ow))
    c1 = min(ow, int((maxx - e0) / (e1 - e0) * ow) + 1)
    r0 = max(0, int((n1 - maxy) / (n1 - n0) * oh))
    r1 = min(oh, int((n1 - miny) / (n1 - n0) * oh) + 1)
    p = ortho_arr[r0:r1, c0:c1].reshape(-1, 3).astype(float)
    if len(p) < 4:
        return (62, 66, 72)
    r, g, b = np.median(p, axis=0)
    if r > b + 10:
        return (139, 58, 43)          # tuile (brique foncee)
    if (r + g + b) / 3 > 150:
        return (120, 124, 130)        # fibro / toit clair
    return (62, 66, 72)               # ardoise / zinc


# --------------------------------------------------------------------------- #
# Ecriture OBJ (+ .mtl) — sérialisation seulement ; la géométrie/les normales
# viennent de PyVista.  UV analytiques : u = (x - x0)/W , v = (y - y0)/H (dans le
# repere plan cm), pour draper l'ortho.
# --------------------------------------------------------------------------- #
def _faces_from_polydata(mesh):
    """Liste de tuples d'indices (triangles) depuis un pyvista.PolyData triangule."""
    f = mesh.faces.reshape(-1, 4)
    if not (f[:, 0] == 3).all():
        mesh = mesh.triangulate()
        f = mesh.faces.reshape(-1, 4)
    return mesh.points, f[:, 1:]


def write_obj(path, mesh, *, mtl_name: str | None = None, mtl_file: str | None = None,
              drape_bbox_cm: tuple | None = None, group: str = "mesh") -> None:
    """
    Ecrit `mesh` (pyvista.PolyData) en OBJ. Axes SH3D : OBJ y-up donc on ecrit
    (x, z, y) depuis le plan (x_est, y_sud, z_haut) en cm.
    `drape_bbox_cm` = (x0, y0, x1, y1) -> ajoute des `vt` (UV) pour la texture.
    """
    path = Path(path)
    pts, tris = _faces_from_polydata(mesh)
    lines: list[str] = []
    if mtl_file:
        lines.append(f"mtllib {mtl_file}")
    lines.append(f"o {group}")
    for x, y, z in pts:
        lines.append(f"v {x:.1f} {z:.1f} {y:.1f}")          # OBJ y-up
    if drape_bbox_cm:
        x0, y0, x1, y1 = drape_bbox_cm
        w = max(x1 - x0, 1e-6)
        hh = max(y1 - y0, 1e-6)
        for x, y, z in pts:
            u = (x - x0) / w
            v = 1.0 - (y - y0) / hh                          # OBJ v depuis le bas
            lines.append(f"vt {u:.5f} {v:.5f}")
    if mtl_name:
        lines.append(f"usemtl {mtl_name}")
    # l'echange y<->z (passage y-up) est une reflexion -> on INVERSE le winding
    # (c, b, a) pour que les faces restent antihoraires vues de l'exterieur.
    if drape_bbox_cm:
        for a, b, c in tris:
            lines.append(f"f {c+1}/{c+1} {b+1}/{b+1} {a+1}/{a+1}")
    else:
        for a, b, c in tris:
            lines.append(f"f {c+1} {b+1} {a+1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_obj_groups(path, groups, *, mtl_file: str) -> None:
    """
    Ecrit plusieurs meshes dans un seul OBJ, un `o`/`usemtl` par groupe.
    `groups` : liste de (nom, pyvista.PolyData, nom_materiau).  Axes : y-up.
    """
    lines = [f"mtllib {mtl_file}"]
    off = 0
    for name, mesh, mtl in groups:
        pts, tris = _faces_from_polydata(mesh)
        lines.append(f"o {name}")
        for x, y, z in pts:
            lines.append(f"v {x:.1f} {z:.1f} {y:.1f}")
        lines.append(f"usemtl {mtl}")
        for a, b, c in tris:                                 # winding inverse (cf. write_obj)
            lines.append(f"f {c+1+off} {b+1+off} {a+1+off}")
        off += len(pts)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mtl(path, materials: dict) -> None:
    """
    materials : {nom: {"Kd": (r,g,b) 0..1, "map_Kd": "fichier.jpg"|None}}.
    Materiau 100 % MAT : pas de speculaire (Ks 0), Ns bas, illum 1 (ambient+diffuse).
    """
    out = []
    for name, m in materials.items():
        kd = m.get("Kd", (0.6, 0.6, 0.6))
        out += [
            f"newmtl {name}",
            "Ka 0.000 0.000 0.000",                 # pas d'ambiant -> pas de delavage
            f"Kd {kd[0]:.3f} {kd[1]:.3f} {kd[2]:.3f}",
            "Ks 0.000 0.000 0.000",                 # 100 % mat : aucun speculaire
            "Ns 1.0",
            "d 1.0",
            "illum 1",
        ]
        if m.get("map_Kd"):
            out.append(f"map_Kd {m['map_Kd']}")
    Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# PyVista : surface MNT -> solide watertight (sans pv.Plane, casse dans cet env)
# --------------------------------------------------------------------------- #
def grid_surface(EE, NN, ZZ):
    """
    Grille reguliere L93 (EE, NN, ZZ en m / m NGF) -> pyvista.PolyData triangule
    dans le repere plan SH3D (cm), z = alt - z_min.
    """
    import pyvista as pv

    x, y = to_plan_cm(EE, NN)
    z = (np.asarray(ZZ) - META.z_min) * 100.0
    surf = pv.StructuredGrid(x, y, z).extract_surface(algorithm="dataset_surface")
    return surf.triangulate()


def solidify(surf, depth_cm: float = 800.0):
    """
    Surface -> volume ferme : extrusion verticale vers le bas + capot, nettoyage,
    normales reorientees vers l'exterieur.  Le fond est « ondulé » sous la scene
    (invisible) — pas besoin de pv.Plane.
    """
    solid = surf.extrude((0.0, 0.0, -abs(depth_cm)), capping=True).clean()
    return solid.compute_normals(auto_orient_normals=True, consistent_normals=True,
                                 non_manifold_traversal=False)


def polygon_prism(ring_cm, base_z: float, top_z: float):
    """Anneau (liste de (x, y) plan cm, sans point de fermeture) -> prisme ferme."""
    import pyvista as pv

    n = len(ring_cm)
    pts = np.array([[x, y, base_z] for x, y in ring_cm], float)
    poly = pv.PolyData(pts, faces=np.hstack([[n], list(range(n))])).triangulate()
    prism = poly.extrude((0.0, 0.0, top_z - base_z), capping=True).clean()
    return prism.compute_normals(auto_orient_normals=True, non_manifold_traversal=False)


def pyramid_roof(ring_cm, eave_z: float, apex_z: float):
    """
    Toit pyramidal FERME (cone) : anneau d'egout + apex au centroide + fond triangule.
    Volume clos -> `compute_normals(auto_orient_normals)` oriente tout vers l'exterieur,
    donc jamais de face cullee quel que soit l'angle de vue. Le fond recouvre le capot
    du prisme mur (invisible). Valide pour tout polygone simple.
    """
    import pyvista as pv

    n = len(ring_cm)
    cx = float(np.mean([x for x, _ in ring_cm]))
    cy = float(np.mean([y for _, y in ring_cm]))
    pts = np.array([[x, y, eave_z] for x, y in ring_cm] + [[cx, cy, apex_z]], float)
    faces = [[3, i, (i + 1) % n, n] for i in range(n)]          # pans
    faces += [[3, 0, i + 1, i] for i in range(1, n - 1)]        # fond (fan)
    roof = pv.PolyData(pts, faces=np.hstack([f for f in faces])).clean()
    return roof.compute_normals(auto_orient_normals=True, consistent_normals=True,
                                non_manifold_traversal=False)


def bbox_cm(mesh) -> dict:
    """
    Bounds d'un mesh (repere plan : x_est, y_sud, z_haut) -> parametres de recalage
    du meuble importe.  A l'import OBJ, SH3D lit X=largeur, Y=hauteur, Z=profondeur
    et l'OBJ est ecrit y-up -> width<-x, height<-z_plan, depth<-y_plan.
    """
    x0, x1, y0, y1, z0, z1 = mesh.bounds
    return {"x": round((x0 + x1) / 2, 1), "y": round((y0 + y1) / 2, 1),
            "width": round(x1 - x0, 1), "depth": round(y1 - y0, 1),
            "height": round(z1 - z0, 1), "elevation": round(z0, 1)}
