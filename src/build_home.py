"""
build_home.py : assemble le fichier SH3D complet HORS-LIGNE (`Plan 3D.sh3d`).

Plus aucune choregraphie MCP / redemarrage.

  Etape 1 (Python) : ecrit un ZIP intermediaire {Home.xml + modeles OBJ} depuis les
    sorties du pipeline (data/). `Home.xml` reprend l'en-tete du gabarit neutre
    assets/home_template.xml (env, compas, cameras, les 5 <level>) ; le <compass> est
    reoriente sur le centroide du site et les <pieceOfFurniture>/<room> regeneres.
  Etape 2 (Java) : java/Conv.java (compile via le JDK systeme) parse ce Home.xml avec
    `HomeXMLHandler` de SH3D et le REecrit en `.sh3d` complet via `HomeFileRecorder`
    (le loader SH3D exige l'entree `Home` serialisee Java, que Python ne sait pas faire).

Sources (data/) :
  terrain.obj/.mtl + terrain_place.json + terrain_drape.jpg (si present --
    repli couleur unie sinon, cf. terrain.py)
  bati_voisinage.obj/.mtl + bati_place.json + bati_propriete_ref.json
  haies.obj/.mtl + haies_place.json          (si present)
  vegetation_arbres.json  (+ assets/tree.obj/.mtl gabarit historique, et/ou
    modeles espece x variante generes par arbaro_tree.py, cf. issue #82)
  fond_cadastre_ortho.png + sh3d_payload.json

Sortie : Plan 3D.sh3d (racine). Sauvegarde .sh3d.bak.
Prerequis : un JDK (java + javac) sur le PATH ; Sweet Home 3D installe (pour le .jar,
auto-detecte ou [tools].sweethome3d_jar dans site.local.toml).
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path

from PIL import Image

import arbaro_tree
import sitegeo as cg

GEO = cg.GEO
SH3D = cg.HOME_SH3D
JCONV = cg.DATA / "_jconv"                   # cache : jar copie + Conv.class
WALK_EYE_CM = cg.WALK_EYE_CM                  # hauteur d'oeil de la camera de visite 3D

LEVELS = {                       # noms -> ids (repris du gabarit, stables)
    "Cadastre": "level-444fad18-a6ed-490b-9cda-2016da873fcc",
    "Terrain": "level-b1c25b31-ec4d-4776-b2da-dace8e120ffe",
    "Bati voisinage": "level-94f420d7-1fb8-4666-85cc-91384f586dff",
    "Bati propriete": "level-19f6a101-847c-4426-94b8-b0722d1015db",
    "Vegetation": "level-d7571dd8-f841-4ace-9baa-2b5b5df57394",
}
FOOTPRINT_CLEARANCE_CM = 3.0     # marge au-dessus du terrain pour les emprises visibles


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "&apos;"))


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _piece(level, name, model, size, x, y, elev, w, d, h, *, catalog=None,
           creator=None, extra="") -> str:
    a = [f"id='{_uid('pieceOfFurniture')}'", f"level='{LEVELS[level]}'"]
    if catalog:
        a.append(f"catalogId='{_esc(catalog)}'")
    a.append(f"name='{_esc(name)}'")
    if creator:
        a.append(f"creator='{_esc(creator)}'")
    a += [f"model='{model}'", "icon='ico'",
          f"x='{x:.1f}'", f"y='{y:.1f}'", f"elevation='{elev:.1f}'",
          f"width='{w:.1f}'", f"depth='{d:.1f}'", f"height='{h:.1f}'",
          f"modelSize='{size}'"]
    return f"  <pieceOfFurniture {' '.join(a)}{extra}/>"


def _furniture_group(level, name, children: list[str]) -> str:
    """Regroupe des <pieceOfFurniture> deja generees en un <furnitureGroup>.

    x/y/width/depth/height du groupe sont calcules par SH3D (HomeFurnitureGroup)
    a partir de la boite englobante des enfants ; le level porte par les enfants
    est ignore par HomeXMLHandler, seul celui du groupe compte.
    """
    if not children:
        return ""
    inner = "\n".join(children)
    return (f"  <furnitureGroup id='{_uid('furnitureGroup')}' "
            f"level='{LEVELS[level]}' name='{_esc(name)}'>\n{inner}\n"
            f"  </furnitureGroup>")


def _room(level, name, ring_cm, *, floor_color, floor_visible=True, levels=LEVELS) -> str:
    pts = "\n".join(f"    <point x='{x:.1f}' y='{y:.1f}'/>" for x, y in ring_cm)
    fv = "" if floor_visible else " floorVisible='false'"
    av = " areaVisible='true'" if floor_visible else ""
    return (f"  <room id='{_uid('room')}' level='{levels[level]}' name='{_esc(name)}'"
            f"{av}{fv} floorColor='{floor_color}' ceilingVisible='false' "
            f"ceilingFlat='true'>\n{pts}\n  </room>")


def _level(level_id, name, elevation, index) -> str:
    return (f"  <level id='{level_id}' name='{_esc(name)}' elevation='{elevation:.1f}' "
            f"floorThickness='12.0' height='30.0' elevationIndex='{index}'/>")


def _background_image_tag(fond_png: Path, width_m: float) -> str:
    w_px, h_px = Image.open(fond_png).size
    scale = 0.8 * width_m * 100.0                         # cm sur 80 % de la largeur
    x0, x1, ym = 0.1 * w_px, 0.9 * w_px, 0.5 * h_px
    return (f"    <backgroundImage image='bg' scaleDistance='{scale:.3f}' "
            f"scaleDistanceXStart='{x0:.3f}' scaleDistanceYStart='{ym:.3f}' "
            f"scaleDistanceXEnd='{x1:.3f}' scaleDistanceYEnd='{ym:.3f}'/>")


def _compass_tag(_m) -> str:
    """<compass> avec long/lat (radians) du centroide du site (pas stocke au depot)."""
    lon0, lat0, lon1, lat1 = cg.META.bbox_wgs84
    lon = math.radians((lon0 + lon1) / 2.0)
    lat = math.radians((lat0 + lat1) / 2.0)
    return (f"  <compass x='-100.0' y='50.0' diameter='100.0' northDirection='0.0' "
            f"longitude='{lon:.7f}' latitude='{lat:.7f}' timeZone='Europe/Paris'/>")


def _set_walk_camera(head: str, x, y, z: float) -> str:
    """Repositionne la camera observateur (visite 3D) : x/y optionnels, z impose."""
    def repl(m):
        tag = m.group(0)
        if x is not None:
            tag = re.sub(r"\bx='[-\d.]+'", f"x='{x:.1f}'", tag)
            tag = re.sub(r"\by='[-\d.]+'", f"y='{y:.1f}'", tag)
        return re.sub(r"\bz='[-\d.]+'", f"z='{z:.1f}'", tag)
    return re.sub(r"<observerCamera attribute='observerCamera'[^>]*/>", repl,
                  head, count=1)


def main() -> None:
    payload = json.loads((GEO / "sh3d_payload.json").read_text(encoding="utf-8"))
    fond_png = GEO / "fond_cadastre_ortho.png"
    stats = json.loads((GEO / "terrain_stats.json").read_text(encoding="utf-8"))
    z_max_cm = (stats["z_max_ngf"] - stats["z_min_ngf"]) * 100.0

    # -- gabarit (en-tete SH3D neutre : home/env/compas/cameras/5 levels) --
    tmpl = (cg.ASSETS / "home_template.xml").read_text(encoding="utf-8")
    tree_obj = (cg.ASSETS / "tree.obj").read_bytes()
    tree_mtl = (cg.ASSETS / "tree.mtl").read_bytes()
    head = tmpl[: tmpl.rindex("</home>")]

    # especes generees (issue #82) : {} si arbaro indisponible au moment de ce
    # run (meme cache disque que vegetation.py -- deja genere/reutilise dans
    # data/arbaro_cache, cet appel est donc rapide, jamais une regeneration).
    # Les arbres dont vegetation_arbres.json ne porte pas de "model" (gabarit
    # unique historique) restent inchanges quel que soit ce resultat.
    species_models = arbaro_tree.prepare_species_models(log=print)

    # fond de plan : remplacer la <backgroundImage> du niveau Cadastre
    head = re.sub(r"[ \t]*<backgroundImage\b[^>]*/>",
                  _background_image_tag(fond_png, payload["fond"]["width_m"]), head)
    # compas : oriente le soleil sur le centroide reel du site (gabarit = neutre)
    head = re.sub(r"[ \t]*<compass\b[^>]*/>", _compass_tag(None), head, count=1)
    # camera de visite 3D : hauteur d'oeil au-dessus du sol LE PLUS HAUT sous les
    # batiments de la propriete, posee sur la parcelle propriete. Repli (pas de bati
    # propriete) : au-dessus du point haut du terrain.
    ref = json.loads((GEO / "bati_propriete_ref.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    if ref.get("sol_bati_max_cm") and prop:
        wx, wy = prop["centroid_cm"]
        wz = ref["sol_bati_max_cm"] + WALK_EYE_CM
    else:
        wx, wy, wz = None, None, z_max_cm + 60
    head = _set_walk_camera(head, wx, wy, wz)

    # ---- niveaux dynamiques : emprises au sol visibles des batiments propriete ----
    # Un <room> SH3D n'a pas d'elevation propre, seulement celle de son niveau (cf.
    # "Bati propriete" plus bas, plancher invisible car sa geometrie 3D vient de
    # bati_propriete.obj). Pour une emprise VISIBLE posee sur un terrain non plan, un
    # niveau unique partage clipperait forcement certains batiments dans le maillage
    # terrain (site reel observe : jusqu'a ~2,5 m d'ecart de sol entre deux batiments
    # propriete) -> un niveau dedie par batiment, cale sur le point de terrain le PLUS
    # HAUT sous son emprise (sol_max_cm, calcule par bati.py) + FOOTPRINT_CLEARANCE_CM,
    # jamais clippe. Ids prives (pas dans LEVELS, qui reste le registre stable du
    # gabarit) -> passes explicitement a _room via son parametre `levels`.
    footprint_cmds = [c for c in ref["commands"] if c["action"] == "create_room_polygon"]
    base_level_count = len(LEVELS)
    footprint_levels_xml = []
    footprint_levels = {}               # nom de niveau prive -> id
    footprint_rooms = []                # (level_name, ring_cm), consommes plus bas
    for i, (cmd, fp) in enumerate(zip(footprint_cmds, ref["footprints"])):
        ring = [(pt["x"], pt["y"]) for pt in cmd["params"]["points"]]
        elevation = fp["sol_max_cm"] + FOOTPRINT_CLEARANCE_CM
        level_name = f"Emprise {fp['id']}"
        level_id = _uid("level")
        footprint_levels[level_name] = level_id
        footprint_levels_xml.append(_level(level_id, level_name, elevation, base_level_count + i))
        footprint_rooms.append((level_name, ring))
    head += "\n" + "\n".join(footprint_levels_xml) + "\n"

    # ---- pieces ----
    pieces = []
    tp = json.loads((GEO / "terrain_place.json").read_text(encoding="utf-8"))
    pieces.append(_piece("Terrain", "Terrain (LIDAR HD + ortho)", "t/terrain.obj",
                         (GEO / "terrain.obj").stat().st_size,
                         tp["x"], tp["y"], tp["elevation"], tp["width"], tp["depth"],
                         tp["height"], creator="IGN LIDAR HD",
                         extra=" deformable='false'"))

    bp = json.loads((GEO / "bati_place.json").read_text(encoding="utf-8"))
    pieces.append(_piece("Bati voisinage", "Bati voisinage (BD TOPO + LIDAR)",
                         "b/bati_voisinage.obj", (GEO / "bati_voisinage.obj").stat().st_size,
                         bp["x"], bp["y"], bp["elevation"], bp["width"], bp["depth"],
                         bp["height"], creator="IGN BD TOPO", extra=" deformable='false'"))

    has_bati_propriete = (GEO / "bati_propriete.obj").exists()
    if has_bati_propriete:
        pp = json.loads((GEO / "bati_propriete_place.json").read_text(encoding="utf-8"))
        pieces.append(_piece("Bati propriete", "Bati propriete (LIDAR HD multi-pans)",
                             "p/bati_propriete.obj", (GEO / "bati_propriete.obj").stat().st_size,
                             pp["x"], pp["y"], pp["elevation"], pp["width"], pp["depth"],
                             pp["height"], creator="IGN LIDAR HD", extra=" deformable='false'"))

    hedge_pieces = []
    if (GEO / "haies.obj").exists():
        hp = json.loads((GEO / "haies_place.json").read_text(encoding="utf-8"))
        hedge_pieces.append(_piece("Vegetation", "Haies (MNH LIDAR HD)", "h/haies.obj",
                             (GEO / "haies.obj").stat().st_size, hp["x"], hp["y"],
                             hp["elevation"], hp["width"], hp["depth"], hp["height"],
                             creator="IGN LIDAR HD", extra=" deformable='false'"))

    tree_pieces = []
    veg = json.loads((GEO / "vegetation_arbres.json").read_text(encoding="utf-8"))
    tsz = len(tree_obj)
    # modeles espece x variante REELLEMENT references (jamais tous : ne pas
    # embarquer dans le zip un modele que species_models fournirait mais
    # qu'aucun arbre de CE site n'utilise).
    used_models = {rz.get("model") for rz in veg["resize"]} & species_models.keys()
    for pl, rz in zip(veg["place"]["commands"], veg["resize"]):
        p = pl["params"]
        model_key = rz.get("model")
        if model_key in species_models:
            tree_pieces.append(_piece("Vegetation", "Arbre", f"{model_key}/{model_key}.obj",
                                 len(species_models[model_key]["obj"]),
                                 p["x"], p["y"], p["elevation"],
                                 rz["width"], rz["depth"], rz["height"],
                                 creator="Arbaro (Weber & Penn) + parametres du projet",
                                 extra=" movable='false'"))
        else:
            tree_pieces.append(_piece("Vegetation", "Arbre", "tree/tree.obj", tsz,
                                 p["x"], p["y"], p["elevation"],
                                 rz["width"], rz["depth"], rz["height"],
                                 catalog="OlaKristianHoff#tree", creator="Ola-Kristian Hoff",
                                 extra=" movable='false' license='Free Art / CC-BY'"))

    pieces.append(_furniture_group("Vegetation", "Arbres", tree_pieces))
    pieces.append(_furniture_group("Vegetation", "Haies", hedge_pieces))

    # ---- rooms ----
    rooms = []
    for pc in payload["parcels"]:
        col = "00C8E6C9" if pc["is_property"] else "00E6E7E9"
        tag = " (propriete)" if pc["is_property"] else " (voisin)"
        for ring in pc["rings_cm"]:
            rooms.append(_room("Cadastre", f"{cg.SECTION} {pc['numero']} {tag}", ring,
                               floor_color=col))
    for cmd in footprint_cmds:
        pr = cmd["params"]
        ring = [(pt["x"], pt["y"]) for pt in pr["points"]]
        rooms.append(_room("Bati propriete", pr["name"], ring,
                           floor_color="00B0A48F", floor_visible=False))
    for level_name, ring in footprint_rooms:
        rooms.append(_room(level_name, level_name, ring, floor_color="00B0A48F",
                           levels=footprint_levels))

    home_xml = head + "\n".join(pieces) + "\n" + "\n".join(rooms) + "\n</home>\n"
    (GEO / "home_source.xml").write_text(home_xml, encoding="utf-8")   # debug / diff

    # ---- etape 1 : zip intermediaire {Home.xml + modeles} ----
    raw = GEO / "_home_raw.zip"
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("Home.xml", home_xml)
        z.write(fond_png, "bg")
        z.write(GEO / "terrain.obj", "t/terrain.obj")
        z.write(GEO / "terrain.mtl", "t/terrain.mtl")
        if (GEO / "terrain_drape.jpg").exists():
            # absent -> repli deliberement gere par terrain.py (WMS ortho
            # indisponible : couleur unie COL_HERBE, terrain.mtl sans
            # map_Kd) -- jamais une raison de faire echouer l'assemblage.
            z.write(GEO / "terrain_drape.jpg", "t/terrain_drape.jpg")
        z.write(GEO / "bati_voisinage.obj", "b/bati_voisinage.obj")
        z.write(GEO / "bati_voisinage.mtl", "b/bati_voisinage.mtl")
        if has_bati_propriete:
            z.write(GEO / "bati_propriete.obj", "p/bati_propriete.obj")
            z.write(GEO / "bati_propriete.mtl", "p/bati_propriete.mtl")
        if (GEO / "haies.obj").exists():
            z.write(GEO / "haies.obj", "h/haies.obj")
            z.write(GEO / "haies.mtl", "h/haies.mtl")
        if any(rz.get("model") not in species_models for rz in veg["resize"]):
            z.writestr("tree/tree.obj", tree_obj)
            z.writestr("tree/tree.mtl", tree_mtl)
        # chaque modele dans son PROPRE dossier de premier niveau (pas un
        # "tree/" partage) : bug constate dans HomeContentContext.lookupContent
        # (SweetHome3D, appele par Conv.java/HomeXMLHandler) -- son cache de
        # contenu est keye par le PREMIER segment du chemin, pas le chemin
        # complet, donc plusieurs pieceOfFurniture sans catalogId referencant
        # des fichiers sous le MEME premier segment ("tree/xxx.obj" pour
        # toutes les variantes) recoivent TOUTES le Content du premier
        # resolu -- silhouette identique partout malgre des model= distincts
        # dans Home.xml, confirme par reproduction minimale isolee (varier
        # name/creator/catalogId/icon/elevation/niveau ne change rien, seul
        # le premier segment du chemin importe). Le .mtl est duplique dans
        # chaque dossier (plus de partage inter-variantes) : cout negligeable
        # (quelques centaines d'octets), la duplication est ce qui garantit
        # des premiers segments distincts.
        for model_key in used_models:
            m = species_models[model_key]
            z.writestr(f"{model_key}/{model_key}.obj", m["obj"])
            z.writestr(f"{model_key}/{m['mtl_name']}", m["mtl"])
        ico = io.BytesIO()
        Image.new("RGB", (48, 48), (110, 130, 90)).save(ico, "PNG")
        z.writestr("ico", ico.getvalue())

    # ---- etape 2 : Java -> .sh3d complet (Home serialise) ----
    jar = _prepare_java()
    if SH3D.exists():
        shutil.copy2(SH3D, SH3D.with_suffix(".sh3d.bak"))
    r = subprocess.run(
        ["java", "-cp", f"{jar}{os.pathsep}{JCONV}",
         "com.eteks.sweethome3d.io.Conv", str(raw), str(SH3D)],
        capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip()[:800])
    raw.unlink(missing_ok=True)
    if r.returncode != 0 or not SH3D.exists():
        raise SystemExit("echec de la conversion Java (voir ci-dessus)")

    print(f"\n>>> {SH3D.name}  ({SH3D.stat().st_size // 1024} Ko , {len(pieces)} pieces, "
          f"{len(rooms)} pieces-plan). Double-clique pour ouvrir.")
    print(f"    (ancien : {SH3D.with_suffix('.sh3d.bak').name} ; source XML : data/home_source.xml)")


def _prepare_java() -> Path:
    """Copie le .jar SH3D et compile Conv.java dans data/_jconv/ (une seule fois)."""
    JCONV.mkdir(parents=True, exist_ok=True)
    jar = JCONV / "SweetHome3D.jar"
    if not jar.exists():
        shutil.copy2(cg.find_sweethome3d_jar(), jar)
    cls = JCONV / "com" / "eteks" / "sweethome3d" / "io" / "Conv.class"
    src = cg.JAVA / "Conv.java"
    if not cls.exists() or cls.stat().st_mtime < src.stat().st_mtime:
        r = subprocess.run(["javac", "-cp", str(jar), "-d", str(JCONV), str(src)],
                           check=False, capture_output=True, text=True)
        if not cls.exists():
            print(r.stdout.strip() or r.stderr.strip()[:800])
            raise SystemExit("javac a echoue (JDK sur le PATH, ou erreur de compilation ci-dessus)")
    return jar


if __name__ == "__main__":
    main()
