"""
view_point_cloud.py : visualisation 3D interactive d'un nuage de points LiDAR
(.las/.laz), tel qu'il sort du LiDAR HD IGN, sans aucune reconstruction
geometrique.

Outil autonome, decouple du pipeline principal :
  - pas d'import de src/ (pas de `import sitegeo`)
  - pas de dependance a l'env conda `sitegeo`, a Java, ni a Sweet Home 3D
  - a installer dans un venv separe : pip install -r requirements.txt

Le fichier .las/.laz d'entree n'est PAS fourni : le nuage de points brut
(dalle 1 km x 1 km) se recupere via find_tile.py ou a la main sur la page du
jeu de donnees, puis se passe en argument ici. Rien de confidentiel
(emprise, coordonnees) ne doit etre code en dur dans ce script.

Usage :
    python view_point_cloud.py DALLE.laz -o apercu.html
    python view_point_cloud.py DALLE.laz --bbox E0 N0 E1 N1 -o parcelle.html
    python view_point_cloud.py DALLE.laz --classes 6 -o bati.html
    python view_point_cloud.py DALLE.laz --color-by height -o releve.html

Sortie : un .html autonome (plotly.js embarque), a ouvrir dans n'importe quel
navigateur -- aucune connexion reseau necessaire a l'ouverture.
"""
from __future__ import annotations

import argparse

import numpy as np
import plotly.graph_objects as go

# Classification IGN LiDAR HD (etend l'ASPRS standard) : code -> (libelle, couleur).
CLASSES = {
    1: ("non classe", "#999999"),
    2: ("sol", "#8B5A2B"),
    3: ("vegetation basse", "#A8D08D"),
    4: ("vegetation moyenne", "#548235"),
    5: ("vegetation haute", "#274E13"),
    6: ("bati", "#C0504D"),
    9: ("eau", "#4472C4"),
    17: ("pont", "#7F7F7F"),
    64: ("sursol perenne", "#BF9000"),
    65: ("artefact", "#FF00FF"),
    66: ("points virtuels", "#000000"),
}


def _load(path: str):
    import laspy

    las = laspy.read(path)
    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    z = np.asarray(las.z, dtype=np.float64)
    classification = np.asarray(las.classification, dtype=np.int32)
    rgb = None
    if all(dim in las.point_format.dimension_names for dim in ("red", "green", "blue")):
        r = np.asarray(las.red, dtype=np.float64)
        g = np.asarray(las.green, dtype=np.float64)
        b = np.asarray(las.blue, dtype=np.float64)
        scale = 255.0 / max(r.max(), g.max(), b.max(), 1.0)
        rgb = np.stack([r, g, b], axis=-1) * scale
    return x, y, z, classification, rgb


def _filter(x, y, z, classification, rgb, bbox, classes):
    mask = np.ones(x.shape, dtype=bool)
    if bbox is not None:
        e0, n0, e1, n1 = bbox
        mask &= (x >= e0) & (x <= e1) & (y >= n0) & (y <= n1)
    if classes:
        mask &= np.isin(classification, classes)
    idx = np.nonzero(mask)[0]
    rgb_f = rgb[idx] if rgb is not None else None
    return x[idx], y[idx], z[idx], classification[idx], rgb_f


def _subsample(n_points: int, max_points: int) -> np.ndarray:
    if n_points <= max_points:
        return np.arange(n_points)
    rng = np.random.default_rng(0)
    return rng.choice(n_points, size=max_points, replace=False)


def _traces(x, y, z, classification, rgb, color_by: str):
    if color_by == "rgb" and rgb is not None:
        colors = ["rgb({},{},{})".format(*p) for p in rgb.astype(int)]
        return [go.Scatter3d(x=x, y=y, z=z, mode="markers",
                             marker=dict(size=1.5, color=colors), name="nuage")]
    if color_by == "height":
        return [go.Scatter3d(x=x, y=y, z=z, mode="markers", name="altitude",
                             marker=dict(size=1.5, color=z, colorscale="Viridis",
                                        colorbar=dict(title="z (m)")))]
    # color_by == "classification" (defaut) : une trace par classe presente,
    # pour beneficier de la legende cliquable (isoler le bati d'un clic).
    traces = []
    for code in sorted(set(classification.tolist())):
        label, color = CLASSES.get(code, (f"classe {code}", "#333333"))
        sel = classification == code
        traces.append(go.Scatter3d(
            x=x[sel], y=y[sel], z=z[sel], mode="markers", name=label,
            marker=dict(size=1.5, color=color)))
    return traces


def build_figure(path: str, bbox=None, classes=None, color_by: str = "classification",
                 max_points: int = 300_000) -> go.Figure:
    x, y, z, classification, rgb = _load(path)
    x, y, z, classification, rgb = _filter(x, y, z, classification, rgb, bbox, classes)
    if x.size == 0:
        raise SystemExit("aucun point apres filtrage (bbox/classes) -- verifier l'emprise.")

    keep = _subsample(x.size, max_points)
    x, y, z = x[keep], y[keep], z[keep]
    classification = classification[keep]
    rgb = rgb[keep] if rgb is not None else None

    fig = go.Figure(data=_traces(x, y, z, classification, rgb, color_by))
    fig.update_layout(
        scene=dict(
            xaxis_title="Est (Lambert-93, m)", yaxis_title="Nord (Lambert-93, m)",
            zaxis_title="altitude NGF (m)", aspectmode="data",
        ),
        legend_title="classification LiDAR",
        margin=dict(l=0, r=0, t=30, b=0),
        title=f"{x.size} points affiches" + (f" / echantillonnes sur {keep.size}"
                                             if keep.size < x.size else ""),
    )
    return fig


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("laz", help="fichier .las/.laz (dalle LiDAR HD ou extrait)")
    p.add_argument("--bbox", nargs=4, type=float, metavar=("E0", "N0", "E1", "N1"),
                  help="emprise Lambert-93 (m) ; defaut : toute la dalle")
    p.add_argument("--classes", nargs="+", type=int,
                  help="codes de classification a garder (ex. 6 = bati)")
    p.add_argument("--color-by", choices=["classification", "height", "rgb"],
                  default="classification")
    p.add_argument("--max-points", type=int, default=300_000,
                  help="sous-echantillonnage aleatoire au-dela de ce nombre de points")
    p.add_argument("-o", "--out", default="apercu_lidar.html")
    args = p.parse_args()

    fig = build_figure(args.laz, bbox=args.bbox, classes=args.classes,
                       color_by=args.color_by, max_points=args.max_points)
    fig.write_html(args.out, include_plotlyjs=True, full_html=True)
    print(f">>> {args.out} (ouvrir dans un navigateur, aucune connexion requise)")


if __name__ == "__main__":
    main()
