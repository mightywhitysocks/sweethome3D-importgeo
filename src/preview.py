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
from PIL import Image
from shapely.geometry import LineString, MultiPoint, Point

import sitegeo as cg

CAM_UP_CM = 250.0            # camera au-dessus du sol (vue "1er etage", moins rasante)

# FOV : `fieldOfView` est transmis et applique TEL QUEL par le renderer --
# convention pinhole standard, verifie deux fois independamment :
#  1. Decompilation bytecode (CFR) du PhotoRenderer.class et YafarayRenderer.class
#     REELLEMENT charges par ce pipeline (pas un mirror externe) : les deux
#     utilisent `camera.getFieldOfView()` directement (radians), aucune
#     transformation intermediaire. `org.sunflow.core.camera.PinholeLens`
#     (jar reellement charge) : `au = tan(toRadians(fov)/2)`, la formule
#     manuel du moteur.
#  2. Mesure directe sur un rendu reel : un cube de largeur angulaire connue
#     (geometrie de la scene, calculee depuis la position camera) mesure a
#     206 px sur 1024 -- 219 px predits avec le FOV transmis tel quel,
#     876 px predits si un facteur cache de x4 s'appliquait. Aucune ambiguite.
# Une session anterieure avait pose l'inverse (un facteur ~x4 mesure par
# angle des sommets d'un batiment reel) et ne l'avait jamais redemontre --
# cette mesure s'est revelee fausse (methode ou distance/reference erronee,
# jamais identifie precisement) et etait reutilisee sans verification dans
# tout le fichier (`DEFAULT_FOV * 4` transmis a chaque rendu). Corrige ici.
#
# Corollaire toujours valide en soi (teste independamment, fov transmis
# directement, pas lie au x4 ci-dessus) : `fieldOfView` > pi fait basculer
# `tan(fov/2)` en negatif et retourne l'image (haut/bas inverses). Sans
# objet en pratique aux valeurs utilisees ici (~0.5 rad, tres loin de pi) --
# a garder en tete seulement si `DEFAULT_FOV`/`ENSEMBLE_FOV` sont un jour
# significativement agrandis.
DEFAULT_FOV = 2.0             # rad (~114.6 deg, grand angle), transmis et applique tel
                               # quel. Choisi empiriquement une fois le FOV_RENDER_
                               # CORRECTION corrige : le site de test reel (proprietes
                               # + batiments) a un rayon ~28 m, et _terrain_max_standoff
                               # (45% du plus petit cote du terrain modelise) plafonne le
                               # recul bien avant qu'un FOV etroit (~29 deg) puisse cadrer
                               # pile -- il faut un grand angle pour rester dans l'emprise
                               # du terrain sans rogner le sujet. 2.0 rad reste "libre"
                               # (distance de cadrage sous le plafond terrain) sur le site
                               # de test, avec de la marge -- meme valeur reelle que
                               # l'ancien bug transmettait par accident, donc memes rendus
                               # deja valides visuellement (PR #61), desormais delibere et
                               # correctement documente plutot qu'un sous-produit d'un
                               # calcul errone.
MARGIN_FACTOR = 1.35         # standoff = distance de cadrage pile x1.35 -> un peu d'air
MIN_STANDOFF_CM = 300.0      # jamais a moins de 3 m, meme d'un cabanon minuscule
# Pas de plafond de standoff fixe : cf. _terrain_max_standoff (la distance de
# cadrage varie avec la taille du sujet, un plafond en dur serait soit trop
# court sur un grand site, soit pousserait la camera hors de l'emprise
# modelisee sur un petit site).
STANDOFF_STEP_CM = 300.0     # pas de repli "reculer encore" si tous les angles restent bloques
HEIGHT_DEFAULT_M = 6.0       # repli si `hauteur` BD TOPO est null (maison R+1 + toiture)
ANGLE_STEP_DEG = 15.0        # pas de balayage angulaire (~24 candidats sur 360 deg)
SIGHT_INSET = 0.8            # rayons "d'epaule" testes en plus du centre (silhouette approx.)
PITCH_MIN, PITCH_MAX = -0.35, 0.75

