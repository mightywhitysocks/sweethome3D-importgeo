# Image CI figee pour le pipeline de generation (phase1_cadastre -> ... ->
# build_home), publiee par .github/workflows/build-image.yml et consommee
# par .github/workflows/generation.yml. Image de base, telechargements
# binaires externes (roofer, Sweet Home 3D -- avec somme de controle) et
# dependances Python epingles par version (aucun "latest") ; versions
# harmonisees avec config/environment.yml / config/requirements-venv.txt --
# cf. CLAUDE.md section Environnement. Seuls les paquets `apt-get install`
# ci-dessous ne le sont pas (versions Debian `trixie`, susceptibles de
# deriver dans le temps au gre des mises a jour de securite) :
# reproductibilite partielle sur ce point precis, pas totale.
#
# Ne contient AUCUNE donnee de site : config/site.local.toml est ecrit par
# le workflow a partir d'un secret de repo, jamais bake ici.

FROM python:3.14.7-slim-trixie

# openjdk-21-jdk-headless et gdal-bin sont natifs sur trixie (absents sur
# bookworm, cf. recherches du plan) -- java/javac et gdal_contour deja sur
# le PATH apres cette etape, pas de JAVA_HOME a bricoler.
RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-21-jdk-headless \
        gdal-bin \
        curl \
        ca-certificates \
        gzip \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY config/requirements-venv.txt /app/config/requirements-venv.txt
RUN pip install --no-cache-dir -r /app/config/requirements-venv.txt

# roofer : binaire precompile officiel (pas de script curl|bash execute --
# cf. plan, revue securite). Contient son propre bin/ + share/proj + share/
# gdal (PROJ/GDAL statiquement lies) : on garde l'arborescence telle quelle
# et on ajoute bin/ au PATH, pas de copie isolee du seul binaire.
#
# CAUSE REELLE des echecs precedents (confirmee via diagnostic `curl -v` +
# capture d'exit code sur un run reel -- cf. historique PR) : le tar.gz
# officiel embarque `bin/roofer` en `-rw-r--r--` (pas executable), pas un
# probleme reseau -- `chmod +x` explicite apres extraction (le tar
# lui-meme se telecharge/extrait sans probleme, confirme sur ce run).
# Somme de controle calculee sur l'archive telle que publiee sur ce tag GitHub
# release (immutable) -- gzip -t seul valide l'integrite de l'archive, pas son
# contenu : un miroir compromis ou une attaque MITM servant un gzip valide
# mais altere passerait silencieusement sinon.
ARG ROOFER_SHA256=12096b4bc2f96d9134aba4b9a5d9268c06c69b873619a742b08c6f22ba2c2e99
RUN mkdir -p /opt/roofer \
    && curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
       "https://github.com/3DBAG/roofer/releases/download/v1.1.0-beta.1/roofer-linux-x86_64-v1.1.0-beta.1.tar.gz" \
       -o /tmp/roofer.tar.gz \
    && echo "${ROOFER_SHA256}  /tmp/roofer.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/roofer.tar.gz -C /opt/roofer \
    && rm /tmp/roofer.tar.gz \
    && chmod +x /opt/roofer/bin/roofer \
    && test -x /opt/roofer/bin/roofer
ENV PATH="/opt/roofer/bin:${PATH}"

