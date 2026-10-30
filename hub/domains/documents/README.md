# Domaine Documents (code)

Fiches d'objets et documents de la maison ([D-025](../../../docs/decisions.md)), repris de la
bibliothèque de l'assistant de Domia. L'usage : [docs/documents.md](../../../docs/documents.md).

| Module | Ce qu'il tient |
|---|---|
| `domain.py` | `DocumentsDomain`, le contrat de domaine ; lectures, recherche, constats, santé |
| `model.py` | pur : champs d'une fiche, échéances d'entretien (« 1 mois »), découpage en passages |
| `store.py` | `documents.db` par le registre chaîné ; fiche courante, marque courante |
| `archive.py` | l'archive chiffrée : `files/<sha256>.age`, `records/<table>/<seq>.json.age` |
| `index.py` | les passages et leur recherche FTS5 (trigrammes) |
| `text.py` | le texte d'un fichier : `.txt`, `.md`, `.eml`, `.pdf` (`pdftotext`, processus plafonné) |
| `service.py` | écrire (document, fiche), boîte d'entrée, reprise de la bibliothèque, reconstruction |
| `kinds.py` | `save_card` (l'assistant peut le proposer), `mark_household` (réversible) |
| `tools.py` | les outils de l'assistant |
| `api.py` | `/api/documents/overview`, `/counts`, `/search`, `/cards` ; `hub documents …` |

- **En ajout seul** : `cards` (une version par changement, la dernière fait foi), `documents`
  (jamais modifié), `marks` (la marque « foyer » ; aucune : privé). Les passages ne sont pas
  protégés : ils se recalculent.
- **L'archive d'abord** : un fichier est chiffré dans l'archive avant sa ligne ; une ligne
  validée y est copiée aussitôt (`Library.export`, rattrapé chaque nuit). `hub verify` signale
  une ligne pas encore archivée ; `rebuild --check` rejoue l'archive dans une base jetable et
  compare.
- **Portées** : `documents:household` ouvre les fiches et les documents « foyer » ;
  `documents:read` ouvre aussi les privés ; `documents:aggregates`, des nombres ;
  `documents:propose`, une fiche à compléter.
- **URN** : `hub:documents:document:<id>`, `hub:documents:card:<id de fiche en base64>` (un id
  de fiche porte des espaces).