ENSEMBLE_MARGIN = 1.6        # vue d'ensemble : plus d'air (montrer le terrain autour)
ENSEMBLE_PITCH = 0.75        # rad (~43 deg), entre observerCamera(0.135) et topCamera(0.945)
ENSEMBLE_FOV = DEFAULT_FOV   # meme FOV reel que les autres vues, pas de raison de varier
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

# Bandes d'azimut suspectes (repere plan SH3D, yaw=0 = direction +Y/sud->nord) :
# mesurees empiriquement sur UNE scene synthetique de test (gizmo d'axes colore
# + cube 6 couleurs, sol repere par coordonnees -- cf. issue #65) a une seule
# configuration camera (distance 2500 cm, pitch 0.5 rad, FOV 2.0 rad, cible a
# l'origine). PAS une constante universelle du bug directionnel SunFlow/
# YafaRay (docs/PIPELINE.md #12) : sur le site de test reel, un balayage
# complet des azimuts a distance/pitch/FOV differents (cf. commentaire dans
# _viewpoints ci-dessous) ne reproduit PAS ces bandes. La DISTANCE seule est
# ecartee comme cause de cet ecart : balayage synthetique dedie (5 distances,
# 800 a 8000 cm -- facteur x10 -- pitch/FOV fixes a la config de reference),
# motif de visibilite par azimut IDENTIQUE bit a bit aux 5 distances (cf.
# issue #65, mise a jour distance). Reste donc du FOV/pitch/geometrie
# (non isoles individuellement) pour expliquer l'ecart site reel/synthetique.
# Utilisee ICI uniquement comme PREFERENCE FAIBLE
# (tie-break entre angles par ailleurs equivalents, cf. _camera_for_building)
# -- jamais comme exclusion dure. `_looks_degraded` reste seul juge apres
# rendu, quel que soit l'angle choisi : ne jamais faire confiance a ces
# bandes seules pour decider qu'une vue est bonne.
SUSPECT_YAW_BANDS_DEG = [(41.5, 138.5), (221.5, 321.5)]

# Repli en yaw sur rendu degrade (cf. main()) : la distance et la taille de
# l'objet vise sont ecartees comme facteurs (issue #65, testees x10/x16 sans
# effet) -- seul un changement d'azimut est donc tente ici plutot que de
# reculer/rapprocher/elargir le FOV, qui degraderaient le cadrage voulu sans
# raison de corriger le bug. Portee bornee (pas un balayage 360 deg complet,
# cf. _offset_sweep utilise ailleurs pour ca) : chaque palier ajoute un rendu
# SunFlow/YafaRay complet, cout non negligeable en CI. +/-30 deg (2 pas de
# ANGLE_STEP_DEG) est un compromis cout/couverture choisi arbitrairement --
# PAS valide sur un cas reel degrade (le bug ne s'est plus reproduit sur le
# site de test depuis la correction du FOV, cf. docs/PIPELINE.md #12) : les
# bandes mortes mesurees sur la scene synthetique dediee font ~100 deg de
# large, un azimut au milieu d'une bande aussi large resterait hors de portee
# de ce repli. A elargir si un site futur retombe reellement dans une bande
# et que ce repli s'avere insuffisant en pratique.
DEGRADED_RETRY_MAX_OFFSET_DEG = 30.0


def _offset_sweep(step_deg, max_deg):
    """Deplacements angulaires (rad), pas croissants alternes +/- : 0, +step,
    -step, +2*step, -2*step, ... jusqu'a +/-max_deg inclus. Partage entre le
    balayage d'obstruction (_camera_for_building, max_deg=180 = tour complet)
    et le repli en yaw sur rendu degrade (cf. DEGRADED_RETRY_MAX_OFFSET_DEG,
    max_deg borne pour rester bon marche en rendu)."""
    step = math.radians(step_deg)
    max_rad = math.radians(max_deg)
    offsets = [0.0]
    k = 1
    while k * step <= max_rad:
        offsets += [k * step, -k * step]
        k += 1
    return offsets


