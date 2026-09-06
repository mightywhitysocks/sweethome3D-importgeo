"""
interieur_init.py : bootstrap un projet .sh3d intérieur par bâtiment propriété
(un fichier par emprise/ring, dans interieur/ -- racine du dépôt, git-ignoré).

Étape HORS du pipeline principal : jamais dans le tableau `all` de
run.sh/run.ps1, jamais invoquée par generation.yml -- s'appelle explicitement
(`./run.sh interieur_init`), une fois après `bati.py`. Dépendances réelles :
data/meta.json (phase1_cadastre.py, pour le compass), data/bati.json et
data/bati_propriete_ref.json (bati.py) -- qui dépend lui-même de
data/terrain_grid.npz (terrain.py) via cg.terrain_z_at pour calculer
sol_max_cm. Séquence minimale :
`./run.sh phase1_cadastre terrain bati interieur_init`.

Chaque fichier interieur/<id>.sh3d reprend le MEME repère plan absolu (cm,
origine Lambert-93 du site) que Plan 3D.sh3d -- pas de repère local par
bâtiment : les murs dessinés à la main dans l'appli Sweet Home 3D native
atterrissent directement à la bonne position réelle, sans translation à la
fusion (cf. fusion_interieur.py). Chaque niveau porte un <room> "guide"
(contour exact de l'emprise extérieure du bâtiment, cf.
bati_propriete_ref.json) -- convention visuelle de calage, pas un verrou :
SH3D n'a pas de mécanisme de lock sur <room>, rien n'empêche l'utilisateur
de la modifier/supprimer par erreur.

Ne réécrit JAMAIS un interieur/<id>.sh3d déjà présent : c'est du travail
manuel utilisateur (édition dans l'appli native), même logique de prudence
que le reste du projet vis-à-vis des fichiers édités à la main. Relancer ce
script après un nouveau `bati.py` (nouveau bâtiment détecté, par exemple)
crée seulement les fichiers manquants, sans toucher aux existants.
"""
from __future__ import annotations

import json
import zipfile

import sh3d_xml
import sitegeo as cg

GEO = cg.GEO
OUT_DIR = cg.ROOT / "interieur"
STOREY_HEIGHT_CM = 270.0   # hauteur d'etage courante (pas de section config dediee : cf. CLAUDE.md)


def _cleabs_for(rid: str, i: int, n_polys: int) -> str:
    """Duplique volontairement roofer_roof.cleabs_for (suffixe uniquement si
    MultiPolygon) plutot que d'importer tout roofer_roof.py (pyvista + shapely,
    aucun autre besoin ici) pour une fonction pure d'une ligne. DOIT rester en
    synchro avec roofer_roof.cleabs_for et bati.py::_propriete_ref (meme id que
    bati_propriete_ref.json[footprints[].id])."""
    return rid if n_polys == 1 else f"{rid}_{i}"


def _etages_by_fid(bati: dict) -> dict[str, float | None]:
    """Reconstruit id-de-ring (fid) -> nombre d'etages BD TOPO, en rejouant EXACTEMENT
    la meme derivation d'id que bati.py::_propriete_ref (_cleabs_for sur
    b['id'][-4:], un par ring) -- bati.json ne porte 'etages' qu'au niveau du
    batiment entier, pas du ring individuel."""
    out: dict[str, float | None] = {}
    for b in bati["batiments"]:
        if b["classe"] != "propriete":
            continue
        n_rings = len(b["rings_cm"])
        for i in range(n_rings):
            fid = _cleabs_for(b["id"][-4:], i, n_rings)
            out[fid] = b["etages"]
    return out


def _home_xml(fid: str, ring_cm, n_etages: int, sol_max_cm: float) -> str:
    n_etages = max(1, int(n_etages or 1))
    cx = sum(x for x, _ in ring_cm) / len(ring_cm)
    cy = sum(y for _, y in ring_cm) / len(ring_cm)

    levels: dict[str, str] = {}
    levels_xml = []
    rooms_xml = []
    for i in range(n_etages):
        name = "RDC" if i == 0 else f"Etage {i}"
        level_id = sh3d_xml.uid("level")
        elevation = sol_max_cm + sh3d_xml.FOOTPRINT_CLEARANCE_CM + i * STOREY_HEIGHT_CM
        levels[name] = level_id
        levels_xml.append(sh3d_xml.level(level_id, name, elevation, i))
        rooms_xml.append(sh3d_xml.room(
            levels, name, "Repere exterieur - ne pas modifier", ring_cm,
            floor_color="00B0A48F"))

    head = (
        "<?xml version='1.0'?>\n"
        f"<home version='7400' name='{sh3d_xml.esc(fid)}.sh3d' camera='topCamera' "
        "wallHeight='250.0'>\n"
        "  <environment groundColor='FF8A9A5B' skyColor='FFB9D4E8' lightColor='00D0D0D0' "
        "ceillingLightColor='00D0D0D0' photoWidth='400' photoHeight='400' "
        "photoAspectRatio='SQUARE_RATIO' photoQuality='3' videoWidth='320' "
        "videoAspectRatio='RATIO_4_3' videoQuality='0' videoFrameRate='25'/>\n"
        f"{sh3d_xml.compass_tag()}\n"
        f"  <observerCamera attribute='observerCamera' lens='PINHOLE' x='{cx:.1f}' "
        f"y='{cy:.1f}' z='{sol_max_cm + cg.WALK_EYE_CM:.1f}' yaw='0.0' pitch='0.0' "
        "fieldOfView='1.0995575'/>\n"
        f"  <camera attribute='topCamera' lens='PINHOLE' x='{cx:.1f}' y='{cy:.1f}' "
        f"z='{sol_max_cm + 2000.0:.1f}' yaw='0.0' pitch='1.5' fieldOfView='1.0995575'/>\n"
    )
    return head + "\n".join(levels_xml) + "\n" + "\n".join(rooms_xml) + "\n</home>\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bati = json.loads((GEO / "bati.json").read_text(encoding="utf-8"))
    ref = json.loads((GEO / "bati_propriete_ref.json").read_text(encoding="utf-8"))
    footprint_cmds = [c for c in ref["commands"] if c["action"] == "create_room_polygon"]
    etages_by_fid = _etages_by_fid(bati)

    created, skipped = 0, 0
    for cmd, fp in zip(footprint_cmds, ref["footprints"]):
        fid = fp["id"]
        out = OUT_DIR / f"{fid}.sh3d"
        if out.exists():
            print(f"  interieur/{out.name} existe deja -> non touche")
            skipped += 1
            continue
        ring = [(pt["x"], pt["y"]) for pt in cmd["params"]["points"]]
        home_xml = _home_xml(fid, ring, etages_by_fid.get(fid) or 1, fp["sol_max_cm"])

        raw = OUT_DIR / f"_{fid}_raw.zip"
        with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Home.xml", home_xml)
        try:
            sh3d_xml.convert_to_sh3d(raw, out)
        finally:
            raw.unlink(missing_ok=True)
        print(f"  interieur/{out.name} cree ({int(etages_by_fid.get(fid) or 1)} niveau(x))")
        created += 1

    print(f">>> interieur_init : {created} cree(s), {skipped} deja present(s) et non touche(s).")
    if created:
        print("    Ouvrir dans l'appli Sweet Home 3D native pour dessiner murs/pieces/mobilier.")
        print("    Fusion ponctuelle dans Plan 3D.sh3d : ./run.sh fusion_interieur")


if __name__ == "__main__":
    main()
