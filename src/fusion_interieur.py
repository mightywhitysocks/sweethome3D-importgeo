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
"""
from __future__ import annotations

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
SKIP_ENTRIES = {"Home.xml", "Home", "ContentDigests"}


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


def _merge_one(path: Path, ext_root: ET.Element, next_index: int,
                out_entries: dict[str, bytes]) -> tuple[int, int, int]:
    """Fusionne un interieur/<fid>.sh3d dans ext_root (in place). Renvoie
    (niveaux ajoutes, elements ajoutes, next_index mis a jour)."""
    fid = path.stem
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("Home.xml"))
        known_content = _content_entries(zf)
        levels = root.findall("level")
        solo_level_id = levels[0].get("id") if len(levels) == 1 else None

        id_map: dict[str, str] = {}
        added_levels = 0
        for lvl in levels:
            old_id = lvl.get("id")
            new_id = sh3d_xml.uid("level")
            id_map[old_id] = new_id
            new_lvl = ET.Element("level", dict(lvl.attrib))
            new_lvl.set("id", new_id)
            new_lvl.set("elevationIndex", str(next_index))
            ext_root.append(new_lvl)
            next_index += 1
            added_levels += 1

        added_items = 0
        for child in list(root):
            if child.tag not in LEVEL_SCOPED_TAGS:
                continue
            lvl_id = child.get("level") or solo_level_id
            if lvl_id is None or lvl_id not in id_map:
                print(f"  {path.name} : <{child.tag}> sans niveau resoluble -> ignore")
                continue
            refs: set[str] = set()
            _collect_content_refs(child, known_content, refs)
            if refs:
                prefix = f"int_{fid}"
                for name in refs:
                    out_entries[f"{prefix}/{name}"] = zf.read(name)
                _rewrite_content_refs(child, prefix, known_content)
            child.set("level", id_map[lvl_id])
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
        ext_root = ET.fromstring(ext_zip.read("Home.xml"))
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
    try:
        sh3d_xml.convert_to_sh3d(raw, OUT_SH3D)
    finally:
        raw.unlink(missing_ok=True)

    print(f">>> {OUT_SH3D.name} : {total_levels} niveau(x) et {total_items} element(s) "
          f"interieur(s) fusionnes depuis {len(interior_files)} fichier(s). "
          f"{SH3D.name} n'est pas modifie.")


if __name__ == "__main__":
    main()
