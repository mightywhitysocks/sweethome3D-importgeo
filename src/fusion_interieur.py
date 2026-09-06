"""
fusion_interieur.py : fusion PONCTUELLE des projets .sh3d intérieurs
(interieur/<id>.sh3d, cf. interieur_init.py) dans Plan 3D.sh3d.

Étape HORS du pipeline principal, jamais automatique : jamais dans le
tableau `all` de run.sh/run.ps1, jamais invoquée par generation.yml -- se
lance à la main (`./run.sh fusion_interieur`) une fois Plan 3D.sh3d généré
ET un ou plusieurs interieur/<id>.sh3d édités dans l'appli Sweet Home 3D
native. Ne modifie jamais Plan 3D.sh3d lui-même : écrit un fichier séparé,
"Plan 3D (avec interieur).sh3d" -- les deux cycles de vie (génération
extérieure automatique, édition intérieure manuelle) restent découplés.

Principe : les fichiers interieur/*.sh3d partagent le MEME repère plan
absolu (cm, origine Lambert-93 du site) que Plan 3D.sh3d (cf.
interieur_init.py) -- aucune translation de coordonnées n'est nécessaire ;
la fusion est purement structurelle (recopie des <level> et des elements
qu'ils portent, renumerotation d'id/elevationIndex, copie des eventuels
fichiers de contenu -- modeles/icones de mobilier).

Format XML natif verifie avant d'ecrire ce parseur (JDK + SweetHome3D.jar,
cf. CLAUDE.md) : un objet porte un attribut `level='...'` explicite des
qu'il y a plusieurs niveaux dans le fichier (absent seulement si le fichier
n'a qu'un seul niveau -- cas alors sans ambiguite). Un meuble de catalogue
embarque sa propre copie de modele/icone dans le zip sous forme d'entrees
numeriques (ex. `model='1'`, `icon='0'`) -- jamais une reference catalogue
pure : ces entrees doivent etre copiees, pas seulement les attributs qui
les referencent.

Chaque interieur/<id>.sh3d est dans son propre repere LOCAL (cf.
interieur_init.py::_local_frame, rectangle englobant minimal de l'emprise --
bien plus pratique a l'edition qu'un batiment loin de l'origine et en biais
sur la trame Lambert-93 du site). La fusion doit donc appliquer la
transformation INVERSE (repere local -> repere absolu de Plan 3D.sh3d) a
chaque point/angle retenu, lue dans interieur/<id>.transform.json (ecrit une
seule fois par interieur_init.py) -- repli sur la transformation identite si
ce fichier annexe est absent (compatibilite avec un interieur/<id>.sh3d cree
par une version anterieure de interieur_init.py, deja en repere absolu).
Schema verifie empiriquement (JDK + SweetHome3D.jar, meme methode que le
reste de ce mecanisme) : <room>/<polyline> portent leurs points en <point x
y/> imbriques ; <wall>/<dimensionLine> ont xStart/yStart/xEnd/yEnd (l'offset
d'une cote est une distance perpendiculaire a la ligne, invariante par
rotation) ; <pieceOfFurniture>/<furnitureGroup>/<label> ont x/y + un angle en
RADIANS ; <room> porte aussi areaAngle/nameAngle (radians).

La piece-repere de l'emprise (sh3d_xml.GUIDE_ROOM_NAME, creee par
interieur_init.py comme calque de tracage) n'est JAMAIS copiee dans le
fichier fusionne -- reconnue par son nom exact (limite assumee : perdue si
l'utilisateur la renomme, repli sur en element normal, pas un crash).
"""
from __future__ import annotations

import json
import math
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import sh3d_xml
import sitegeo as cg

SH3D = cg.HOME_SH3D
INT_DIR = cg.ROOT / "interieur"
OUT_SH3D = cg.ROOT / "Plan 3D (avec interieur).sh3d"

LEVEL_SCOPED_TAGS = {"room", "wall", "pieceOfFurniture", "furnitureGroup",
                     "dimensionLine", "polyline", "label"}
CONTENT_ATTRS = {"model", "icon", "planIcon", "image", "texture"}
WALL_REF_ATTRS = ("wallAtStart", "wallAtEnd")
SKIP_ENTRIES = {"Home.xml", "Home", "ContentDigests"}

