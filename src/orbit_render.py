"""
orbit_render.py : animation video (tour a 360 deg autour de la parcelle),
option du job rendu (`.github/workflows/render.yml`, entree `animation`).
Reprend le meme moteur SunFlow que preview.py (post-build), jamais lance par
run.sh/run.ps1 (cout : un rendu SunFlow complet par image de la sequence,
significatif meme en qualite basse).

Cadrage : identique a preview.py::VIEW_SPECS[0] (`ensemble_large`, seule vue
validee fiable sur le site de test reel -- cf. docs/PIPELINE.md limitation
#12 et issue #65), en ne faisant tourner QUE le yaw autour de la parcelle
(preview._ensemble_camera, memes marge/pitch/FOV par defaut). Un tour complet
balaie necessairement tous les azimuts, y compris ceux ou le bug directionnel
documente en issue #65 peut degrader un rendu (disparition totale de l'objet
vise, boite noire SunFlow/YafaRay -- ni la distance camera-cible ni la taille
de l'objet n'ont d'effet, seul l'azimut/FOV/pitch absolu de la camera compte).

Mitigation, dans l'esprit du repli en yaw de preview.py mais adaptee a une
sequence (le nombre d'images et la duree doivent rester constants, un saut de
montage ou une image quasi vide seraient plus genants dans une boucle que
dans une vue isolee) : chaque image degradee tente d'abord le meme repli en
yaw que preview.py (`DEGRADED_RETRY_MAX_OFFSET_DEG`) ; si le repli echoue
aussi, l'image est remplacee par un GEL de la derniere image bonne (jamais
publiee telle quelle, jamais retiree de la sequence). Les toutes premieres
images (si degradees avant qu'aucune bonne image n'ait ete trouvee) sont
comblees a posteriori par la 1re bonne image de la sequence.

Assemblage en MP4 via `ffmpeg` (outil systeme, meme famille que la dependance
`xvfb` deja installee par le job rendu pour Java3D -- pas de nouvelle
dependance Python/pip).

  python src/orbit_render.py                  # 1024x640, qualite basse, 24 images (15 deg/image)
  python src/orbit_render.py 1280 800 low 36
"""
from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import preview
import sitegeo as cg

DEFAULT_FRAMES = 24   # 360/24 = 15 deg de pas, meme granularite que preview.ANGLE_STEP_DEG
FPS = 12               # boucle courte et fluide sans exiger un trop grand nombre de rendus


def _orbit_candidates(n_frames):
    """[[camera, ...], ...] : une liste par image de la sequence (yaw
    regulierement reparti sur 360 deg, memes marge/pitch/FOV par defaut que
    preview._ensemble_camera -- cadrage `ensemble_large`), chaque entree
    suivie de ses candidats de repli en yaw (cf. preview.DEGRADED_RETRY_MAX_
    OFFSET_DEG) -- meme structure que preview._viewpoints, une camera
    entierement recalculee par candidat plutot qu'un yaw retouche seul
    (la position depend elle aussi du yaw, cf. preview._ensemble_camera)."""
    props, prop = preview._props_and_parcel()
    if not props:
        return []
    max_standoff = preview._terrain_max_standoff()
    retry_offsets = preview._offset_sweep(preview.ANGLE_STEP_DEG,
                                           preview.DEGRADED_RETRY_MAX_OFFSET_DEG)
    step = 2.0 * math.pi / n_frames
    return [
        [preview._ensemble_camera(props, prop, max_standoff, yaw=i * step + off)
         for off in retry_offsets]
        for i in range(n_frames)
    ]


def _render_frame(candidates, out_path, size, quality):
    """Rend le 1er candidat non degrade (memes criteres que preview.main) sur
    `out_path` (ecrase a chaque essai). Renvoie (chemin, None) si une image
    exploitable a ete produite, (None, "indisponible") si le rendu lui-meme
    est indisponible (JDK/jars manquants -- inutile d'essayer les images
    suivantes), (None, "degrade") si tous les candidats sont quasi vides."""
    for cam in candidates:
        r = cg.render_photo(out_path, camera=cam, size=size, quality=quality)
        if r is None:
            return None, "indisponible"
        if not preview._looks_degraded(r):
            return r, None
    return None, "degrade"


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    quality = sys.argv[3] if len(sys.argv) > 3 else "low"
    n_frames = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_FRAMES

    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg introuvable sur le PATH -> animation ignoree.")

    frames = _orbit_candidates(n_frames)
    if not frames:
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json ; lancer bati.py.")

    out_mp4 = cg.VERIF / "orbit.mp4"
    with tempfile.TemporaryDirectory(prefix="orbit_") as tmp_str:
        tmp = Path(tmp_str)
        frame_paths = [None] * n_frames
        last_good = None
        frozen = 0
        for i, candidates in enumerate(frames):
            out_path = tmp / f"frame_{i:04d}.png"
            r, reason = _render_frame(candidates, out_path, (w, h), quality)
            if reason == "indisponible":
                raise SystemExit("rendu indisponible (JDK/jars de rendu manquants) -> animation abandonnee.")
            if r is not None:
                frame_paths[i] = out_path
                last_good = out_path
            elif last_good is not None:
                shutil.copyfile(last_good, out_path)
                frame_paths[i] = out_path
                frozen += 1
            # sinon (degrade, pas encore de bonne image) : comble plus bas

        if last_good is None:
            raise SystemExit(f"{n_frames} azimuts testes, tous quasi vides -- "
                              "bug directionnel connu (issue #65) ; aucune image exploitable.")

        first_good = next(p for p in frame_paths if p is not None)
        for i, p in enumerate(frame_paths):
            if p is None:
                dest = tmp / f"frame_{i:04d}.png"
                shutil.copyfile(first_good, dest)
                frame_paths[i] = dest
                frozen += 1

        cg.VERIF.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(tmp / "frame_%04d.png"),
               # dimensions paires exigees par yuv420p (libx264) -- au cas ou
               # largeur/hauteur impaires seraient passees en argument.
               "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("ffmpeg a echoue -> " + (r.stderr or r.stdout).strip()[:400])

    note = f" ({frozen} image(s) gelee(s) sur rendu degrade, cf. issue #65)" if frozen else ""
    print(f">>> {out_mp4} ({n_frames} images, {FPS} im/s){note}")


if __name__ == "__main__":
    main()
