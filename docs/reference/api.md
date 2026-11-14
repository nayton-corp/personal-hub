<!-- Généré par `make reference` (scripts/reference.py) : ne pas modifier à la main. -->

# Routes de l'API

Toutes les routes, cœur puis domaines installés. La portée exigée et les erreurs sont dans le code ; le contrat complet du cœur est `tests/openapi.snapshot.json`.

## Cœur

| Méthode | Chemin | Rôle |
|---|---|---|
| `POST` | `/api/approvals/challenge` | Défi WebAuthn qui contient `approval_digest` : un seul Face ID pour tout le lot. |
| `GET` | `/api/assistant/history` | History |
| `GET` | `/api/assistant/status` | Status |
| `POST` | `/api/assistant/talk` | Talk |
| `POST` | `/api/assistant/voice` | Voice |
| `POST` | `/api/auth/logout` | Logout |
| `POST` | `/api/auth/passkey/confirm/begin` | Défi qu'une passkey en place signe avant d'en ajouter ou d'en retirer une. |
| `POST` | `/api/auth/passkey/login/begin` | Login Begin |
| `POST` | `/api/auth/passkey/login/finish` | Login Finish |
| `POST` | `/api/auth/passkey/register/begin` | Register Begin |
| `POST` | `/api/auth/passkey/register/finish` | Register Finish |
| `GET` | `/api/auth/passkeys` | List Passkeys |
| `DELETE` | `/api/auth/passkeys/{credential_id}` | Retire une passkey (jamais la dernière) sous Face ID d'une passkey en place ; ses sessions sont fermées, la sienne comprise. |
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
| `GET` | `/api/collectors/{name}/needs` | Ce que la connexion doit chercher pour le domaine qui a déclaré son connecteur : rien si le domaine n'en dit rien, ou s'il n'est pas monté sur cette instance. |
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
| `GET` | `/api/tasks` | Chaque tâche : son horaire, sa dernière demande, son dernier passage. |
| `POST` | `/api/tasks/refresh` | « Tout actualiser » : chaque connexion active, puis les calculs des domaines quand elles ont fini. |
| `POST` | `/api/tasks/{name}/run` | Relancer une tâche maintenant : le planificateur la prend dans la minute. |
| `GET` | `/api/tools` | Capabilities |
| `GET` | `/api/tools/{domain}` | Domain Tools |
| `POST` | `/api/tools/{domain}/{name}` | Call Tool |

## Agenda

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/agenda/counts` | Des nombres seulement : événements de la semaine, rappels ouverts et en retard. |
| `GET` | `/api/agenda/overview` | Le bloc de l'accueil : la semaine, les rappels ouverts, la liste de courses ; le pont absent se dit (`available: false`). |
| `GET` | `/api/agenda/upcoming` | Les événements des prochains jours, les rappels ouverts et la liste de courses. |

## Documents

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/documents/cards` | Cards |
| `GET` | `/api/documents/cards/{card_id}` | Card |
| `GET` | `/api/documents/counts` | Des nombres seulement : fiches, documents, documents du foyer, entretiens dus. |
| `GET` | `/api/documents/overview` | Le bloc de l'accueil : les nombres, les entretiens dus, les derniers documents. |
| `GET` | `/api/documents/search` | Les passages et les fiches qui répondent, avec leur source et leur page. |

## Finance