def _yaw_in_suspect_band(yaw) -> bool:
    """Vrai si `yaw` (rad, repere plan SH3D) tombe dans une bande d'azimut
    suspecte (cf. SUSPECT_YAW_BANDS_DEG). Tie-break faible, pas une
    exclusion -- cf. docstring de la constante."""
    deg = math.degrees(yaw) % 360.0
    return any(lo <= deg <= hi for lo, hi in SUSPECT_YAW_BANDS_DEG)


def _terrain_max_standoff():
    """Distance de recul maximale sure : meme avec un FOV grand-angle
    (cf. DEFAULT_FOV ci-dessus), un site etendu ou un batiment haut peut
    demander une distance de cadrage qui depasse l'emprise du terrain
    modelise (`data/terrain_grid.npz`) -- une camera hors de cette zone n'a
    rien a montrer (extrapolation du MNT, generalement le vide/ciel).
    Plafonne a 45% de la plus petite dimension du terrain, pour rester loin
    des bords quelle que soit la direction de recul."""
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

    offsets = _offset_sweep(ANGLE_STEP_DEG, 180.0)

    # position caméra = cible - standoff*direction_visée (reculer dans le sens
    # OPPOSE a ce qu'on regarde) ; yaw transmis au renderer = direction_visee
    # telle quelle. Verifie par calcul direct (angle reel camera->cible vs yaw
    # stocke) : le pattern position=cible+standoff*dir / yaw=dir (utilise par
    # l'ancien code) fait regarder la camera a 180 deg de la cible -- jamais
    # detecte car aucun rendu bati* n'avait encore ete vu avant ce fix.
    #
    # Tri par (obstruction, bande d'azimut suspecte, |offset|) : l'obstruction
    # reste le critere dur (jamais sacrifie pour eviter une bande suspecte) ;
    # a obstruction egale, preference faible pour un azimut hors des bandes
    # mesurees (cf. SUSPECT_YAW_BANDS_DEG) ; a egalite sur les deux, le plus
    # proche de la direction naturelle. Ne pas s'arreter au premier n==0
    # trouve s'il tombe dans une bande suspecte -- un candidat n==0 hors
    # bande, teste plus loin dans le balayage, doit pouvoir le remplacer.
    best = None  # (n_bloques, bande_suspecte, |offset|, px, py, yaw)
    for off in offsets:
        yaw = base_yaw + off
        px, py = cx - standoff * math.sin(yaw), cy - standoff * math.cos(yaw)
        n = _blocked((px, py), (cx, cy), radius, obstacles, b["id"])
        suspect = _yaw_in_suspect_band(yaw)
        cand = (n, suspect, abs(off), px, py, yaw)
        if best is None or cand[:3] < best[:3]:
            best = cand
        if n == 0 and not suspect:
            break

    n, _, _, px, py, yaw = best
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
    return px, py, z, yaw, pitch, DEFAULT_FOV


