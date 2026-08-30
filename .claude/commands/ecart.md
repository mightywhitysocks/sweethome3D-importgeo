---
description: Journalise, dans docs/PIPELINE.md, un écart assumé par rapport à une limite documentée du pipeline (ou une nouvelle limite non encore listée).
disable-model-invocation: true
---

Ce projet n'a pas de cahier des charges séparé — la référence est la
section `## Limitations connues` de `docs/PIPELINE.md` (11 points
numérotés à ce jour). Journaliser un écart consiste à maintenir 3
emplacements synchronisés dans ce seul fichier (au lieu de 4 fichiers
séparés, l'échelle du projet ne le justifie pas) :

1. Si l'écart correspond à une limite déjà listée (ex. le point 6, toits
   pyramidaux simples) : ajoute une ligne dans un tableau `## Écarts
   assumés` (à créer sous `## Limitations connues` s'il n'existe pas
   encore) avec les colonnes `# | Limite concernée | Contexte | Choix
   assumé`. Si c'est une limite nouvelle, pas encore dans la liste
   numérotée : ajoute-la d'abord à `## Limitations connues` (numéro
   suivant), puis référence ce numéro.
2. Ajoute un paragraphe court juste après le tableau expliquant *pourquoi*
   le comportement documenté ne convient pas dans ce cas précis et ce qui
   a été fait à la place.
3. Mets à jour le compte en tête de la section `## Écarts assumés` (ex.
   "3 écarts assumés à ce jour").

Vérifie toi-même, en te relisant, que les 3 emplacements restent cohérents
(pas de script dédié séparé pour ça, contrairement à un projet plus
gros). N'écris jamais de donnée confidentielle dans cette section — un
écart se décrit en termes de comportement du pipeline, jamais en citant la
commune, la section ou le numéro de parcelle concernés.