# Sweet Home 3D : archive Linux officielle, chemin fixe reutilise par
# generation.yml pour ecrire [tools].sweethome3d_jar. `--strip-components=1`
# retire le dossier versionne (SweetHome3D-7.5/) du tgz -- le jar et les jars
# de rendu vivent ensuite dans lib/ (verifie sur l'archive reelle), PAS a la
# racine de l'archive.
#
# SourceForge (Cloudflare) bloque de facon persistante les telechargements
# automatises de ce fichier precis -- confirme sur plusieurs runs CI reels
# ET depuis une machine de dev separee (pas specifique aux IP GitHub
# Actions). Chaine de sources essayees dans l'ordre, la premiere qui rend
# un gzip VALIDE l'emporte (`-f` seul ne suffit pas : SourceForge peut
# repondre 200 avec une page HTML d'interstitiel a la place du binaire,
# `gzip -t` le detecte) :
#   1-4. quelques miroirs SourceForge directs (contournent le frontend
#        sourceforge.net/download, marchent peut-etre depuis d'autres IP
#        que celles testees ici) ;
#   5. repli fiable : copie miroir hebergee en asset de ce depot
#      (sweethome3d-mirror-7.5, verifiee identique octet pour octet a
#      l'archive officielle, redistribution GPL non modifiee -- cf.
#      NOTICE).
# Somme de controle unique pour les 5 miroirs : tous censes servir le meme
# fichier officiel SweetHome3D-7.5-linux-x64.tgz (le miroir 5, copie hebergee
# par ce depot, est verifie identique octet pour octet a l'archive officielle,
# cf. NOTICE) -- gzip -t seul (deja en place) ne detecte qu'un gzip invalide
# (page HTML d'interstitiel SourceForge), pas un contenu altere par un miroir
# compromis ou une attaque MITM.
ARG SH3D_SHA256=53487eed09650d5cd4310733e3ec80434633ed9df372793acd6fab2c319c2322
RUN mkdir -p /opt/sweethome3d \
    && ok=0 \
    && for u in \
         "https://sourceforge.net/projects/sweethome3d/files/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz/download" \
         "https://excellmedia.dl.sourceforge.net/project/sweethome3d/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz" \
         "https://netactuate.dl.sourceforge.net/project/sweethome3d/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz" \
         "https://deac-riga.dl.sourceforge.net/project/sweethome3d/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz" \
         "https://github.com/mightywhitysocks/sweethome3D-importgeo/releases/download/sweethome3d-mirror-7.5/sh3d.tgz" \
       ; do \
         echo "sh3d : essai $u"; \
         curl -fsSL --max-time 20 -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" "$u" -o /tmp/sh3d.tgz 2>/dev/null || { echo "  -> curl echoue"; continue; }; \
         gzip -t /tmp/sh3d.tgz 2>/dev/null || { echo "  -> pas un gzip valide (page HTML probable)"; continue; }; \
         echo "${SH3D_SHA256}  /tmp/sh3d.tgz" | sha256sum -c - 2>/dev/null || { echo "  -> gzip valide mais somme de controle incorrecte"; continue; }; \
         echo "  -> OK"; \
         ok=1; break; \
       done \
    && [ "$ok" -eq 1 ] \
    && tar -xzf /tmp/sh3d.tgz -C /opt/sweethome3d --strip-components=1 \
    && rm /tmp/sh3d.tgz \
    && test -f /opt/sweethome3d/lib/SweetHome3D.jar

# arbaro (variete des houppiers, issue #82) : pas de binaire officiel publie
# pour Linux (contrairement a roofer) -- construit depuis les sources
# (GPL-2, https://github.com/wdiestel/arbaro), appele en sous-processus CLI
# depuis src/arbaro_tree.py (aucun code copie/lie, meme principe que
# roofer). Integrite assuree par un COMMIT git fige (immutable, contrairement
# a un tag) verifie apres clone, plutot qu'une somme de controle sur une
# archive (aucune archive officielle equivalente n'existe pour ce depot).
# Paquet gui/ exclu de la compilation : inutile en CLI (javax.swing), meme
# choix que arbaro_cmd.jar officiel (cf. build.xml du depot). Etape non
# bloquante pour le reste de l'image : `arbaro_tree.find_arbaro_jar` renvoie
# None si ce jar est absent/invalide, `vegetation.py` se replie alors sur le
# gabarit d'arbre unique historique (cf. CLAUDE.md).
ARG ARBARO_COMMIT=e01a77657f8c831b1049f4b0ebb20f1fcb2f7c31
RUN git clone --quiet https://github.com/wdiestel/arbaro.git /tmp/arbaro-src \
    && cd /tmp/arbaro-src \
    && test "$(git rev-parse HEAD)" = "${ARBARO_COMMIT}" \
    && mkdir -p /tmp/arbaro-bin /opt/arbaro \
    && javac -d /tmp/arbaro-bin $(find src/net/sourceforge/arbaro -name "*.java" \
         ! -path "*/gui/*" ! -name "arbaro_gui.java") \
    && printf 'Main-Class: net.sourceforge.arbaro.arbaro\n' > /tmp/arbaro-manifest.txt \
    && jar cfm /opt/arbaro/arbaro_cmd.jar /tmp/arbaro-manifest.txt \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/arbaro.class \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/export \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/mesh \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/params \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/transformation \
         -C /tmp/arbaro-bin net/sourceforge/arbaro/tree \
    && rm -rf /tmp/arbaro-src /tmp/arbaro-bin /tmp/arbaro-manifest.txt \
    && test -f /opt/arbaro/arbaro_cmd.jar

WORKDIR /workspace
