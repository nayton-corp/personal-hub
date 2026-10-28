# Journal des changements

## [Non publié]

### Hub générique — G4 : connexions en base, deux services collecteurs

- Ce que l'instance collecte est une liste de connexions dans `core.db` (migration
  `0004_connections`) : connecteur du catalogue, identifiant, nom, horaire, réglages sans secret
  et secrets chiffrés par age vers la clé de la machine. L'API les chiffre à la saisie et ne les
  relit jamais ; seul le service collecteur qui exécute la connexion les déchiffre, au run.
- Les huit conteneurs collecteurs deviennent deux services, `collector-browser` (BCF, VIAC) et
  `collector-api` (le reste), qui demandent chaque minute leurs connexions prêtes au hub
  (`GET /api/collectors/runner/{service}`, portée `collector`). Plusieurs connexions d'un même
  connecteur sont possibles (deux banques par Enable Banking, par exemple).
- Le connecteur « revolut » devient `enable_banking` (réglages `aspsp_name`, `aspsp_country`…) ;
  la connexion existante garde l'identifiant « revolut », donc son URL de retour et son état.
- `hub connections list|catalog|add|set|secrets|remove|import` et, pour l'app,
  `GET|POST /api/collectors/connections`, `PATCH …/{id}`, `PUT …/{id}/secrets`,
  `DELETE …/{id}`. `hub connections secrets ID --file -` lit un YAML sur l'entrée standard.
- `hub-collector run|relogin|link|aspsps|consent <connexion>` ; `hub-collector revolut
  link|aspsps|status` reste.
- Reprise automatique par `make deploy` : la migration crée une connexion par collecteur connu,
  `hub connections import` reprend les secrets des `<nom>.enc.yaml` (sans l'ancien jeton) et les
  horaires de `[collectors] schedules`, écrit les fichiers et jetons des deux services, et les
  anciens volumes sont recopiés dans ceux des services. Les anciens jetons restent valides pour
  un retour arrière ; à révoquer une fois la version validée.
- `[collectors] schedules` n'est plus lu au run : les horaires vivent dans les connexions.
- Limite connue : l'importeur Finance des fichiers Enable Banking reste au format Revolut
  (`hub.revolut.v1`, comptes `revolut:`) ; une autre banque demandera son adaptation.

### Hub générique — G1b : devise de base

- La devise de base vient de `HUB_CURRENCY` (CHF par défaut), posée par compose comme `HUB_TZ`
  et lue par `hub.core.money.base_currency()`. Valorisation, instantanés, chiffres clés,
  budgets, outils de l'assistant, cours du collecteur « market » (BCE et CoinGecko dans cette
  base, le franc compris) et app l'emploient au lieu du CHF codé en dur.
- Migration `0010_base_currency` : la devise est fixée dans `finance.db` à sa création ; une base
  qui a déjà des écritures reste en CHF. Si `HUB_CURRENCY` ne la suit plus, la migration échoue
  avec un message clair et `/api/health` signale `currency_mismatch`.
- Le profil (`/api/profile`) donne `currency` ; l'assistant écrit ses montants dans cette devise.
- L'outil `finance_propose_budget` prend `amount` ; l'ancien `amount_chf` reste accepté.

### Hub générique — G2 : packs de règles

- Les règles de départ ne viennent plus des migrations mais de packs YAML versionnés
  (`hub/domains/finance/packs/`) : `base` (mots génériques, services internationaux) et `ch`
  (commerces et prestataires suisses), découpés du fichier de départ de l'ancien script sans
  ses lieux personnels (bars et administrations de Fribourg, comptes Revolut et Raiffeisen).
- Une base neuve reçoit `base` et le pack du pays du profil ; `0004_rules` n'y installe plus
  que les catégories et `0008_crypto_cost` n'a plus rien à faire. Une base existante garde ses
  règles `seed-` et n'a aucun pack installé. Migration `0009_rule_packs` (version installée de
  chaque pack), recopiée par la reconstruction.
- `fin rules packs list|install [--dry-run]` (nom de pack ou fichier `.yaml`) et
  `fin rules export FICHIER [--origin user…]` : les règles personnelles se sortent au format
  d'un pack et se réinstallent ailleurs. Une règle de même forme n'est jamais doublée, une
  règle de pack désactivée le reste, une nouvelle version désactive ce qu'elle retire.
