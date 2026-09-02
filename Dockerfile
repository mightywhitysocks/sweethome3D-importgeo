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
#
# DIAGNOSTIC TEMPORAIRE (`set -x` + `curl -v`, pas de `set -e` autour du
# curl) : deux runs reels ont echoue ici en <1s, sans AUCUNE sortie curl
# malgre `-S`/`--retry-all-errors` (donc pas une histoire de code
# retryable) -- irreproductible en local (meme URL, memes flags,
# telechargement propre a chaque essai, y compris trace `-v` complete).
# Capture explicite du code retour + affichage AVANT tout `exit`, au cas ou
# le log perdrait la fin de sortie d'une etape qui echoue tres vite. A
# alleger une fois la cause confirmee sur un run reel.
RUN set -ux; \
    mkdir -p /opt/roofer; \
    curl -v -fL --retry 5 --retry-delay 5 --retry-all-errors \
      "https://github.com/3DBAG/roofer/releases/download/v1.1.0-beta.1/roofer-linux-x86_64-v1.1.0-beta.1.tar.gz" \
      -o /tmp/roofer.tar.gz; \
    curl_rc=$?; \
    echo "=== curl roofer exit code: $curl_rc ==="; \
    ls -la /tmp/roofer.tar.gz 2>&1 || echo "=== /tmp/roofer.tar.gz absent ==="; \
    [ "$curl_rc" -eq 0 ] || exit "$curl_rc"; \
    tar -xzf /tmp/roofer.tar.gz -C /opt/roofer; \
    rm /tmp/roofer.tar.gz; \
    test -x /opt/roofer/bin/roofer
ENV PATH="/opt/roofer/bin:${PATH}"

# Sweet Home 3D : archive Linux officielle SourceForge, chemin fixe reutilise
# par generation.yml pour ecrire [tools].sweethome3d_jar. `--strip-components=1`
# retire le dossier versionne (SweetHome3D-7.5/) du tgz -- le jar et les jars
# de rendu vivent ensuite dans lib/ (verifie sur l'archive reelle), PAS a la
# racine de l'archive. SourceForge peut repondre 403 (Cloudflare) a certains
# clients/IP sans user-agent de navigateur -- `-A` en best-effort ; si ca
# s'avere instable en pratique en CI, repli possible : heberger ce tgz en
# asset d'une release du depot plutot que sur SourceForge. Meme verbosite
# diagnostique temporaire que roofer ci-dessus.
RUN set -ux; \
    mkdir -p /opt/sweethome3d; \
    curl -v -fL --retry 5 --retry-delay 5 --retry-all-errors \
      -A "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36" \
      "https://sourceforge.net/projects/sweethome3d/files/SweetHome3D/SweetHome3D-7.5/SweetHome3D-7.5-linux-x64.tgz/download" \
      -o /tmp/sh3d.tgz; \
    curl_rc=$?; \
    echo "=== curl sweethome3d exit code: $curl_rc ==="; \
    ls -la /tmp/sh3d.tgz 2>&1 || echo "=== /tmp/sh3d.tgz absent ==="; \
    [ "$curl_rc" -eq 0 ] || exit "$curl_rc"; \
    tar -xzf /tmp/sh3d.tgz -C /opt/sweethome3d --strip-components=1; \
    rm /tmp/sh3d.tgz; \
    test -f /opt/sweethome3d/lib/SweetHome3D.jar

WORKDIR /workspace
