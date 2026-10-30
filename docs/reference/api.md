<!-- Généré par `make reference` (scripts/reference.py) : ne pas modifier à la main. -->

# Routes de l'API

Toutes les routes, cœur puis domaines installés. La portée exigée et les erreurs sont dans le code ; le contrat complet du cœur est `tests/openapi.snapshot.json`.

## Cœur

| Méthode | Chemin | Rôle |
|---|---|---|
| `POST` | `/api/approvals/challenge` | Défi WebAuthn qui contient `approval_digest` : un seul Face ID pour tout le lot. |
| `POST` | `/api/auth/logout` | Logout |
| `POST` | `/api/auth/passkey/login/begin` | Login Begin |
| `POST` | `/api/auth/passkey/login/finish` | Login Finish |
| `POST` | `/api/auth/passkey/register/begin` | Register Begin |
| `POST` | `/api/auth/passkey/register/finish` | Register Finish |
| `GET` | `/api/auth/passkeys` | List Passkeys |
| `GET` | `/api/auth/session` | Session |
| `GET` | `/api/collectors` | List Collectors |
| `GET` | `/api/collectors/catalog` | Les connecteurs que ce hub sait collecter (méthode, pays, secrets attendus). |
| `GET` | `/api/collectors/connections` | Les connexions de l'instance, sans leurs secrets (seulement s'ils sont donnés). |
| `POST` | `/api/collectors/connections` | Create Connection |
| `PATCH` | `/api/collectors/connections/{cid}` | Update Connection |
| `DELETE` | `/api/collectors/connections/{cid}` | Delete Connection |
| `PUT` | `/api/collectors/connections/{cid}/secrets` | Remplace les secrets : chiffrés vers la clé de la machine, jamais relus par l'API. |
| `POST` | `/api/collectors/refresh` | « Tout actualiser » : un run de chaque connexion prête et active, dans la minute. |
| `GET` | `/api/collectors/runner/{runner}` | Ce qu'un service collecteur exécute : connexions prêtes, secrets toujours chiffrés. |
| `GET` | `/api/collectors/{name}` | Get Collector |
| `POST` | `/api/collectors/{name}/check` | Demande un run de contrôle (connexion et sélecteurs, sans téléchargement). |
| `POST` | `/api/collectors/{name}/link` | Nouveau consentement Enable Banking : le service collecteur ouvre l'autorisation dans la minute ; l'adresse à ouvrir apparaît ensuite dans `link_url`. |
| `PUT` | `/api/collectors/{name}/link-url` | Set Link Url |
| `POST` | `/api/collectors/{name}/links` | Register Link |
| `GET` | `/api/collectors/{name}/links/{state}` | Le code de retour, rendu une seule fois ; `code` nul tant qu'il n'est pas arrivé. |
| `POST` | `/api/collectors/{name}/mode` | Couper un collecteur, ou le remettre en marche après un contrôle réussi. |
| `POST` | `/api/collectors/{name}/notify` | Le bot attend une validation sur le téléphone, ou un consentement arrive à échéance. |
| `POST` | `/api/collectors/{name}/refresh` | Actualiser maintenant : un run complet hors horaire, pris dans la minute par le service collecteur ; les limites de la source (synchros par jour) restent celles du flux. |
| `GET` | `/api/collectors/{name}/runs` | List Runs |
| `POST` | `/api/collectors/{name}/runs` | Déclare un run ; applique la table des échecs et envoie les alertes ntfy. |
| `GET` | `/api/digest` | Effets appliqués au palier auto_digest, avec leur inverse d'un geste. |
| `GET` | `/api/domains` | Les domaines actifs et leurs manifestes : onglets, cartes d'accueil et rubriques que l'app monte, fichiers que chacun réclame. Un jeton ne voit que les domaines qu'il ouvre. |
| `GET` | `/api/health` | Health |
| `GET` | `/api/links` | Links |
| `GET` | `/api/observations` | Les constats de chaque domaine lisible (budget dépassé, document à renouveler), les plus récents d'abord. Il faut la lecture du domaine : un constat peut nommer une contrepartie (un abonnement en hausse), ce que `…:aggregates` ne voit jamais. |
| `GET` | `/api/profile` | Get Profile |
| `POST` | `/api/profile` | Update Profile |
| `GET` | `/api/proposals` | List Proposals |
| `POST` | `/api/proposals` | Create Proposal |
| `POST` | `/api/proposals/accept` | Valide un lot signé ; chaque proposition s'applique seule, avec son propre statut. Une signature qui porte sur une autre révision ou une autre empreinte est refusée. |
| `GET` | `/api/proposals/{proposal_id}` | Get Proposal |
| `POST` | `/api/proposals/{proposal_id}/reject` | Reject Proposal |
| `POST` | `/api/proposals/{proposal_id}/revert` | Crée et applique l'inverse d'une proposition réversible (un Face ID). |
| `GET` | `/api/resolve` | Resolve |
| `GET` | `/api/search` | Les domaines lisibles, fusionnés par rang (`hub.core.search`) : chaque résultat dit son domaine, son rang dans ce domaine et le passage trouvé. |
| `GET` | `/api/tools` | Capabilities |
| `GET` | `/api/tools/{domain}` | Domain Tools |
| `POST` | `/api/tools/{domain}/{name}` | Call Tool |

