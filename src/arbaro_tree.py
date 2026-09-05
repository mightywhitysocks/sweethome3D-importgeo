"""
arbaro_tree.py : houppiers varies par archetype de vegetation, generes par
l'outil externe `arbaro` (implementation Java -- GPL-2 -- de l'algorithme
Weber & Penn de generation procedurale d'arbres, https://github.com/wdiestel/
arbaro), appele en sous-processus CLI -- aucun code arbaro copie/lie, meme
esprit que `roofer_roof.py` (cf. CLAUDE.md "Dependance externe : roofer").

Contexte (issues #81/#82) : aucun pipeline open source ne va de "position +
hauteur (+ essence) detectee" jusqu'a un modele 3D OBJ variable exportable --
`arbaro` fournit l'algorithme et l'export OBJ, mais PAS de presets par
essence prets a l'emploi. Les 3 fichiers de parametres Weber & Penn
(`assets/arbaro_species/*.xml`) sont donc ecrits par ce projet (donnees
numeriques originales, PAS une copie des arbres de demonstration du depot
arbaro -- cf. NOTICE), pour 3 archetypes de silhouette :
  - conifere : houppier etroit et pointu (Shape=conical), feuillage sombre.
  - feuillu  : houppier large et arrondi (Shape=hemispherical), feuillage clair.
  - arbuste  : silhouette basse et dense (Shape=spherical), pour les detections
    de faible hauteur, pres du seuil H_ARBRE de `vegetation.py`.

Nombre de branches/segments REDUITS par rapport aux arbres de demonstration
du depot arbaro (ex. `trees/tamarack.xml`) : constate empiriquement dans
cette session -- un preset de demo standard (Levels=3, ~75x50 branches,
CurveRes=8) produit ~300 000 faces pour un seul arbre (29 Mo en OBJ), bien
trop lourd pour un objet repete plusieurs fois dans une scene SH3D (a
comparer aux ~5000 faces / 165 Ko du gabarit unique historique,
`assets/tree.obj`). Les presets de ce fichier (Levels=2, ~25-35 branches,
CurveRes=3, `--smooth 0.0`) visent le meme ordre de grandeur (~5000-6000
faces), verifie sur les 3 archetypes lors de cette session.

Pas de detection d'essence reelle (especes) : `_classify_essence` (cote
`vegetation.py`) est une heuristique grossiere a 2 indices (forme du houppier
depuis le MNH + teinte depuis l'ortho), suffisante pour choisir entre les 3
archetypes ci-dessus -- pas une identification botanique.

Chaque archetype est decline en `N_VARIANTS` graines (silhouettes legerement
differentes, memes parametres) pour eviter que tous les arbres d'un meme
archetype soient des clones identiques.

Sortie OBJ d'arbaro : groupes `trunk` / `stems_1` / `leaves` (`usemtl` du
meme nom), SANS `mtllib` (l'exporteur arbaro n'ecrit pas de .mtl) -- ce
module l'ajoute (`_mtl_text`, meme convention "100% mat" que le reste du
projet, cf. CLAUDE.md ".mtl 100% mat").

`prepare_species_models()` renvoie {} (jamais d'exception) si le binaire est
introuvable ou si tous les appels CLI echouent -- l'appelant (`vegetation.py`,
`build_home.py`) se replie alors entierement sur l'ancien gabarit unique
(`assets/tree.obj`, catalogId "OlaKristianHoff#tree"), jamais un pipeline
casse ni un rendu partiellement degrade.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import sitegeo as cg

SPECIES = ("conifere", "feuillu", "arbuste")
N_VARIANTS = 3
SEEDS = (11, 23, 47)                 # une graine par variante, memes pour toutes les especes
SMOOTH = 0.0                          # cf. module docstring : poids/faces au minimum
ARBARO_TIMEOUT_S = 120

CACHE_DIR = cg.DATA / "arbaro_cache"
SPECIES_DIR = cg.ASSETS / "arbaro_species"

# Couleurs par archetype (Kd), memes noms de groupe que ceux ecrits par
# l'exporteur OBJ d'arbaro (OBJExporter.java : "trunk", "stems_<n>", "leaves").
# Convention "100% mat" du projet : Ka 0, Ks 0, Ns 1, illum 1 (cf. CLAUDE.md).
_COLORS = {
    "conifere": {"trunk": (0.32, 0.23, 0.14), "stems_1": (0.32, 0.23, 0.14),
                 "leaves": (0.07, 0.20, 0.13)},
    "feuillu":  {"trunk": (0.45, 0.35, 0.22), "stems_1": (0.45, 0.35, 0.22),
                 "leaves": (0.24, 0.42, 0.11)},
    "arbuste":  {"trunk": (0.40, 0.30, 0.19), "stems_1": (0.40, 0.30, 0.19),
                 "leaves": (0.18, 0.36, 0.12)},
}


def find_arbaro_jar() -> Path | None:
    """Meme esprit que `roofer_roof.find_roofer_bin` : None si absent, jamais
    d'exception -- l'appelant decide du repli (gabarit unique historique).
    [tools].arbaro_jar (config/site.local.toml) prioritaire, sinon
    l'emplacement conventionnel documente dans le README (pas d'installeur
    officiel arbaro, contrairement a roofer -- a construire depuis les
    sources ou a recuperer depuis l'archive SourceForge, cf. README)."""
    if cg.ARBARO_JAR_CFG:
        p = Path(cg.ARBARO_JAR_CFG)
        return p if p.is_file() else None
    p = Path.home() / ".local" / "share" / "arbaro" / "arbaro_cmd.jar"
    return p if p.is_file() else None


