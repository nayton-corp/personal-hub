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
| `finance_settings` | `finance:aggregates` | — | Le mois budgétaire : jour où il commence, mois en cours et ses dates, règles datées. |
| `finance_month_summary` | `finance:aggregates` | `month`? | Totaux d'un mois : revenus, dépenses, épargne, et montant par catégorie (en positif). Répond à « combien en restaurants ce mois ? ». |
| `finance_budget_status` | `finance:aggregates` | `month`? | Budget d'un mois : dépensé contre cible par catégorie, projection à fin de mois, dépassements, reste à vivre. |
| `finance_budget_months` | `finance:aggregates` | `month`?, `months`? | Revenus, dépenses fixes et variables, épargne, placements et taux d'épargne, mois par mois jusqu'au mois demandé. |
| `finance_flows` | `finance:aggregates` | `month`?, `period`? | Les flux d'un mois : revenus par source, puis fixe, variable, épargne par catégorie, et le reste sur compte ; `period: q` pour le trimestre. |
| `finance_category_trend` | `finance:aggregates` | `category`, `months`? | Montant d'une catégorie mois par mois, jusqu'au mois en cours. |
| `finance_networth` | `finance:aggregates` | — | Patrimoine net dans la devise de base, répartition par enveloppe, variations sur un mois et depuis janvier, marge 3a de l'année. |
| `finance_networth_history` | `finance:aggregates` | `from`?, `to`? | Le patrimoine mois par mois : valeur, versements cumulés, valeur par enveloppe. |
| `finance_holdings` | `finance:aggregates` | `on`? | Positions des comptes de titres et des cryptos à une date (aujourd'hui par défaut) : parts, cours, valeur, prix de revient, gain, et le résultat crypto. |
| `finance_performance` | `finance:aggregates` | `from`?, `to`?, `step`? | Performance des placements entre deux dates : gain, apports nets, rendement pondéré dans le temps, revenus, frais, par compte et par actif, par mois et par année, risque, et les événements de la courbe. |
| `finance_lookthrough` | `finance:aggregates` | `dimension`? | Positions ventilées par région, secteur, devise, ou les plus grosses lignes sous-jacentes des fonds. |
| `finance_prices` | `finance:aggregates` | `isin`, `from`?, `to`? | Cours connus d'un actif (ISIN ou symbole) entre deux dates, dans sa devise. |
| `finance_breaks` | `finance:aggregates` | — | Rapprochement d'aujourd'hui : les soldes non expliqués (compte, actif, parts, valeur, cause, gestes possibles), leur total, la part des placements expliquée. |
| `finance_debts` | `finance:aggregates` | — | Dettes et leur solde aujourd'hui : départ, paiements et intérêts depuis, mensualité habituelle, fin projetée. |
| `finance_transfers` | `finance:aggregates` | — | Virements appariés entre mes comptes, par méthode, et le nombre de virements sans autre côté (leur liste avec la lecture complète). |
| `finance_recurring` | `finance:read` | — | Abonnements et paiements réguliers : montant, cadence, prochaine échéance. |
| `finance_to_review` | `finance:read` | `limit`?, `offset`? | Écritures sans catégorie, groupées par commerçant ; known_merchant dit si ce commerçant a déjà été catégorisé. |
| `finance_search` | `finance:read` | `query`, `month`? | Écritures qui contiennent un texte (au plus 50), éventuellement dans un mois. |
| `finance_entries` | `finance:read` | `account`?, `month`?, `category`?, `uncategorized`?, `limit`? | Écritures d'un compte, d'un mois ou d'une catégorie (au plus 50, les plus récentes), ou celles sans catégorie. |
| `finance_entry` | `finance:read` | `entry_id` | Une écriture en détail : catégorisations, notes, corrections. |
| `finance_trades` | `finance:read` | `isin`, `account`? | Achats et ventes d'un actif (ISIN ou symbole), par compte si demandé. |
| `finance_rule_packs` | `finance:aggregates` | — | Packs de règles livrés, version installée, ceux du pays, et le nombre de règles actives (`finance_propose_install_pack` en installe un). |
| `finance_pending_accounts` | `finance:aggregates` | — | Comptes vus dans des relevés en attente (Revolut) mais pas encore créés : clé, devise, nombre d'écritures, période ; `finance_propose_create_account` les ouvre. |
| `finance_propose_category` | `finance:propose` | `entry_id`, `category`, `reason`? | Propose une catégorie pour une écriture. Crée une carte à valider dans l'app ; rien n'est appliqué. |
| `finance_propose_categories` | `finance:propose` | `entry_ids`, `category`, `reason`? | Propose une même catégorie pour plusieurs écritures (au plus 30), des achats uniques qu'aucune règle ne retrouvera. Une seule carte à valider ; rien n'est appliqué. |
| `finance_propose_rule` | `finance:propose` | `keyword`, `category`, `direction`?, `reason`? | Propose une règle : toute écriture qui contient le mot-clé prend la catégorie. La carte montre les écritures touchées ; rien n'est appliqué. |
| `finance_propose_budget` | `finance:propose` | `category`, `amount`, `cadence`?, `reason`? | Propose une cible, dans la devise de base, pour une catégorie de dépense : mensuelle, ou annuelle (cadence year, suivie en cumul depuis janvier) pour les dépenses par à-coups ; rien n'est appliqué. |
| `finance_propose_note` | `finance:propose` | `entry_id`, `note` | Propose une note libre sur une écriture (un TWINT entre particuliers…) ; rien n'est appliqué. |
| `finance_proposal_status` | `finance:propose` | `proposal_id` | Dit si une proposition est en attente, acceptée, refusée ou expirée. |
| `finance_propose_categorize_rest` | `finance:propose` | `before`, `direction`?, `category_id`, `reason`? | Propose la même catégorie pour tout ce qui reste à classer d'un commerçant. |
| `finance_propose_correct_entry` | `finance:propose` | `entry_id`, `amount_minor`?, `booking_date`?, `account_id`?, `reason` | Propose de corriger le montant, la date ou le compte d'une écriture (une annulation puis une remplaçante, l'original reste). |
| `finance_propose_create_account` | `finance:propose` | `institution`, `name`, `kind`?, `currency`?, `iban`?, `external_ref`?, `liquid`?, `budget_account`?, `reason`? | Propose d'ouvrir un compte (finance_pending_accounts en liste à ouvrir). |
| `finance_propose_create_category` | `finance:propose` | `id`, `name`, `grp`, `reason`? | Propose une nouvelle catégorie (identifiant, nom, groupe). |
| `finance_propose_decide_break` | `finance:propose` | `break_id`, `decision`, `cost_minor`?, `note`?, `reason`? | Propose de régler une rupture du rapprochement (finance_breaks) : coût saisi (`cost`, avec cost_minor), garder tel quel (`accept`), parti hors de mes comptes (`gone`). |
| `finance_propose_disable_rule` | `finance:propose` | `rule_id`, `reason`? | Propose de désactiver une règle de catégorisation. |
| `finance_propose_edit_account` | `finance:propose` | `account_id`, `name`?, `goal`?, `availability`?, `category`?, `hidden`?, `target`?, `reason`? | Propose les réglages d'un compte : nom, objectif, disponibilité, catégorie, masqué. |
| `finance_propose_install_pack` | `finance:propose` | `name`, `reason`? | Propose d'installer un pack de règles (finance_rule_packs). |
| `finance_propose_link_crypto_moves` | `finance:propose` | `entry_id`, `peer_id`, `kind`, `reason`? | Propose de relier deux mouvements crypto : virement entre mes comptes, ou mise et sortie de staking. |
| `finance_propose_record_debt_balance` | `finance:propose` | `debt_id`, `on_date`, `amount_minor`, `reason`? | Propose un solde constaté d'une dette à une date. |
| `finance_propose_save_debt` | `finance:propose` | `debt_id`?, `name`?, `lender`?, `kind`?, `currency`?, `original_minor`?, `rate_pct`?, `payment_minor`?, `ends_on`?, `category_id`?, `account_id`?, `closed_on`?, `balance_minor`?, `balance_on`?, `opening_entry_id`?, `reason`? | Propose une dette ou sa mise à jour (nom, prêteur, départ, mensualité, taux). |
| `finance_propose_set_account_goal` | `finance:propose` | `account_id`, `goal`, `reason`? | Propose l'objectif d'un compte (current, safety, projects, long_term, retirement). |
| `finance_propose_set_month_start` | `finance:propose` | `start_day`, `valid_from`?, `reason`? | Propose le jour où commence le mois budgétaire, dès un mois donné. |
| `finance_propose_unlink_crypto_moves` | `finance:propose` | `entry_id`, `peer_id`, `kind`, `reason`? | Propose de défaire un lien entre deux mouvements crypto. |
| `finance_propose_withdraw_break_decision` | `finance:propose` | `decision_id`, `reason`? | Propose de retirer une décision de rapprochement : la rupture se rouvre. |