- `legacy.DEFAULT_RULES` quitte le code ; `import-legacy` reprend toujours un `bcf_rules.json`.

### Hub générique — G3 : catalogue de connecteurs

- `hub/core/connectors.py` déclare une fois chaque connecteur : méthode (`open_banking`, `api`,
  `public`, `browser`), pays, types de comptes, champs de secrets, horaire par défaut, sources
  d'import. Les listes du cœur (`COLLECTORS`) et des conteneurs (`NAMES`) et les horaires par
  défaut en sont tirés ; `[collectors] schedules` ne remplace plus que les horaires qu'il nomme.
  Route `GET /api/collectors/catalog` (app). Des tests vérifient que compose, le code des
  collecteurs (secrets lus) et le planificateur suivent le catalogue.
- `hub/domains/finance/institutions.py` déclare les codes d'opération VIAC et IBKR et leur rôle
  (virement, mouvement interne, effet marché, versement 3a) ; l'appariement, la valorisation et
  le suivi du 3a les lisent au lieu de listes écrites en dur. Un test vérifie qu'ils concordent
  avec les règles système des migrations. Aucun changement de résultat.

### Hub générique — G1 : profil de l'instance

- `core.db` (migration `0003_profile`) : profil de l'instance, prénom et pays. Une base existante
  reçoit la Suisse, sans prénom. Routes `GET /api/profile` (app et jetons de lecture) et
  `POST /api/profile` (app seulement), carte « Profil » dans Sources, `hub profile show|set`.
