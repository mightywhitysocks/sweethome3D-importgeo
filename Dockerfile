# Image CI figee pour le pipeline de generation (phase1_cadastre -> ... ->
# build_home), publiee par .github/workflows/build-image.yml et consommee
# par .github/workflows/generation.yml. Toutes les versions sont epinglees
# (aucun "latest") ; versions harmonisees avec config/environment.yml /
# config/requirements-venv.txt -- cf. CLAUDE.md section Environnement.
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
RUN mkdir -p /opt/roofer \
    && curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
       "https://github.com/3DBAG/roofer/releases/download/v1.1.0-beta.1/roofer-linux-x86_64-v1.1.0-beta.1.tar.gz" \
       -o /tmp/roofer.tar.gz \
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
         echo "  -> OK"; \
         ok=1; break; \
       done \
    && [ "$ok" -eq 1 ] \
    && tar -xzf /tmp/sh3d.tgz -C /opt/sweethome3d --strip-components=1 \
    && rm /tmp/sh3d.tgz \
    && test -f /opt/sweethome3d/lib/SweetHome3D.jar

WORKDIR /workspace
