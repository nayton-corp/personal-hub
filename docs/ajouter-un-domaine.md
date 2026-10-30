# Ajouter un domaine

Un domaine, c'est un paquet Python sous `hub/domains/<nom>/` et ses modules de l'app dans
`hub/domains/<nom>/web/`. On n'écrit pas une ligne du cœur, de la finance ni de la coquille de l'app : le
cœur lit le contrat (`hub.core.domain.Domain`) et le manifeste (`hub.core.manifest`), l'app
lit `/api/domains`. Le domaine factice des tests (`tests/support/demo_domain.py`, modules
`tests/web/modules/`) suit cette recette pas à pas ; `tests/test_domain_recipe.py` vérifie
que la recette couvre tout le contrat et que le domaine factice en remplit chaque point.

Les mots sont ceux du [glossaire](glossaire.md) ; la décision qui fonde le manifeste est
[D-016](decisions.md), l'app modulaire [D-018](decisions.md).

## 1. Le paquet et son nom

- `hub/domains/<nom>/__init__.py` expose une fabrique `create(settings) -> Domain`.
- Le point d'entrée `hub.domains` de `pyproject.toml` la déclare : `<nom> =
  "hub.domains.<nom>:create"`. `HUB_DOMAINS` (dans `deploy/.env`) choisit les domaines
  montés ; un domaine éteint n'a ni base, ni route, ni onglet.
- Attributs du contrat : `name`, `description` (une phrase pour l'app et l'assistant),
  `schema_version`, `scopes` (`<nom>:read`, `<nom>:aggregates`, `<nom>:propose`), et
  `proposal_kinds`.
- Le domaine n'importe aucun autre domaine ; pour lire un autre domaine, il passe par son
  `public.py` (contrat import-linter « domaines indépendants »).

## 2. Sa base et son intégrité

- `engine()` : sa base SQLite, `<data>/<nom>.db`. `migrate()` la met à jour (Alembic, SQL
  explicite, une migration par changement de forme).
- La première migration crée le journal chaîné et les deux tables communes avec
  `hub.core.integrity.schema()` ; un registre `integrity.Ledger(fields)` écrit chaque ligne
  protégée avec son maillon. Les tables protégées sont en ajout seul (triggers anti
  `UPDATE`/`DELETE`, `integrity.append_only`).
- `events_since(cursor, limit)` lit sa boîte de sortie, `applied(ids)` et
  `record_applied(...)` tiennent `applied_proposals` : `integrity.events_since`,
  `integrity.applied` et `Ledger.record_applied` le font pour lui.
- `health()` et `verify()` disent si la base répond et si le journal tient ; `hub verify` les
  appelle et contrôle les triggers des tables protégées.

## 3. Son manifeste

`manifest()` renvoie un `Manifest` : le registre le valide au démarrage et refuse un manifeste
invalide.

- `description` et `assistant` : ce que l'assistant lit du domaine, et ses consignes.
- `app` : `tabs` (onglets : identifiant, libellé, icône, module, ordre), `home_cards` (blocs
  de l'accueil, lus sur une route du domaine), `settings` (rubriques de « Sources et
  réglages », rangées par groupe), `cards` (module qui dessine ses cartes à valider), `home`
  (module de ses blocs d'accueil), `module` (son module : démarrage, rendu commun, liens des
  notifications). Un écran ne reprend jamais celui de la coquille ni d'un autre domaine.
- `importers` : les fichiers de la boîte d'entrée qu'il réclame (extensions, et `claims`
  quand l'extension ne suffit pas).
- `connectors` : les entrées du catalogue qui le nourrissent (le catalogue lui-même passe
  par le point d'entrée `hub.connectors`).
- `protected_tables` : ses tables en ajout seul.

## 4. Ce qu'il apporte au hub

- `router()` : ses routes, montées sous `/api/<nom>` ; chaque route exige une portée
  (`require("app", "<nom>:read")`).
- `cli()` : ses commandes `hub <nom> …`, ou `None`.
- `mcp_tools()` : ses outils pour l'assistant, chacun avec sa portée ; un outil qui écrit
  crée une proposition, jamais un effet.
- `proposal_kinds` : ses types de proposition (paramètres validés, aperçu avec empreinte,
  `apply()` dans la transaction du cœur) : le Double Sas. `tier` donne le palier par défaut
  d'un type (`human` sauf raison écrite) ; la personne le change par `hub proposals policy`.
- `search(q, limit, scopes)` et `resolve(urn)` : sa part de la recherche et des liens. Le
  score d'un `Hit` ne sert qu'à classer ses propres résultats (le cœur fusionne par rang) ;
  `excerpt` porte le passage trouvé (`hub.core.search.excerpt`), jamais un montant. Un objet que
  `resolve` connaît peut être lié à un autre par une carte `core/link`.
- `observations(limit)` : ses constats (budget dépassé, document à renouveler…), servis par
  `GET /api/observations` à qui lit le domaine ; une clé opaque, un titre sans montant.
- `process_inbox()` : traite `inbox/<nom>/`, où `hub watch-inbox` range les fichiers qu'il
  réclame.
- `nightly()` : sa tâche de nuit.

## 5. Son module dans l'app

- Un fichier par module nommé au manifeste, dans le dossier `web/` du domaine, que
  `AppModule.web` déclare (`Path(__file__).parent / "web"`). Il est servi sous `/d/<nom>/` :
  l'image `web` l'y copie, et l'API le monte en développement. Un module n'importe que la
  coquille (`../../ui.js`, `../../store.js`…) et les modules de son dossier ; jamais un autre
  domaine (`tests/web/test_front_boundaries.py`). Un onglet exporte
  `render()` et `actions` (et, au besoin, `todoCount()`, `todoLabel`) ; un bloc d'accueil
  exporte `render(box)`, et au besoin `lead` (son bloc passe avant « À faire ») et `rows()` (ses
  lignes de « À faire » et « À savoir », `null` tant que ses données manquent) ; le module de
  cartes exporte au besoin `detail(p)` (ce qui se déplie sous une carte) et `prepare(ids)`
  (cartes retouchées avant le Face ID) ; une rubrique exporte `rubric(id)` et `rubricStatus(id)` ; le module
  du domaine exporte `init()`, `after()`, `deeplink(hash)`.
- L'accueil, « À faire », « À valider » et le Face ID appartiennent à la coquille (`accueil.js`,
  `approvals.js`) : un domaine y apporte ses blocs, ses lignes et le détail de ses cartes, jamais
  l'écran lui-même.
- `index.html` et `styles.css` ne connaissent aucun domaine. Un module pose ses balises par
  `markup` ([sélecteur, position, html], avant tout rendu), sa feuille de style comprise ; un
  onglet ou une rubrique sans balisage reçoit une page générique : il dessine dans
  `#<onglet>-body` ou `#rub-<rubrique>`.
- Le service worker garde les modules du domaine au premier chargement : rien à déclarer.
- Sans aucun autre domaine, l'app démarre (`tests/web/test_app_without_finance.py`).

## 6. Ses garde-fous

- `docs/<nom>.md` (le domaine vu de l'utilisateur) et `hub/domains/<nom>/README.md` (son
  code : sous-contextes, couches).
- Un domaine qui grossit se range comme la finance : sous-contextes, chacun en `interface` →
  `app` → `infra` → `model`, avec ses contrats import-linter ([D-019](decisions.md)).
- `make reference` met à jour `docs/reference/` (routes, outils, connecteurs) ; la CI refuse
  une référence périmée.
- Des tests sur des données fictives seulement : jamais une donnée réelle dans le dépôt.