# Attributs point (x,y) et angle (radians) par type d'element, pour la
# transformation repere local -> absolu (cf. module docstring). Les <point>
# imbriques de <room>/<polyline> sont geres a part (meme tag "point" pour les
# deux, cf. _apply_transform).
POINT_ATTR_PAIRS = {
    "wall": [("xStart", "yStart"), ("xEnd", "yEnd")],
    "dimensionLine": [("xStart", "yStart"), ("xEnd", "yEnd")],
    "pieceOfFurniture": [("x", "y")],
    "furnitureGroup": [("x", "y")],
    "label": [("x", "y")],
}
ANGLE_ATTRS = {
    "pieceOfFurniture": ("angle",),
    "furnitureGroup": ("angle",),
    "label": ("angle",),
    "room": ("areaAngle", "nameAngle"),
}
_TWO_PI = 2.0 * math.pi


def _home_xml(zf: zipfile.ZipFile, label: str) -> ET.Element:
    try:
        data = zf.read("Home.xml")
    except KeyError:
        raise SystemExit(
            f"{label} : aucune entree Home.xml dans ce .sh3d -- format inattendu "
            "(version de Sweet Home 3D tres ancienne ?), impossible de fusionner.")
    return ET.fromstring(data)


def _content_entries(zf: zipfile.ZipFile) -> set[str]:
    return {n for n in zf.namelist() if n not in SKIP_ENTRIES}


def _collect_content_refs(elem: ET.Element, known: set[str], found: set[str]) -> None:
    for e in elem.iter():
        for k, v in e.attrib.items():
            if k in CONTENT_ATTRS and v in known:
                found.add(v)


def _rewrite_content_refs(elem: ET.Element, prefix: str, known: set[str]) -> None:
    for e in elem.iter():
        for k, v in list(e.attrib.items()):
            if k in CONTENT_ATTRS and v in known:
                e.attrib[k] = f"{prefix}/{v}"


def _read_transform(fid: str) -> tuple[float, float, float]:
    """(angle_rad, x0_cm, y0_cm) depuis interieur/<fid>.transform.json --
    repli sur la transformation identite (0,0,0) si absent (cf. module
    docstring : compatibilite avec un fichier cree avant l'introduction du
    repere local)."""
    path = INT_DIR / f"{fid}.transform.json"
    if not path.is_file():
        return 0.0, 0.0, 0.0
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["angle_rad"], data["x0_cm"], data["y0_cm"]


def _apply_transform(children: list[ET.Element], transform: tuple[float, float, float]) -> None:
    """Applique en place, a tous les points/angles des sous-arbres retenus, la
    transformation repere local -> absolu inverse de
    interieur_init.py::_local_frame : absolute = R(angle) . (local + (x0,y0)).
    No-op pour la transformation identite (fichier sans .transform.json)."""
    angle, x0, y0 = transform
    if angle == 0.0 and x0 == 0.0 and y0 == 0.0:
        return
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def to_absolute(lx: float, ly: float) -> tuple[float, float]:
        x, y = lx + x0, ly + y0
        return x * cos_a - y * sin_a, x * sin_a + y * cos_a

    for child in children:
        for e in child.iter():
            if e.tag == "point":
                x, y = to_absolute(float(e.get("x")), float(e.get("y")))
                e.set("x", f"{x:.2f}")
                e.set("y", f"{y:.2f}")
                continue
            for ax, ay in POINT_ATTR_PAIRS.get(e.tag, []):
                x, y = to_absolute(float(e.get(ax)), float(e.get(ay)))
                e.set(ax, f"{x:.2f}")
                e.set(ay, f"{y:.2f}")
            for aa in ANGLE_ATTRS.get(e.tag, []):
                if e.get(aa) is None:
                    continue
                e.set(aa, f"{(float(e.get(aa)) + angle) % _TWO_PI:.7f}")


def _remap_ids(children: list[ET.Element]) -> None:
    """Reassigne un id frais a CHAQUE element id= des sous-arbres retenus (pas
    seulement les niveaux) et met a jour les references croisees connues
    (wallAtStart/wallAtEnd) en consequence. Necessaire meme si les ids sources
    sont des UUID a priori uniques : un fichier interieur/*.sh3d duplique a la
    main (copie du fichier lui-meme) pour amorcer un 2e batiment reproduirait
    des ids identiques -- sans ce remap, deux <room>/<wall> de fichiers source
    differents pourraient collisionner sur le meme id dans le Home.xml fusionne,
    ce qui casserait la resolution de wallAtStart/wallAtEnd par HomeXMLHandler."""
    id_map: dict[str, str] = {}
    for child in children:
        for e in child.iter():
            old = e.get("id")
            if old is not None:
                id_map[old] = sh3d_xml.uid(e.tag)
    for child in children:
        for e in child.iter():
            old = e.get("id")
            if old in id_map:
                e.set("id", id_map[old])
            for attr in WALL_REF_ATTRS:
                ref = e.get(attr)
                if ref in id_map:
                    e.set(attr, id_map[ref])


