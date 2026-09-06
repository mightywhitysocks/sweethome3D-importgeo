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
import re
import shutil
import zipfile
from pathlib import Path

from PIL import Image

import arbaro_tree
import sh3d_xml
import sitegeo as cg

GEO = cg.GEO
SH3D = cg.HOME_SH3D
WALK_EYE_CM = cg.WALK_EYE_CM                  # hauteur d'oeil de la camera de visite 3D

LEVELS = {                       # noms -> ids (repris du gabarit, stables)
    "Cadastre": "level-444fad18-a6ed-490b-9cda-2016da873fcc",
    "Terrain": "level-b1c25b31-ec4d-4776-b2da-dace8e120ffe",
    "Bati voisinage": "level-94f420d7-1fb8-4666-85cc-91384f586dff",
    "Bati propriete": "level-19f6a101-847c-4426-94b8-b0722d1015db",
    "Vegetation": "level-d7571dd8-f841-4ace-9baa-2b5b5df57394",
}


def _background_image_tag(fond_png: Path, width_m: float) -> str:
    w_px, h_px = Image.open(fond_png).size
    scale = 0.8 * width_m * 100.0                         # cm sur 80 % de la largeur
    x0, x1, ym = 0.1 * w_px, 0.9 * w_px, 0.5 * h_px
    return (f"    <backgroundImage image='bg' scaleDistance='{scale:.3f}' "
            f"scaleDistanceXStart='{x0:.3f}' scaleDistanceYStart='{ym:.3f}' "
            f"scaleDistanceXEnd='{x1:.3f}' scaleDistanceYEnd='{ym:.3f}'/>")


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
    head = re.sub(r"[ \t]*<compass\b[^>]*/>", sh3d_xml.compass_tag(), head, count=1)
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
    head = sh3d_xml.set_walk_camera(head, wx, wy, wz)

    # ---- niveaux dynamiques : emprises au sol visibles des batiments propriete ----
    # Un <room> SH3D n'a pas d'elevation propre, seulement celle de son niveau (cf.
    # "Bati propriete" plus bas, plancher invisible car sa geometrie 3D vient de
    # bati_propriete.obj). Pour une emprise VISIBLE posee sur un terrain non plan, un
    # niveau unique partage clipperait forcement certains batiments dans le maillage
    # terrain (site reel observe : jusqu'a ~2,5 m d'ecart de sol entre deux batiments
    # propriete) -> un niveau dedie par batiment, cale sur le point de terrain le PLUS
    # HAUT sous son emprise (sol_max_cm, calcule par bati.py) + FOOTPRINT_CLEARANCE_CM,
    # jamais clippe. Ids prives (pas dans LEVELS, qui reste le registre stable du
    # gabarit) -> passes explicitement a sh3d_xml.room via son parametre `levels`.
    footprint_cmds = [c for c in ref["commands"] if c["action"] == "create_room_polygon"]
    base_level_count = len(LEVELS)
    footprint_levels_xml = []
    footprint_levels = {}               # nom de niveau prive -> id
    footprint_rooms = []                # (level_name, ring_cm), consommes plus bas
    for i, (cmd, fp) in enumerate(zip(footprint_cmds, ref["footprints"])):
        ring = [(pt["x"], pt["y"]) for pt in cmd["params"]["points"]]
        elevation = fp["sol_max_cm"] + sh3d_xml.FOOTPRINT_CLEARANCE_CM
        level_name = f"Emprise {fp['id']}"
        level_id = sh3d_xml.uid("level")
        footprint_levels[level_name] = level_id
        footprint_levels_xml.append(sh3d_xml.level(level_id, level_name, elevation, base_level_count + i))
        footprint_rooms.append((level_name, ring))
    head += "\n" + "\n".join(footprint_levels_xml) + "\n"

    # ---- pieces ----
    pieces = []
    tp = json.loads((GEO / "terrain_place.json").read_text(encoding="utf-8"))
    pieces.append(sh3d_xml.piece(LEVELS, "Terrain", "Terrain (LIDAR HD + ortho)", "t/terrain.obj",
                         (GEO / "terrain.obj").stat().st_size,
                         tp["x"], tp["y"], tp["elevation"], tp["width"], tp["depth"],
                         tp["height"], creator="IGN LIDAR HD",
                         extra=" deformable='false'"))

    bp = json.loads((GEO / "bati_place.json").read_text(encoding="utf-8"))
    pieces.append(sh3d_xml.piece(LEVELS, "Bati voisinage", "Bati voisinage (BD TOPO + LIDAR)",
                         "b/bati_voisinage.obj", (GEO / "bati_voisinage.obj").stat().st_size,
                         bp["x"], bp["y"], bp["elevation"], bp["width"], bp["depth"],
                         bp["height"], creator="IGN BD TOPO", extra=" deformable='false'"))

    has_bati_propriete = (GEO / "bati_propriete.obj").exists()
    if has_bati_propriete:
        pp = json.loads((GEO / "bati_propriete_place.json").read_text(encoding="utf-8"))
        pieces.append(sh3d_xml.piece(LEVELS, "Bati propriete", "Bati propriete (LIDAR HD multi-pans)",
                             "p/bati_propriete.obj", (GEO / "bati_propriete.obj").stat().st_size,
                             pp["x"], pp["y"], pp["elevation"], pp["width"], pp["depth"],
                             pp["height"], creator="IGN LIDAR HD", extra=" deformable='false'"))

    hedge_pieces = []
    if (GEO / "haies.obj").exists():
        hp = json.loads((GEO / "haies_place.json").read_text(encoding="utf-8"))
        hedge_pieces.append(sh3d_xml.piece(LEVELS, "Vegetation", "Haies (MNH LIDAR HD)", "h/haies.obj",
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
            tree_pieces.append(sh3d_xml.piece(LEVELS, "Vegetation", "Arbre", f"{model_key}/{model_key}.obj",
                                 len(species_models[model_key]["obj"]),
                                 p["x"], p["y"], p["elevation"],
                                 rz["width"], rz["depth"], rz["height"],
                                 creator="Arbaro (Weber & Penn) + parametres du projet",
                                 extra=" movable='false'"))
        else:
            tree_pieces.append(sh3d_xml.piece(LEVELS, "Vegetation", "Arbre", "tree/tree.obj", tsz,
                                 p["x"], p["y"], p["elevation"],
                                 rz["width"], rz["depth"], rz["height"],
                                 catalog="OlaKristianHoff#tree", creator="Ola-Kristian Hoff",
                                 extra=" movable='false' license='Free Art / CC-BY'"))

    pieces.append(sh3d_xml.furniture_group(LEVELS, "Vegetation", "Arbres", tree_pieces))
    pieces.append(sh3d_xml.furniture_group(LEVELS, "Vegetation", "Haies", hedge_pieces))

    # ---- rooms ----
    rooms = []
    for pc in payload["parcels"]:
        col = "00C8E6C9" if pc["is_property"] else "00E6E7E9"
        tag = " (propriete)" if pc["is_property"] else " (voisin)"
        for ring in pc["rings_cm"]:
            rooms.append(sh3d_xml.room(LEVELS, "Cadastre", f"{cg.SECTION} {pc['numero']} {tag}", ring,
                               floor_color=col))
    for cmd in footprint_cmds:
        pr = cmd["params"]
        ring = [(pt["x"], pt["y"]) for pt in pr["points"]]
        rooms.append(sh3d_xml.room(LEVELS, "Bati propriete", pr["name"], ring,
                           floor_color="00B0A48F", floor_visible=False))
    for level_name, ring in footprint_rooms:
        rooms.append(sh3d_xml.room(footprint_levels, level_name, level_name, ring,
                           floor_color="00B0A48F"))

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
    if SH3D.exists():
        shutil.copy2(SH3D, SH3D.with_suffix(".sh3d.bak"))
    try:
        sh3d_xml.convert_to_sh3d(raw, SH3D)
    finally:
        raw.unlink(missing_ok=True)

    print(f"\n>>> {SH3D.name}  ({SH3D.stat().st_size // 1024} Ko , {len(pieces)} pieces, "
          f"{len(rooms)} pieces-plan). Double-clique pour ouvrir.")
    print(f"    (ancien : {SH3D.with_suffix('.sh3d.bak').name} ; source XML : data/home_source.xml)")


if __name__ == "__main__":
    main()
