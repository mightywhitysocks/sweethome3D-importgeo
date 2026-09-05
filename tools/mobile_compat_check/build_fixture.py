"""
build_fixture.py : assemble `fixture.sh3d`, un plan Sweet Home 3D synthetique
(3 niveaux, un batiment, un furnitureGroup vegetation, une parcelle, une image
de fond), utilise pour verifier la compatibilite du format `.sh3d` avec le
moteur JS de l'appli mobile (cf. `tools/mobile_compat_check/README.md`).

Outil **autonome**, sans lien avec le pipeline principal (meme principe que
`tools/lidar_view/`) : aucun `import sitegeo`, aucune donnee geographique
reelle -- seulement des formes synthetiques (cube, pyramide) commitees dans
`fixture/`. Reutilise `java/Conv.java` du depot (meme brique que
`src/build_home.py` pour produire un `.sh3d` complet, entree `Home`
serialisee Java comprise -- le loader SH3D refuse un `.sh3d` XML seul).

Usage :
    python3 build_fixture.py --sh3d-jar /chemin/vers/SweetHome3D.jar [--out fixture.sh3d]

Le `.jar` n'est pas fourni par ce depot (cf. README de ce dossier pour
l'obtenir). Sortie ecrite a cote de ce script par defaut, jamais commitee.
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
FIXTURE_DIR = HERE / "fixture"
JAVA_SRC = REPO_ROOT / "java" / "Conv.java"
BUILD_DIR = HERE / "_build"

# PNG 8x8 uni (vert clair), sert de fond de niveau minimal -- evite toute
# dependance a PIL/Pillow dans cet outil autonome.
_BG_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAFUlEQVR4nGP4"
    "z8DwjwGKGdCEIBAAyx0EAT9BwSAAAAAASUVORK5CYII="
)


def _prepare_java(sh3d_jar: Path) -> tuple[Path, Path]:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    jar = BUILD_DIR / "SweetHome3D.jar"
    if not jar.exists() or jar.stat().st_size != sh3d_jar.stat().st_size:
        jar.write_bytes(sh3d_jar.read_bytes())
    cls = BUILD_DIR / "com" / "eteks" / "sweethome3d" / "io" / "Conv.class"
    if not cls.exists() or cls.stat().st_mtime < JAVA_SRC.stat().st_mtime:
        r = subprocess.run(
            ["javac", "-cp", str(jar), "-d", str(BUILD_DIR), str(JAVA_SRC)],
            capture_output=True, text=True,
        )
        if not cls.exists():
            print(r.stdout.strip() or r.stderr.strip()[:800], file=sys.stderr)
            raise SystemExit("javac a echoue (JDK sur le PATH ?)")
    return jar, BUILD_DIR


def build(sh3d_jar: Path, out: Path) -> None:
    raw = BUILD_DIR / "_fixture_raw.zip"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(FIXTURE_DIR / "home_fixture.xml", "Home.xml")
        z.writestr("bg", base64.b64decode(_BG_PNG_B64))
        z.write(FIXTURE_DIR / "cube.obj", "cube/cube.obj")
        z.write(FIXTURE_DIR / "cube.mtl", "cube/cube.mtl")
        z.write(FIXTURE_DIR / "pyramid.obj", "pyramid/pyramid.obj")
        z.write(FIXTURE_DIR / "pyramid.mtl", "pyramid/pyramid.mtl")
        ico = io.BytesIO()
        ico.write(base64.b64decode(_BG_PNG_B64))
        z.writestr("ico", ico.getvalue())

    jar, jconv = _prepare_java(sh3d_jar)
    r = subprocess.run(
        ["java", "-cp", f"{jar}{os.pathsep}{jconv}",
         "com.eteks.sweethome3d.io.Conv", str(raw), str(out)],
        capture_output=True, text=True,
    )
    print(r.stdout.strip() or r.stderr.strip()[:800])
    raw.unlink(missing_ok=True)
    if r.returncode != 0 or not out.exists():
        raise SystemExit("echec de la conversion Java (voir ci-dessus)")
    print(f">>> {out}  ({out.stat().st_size} o)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sh3d-jar", required=True, type=Path,
                    help="chemin vers SweetHome3D.jar (cf. README de ce dossier)")
    p.add_argument("--out", type=Path, default=HERE / "_build" / "fixture.sh3d")
    args = p.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    build(args.sh3d_jar, args.out)


if __name__ == "__main__":
    main()
