# Documents

Les fiches d'objets de la maison (marque, modèle, numéro de série, garantie, entretien, pièces)
et les documents qui vont avec : notices, contrats, garanties, factures, courriels. L'accueil
montre les entretiens dus et les derniers documents ; l'assistant y cherche une réponse et cite
sa source et sa page.

## Faire entrer un document

- **Par la boîte d'entrée** : un courriel (`.eml`), une note (`.md`, `.txt`) déposé à la racine
  de `inbox/` part tout seul dans `inbox/documents/`. Un PDF ou une photo se dépose directement
  dans `inbox/documents/` (la finance réclame les PDF de la racine : relevés, rapports).
- Le fichier est archivé chiffré, son texte indexé, puis il quitte la boîte d'entrée. Le même
  fichier reçu deux fois n'en fait qu'un.
- Un document reçu est **privé** : seuls les propriétaires le lisent. Le marquer « foyer » (une
  carte, réversible d'un geste) le rend lisible par l'assistant pour tout le foyer.

## Ce qui passe par une carte

| Geste | Qui le propose |
|---|---|
| créer ou compléter une fiche d'objet | l'app, ou l'assistant (`documents_propose_card`) |
| marquer un document « foyer », ou le rendre privé | l'app seule ; réversible |
| lier un document à une écriture de la finance (facture, garantie) | `core/link`, comme tout lien |

## Reprise de la bibliothèque de Domia (une fois)

La bibliothèque de l'assistant (`~/Domia/Bibliothèque/` : une fiche YAML par objet et ses
documents à côté) entre dans le hub une fois, puis l'assistant ne la lit plus :

```sh
# sur le Mac, le dossier monté en lecture seule dans un conteneur jetable
docker compose --project-directory deploy -f deploy/compose.yaml --env-file deploy/.env \
  run --rm --no-deps -v "$HOME/Domia/Bibliothèque:/import:ro" api hub documents import-library /import
```

Les fiches gardent leurs champs connus (un champ inconnu est compté, pas repris) ; les documents
sont marqués « foyer » (tout le foyer les lisait déjà) et rattachés à leur fiche (liste
`documents` de la fiche, ou dossier au nom de la fiche). Le dossier `à-trier/` n'est pas repris.
La commande se rejoue sans rien doubler.

## Reconstruire

La base se reconstruit de son archive seule (`archive/documents/`, chiffrée par age) :

- `hub documents rebuild --check` reconstruit à côté et compare, table par table ;
- base perdue : la recréer vide (`hub migrate`), puis `hub documents rebuild` ;
- `hub documents index` recalcule les passages de tous les documents.