def _ensemble_camera(props, prop, max_standoff, *, margin=ENSEMBLE_MARGIN,
                      pitch=ENSEMBLE_PITCH, yaw=0.0):
    """Vue d'ensemble : cadre le centre de bbox (pas le centroide -- robuste
    sur parcelle concave/en L) de l'union des empreintes batiments-propriete
    et du contour de la parcelle propriete, distance derivee du FOV comme
    pour les batiments -> s'adapte a la taille reelle du site. `max_standoff`
    cf. _terrain_max_standoff. `margin`/`pitch`/`yaw` parametrables (defaut =
    vue large validee) pour decliner plusieurs variantes depuis _viewpoints
    (distance/hauteur/angle differents) sans dupliquer ce calcul."""
    pts = [pt for b in props for ring in b["rings_cm"] for pt in ring]
    if prop:
        pts += [pt for ring in prop["rings_cm"] for pt in ring]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bx, by = (min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0
    radius = 0.5 * math.hypot(max(xs) - min(xs), max(ys) - min(ys))
    height = max((_height_cm(b) for b in props), default=HEIGHT_DEFAULT_M * 100.0)

    dist = _frame_distance(radius, height, ENSEMBLE_FOV, margin)
    dist = max(ENSEMBLE_MIN_DIST_CM, min(max_standoff, dist))
    back, up = dist * math.cos(pitch), dist * math.sin(pitch)

    # meme correction de signe que _camera_for_building : position = cible -
    # standoff*direction_visee (yaw=0.0 = direction +Y/sud -> camera reculee
    # au nord, regarde vers le sud/le centre).
    px, py = bx - back * math.sin(yaw), by - back * math.cos(yaw)
    z = cg.terrain_z_at(bx, by) + up
    return (px, py, z, yaw, pitch, ENSEMBLE_FOV)


# (label, margin, pitch, yaw voulu) pour chaque vue d'ensemble publiee --
# yaw=-pi/4 pour ensemble_laterale : donne un angle lateral/oblique distinct
# de ensemble_large (yaw=0) plutot qu'une raison de contourner un azimut
# degrade -- re-balaye apres la correction du FOV (grand-angle, cf.
# DEFAULT_FOV) sur le site de test : les 8 azimuts cardinaux/diagonaux
# (0/45/90/.../315 deg) rendent tous correctement (white_frac 0.26-0.53, bien
# sous le seuil `_looks_degraded`), y compris +pi/2 qui produisait une image
# quasi vide avant ce correctif.
VIEW_SPECS = [
    ("ensemble_large", ENSEMBLE_MARGIN, ENSEMBLE_PITCH, 0.0),
    ("ensemble_rapprochee", 1.15, 0.5, 0.0),
    ("ensemble_laterale", ENSEMBLE_MARGIN, ENSEMBLE_PITCH, -math.pi / 4.0),
]


def _viewpoints():
    """[(label, [(x, y, z, yaw, pitch[, fov]), ...]), ...] en repere plan SH3D
    (cm / rad) : pour chaque vue publiee, l'azimut voulu (VIEW_SPECS) suivi
    de candidats de repli en yaw (cf. DEGRADED_RETRY_MAX_OFFSET_DEG) --
    main() essaie chaque candidat dans l'ordre et garde le premier rendu non
    degrade.

    Vues d'ensemble uniquement (docs/PIPELINE.md #12) : les vues par batiment
    (_camera_for_building, conservee ci-dessus pour reference/reprise future,
    cf. meme logique que roof_lidar.py) visent geometriquement juste --
    verifie par calcul direct, yaw = azimut camera->cible a 0.0 deg pres sur
    plusieurs batiments -- mais le rendu SunFlow reste par endroits quasi vide
    (ciel/sol) sans obstacle ni relief pouvant l'expliquer, y compris a
    seulement 18 m d'un batiment volumineux (bug non identifie malgre
    investigation ciblee cette session). Seule la vue d'ensemble a ete
    validee fiable par rendu reel -> seules des variantes de cette meme vue
    (distance/hauteur/angle differents, cf. _ensemble_camera) sont publiees
    pour l'instant, jamais les vues par batiment. Le bug directionnel du
    renderer reste confirme independamment (scene synthetique, cf.
    docs/PIPELINE.md #12) -- il ne se manifeste simplement plus, sur CE site
    et a distance/pitch actuels, une fois le FOV reellement transmis large
    plutot qu'etroit. `_looks_degraded` + le repli en yaw ci-dessous restent
    donc geres comme un filet de securite (jamais retires), au cas ou un
    autre site/cadrage retombe dans une zone sensible -- cf. issue #65 : la
    distance et la taille de l'objet vise sont ecartees comme causes (aucun
    effet mesure), seul le FOV/pitch/yaw absolu de la camera compte, d'ou le
    choix de ne rejouer QUE le yaw en repli (les deux premiers sont fixes par
    le cadrage voulu, pas par ce bug)."""
    bat = json.loads((cg.DATA / "bati.json").read_text(encoding="utf-8"))["batiments"]
    props = [b for b in bat if b["classe"] == "propriete"]
    payload = json.loads((cg.DATA / "sh3d_payload.json").read_text(encoding="utf-8"))
    prop = next((p for p in payload["parcels"] if p["is_property"]), None)

    max_standoff = _terrain_max_standoff()
    if not props:
        return []
    retry_offsets = _offset_sweep(ANGLE_STEP_DEG, DEGRADED_RETRY_MAX_OFFSET_DEG)
    return [
        (label, [_ensemble_camera(props, prop, max_standoff, margin=margin,
                                   pitch=pitch, yaw=base_yaw + off)
                 for off in retry_offsets])
        for label, margin, pitch, base_yaw in VIEW_SPECS
    ]


EMPTY_WHITE_THRESHOLD = 235   # niveau de gris au-dela duquel un pixel compte "ciel"
EMPTY_WHITE_FRAC = 0.60       # fraction de pixels "ciel" au-dela de laquelle une vue
                              # est jugee degradee (cf. _looks_degraded)


def _looks_degraded(png_path) -> bool:
    """Heuristique bon marche pour ne jamais publier une vue rendue quasi
    vide par le bug directionnel SunFlow non resolu (docs/PIPELINE.md #12) :
    fraction de pixels quasi blancs (ciel). Calibree empiriquement sur des
    rendus reels de cette session (vue confirmee degradee ~0.65 de ciel,
    vues propres entre 0.42 et 0.55) -- pas un detecteur precis, un filtre
    pragmatique, necessaire depuis que la vue d'ensemble elle-meme s'est
    revelee touchee par ce bug selon l'angle (pas seulement les vues par
    batiment, cf. commentaire dans _viewpoints)."""
    im = np.array(Image.open(png_path).convert("RGB"))
    white_frac = float((im.mean(axis=2) > EMPTY_WHITE_THRESHOLD).mean())
    return white_frac > EMPTY_WHITE_FRAC


def main() -> None:
    w = int(sys.argv[1]) if len(sys.argv) > 1 else 1024
    h = int(sys.argv[2]) if len(sys.argv) > 2 else 640
    quality = sys.argv[3] if len(sys.argv) > 3 else "low"

    views = _viewpoints()
    if not views:
        raise SystemExit("aucun batiment 'propriete' dans data/bati.json ; lancer bati.py.")

    done = []
    for label, candidates in views:
        out_path = cg.VERIF / f"preview_{label}.png"
        out, unavailable, tried = None, False, 0
        for cam in candidates:
            tried += 1
            r = cg.render_photo(out_path, camera=cam, size=(w, h), quality=quality)
            if r is None:
                unavailable = True
                break
            if not _looks_degraded(r):
                out = r
                break
            r.unlink()
        if out:
            base_yaw, yaw = candidates[0][3], candidates[tried - 1][3]
            retry_note = "" if tried == 1 else f" (repli yaw {math.degrees(yaw - base_yaw):+.0f} deg, essai {tried}/{len(candidates)})"
            print(f"  {label:16} -> OK  {out.name}{retry_note}")
            done.append(out)
        elif unavailable:
            print(f"  {label:16} -> indisponible / echec")
        else:
            print(f"  {label:16} -> ecarte ({tried} azimuts testes, tous quasi vides -- bug directionnel connu)")
    print(f"\n>>> {len(done)}/{len(views)} apercus -> {cg.VERIF}")
    if not done:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
