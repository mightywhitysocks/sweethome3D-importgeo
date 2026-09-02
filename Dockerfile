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
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY config/requirements-venv.txt /app/config/requirements-venv.txt
RUN pip install --no-cache-dir -r /app/config/requirements-venv.txt

# roofer : binaire precompile officiel (pas de script curl|bash execute --
# cf. plan, revue securite). Contient son propre bin/ + share/proj + share/
# gdal (PROJ/GDAL statiquement lies) : on garde l'arborescence telle quelle
# et on ajoute bin/ au PATH, pas de copie isolee du seul binaire.
RUN mkdir -p /opt/roofer \
    && curl -fsSL "https://github.com/3DBAG/roofer/releases/download/v1.1.0-beta.1/roofer-linux-x86_64-v1.1.0-beta.1.tar.gz" \
       -o /tmp/roofer.tar.gz \
    && tar -xzf /tmp/roofer.tar.gz -C /opt/roofer \
    && rm /tmp/roofer.tar.gz \
    && test -x /opt/roofer/bin/roofer
ENV PATH="/opt/roofer/bin:${PATH}"

# Sweet Home 3D : archive Linux officielle SourceForge, chemin fixe reutilise
# par generation.yml pour ecrire [tools].sweethome3d_jar. `--strip-components=1`
# retire le dossier versionne (SweetHome3D-7.5/) du tgz -- le jar et les jars
# de rendu vivent ensuite dans lib/ (verifie sur l'archive reelle), PAS a la
# racine de l'archive.
RUN mkdir -p /opt/sweethome3d \
    && curl -fsSL "https://sourceforge.net/projects/sweethome3d/files/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz/download" \
       -o /tmp/sh3d.tgz \
    && tar -xzf /tmp/sh3d.tgz -C /opt/sweethome3d --strip-components=1 \
    && rm /tmp/sh3d.tgz \
    && test -f /opt/sweethome3d/lib/SweetHome3D.jar

WORKDIR /workspace
