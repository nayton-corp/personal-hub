# Le contrat avec Domia

L'assistant parle à Domia par son API. Ce dossier en garde une copie figée, prise dans le dépôt
de Domia : les réponses de référence de l'API (`api/`, tirées de
`backend/src/test/resources/api/`), la référence de la configuration (`config-reference.md`,
que l'outil des réglages cite) et la maison de démonstration du banc (`seed-local.yaml`).

`DOMIA_VERSION` dit de quelle version de Domia vient la copie : la plus ancienne que
l'assistant sait lire. `make domia-contract DOMIA=~/domia` la reprend depuis un clone de Domia ;
les tests de l'assistant tournent contre elle.
