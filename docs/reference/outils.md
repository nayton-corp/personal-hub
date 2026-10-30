<!-- Généré par `make reference` (scripts/reference.py) : ne pas modifier à la main. -->

# Outils de l'assistant

Les outils que chaque domaine donne à l'assistant (`hub_capabilities`, puis `hub_load_tools`). Un outil `…:aggregates` est aussi ouvert à `…:read` ; un outil de proposition crée une carte à valider dans l'app, jamais un effet.

## Agenda

| Outil | Portée | Paramètres | Rôle |
|---|---|---|---|
| `agenda_upcoming` | `agenda:read` | `days`? | Les événements des prochains jours (7 par défaut), les rappels ouverts et la liste de courses, avec leurs identifiants. |
| `agenda_counts` | `agenda:aggregates` | — | Combien d'événements cette semaine, de rappels ouverts ou en retard, d'articles à acheter (des nombres, jamais les titres). |
| `agenda_propose_reminder` | `agenda:propose` | `title`, `list`?, `due`?, `notes`? | Propose un rappel (titre, liste, échéance) : une carte à valider dans l'app. |
| `agenda_propose_event` | `agenda:propose` | `title`, `start`, `end`, `calendar`?, `notes`? | Propose un événement du calendrier (titre, début, fin) : une carte à valider. |
| `agenda_propose_complete` | `agenda:propose` | `reminder_id`, `title` | Propose de cocher un rappel (son identifiant, tel que rendu par agenda_upcoming). |
| `agenda_add_shopping` | `agenda:propose` | `title` | Ajoute un article à la liste de courses (palier automatique, sans carte). |

## Documents

| Outil | Portée | Paramètres | Rôle |
|---|---|---|---|
| `documents_search` | `documents:household` | `q`, `limit`? | Cherche dans les documents (notices, contrats, garanties, factures) et les fiches d'objets : les passages trouvés, avec leur source et leur page à citer. |
| `documents_cards` | `documents:household` | — | Les fiches d'objets de la maison (identifiant, nom, pièce). |
| `documents_card` | `documents:household` | `card_id` | Une fiche d'objet entière (marque, modèle, numéro de série, garantie, entretien, pièces) et ses documents. |
| `documents_maintenance_due` | `documents:household` | — | Les entretiens dont l'échéance est passée, d'après les fiches d'objets. |
| `documents_counts` | `documents:aggregates` | — | Combien de fiches, de documents, de documents du foyer et d'entretiens dus. |
| `documents_propose_card` | `documents:propose` | `card_id`, `fields` | Propose de créer ou de compléter une fiche d'objet (champs : name, room, brand, model, serial, bought_at, shop, price_chf, warranty_until, maintenance, parts, notes) : une carte à valider dans l'app. |

## Finance

| Outil | Portée | Paramètres | Rôle |
|---|---|---|---|
| `finance_list_accounts` | `finance:aggregates` | — | Comptes, solde calculé et valeur (titres au dernier cours), date du dernier relevé. Aucun IBAN. |
| `finance_data_freshness` | `finance:aggregates` | — | Fraîcheur des données : dernier import et dernier relevé par compte, état des collecteurs. À consulter avant d'affirmer qu'un mois est complet. |
| `finance_list_categories` | `finance:aggregates` | — | Catégories valides (identifiant, nom, groupe), à utiliser dans les autres outils. |
| `finance_month_summary` | `finance:aggregates` | `month`? | Totaux d'un mois : revenus, dépenses, épargne, et montant par catégorie (en positif). Répond à « combien en restaurants ce mois ? ». |
| `finance_budget_status` | `finance:aggregates` | `month`? | Budget d'un mois : dépensé contre cible par catégorie, projection à fin de mois, dépassements, reste à vivre. |
| `finance_category_trend` | `finance:aggregates` | `category`, `months`? | Montant d'une catégorie mois par mois, jusqu'au mois en cours. |
| `finance_networth` | `finance:aggregates` | — | Patrimoine net dans la devise de base, répartition par enveloppe, variations sur un mois et depuis janvier, marge 3a de l'année. |
| `finance_recurring` | `finance:read` | — | Abonnements et paiements réguliers : montant, cadence, prochaine échéance. |
| `finance_to_review` | `finance:read` | `limit`?, `offset`? | Écritures sans catégorie, groupées par commerçant ; known_merchant dit si ce commerçant a déjà été catégorisé. |
| `finance_search` | `finance:read` | `query`, `month`? | Écritures qui contiennent un texte (au plus 50), éventuellement dans un mois. |
| `finance_propose_category` | `finance:propose` | `entry_id`, `category`, `reason`? | Propose une catégorie pour une écriture. Crée une carte à valider dans l'app ; rien n'est appliqué. |
| `finance_propose_categories` | `finance:propose` | `entry_ids`, `category`, `reason`? | Propose une même catégorie pour plusieurs écritures (au plus 30), des achats uniques qu'aucune règle ne retrouvera. Une seule carte à valider ; rien n'est appliqué. |
| `finance_propose_rule` | `finance:propose` | `keyword`, `category`, `direction`?, `reason`? | Propose une règle : toute écriture qui contient le mot-clé prend la catégorie. La carte montre les écritures touchées ; rien n'est appliqué. |
| `finance_propose_budget` | `finance:propose` | `category`, `amount`, `cadence`?, `reason`? | Propose une cible, dans la devise de base, pour une catégorie de dépense : mensuelle, ou annuelle (cadence year, suivie en cumul depuis janvier) pour les dépenses par à-coups ; rien n'est appliqué. |
| `finance_propose_note` | `finance:propose` | `entry_id`, `note` | Propose une note libre sur une écriture (un TWINT entre particuliers…) ; rien n'est appliqué. |
| `finance_proposal_status` | `finance:propose` | `proposal_id` | Dit si une proposition est en attente, acceptée, refusée ou expirée. |