| Méthode | Chemin | Rôle |
|---|---|---|
| `GET` | `/api/finance/accounts` | Comptes, IBAN masqué, solde calculé, dernier CLBD et écart. |
| `GET` | `/api/finance/accounts/pending` | Comptes vus dans des relevés en attente (Enable Banking, CSV Revolut) mais pas encore créés : clé, devise, nombre d'écritures et période. Aucun montant. |
| `GET` | `/api/finance/breaks` | Rapprochement d'aujourd'hui : les ruptures ouvertes (compte, actif, parts, valeur, cause, gestes), leur total et la part des placements expliquée et cotée. Une rupture se règle par la proposition `decide_break` (Double Sas). |
| `GET` | `/api/finance/budget` | Réel et cible par catégorie de dépense, dépassements, reste à vivre, jours restants. `period=q` : les trois mois complets avant `month`. |
| `GET` | `/api/finance/budget/months` | Les totaux du budget mois par mois, jusqu'à `month` compris. |
| `GET` | `/api/finance/budget/totals` | Revenus, dépenses (fixes, variables), épargne, placements et taux d'épargne. |
| `GET` | `/api/finance/categories` | Categories |
| `GET` | `/api/finance/debts` | Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, fin projetée. |
| `GET` | `/api/finance/entries` | Écritures filtrées ; montants en centimes, comparés en valeur absolue. |
| `GET` | `/api/finance/entries/{entry_id}` | Entry |
| `GET` | `/api/finance/export.csv` | Journal complet en CSV (UTF-8, séparateur virgule) : tout s'exporte. |
| `GET` | `/api/finance/fees` | Frais courants des fonds détenus : TER, coût par an et sur trente ans (ordre de grandeur, au rendement supposé `assumed_return_pct`). Un fonds sans TER connu a `ter_pct` nul et reste hors des totaux. Saisir un TER : `set_fund_fee` (Double Sas). |
| `GET` | `/api/finance/flows` | Revenus → groupes (fixe, variable, épargne) → catégories, et le reste sur compte. `period=q` : les trois mois complets avant `month`, comme le budget. |
| `GET` | `/api/finance/freshness` | Freshness |
| `GET` | `/api/finance/goods` | Biens hors comptes (logement, véhicule, objet, prêt accordé) et leur valeur aujourd'hui : la dernière valeur saisie, suivie de la variation annuelle du bien. Écrire : `save_good` (Double Sas). |
| `GET` | `/api/finance/holdings` | Positions des comptes de titres (VIAC) à une date, aujourd'hui par défaut. |
| `POST` | `/api/finance/imports` | Corps brut (XML, zip, PDF VIAC, JSON, CSV ou relevé SwissBorg .xlsx) ; même traitement que `inbox/`. |
| `GET` | `/api/finance/imports/{import_id}` | Import Detail |
| `GET` | `/api/finance/kpis` | Chiffres clés de l'accueil : patrimoine et variations, mois, liquidités, à traiter. |
| `GET` | `/api/finance/lookthrough` | Le patrimoine réparti par région, secteur ou devise, liquidités comprises, ou les dix plus grosses lignes sous-jacentes des fonds. `line` : la sélection de l'écran, comme pour `/performance` (par défaut, les lignes de l'app). La somme des cases (`total`), dettes à part (`owed`), est la valeur de la sélection. Des agrégats seulement. |
| `GET` | `/api/finance/networth/history` | Instantanés : patrimoine, versements cumulés, valeur par enveloppe et par compte. `step=day` ou `week` : un point par jour ou par semaine, calculé à la demande entre `from` et `to` (aujourd'hui par défaut), au plus 400 points. |
| `GET` | `/api/finance/performance` | Performance d'une sélection (`account=<compte>` : toutes ses lignes, celles d'une position vendue depuis comprises ; `line=<compte>\|<instrument>`, `<compte>\|cash`, `debt:<id>` ; par défaut, les lignes de l'app) : courbe de la valeur, des apports nets, du gain et du rendement pondéré dans le temps ; résumé (gain, revenus, frais, rendement, rendement personnel annuel) ; le même par compte, par actif, par ligne ; par mois et par année ; risque. Les points tombent sur le calendrier (chaque jour, chaque dimanche, chaque fin de mois) ; au-delà de 400, le pas s'élargit. `extremes` : le plus haut et le plus bas de tous les jours de la période. Des agrégats seulement. |
| `GET` | `/api/finance/prices` | Cours connus d'un instrument entre deux dates, dans sa devise de cotation, au plus 400 points : la courbe « Cours » de la page d'un actif. |
| `GET` | `/api/finance/recurring` | Abonnements et paiements réguliers, prochaines échéances, total mensuel ; pour la portée `aggregates`, les totaux seulement. |
| `GET` | `/api/finance/review` | Écritures sans catégorie, groupées par contrepartie normalisée. |
| `GET` | `/api/finance/rules/packs` | Packs de règles livrés, version installée, ceux du pays de l'instance, et le nombre de règles actives hors système (parcours d'accueil). |
| `GET` | `/api/finance/search` | Search |
| `GET` | `/api/finance/settings` | Réglages du budget : jour où commence le mois en cours, mois en cours et ses dates, règles datées (`set_month_start` en pose une nouvelle). |
| `GET` | `/api/finance/strategies` | Les stratégies (vendre par paliers, achat régulier, acheter une grosse baisse) : la phrase, où on en est aujourd'hui, l'étape atteinte qui attend une réponse, les étapes passées ; et `scopes`, sur quoi une stratégie peut porter. Le hub ne passe aucun ordre. Écrire : `save_strategy` ; répondre à une étape : `answer_strategy_step` (Double Sas). |
| `GET` | `/api/finance/summary` | Summary |
| `GET` | `/api/finance/todo` | Le nombre d'écritures à classer, seul : la pastille du Journal ne recalcule pas les chiffres clés (audit du 10/11, P1). |
| `GET` | `/api/finance/trades` | Achats et ventes d'un actif (ordres), pour le journal d'un actif dans l'app. |
| `GET` | `/api/finance/transfers` | Virements appariés par méthode et virements sans autre côté. Une lecture n'écrit pas : les instantanés se rafraîchissent après la réponse, en tâche de fond. |
| `GET` | `/api/finance/trend` | Trend |
