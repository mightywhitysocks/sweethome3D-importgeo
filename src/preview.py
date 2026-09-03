"""
preview.py : apercus photo depuis les batiments de la propriete (post-build).

Rend `Plan 3D.sh3d` depuis plusieurs points de vue via le moteur SunFlow de Sweet
Home 3D (comme "Creer photo") : un apercu par batiment de la propriete + une vue
d'ensemble de la parcelle. Sorties : `data/verif/preview_*.png`.

Cadrage et angle calcules analytiquement (aucun reglage site par site,
le pipeline tourne sans supervision en CI) : la distance de camera derive du
champ de vision (formule standard de cadrage CG -- fit FOV/bounding box, cf.
Blender "Frame Selected" / Unity "fit to bounds" : distance = rayon /
tan(fov/2)), et l'angle de prise de vue est choisi par balayage autour du
batiment cible pour qu'aucun autre batiment (propriete OU voisinage) ne
bloque la ligne de vue -- un simple test d'intersection segment/polygone
(shapely), la brique standard pour ce genre de test de visibilite ; pas de
bibliotheque de "meilleur point de vue" (viewpoint entropy et consorts :
disproportionne, pense pour des scenes 3D denses avec rendu offscreen).

Optionnel : ne fait rien si le JDK ou les jars de rendu manquent
(cf. sitegeo.render_photo). Prerequis : le pipeline a tourne (`./run.sh`,
cf. CLAUDE.md section Environnement).

  python src/preview.py             # 1024x640, qualite rapide
  python src/preview.py 1280 800    # taille au choix
  python src/preview.py 1280 800 high
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np
from shapely.geometry import LineString, MultiPoint, Point

import sitegeo as cg

CAM_UP_CM = 250.0            # camera au-dessus du sol (vue "1er etage", moins rasante)

# Calibration empirique du FOV (rendu SunFlow reel, pas theorique -- la valeur
# documentee "1.0995575 rad ~ 63 deg" de RenderPhoto.java/home_template.xml ne
# correspond PAS au FOV reellement observe dans les rendus) :
#  1. le FOV reel applique par PhotoRenderer est ~4x plus etroit que le
#     parametre `fieldOfView` transmis -- mesure par angle exact des sommets
#     d'un batiment reel vu a deux distances/aspect ratios differents (~15.7
#     deg reel pour un parametre nominal de 63 deg, confirme lineaire : un
#     parametre 4x plus grand redonne un FOV ~4x plus large).
#  2. corollaire critique : `fieldOfView` > pi fait basculer `tan(fov/2)` en
#     negatif (fov/2 > 90 deg) -- confirme reproduire une image RETOURNEE
#     (haut/bas inverses) au rendu, quels que soient position/yaw/pitch. Donc
#     le FOV REEL praticable (apres le x4 du point 1) est structurellement
#     plafonne a environ pi/4 (~45 deg) pour rester strictement sous ce seuil,
#     et en pratique il faut rester notablement en dessous (distorsion
#     fisheye deja nette a fov transmis=3.0 rad, propre jusqu'a 2.0 teste) --
#     bien plus etroit que les 63 deg nominaux du template SH3D.
# Cause exacte non identifiee (SunFlow ou Camera SH3D, boite noire -- jar
# tiers, pas de source lisible ; peut-etre lie a
# `environment.photoWidth/Height=400x400` du template). Jamais teste au-dela
# d'un parametre transmis de 3.0 rad, ne pas extrapoler plus loin sans
# revalider par un rendu reel (cf. skill /ecart si ce plafond doit un jour
# etre documente comme limite connue du pipeline).
FOV_RENDER_CORRECTION = 4.0
DEFAULT_FOV = 0.5             # rad (~28.6 deg) REEL vise -- transmis x4 = 2.0 rad, deja
                               # valide sans distorsion ni inversion.
MARGIN_FACTOR = 1.35         # standoff = distance de cadrage pile x1.35 -> un peu d'air
MIN_STANDOFF_CM = 300.0      # jamais a moins de 3 m, meme d'un cabanon minuscule
# Pas de plafond de standoff fixe : cf. _terrain_max_standoff (le FOV reel etant
# etroit, un plafond en dur serait soit trop court sur un grand site, soit
# pousserait la camera hors de l'emprise modelisee sur un petit site).
STANDOFF_STEP_CM = 300.0     # pas de repli "reculer encore" si tous les angles restent bloques
HEIGHT_DEFAULT_M = 6.0       # repli si `hauteur` BD TOPO est null (maison R+1 + toiture)
ANGLE_STEP_DEG = 15.0        # pas de balayage angulaire (~24 candidats sur 360 deg)
SIGHT_INSET = 0.8            # rayons "d'epaule" testes en plus du centre (silhouette approx.)
PITCH_MIN, PITCH_MAX = -0.35, 0.75

ENSEMBLE_MARGIN = 1.6        # vue d'ensemble : plus d'air (montrer le terrain autour)
ENSEMBLE_PITCH = 0.75        # rad (~43 deg), entre observerCamera(0.135) et topCamera(0.945)
ENSEMBLE_FOV = DEFAULT_FOV   # meme plafond calibre -- pas de FOV plus large disponible
                              # (cf. corollaire ci-dessus, deja proche du plafond sur/pi)
ENSEMBLE_MIN_DIST_CM = 1500.0

# Repli defensif documente (docs/PIPELINE.md, limitation #12) : au-dela
# d'environ 20 m, certaines directions de visee produisent une image vide
# (ciel/sol seul) sans obstacle ni relief detectable sur le trajet -- cause
# non identifiee malgre une investigation ciblee (soleil, terrain, vegetation,
# obstacle voisin, winding du maillage, tous ecartes ; cf. `/ecart`). Plafond
# empirique choisi au milieu de la plage testee fiable (15-20 m) plutot que le
# cadrage "pile" theorique -- s'applique seulement aux vues par batiment (la
# vue d'ensemble, a distance/direction differentes, reste validee fiable).
RELIABLE_STANDOFF_CM = 1800.0


def _terrain_max_standoff():
    """Distance de recul maximale sure : le FOV reel praticable etant etroit
    (cf. FOV_RENDER_CORRECTION ci-dessus), les distances de cadrage calculees
    peuvent largement depasser l'emprise du terrain modelise (`data/terrain_
    grid.npz`) -- une camera hors de cette zone n'a rien a montrer (extrapolation
    du MNT, generalement le vide/ciel). Plafonne a 45% de la plus petite
    dimension du terrain, pour rester loin des bords quelle que soit la
    direction de recul."""
    d = np.load(cg.DATA / "terrain_grid.npz")
    w = float(d["x_cm"].max() - d["x_cm"].min())
    h = float(d["y_cm"].max() - d["y_cm"].min())
    return 0.45 * min(w, h)


def _hull(rings_cm):
    """Enveloppe convexe de tous les sommets, tous anneaux confondus -- couvre
    aussi bien un batiment multi-anneaux comme obstacle que comme cible, sans
    avoir a deviner si un 2e anneau est un trou ou un polygone separe."""
    pts = [pt for ring in rings_cm for pt in ring]
    if len(pts) < 3:
        return Point(pts[0]).buffer(1.0)
    return MultiPoint(pts).convex_hull


def _radius_cm(centroid, rings_cm):
    cx, cy = centroid
    return max((math.hypot(x - cx, y - cy) for ring in rings_cm for x, y in ring), default=0.0)


def _height_cm(b):
    h = b.get("hauteur")
    return (h if h else HEIGHT_DEFAULT_M) * 100.0


def _obstacles(bat):
    """{id: enveloppe convexe} pour TOUS les batiments (propriete + voisinage) --
    une camera doit eviter les emprises des deux, pas seulement de sa propre
    classe (un batiment voisin proche bloque tout autant la vue)."""
    return {b["id"]: _hull(b["rings_cm"]) for b in bat}


def _blocked(cam_xy, target_xy, radius_cm, obstacles, exclude_id):
    """Nombre de rayons (centre de la cible + 2 points d'epaule, silhouette
    approchee) bloques par un obstacle autre que la cible elle-meme -- test
    de visibilite standard (segment/polygone), pas juste "la camera est-elle
    dans un batiment" (une camera hors de tout batiment peut quand meme viser
    a travers un batiment plus loin sur la ligne de mire)."""
    cx, cy = cam_xy
    tx, ty = target_xy
    dx, dy = tx - cx, ty - cy
    d = math.hypot(dx, dy) or 1.0
    ux, uy = dx / d, dy / d
    px, py = -uy, ux
    pts = [(tx, ty),
           (tx + px * radius_cm * SIGHT_INSET, ty + py * radius_cm * SIGHT_INSET),
           (tx - px * radius_cm * SIGHT_INSET, ty - py * radius_cm * SIGHT_INSET)]
    obs = [poly for oid, poly in obstacles.items() if oid != exclude_id]
    return sum(any(poly.intersects(LineString([cam_xy, p])) for poly in obs) for p in pts)


def _frame_distance(radius_cm, height_cm, fov, margin):
    """Distance de camera pour cadrer un objet de rayon `radius_cm` (au sol) et
    de hauteur `height_cm`, formule standard de cadrage CG (Blender "Frame
    Selected" / Unity "fit to bounds") : distance = rayon / tan(fov/2).

    Le meme `fov` est applique sur les deux axes (pas de FOV horizontal
    derive de l'aspect ratio) : la convention verticale/horizontale exacte
    de `fieldOfView` cote SweetHome3D/SunFlow n'est pas documentee, et un
    premier essai avec un FOV horizontal elargi (aspect > 1) a produit des
    batiments debordant du cadre (distance sous-estimee) -- rester sur le
    FOV donne tel quel, sans l'elargir, est le choix conservateur qui ne
    peut que reculer un peu plus que necessaire sur le grand axe, jamais
    couper le sujet."""
    d_w = radius_cm / math.tan(fov / 2.0)
    d_h = (height_cm / 2.0) / math.tan(fov / 2.0)
    return max(d_w, d_h) * margin


def _pitch_for(z_cam, z_target_mid, dist_cm):
    """Pitch qui vise le milieu vertical du batiment (entre pied et faitage),
    a partir des altitudes REELLES (terrain_z_at) de la camera et de la
    cible -- pas juste de la hauteur du batiment sur un terrain suppose plat.
    Sur une courte distance l'ecart est negligeable, mais le denivele du
    terrain sur toute une parcelle (plusieurs metres, cf. terrain.py) fausse
    completement la visee quand la camera est reculee loin (cf. bug constate :
    des batiments proches du bord du terrain, camera reculee a 40+ m par le
    plafond de _terrain_max_standoff, ratee verticalement sans cette prise en
    compte). Convention de signe (assets/home_template.xml : topCamera
    pitch=0.945 = vue plongeante, observerCamera pitch=0.135 = quasi
    horizontale) : pitch positif = camera regarde vers le bas."""
    dz = z_target_mid - z_cam
    pitch = math.atan2(-dz, dist_cm)
    return max(PITCH_MIN, min(PITCH_MAX, pitch))


def _camera_for_building(b, tx, ty, obstacles, max_standoff):
    """Camera pour un batiment propriete : standoff derive du FOV (cadrage
    pile + marge), angle balaye autour de la direction "naturelle" (vers le
    centre de la parcelle, comme avant) jusqu'a trouver une ligne de vue
    degagee ; a defaut, garde le meilleur candidat et tente de reculer encore
    sur cet angle. Ne leve jamais d'exception, ne bloque jamais totalement.
    `max_standoff` (cf. _terrain_max_standoff) borne le recul a l'emprise du
    terrain modelise -- au-dela, quitte a etre plus zoome que la marge
    voulue, une camera hors de cette zone n'aurait rien a montrer."""
    cx, cy = b["centroid_cm"]
    radius = _radius_cm((cx, cy), b["rings_cm"])
    height = _height_cm(b)
    standoff = max(MIN_STANDOFF_CM, min(max_standoff,
                   _frame_distance(radius, height, DEFAULT_FOV, MARGIN_FACTOR)))
    base_yaw = math.atan2(tx - cx, ty - cy)

    step = math.radians(ANGLE_STEP_DEG)
    offsets = [0.0]
    k = 1
    while k * step <= math.pi:
        offsets += [k * step, -k * step]
        k += 1

    # position caméra = cible - standoff*direction_visée (reculer dans le sens
    # OPPOSE a ce qu'on regarde) ; yaw transmis au renderer = direction_visee
    # telle quelle. Verifie par calcul direct (angle reel camera->cible vs yaw
    # stocke) : le pattern position=cible+standoff*dir / yaw=dir (utilise par
    # l'ancien code) fait regarder la camera a 180 deg de la cible -- jamais
    # detecte car aucun rendu bati* n'avait encore ete vu avant ce fix.
    best = None  # (n_bloques, |offset|, px, py, yaw)
    for off in offsets:
        yaw = base_yaw + off
        px, py = cx - standoff * math.sin(yaw), cy - standoff * math.cos(yaw)
        n = _blocked((px, py), (cx, cy), radius, obstacles, b["id"])
        cand = (n, abs(off), px, py, yaw)
        if best is None or cand[:2] < best[:2]:
            best = cand
        if n == 0:
            break

    n, _, px, py, yaw = best
    dist = standoff  # distance REELLEMENT utilisee (peut grandir ci-dessous) ; le
                      # pitch doit etre recalcule pour cette distance finale, pas
                      # le standoff initial -- sinon (bug constate) une camera
                      # repoussee tres loin par le repli garde un pitch calibre
                      # pour une distance bien plus courte et rate le batiment
                      # (vise une hauteur qui n'a plus rien a voir).
    if n > 0:
        extra = standoff
        while n > 0 and extra < max_standoff:
            extra += STANDOFF_STEP_CM
            px2, py2 = cx - extra * math.sin(yaw), cy - extra * math.cos(yaw)
            n2 = _blocked((px2, py2), (cx, cy), radius, obstacles, b["id"])
            if n2 <= n:
                n, px, py, dist = n2, px2, py2, extra

    z = cg.terrain_z_at(px, py) + CAM_UP_CM
    z_target_mid = cg.terrain_z_at(cx, cy) + height / 2.0
    pitch = _pitch_for(z, z_target_mid, dist)
    return px, py, z, yaw, pitch, DEFAULT_FOV * FOV_RENDER_CORRECTION


def _ensemble_camera(props, prop, max_standoff):
    """Vue d'ensemble : cadre le centre de bbox (pas le centroide -- robuste
    sur parcelle concave/en L) de l'union des empreintes batiments-propriete
    et du contour de la parcelle propriete, distance derivee du FOV comme
    pour les batiments -> s'adapte a la taille reelle du site. `max_standoff`
    cf. _terrain_max_standoff."""
    pts = [pt for b in props for ring in b["rings_cm"] for pt in ring]
    if prop:
        pts += [pt for ring in prop["rings_cm"] for pt in ring]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bx, by = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    radius = 0.5 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    height = max((_height_cm(b) for b in props), default=HEIGHT_DEFAULT_M * 100.0)

    dist = _frame_distance(radius, height, ENSEMBLE_FOV, ENSEMBLE_MARGIN)
    dist = max(ENSEMBLE_MIN_DIST_CM, min(max_standoff, dist))
    back, up = dist * math.cos(ENSEMBLE_PITCH), dist * math.sin(ENSEMBLE_PITCH)

    # meme correction de signe que _camera_for_building : position = cible -
    # standoff*direction_visee (yaw=0.0 = direction +Y/sud -> camera reculee
    # au nord, regarde vers le sud/le centre).
    px, py = bx, by - back
    z = cg.terrain_z_at(bx, by) + up
    return (px, py, z, 0.0, ENSEMBLE_PITCH, ENSEMBLE_FOV * FOV_RENDER_CORRECTION)


def _viewpoints():
    """[(label, (x, y, z, yaw, pitch[, fov])), ...] en repere plan SH3D (cm / rad)."""
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)
    tx, ty = prop["centroid_cm"] if prop else (0.0, 0.0)

    obstacles = _obstacles(bat)
    max_standoff = _terrain_max_standoff()
    building_max_standoff = min(max_standoff, RELIABLE_STANDOFF_CM)

    views = []
    for i, b in enumerate(props):
        cam = _camera_for_building(b, tx, ty, obstacles, building_max_standoff)
        views.append((f"bati{i}_{b['id'][-4:]}", cam))
    if props:
        views.append(("ensemble", _ensemble_camera(props, prop, max_standoff)))
    return views


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    quality = sys.argv[3] if len(sys.argv) > 3 else "low"

    views = _viewpoints()
    if not views:
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json ; lancer bati.py.")

    done = []
    for label, cam in views:
        out = cg.render_photo(cg.VERIF / f"preview_{label}.png",
                              camera=cam, size=(w, h), quality=quality)
        print(f"  {label:16} -> {('OK  ' + out.name) if out else 'indisponible / echec'}")
        if out:
            done.append(out)
    print(f"\n>>> {len(done)}/{len(views)} apercus -> {cg.VERIF}")
    if not done:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