- Le pays ouvre les modules qui lui sont propres : le pilier 3a (chiffres clés, outil
  `finance_networth`, alerte de fin d'année) ne s'affiche plus hors de Suisse.
- Fuseau de l'instance : `HUB_TZ` (Europe/Zurich par défaut), posé par compose dans tous les
  conteneurs, remplace les fuseaux de Zurich écrits dans le code (jour civil des chiffres,
  horaires des collecteurs et du planificateur, navigateur des robots, dates de l'app).
- Assistant : le prénom et le pays viennent du profil (`GET /api/tools` le renvoie) ; plus aucun
  prénom dans le code, les prompts ni l'exemple `deploy/.env`.

### Cryptos automatiques

- Collecteur `market` : un portefeuille BTC peut se donner par sa clé publique étendue (`xpub`,
  `ypub`, `zpub`) ; ses adresses de réception et de monnaie sont dérivées dans le conteneur
  (embit), jusqu'à 20 adresses vides de suite, sur les quatre types d'adresse pour une `xpub`.
  Une clé privée est refusée.
- Ethereum : jetons USDC et USDT en plus de l'ETH (`erc20_tokens`). Solana : SOL et jetons USDC,
  USDT (`spl_tokens`) par le RPC public. Plusieurs chaînes peuvent alimenter un même compte.
- Un compte dont une adresse ne répond pas est laissé de côté en entier ce jour-là (détail
  `partial wallet.<nom>:…`) ; un portefeuille vide donne un relevé à zéro.
- Collecteurs `binance`, `kucoin` et `coinbase` (API officielles, clés en lecture seule, un
  conteneur et un fichier de secrets chacun) : soldes de la plateforme vers `crypto:<plateforme>`.
- Cours CoinGecko par défaut : SOL, USDC et USDT en plus de BTC et ETH.
- Performance des cryptos (Finance) : `GET /finance/holdings` porte un bloc `crypto` (investi =
  paiements nets de la catégorie « Crypto », valeur, résultat) et un prix de revient par crypto
  (valeur à l'arrivée sur le portefeuille). Les paiements « Crypto » ne comptent plus comme
  sortie du patrimoine. Migration `0008_crypto_cost` : règles de départ KuCoin, Bitpanda,
  Bitstamp, Crypto.com, Bitvavo, Bybit, Pocket Bitcoin, Bitcoin Suisse et Mt Pelerin.
- Historique BTC : au premier passage, le solde de chaque jour où il a bougé est relu sur la
  chaîne (transactions des adresses utilisées) et déposé en relevés passés. Avant la fenêtre
  d'un an de CoinGecko, change BCE et clôtures publiques Binance (USD) pour le valoriser.
- Relevé SwissBorg (`.xlsx`, Profil → Documents → Relevé de compte) : soldes par actif rejoués
  depuis le premier mouvement, un relevé de positions de `crypto:swissborg` par jour où ils
  bougent, cours et change USD/CHF tirés du fichier. La boîte d'entrée et l'import de l'app
  acceptent les `.xlsx` (lecteur interne, première feuille, texte des cellules).
- mempool.space : une seconde entre deux adresses BTC, et sur un refus 429 un nouvel essai après
  10, 30 puis 60 secondes (une liste de 48 adresses était coupée après une vingtaine).

### Lot 7 — IA locale

- Outils de l'assistant : contrat `McpTool.call(args, caller)` (le cœur fournit les portées et
  la création de propositions), routes `GET /api/tools`, `GET /api/tools/{domaine}`,
  `POST /api/tools/{domaine}/{outil}`, réservées aux jetons. Une portée `aggregates` est ouverte
  à la portée `read` du même domaine.
- Les 15 outils Finance du plan : catégories en liste fermée dans le schéma, montants en CHF à
  deux décimales, aucun IBAN, `data_as_of` dans chaque réponse, libellés marqués comme texte
  externe. Le jeton « agrégats » n'a que 7 outils de totaux ; une catégorie ou un mois de moins
  de 3 écritures y est fondu ou masqué.
- Propositions d'un jeton limitées par heure glissante (`auth.token_proposals_per_hour`, 60).
- Sentinelles de nuit (schéma `0007_alerts`) : budget dépassé ou qui va l'être, abonnement en
  hausse, marge 3a pas encore versée en novembre et décembre. Une alerte par occasion, notifiée
  par l'événement `notify.request` (texte générique, ni montant ni nom), route
  `GET /api/finance/alerts`, lignes dans « À traiter ».
- Brain (`hub/brain`, commande `hub-brain`, conteneur `brain` au profil compose « brain ») :
  passerelle MCP sur stdio sans dépendance, routage des outils par domaine
  (`hub_capabilities`, `hub_load_tools`), assistant `ask` sur Ollama par l'API compatible
  OpenAI (MLX possible par la configuration), suggestions de catégorie pour les commerçants
  jamais vus (`suggest`, chaque matin), contrôle de bout en bout `check`.
- App : la raison d'une proposition de l'assistant s'affiche sur sa carte.

### Lot 6 — Patrimoine complet

- Schéma `0006_wealth` : instruments élargis (cryptos, symboles, sorte), compositions des fonds,
  tables dérivées `transfer_links` et `recurring`, vue d'allocation (un virement apparié compte
  comme `transfer-own`), devises supplémentaires, règles système `IBKR/…`.
- IBKR : relevés Flex Query (comptes de liquidités par devise créés au premier relevé, achats,
  ventes, change, commissions, dividendes, positions, cours, soldes de fin comme points de
  contrôle), dédoublonnage par `transactionID`, `fin ibkr add-account` et `import-history`.
- Valorisation multi-devise : comptes et positions convertis en CHF au dernier cours connu ;
  l'enveloppe `ibkr` devient `titres`.
- Fichiers `hub.market.v1` (change BCE, cours, soldes crypto), CSV de positions saisies à la
  main (placements Revolut), compositions de fonds (listes d'émetteur ou CSV générique) ; `fin
  crypto add-wallet`, `fin positions add-account`, `fin derived`.
- Virements appariés (IBAN, référence, montant), abonnements récurrents avec prochaine
  échéance ; routes `lookthrough`, `recurring`, `transfers` ; `kpis.unmatched_transfers`.
- Collecteurs `ibkr` (Flex Web Service) et `market` (BCE, CoinGecko, mempool.space, nœud
  Ethereum, Yahoo facultatif), sans navigateur ; services compose correspondants.
- App : enveloppe Titres, positions de toutes les enveloppes, carte Transparence, carte
  Abonnements, virements sans autre côté dans « À traiter », comptes en devise affichés avec
  leur devise.
- Reconstruction : les documents du lot 6 se rejouent ; `compare` couvre change,
  compositions, virements appariés et abonnements. Raiffeisen (camt.053) couvert par un test.

### Lot 5 — Collecteurs

- Cœur : schéma `0002_collectors` (type de passage, contrôle demandé, liaisons), table des
  échecs de la section 8 (suspension, alertes, retour manuel après un contrôle réussi),
  alertes ntfy génériques, routes `/api/collectors` (état, passages, mode, contrôle, liaison
  Revolut et page de retour), purge nocturne des liaisons.
- Paquet `hub.collectors` (image `collector`, Chromium de Playwright 1.63) : dépôt atomique
  dans la boîte d'entrée avec contrôle de forme et quarantaine, sélecteurs nommés et liste
  blanche de clics, captures `--diagnose` purgées après 7 jours, boucle planifiée.
- Bot BCF (camt.053 depuis J-10, validation push de 3 min, refus détecté tout de suite) et bot
  VIAC (liste Documents, avis nouveaux, rapport tous les 6 jours, `relogin` avec code 2FA tapé
  dans le conteneur), sélecteurs repris des scripts du Mac.
- Revolut par Enable Banking : JWT RS256, liaison avec reprise complète dans la fenêtre de
  5 minutes, au plus 4 synchros par jour, alerte avant la fin du consentement.
- Finance : import des JSON Enable Banking et du CSV Revolut (comptes `revolut:<devise>`,
  ouverture au solde déduit), `fin revolut pending` et `add-account`.
- App : carte Collecteurs dans l'onglet Sources (désactiver, contrôler, réactiver).
- Compose : services `collector-bcf`, `collector-viac`, `collector-revolut` (profil
  `collectors`, un volume et un fichier de secrets chacun) ; l'API lit le sujet ntfy ; CI :
  Chromium pour les tests, image collecteur.

### Lot 4 — VIAC et patrimoine minimal

- Schéma `0005_viac` : instruments, opérations (`trades`), positions (`holdings`) et cours
  (`prices`) en ajout seul et chaînés au journal, `rebuild_meta`, catégories `transfer-titres`,
  `rendement` et `frais-placement`, règles système des codes `VIAC/…`.
- PDF VIAC : `pdftotext -layout` isolé (processus séparé, délai, mémoire et taille plafonnés,
  rien sur le disque), parseurs des avis (achat, vente, dividende, intérêts, commission,
  versement, retrait) et du rapport portés de `viac_parser.py` et `viac_rapport.py` ;
  attestations et relevés reconnus et ignorés, le reste refusé.
- Deux comptes par portefeuille (liquidités 3a et titres) ; boîte d'entrée et dépôt par l'API
  acceptent les `.pdf` ; `hub finance viac add-portfolio` et `viac import-history`.
- Valorisation des titres par positions et cours, versements nets hors rendement et frais
  (l'effet marché n'est plus nul), marge 3a d'après les versements VIAC, valeur de marché dans
  `accounts`, route `holdings`, carte Positions dans l'onglet Patrimoine.
- `hub finance rebuild` (reconstruction du registre par rejeu, nouvelle époque du journal) et
  `hub finance compare`.
- Image et CI : poppler-utils.

### Lot 3 — Catégories et Double Sas

- Moteur de règles (`0004_rules`) : la règle active la plus prioritaire gagne, appliquée à
  l'import et par `hub finance rules run` ; une catégorisation humaine n'est jamais remplacée.
  Les règles et catégories de `bcf_aggregate.py` sont reprises (`seed-`), et
  `hub finance rules import-legacy` reprend le fichier de règles du Mac ; mêmes catégories que
  le script sur les relevés fictifs.
- Double Sas côté cœur : défi WebAuthn qui porte l'empreinte du lot (`/approvals/challenge`),
  validation par lot (`/proposals/accept`), revendication par révision, empreinte revérifiée
  sous le verrou d'écriture (nouvelle révision et 409 si elle a changé), aucun double effet
  même si le COMMIT échoue, inverse d'un geste (`/proposals/{id}/revert`), résumé du jour
  (`/digest`), paliers `human`, `auto_digest`, `auto`.
- Handlers Finance : `recategorize`, `create_rule`, `disable_rule`, `set_budget`, `add_note`,
  `apply_import` (relevé en attente à forcer), `create_account`, `create_category` ; le CLI
  comptes et catégories passe désormais par une proposition.
- `hub proposals list|show|accept|reject|create`.
- App : carte « À valider » (un Face ID pour le lot), « À catégoriser » groupé par
  contrepartie dans le Journal, avec « Ces N écritures » et « Toujours » (règle).
- Correctif : après la première connexion, la barre d'onglets restait vide jusqu'au
  rechargement.

### Lot 2 — App en lecture

- Instantanés du patrimoine (`0003_snapshots`) : une ligne par fin de mois et une pour
  aujourd'hui, recalculées par la tâche de nuit et par l'événement `import.applied` (curseur
  dans la boîte de sortie) ; la série stockée égale le calcul direct.
- Routes de l'app : `kpis`, `networth/history`, `flows`, `budget/totals`, `budget/months`,
  `export.csv` ; `budget` prend `period=m|q` et rend reste à vivre et jours restants. Mois
  toujours en paramètre, début d'année au 31 décembre, rapports en décimales texte.
- Écritures sans catégorie comptées en dépense variable (débit) ou en revenu (crédit) dans
  le résumé, le budget et la tendance, en attendant les règles du lot 3.
- Port du dashboard : d3 7.9.0 servi par le hub, `store.js` à la place du runtime `dash.*`,
  CSS et JS en fichiers (CSP stricte respectée), vues Accueil, Patrimoine, Budget, Journal
  et Sources, bandeau « relevé du … », comptes périmés et écrans sans donnée.

### Lot 1 — Registre BCF

- Base `finance.db` (`0001_ledger`, `0002_fts`) : comptes, imports et relevés, registre
  `entries` en ajout seul, catégories et règles, catégorisations et ventilations, notes,
  checkpoints, budgets, tags, `applied_proposals`, `events`, `fx_rates` (vide au lot 1).
  Journal chaîné commun à toutes les tables protégées et empreintes versionnées (`hash_v`).
- `ledger.append()` dans `BEGIN IMMEDIATE`, identifiant d'écriture déterministe,
  `hub finance verify-ledger`, branché sur `hub verify` et la tâche de nuit.
- Fabrique de relevés camt.053 .04 et .08 fictifs, valides contre les XSD ISO 20022.
- Parseur durci (lxml sans entités, sans réseau, DOCTYPE refusé, 20 Mo au plus), version lue
  dans l'espace de noms, table de correspondance unique, découpage des écritures groupées.
- Clé de dédoublonnage versionnée (`v1|`) avec rang d'occurrence et référence de détail.
- Service d'import : boîte d'entrée (xml et zip), lots triés par compte et date, une
  transaction par relevé, rapprochement interne et registre, anomalies en liste fermée,
  rejeu des relevés en attente, archivage chiffré par age, virements entre comptes propres.
- `hub finance import-history` : continuité vérifiée avant d'écrire, ouverture explicite,
  boîte d'entrée en pause pendant la reprise.
- API de lecture : comptes, écritures paginées, détail, résumé, budget, tendance, à
  catégoriser, recherche FTS5 trigram, catégories, fraîcheur, dépôt et suivi d'un import.
- CLI comptes et catégories (écriture directe en attendant le Double Sas).
- Contrat de domaine : `verify()` (contrôle profond) à côté de `health()`.

### Lot 0 — Socle

- Dépôt et outillage : uv (lockfile), ruff, mypy strict, pytest avec couverture, Hypothesis,
  import-linter, pre-commit, `scripts/check_no_data.sh`, gitleaks, image `linux/arm64`.
- Intégration continue : barrières de la section 11 et construction des images arm64.
- Fondations du cœur : réglages TOML + variables d'environnement, `Money` et devises,
  `normalize()`, masque d'IBAN, ULID et URN, acteurs, journaux JSON filtrés, erreurs
  `problem+json`, secrets chiffrés age déchiffrés en mémoire.
- Contrat de domaine (manifeste, `ProposalKind`, handlers locaux et externes) et registre par
  point d'entrée `hub.domains`.
- Base `core.db` (migration `0001_core_init`) : jetons, passkeys, sessions, codes d'amorçage,
  propositions (9 statuts, `params_hash`, `create_key`, `bundle_id`, `signature_json`),
  audit et liens en ajout seul, politiques d'approbation, défis WebAuthn, limites de débit.
- API : `/api/health`, jetons à portée par domaine, propositions à création idempotente,
  recherche, résolution d'URN, liens, schéma OpenAPI figé par un instantané.
- Passkeys : inscription par code d'amorçage, seconde passkey depuis une session, connexion,
  session de 12 h (`HttpOnly`, `Secure`, `SameSite=Strict`).
- Conteneurs sur le Mac : compose unique (Mac puis Pi), Caddy, Tailscale serve, Litestream,
  planificateur, `deploy.sh` avec retour arrière automatique, test de restauration.
- Coquille PWA : connexion passkey, page d'état, CSP stricte sans script en ligne.
- Kit de secours : modèle à imprimer.