def _merge_one(path: Path, ext_root: ET.Element, next_index: int,
                out_entries: dict[str, bytes]) -> tuple[int, int, int]:
    """Fusionne un interieur/<fid>.sh3d dans ext_root (in place). Renvoie
    (niveaux ajoutes, elements ajoutes, next_index mis a jour)."""
    fid = path.stem
    transform = _read_transform(fid)
    with zipfile.ZipFile(path) as zf:
        root = _home_xml(zf, path.name)
        known_content = _content_entries(zf)
        levels = root.findall("level")
        solo_level_id = levels[0].get("id") if len(levels) == 1 else None

        level_id_map: dict[str, str] = {}
        added_levels = 0
        for lvl in levels:
            new_id = sh3d_xml.uid("level")
            level_id_map[lvl.get("id")] = new_id
            new_lvl = ET.Element("level", dict(lvl.attrib))
            new_lvl.set("id", new_id)
            new_lvl.set("elevationIndex", str(next_index))
            ext_root.append(new_lvl)
            next_index += 1
            added_levels += 1

        all_scoped = [c for c in list(root) if c.tag in LEVEL_SCOPED_TAGS]
        guide_skipped = sum(1 for c in all_scoped
                             if c.tag == "room" and c.get("name") == sh3d_xml.GUIDE_ROOM_NAME)
        retained = [c for c in all_scoped
                    if not (c.tag == "room" and c.get("name") == sh3d_xml.GUIDE_ROOM_NAME)]
        if guide_skipped:
            print(f"  {path.name} : {guide_skipped} piece-repere (calque) exclue(s) de la fusion")
        _apply_transform(retained, transform)
        _remap_ids(retained)

        added_items = 0
        for child in retained:
            lvl_id = child.get("level") or solo_level_id
            if lvl_id is None or lvl_id not in level_id_map:
                print(f"  {path.name} : <{child.tag}> sans niveau resoluble -> ignore")
                continue
            refs: set[str] = set()
            _collect_content_refs(child, known_content, refs)
            if refs:
                prefix = f"int_{fid}"
                for name in refs:
                    out_entries[f"{prefix}/{name}"] = zf.read(name)
                _rewrite_content_refs(child, prefix, known_content)
            child.set("level", level_id_map[lvl_id])
            ext_root.append(child)
            added_items += 1

    return added_levels, added_items, next_index


def main() -> None:
    if not SH3D.exists():
        raise SystemExit(f"{SH3D.name} introuvable -> lancer build_home.py d'abord.")
    interior_files = sorted(INT_DIR.glob("*.sh3d")) if INT_DIR.is_dir() else []
    if not interior_files:
        raise SystemExit(
            f"aucun {INT_DIR.name}/*.sh3d trouve -> lancer interieur_init.py puis "
            "editer au moins un batiment dans l'appli Sweet Home 3D native avant de fusionner.")

    with zipfile.ZipFile(SH3D) as ext_zip:
        ext_root = _home_xml(ext_zip, SH3D.name)
        ext_entries = {n: ext_zip.read(n) for n in ext_zip.namelist() if n not in SKIP_ENTRIES}

    next_index = max((int(l.get("elevationIndex", 0)) for l in ext_root.findall("level")),
                      default=-1) + 1
    out_entries: dict[str, bytes] = {}
    total_levels = total_items = 0
    for path in interior_files:
        n_levels, n_items, next_index = _merge_one(path, ext_root, next_index, out_entries)
        total_levels += n_levels
        total_items += n_items
        print(f"  {path.name} : {n_levels} niveau(x), {n_items} element(s)")

    if total_items == 0:
        raise SystemExit("aucun element interieur exploitable (fichiers non edites ?) -> rien a fusionner.")

    home_xml = "<?xml version='1.0'?>\n" + ET.tostring(ext_root, encoding="unicode")

    raw = cg.DATA / "_fusion_interieur_raw.zip"
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in ext_entries.items():
            z.writestr(name, data)
        for name, data in out_entries.items():
            z.writestr(name, data)
        z.writestr("Home.xml", home_xml)
    if OUT_SH3D.exists():
        shutil.copy2(OUT_SH3D, OUT_SH3D.with_suffix(".sh3d.bak"))
    try:
        sh3d_xml.convert_to_sh3d(raw, OUT_SH3D)
    finally:
        raw.unlink(missing_ok=True)

    print(f">>> {OUT_SH3D.name} : {total_levels} niveau(x) et {total_items} element(s) "
          f"interieur(s) fusionnes depuis {len(interior_files)} fichier(s). "
          f"{SH3D.name} n'est pas modifie.")


if __name__ == "__main__":
    main()