## Agenda

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/agenda/counts` | Des nombres seulement : événements de la semaine, rappels ouverts et en retard. |
| `GET` | `/api/agenda/overview` | Le bloc de l'accueil : la semaine, les rappels ouverts, la liste de courses ; le pont absent se dit (`available: false`). |
| `GET` | `/api/agenda/upcoming` | Les événements des prochains jours, les rappels ouverts et la liste de courses. |

## Finance

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/finance/accounts` | Comptes, IBAN masqué, solde calculé, dernier CLBD et écart. |
| `GET` | `/api/finance/accounts/pending` | Comptes vus dans des relevés en attente (Enable Banking, CSV Revolut) mais pas encore créés : clé, devise, nombre d'écritures et période. Aucun montant. |
| `GET` | `/api/finance/budget` | Réel et cible par catégorie de dépense, dépassements, reste à vivre, jours restants. `period=q` : les trois mois complets avant `month`. |
| `GET` | `/api/finance/budget/months` | Les totaux du budget mois par mois, jusqu'à `month` compris. |
| `GET` | `/api/finance/budget/totals` | Revenus, dépenses (fixes, variables), épargne, placements et taux d'épargne. |
| `GET` | `/api/finance/categories` | Categories |
| `GET` | `/api/finance/debts` | Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, fin projetée. |
| `GET` | `/api/finance/entries` | Écritures filtrées ; montants en centimes, comparés en valeur absolue. |
| `GET` | `/api/finance/entries/{entry_id}` | Entry |
| `GET` | `/api/finance/export.csv` | Journal complet en CSV (UTF-8, séparateur virgule) : tout s'exporte. |
| `GET` | `/api/finance/flows` | Revenus → groupes (fixe, variable, épargne) → catégories, et le reste sur compte. `period=q` : les trois mois complets avant `month`, comme le budget. |
| `GET` | `/api/finance/freshness` | Freshness |
| `GET` | `/api/finance/holdings` | Positions des comptes de titres (VIAC) à une date, aujourd'hui par défaut. |
| `POST` | `/api/finance/imports` | Corps brut (XML, zip, PDF VIAC, JSON, CSV ou relevé SwissBorg .xlsx) ; même traitement que `inbox/`. |
| `GET` | `/api/finance/imports/{import_id}` | Import Detail |
| `GET` | `/api/finance/kpis` | Chiffres clés de l'accueil : patrimoine et variations, mois, liquidités, à traiter. |
| `GET` | `/api/finance/lookthrough` | Positions ventilées par région, secteur, devise, ou les dix plus grosses lignes sous-jacentes (transparence des fonds). |
| `GET` | `/api/finance/networth/history` | Instantanés : patrimoine, versements cumulés, valeur par enveloppe et par compte. `step=day` ou `week` : un point par jour ou par semaine, calculé à la demande entre `from` et `to` (aujourd'hui par défaut), au plus 400 points. |
| `GET` | `/api/finance/performance` | Performance d'une sélection de lignes (`line=<compte>\|<instrument>`, `<compte>\|cash`, `debt:<id>` ; par défaut, celles de l'app) : courbe de la valeur, des apports nets, du gain et du rendement pondéré dans le temps ; résumé (gain, revenus, frais, rendement, rendement personnel annuel) ; le même par compte, par actif, par ligne ; par mois et par année ; risque. Des agrégats seulement. |
| `GET` | `/api/finance/recurring` | Abonnements et paiements réguliers, prochaines échéances, total mensuel ; pour la portée `aggregates`, les totaux seulement. |
| `GET` | `/api/finance/review` | Écritures sans catégorie, groupées par contrepartie normalisée. |
| `GET` | `/api/finance/rules/packs` | Packs de règles livrés, version installée, ceux du pays de l'instance, et le nombre de règles actives hors système (parcours d'accueil). |
| `GET` | `/api/finance/search` | Search |
| `GET` | `/api/finance/settings` | Réglages du budget : jour où commence le mois, mois en cours et ses dates. |
| `POST` | `/api/finance/settings` | Update Settings |
| `GET` | `/api/finance/summary` | Summary |
| `GET` | `/api/finance/trades` | Achats et ventes d'un actif (ordres), pour le journal d'un actif dans l'app. |
| `GET` | `/api/finance/transfers` | Virements appariés par méthode et virements sans autre côté. |
| `GET` | `/api/finance/trend` | Trend |