def _mtl_text(species: str) -> str:
    lines = [f"# {species}.mtl -- genere par arbaro_tree.py (parametres du projet)"]
    for name, (r, g, b) in _COLORS[species].items():
        lines += [f"newmtl {name}", "illum 1", "Ka 0 0 0",
                  f"Kd {r} {g} {b}", "Ks 0 0 0", "Ns 1"]
    return "\n".join(lines) + "\n"


def _obj_bbox_cm(obj_text: str) -> tuple[float, float, float]:
    """(largeur, profondeur, hauteur) en cm depuis les lignes 'v x y z' (m,
    convention Y-up d'arbaro -- verifie dans cette session : meme convention
    que `assets/tree.obj`). Les unites natives d'arbaro (m) n'ont pas besoin
    d'etre converties en cm pour l'usage qu'en fait `vegetation.py` (rapport
    hauteur-cible/hauteur-native, cf. `_tree_cmds`) -- mais `build_home.py`
    exprime bien largeur/profondeur/hauteur en cm dans le XML SH3D, d'ou la
    conversion ici (x100), au meme titre que le gabarit historique."""
    x0 = x1 = y0 = y1 = z0 = z1 = None
    for line in obj_text.splitlines():
        if not line.startswith("v "):
            continue
        _, xs, ys, zs = line.split()
        x, y, z = float(xs), float(ys), float(zs)
        x0 = x if x0 is None else min(x0, x)
        x1 = x if x1 is None else max(x1, x)
        y0 = y if y0 is None else min(y0, y)
        y1 = y if y1 is None else max(y1, y)
        z0 = z if z0 is None else min(z0, z)
        z1 = z if z1 is None else max(z1, z)
    if x0 is None:
        raise ValueError("OBJ sans sommet 'v'")
    return (max(x1 - x0, 1e-3) * 100.0, max(z1 - z0, 1e-3) * 100.0,
            max(y1 - y0, 1e-3) * 100.0)


def _cache_key(species: str, seed: int, xml_bytes: bytes) -> str:
    """Cle de cache derivee du CONTENU du preset (pas seulement son nom) :
    contrairement au cache disque WFS/WMS (jamais invalide, cf. CLAUDE.md --
    justifie par le cout/quota reseau IGN), la generation arbaro est locale,
    deterministe et rapide -- rien ne justifie de s'exposer a un preset
    modifie mais un cache perime : un simple hash du fichier XML suffit a
    invalider automatiquement le cache si `assets/arbaro_species/*.xml`
    change, sans procedure manuelle."""
    h = hashlib.sha1(xml_bytes).hexdigest()[:12]
    return f"{species}_{seed}_{h}"


def _generate_one(jar: Path, species_xml: Path, seed: int, out_obj: Path, *, log) -> bool:
    cmd = ["java", "-jar", str(jar), "-qq", "-f", "OBJ", "--seed", str(seed),
           "--smooth", str(SMOOTH), "-o", str(out_obj), str(species_xml)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=ARBARO_TIMEOUT_S)
    except Exception as e:                                          # noqa: BLE001
        log(f"  vegetation arbaro : appel CLI echoue ({type(e).__name__}: {e})")
        return False
    if r.returncode != 0 or not out_obj.exists():
        log(f"  vegetation arbaro : code retour {r.returncode} pour {species_xml.name}"
            f" -> {r.stderr.strip()[-300:]}")
        return False
    return True


def prepare_species_models(*, log=print) -> dict[str, dict]:
    """Genere (ou reutilise le cache) les modeles OBJ/MTL de chaque archetype
    x variante. Renvoie {cle: {"obj": bytes, "mtl": bytes, "mtl_name": str,
    "w0"/"d0"/"h0": float (cm, dimensions natives du modele)}} -- {} si le
    binaire est introuvable ou si AUCUNE generation n'a reussi (repli complet
    sur l'ancien gabarit unique cote appelant, jamais un melange
    especes-generees/gabarit-historique au sein d'un meme run)."""
    jar = find_arbaro_jar()
    if jar is None:
        log("  vegetation arbaro : arbaro_cmd.jar introuvable -> gabarit unique historique")
        return {}
    if not SPECIES_DIR.is_dir():
        log(f"  vegetation arbaro : {SPECIES_DIR} absent -> gabarit unique historique")
        return {}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    models: dict[str, dict] = {}
    for species in SPECIES:
        species_xml = SPECIES_DIR / f"{species}.xml"
        if not species_xml.is_file():
            continue
        xml_bytes = species_xml.read_bytes()
        mtl_text = _mtl_text(species)
        for variant, seed in enumerate(SEEDS[:N_VARIANTS]):
            key = f"{species}_{variant}"
            cache_obj = CACHE_DIR / f"{_cache_key(species, seed, xml_bytes)}.obj"
            if not cache_obj.exists():
                tmp = cache_obj.with_suffix(".part")
                if not _generate_one(jar, species_xml, seed, tmp, log=log):
                    tmp.unlink(missing_ok=True)          # sortie partielle eventuelle
                    continue
                tmp.rename(cache_obj)
            obj_text = cache_obj.read_text(encoding="utf-8")
            try:
                w0, d0, h0 = _obj_bbox_cm(obj_text)
            except ValueError as e:
                log(f"  vegetation arbaro : {key} inexploitable ({e})")
                continue
            mtl_name = f"{species}.mtl"
            obj_bytes = (f"mtllib {mtl_name}\n" + obj_text).encode("utf-8")
            models[key] = {"obj": obj_bytes, "mtl": mtl_text.encode("utf-8"),
                           "mtl_name": mtl_name, "w0": w0, "d0": d0, "h0": h0}
    if not models:
        log("  vegetation arbaro : aucune generation exploitable -> gabarit unique historique")
    else:
        log(f"  vegetation arbaro : {len(models)} modele(s) espece x variante disponibles")
    return models
