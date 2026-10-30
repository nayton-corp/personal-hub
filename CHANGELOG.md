# Journal des changements

## [Non publié]

## [0.13.3] · 2026-10-30

### Sécurité

- L'image hub passe à restic 0.19.1 : le binaire de la 0.18.1, compilé avec Go 1.25.1, portait
  deux failles critiques corrigées (grpc CVE-2026-33186, crypto/tls CVE-2025-68121), qui
  bloquaient la publication de 0.13.2.
- La CI des pull requests passe les trois images à la même barrière Trivy que la release
  (critiques corrigeables) : une faille bloque la PR avant le tag, plus une version publiée.

## [0.13.2] · 2026-10-30

### Sécurité

- Les trois images (hub, web, collecteurs) appliquent les correctifs de sécurité des paquets
  de leur base à la construction : brotli-libs (CVE-2026-111497) bloquait la publication de
  0.13.1.

## [0.13.1] · 2026-10-30

### Sécurité

- L'image web passe à Caddy 2.11.7 : la 2.10.2 portait quatre failles critiques corrigées
  (smallstep/certificates, grpc, crypto/tls de Go), qui bloquaient la publication de 0.13.0.

## [0.13.0] · 2026-10-30

### Domaine Documents (chantier S12)

- Les fiches d'objets de la maison et leurs documents (notices, contrats, garanties, courriels)
  dans le hub : un bloc d'accueil (entretiens dus, derniers documents), `/api/documents/…`, des
  outils pour l'assistant qui citent source et page, la recherche et un constat « entretien ».
- Une archive chiffrée dont la base se reconstruit seule (`hub documents rebuild --check`) ;
  un index local des passages (FTS5).
- Un document est privé tant qu'il n'est pas marqué « foyer » (une carte, réversible) ; la
  portée `documents:household` n'ouvre que cette part et les fiches.
- Reprise unique de la bibliothèque de Domia : `hub documents import-library DIR`.

### Domaine Agenda (chantier S11)

- Rappels et Calendrier du Mac dans le hub, par le pont EventKit (`assistant/eventkit`) : un
  bloc d'accueil (la semaine, les rappels ouverts, la liste de courses), `/api/agenda/…`, des
  outils pour l'assistant, la recherche et un constat « rappels en retard ».
- Ajouter un rappel, un événement, cocher : des cartes à valider ; un article sur la liste de
  courses : automatique. Jamais de suppression. Aucune copie dans le hub ; les envois sont
  tracés pour l'idempotence et la réconciliation.
- L'API joint le pont par `host.docker.internal` (`[agenda]` de `deploy/settings.toml`).

### Paliers d'approbation réglables (chantier S11)

- Un type de proposition déclare son palier par défaut (`human`, `auto_digest` ou `auto`) ;
  `hub proposals policy` montre et change les paliers. Un modèle reste à la carte tant qu'il
  ne déclare pas « pas de texte externe ».

### Un seul assistant, venu de Domia (chantier S10)

- L'assistant de Domia arrive dans `assistant/`, avec ses 149 tests, son banc, ses gabarits de
  modèle, ses LaunchAgents et le pont Rappels/Calendrier (`eventkit/`) : un paquet à part, testé
  par sa propre tâche de CI (`make assistant-test`).
- Le contrat avec l'API de Domia est figé dans `assistant/domia_assistant/contract/`
  (`make domia-contract DOMIA=~/domia`).
- L'assistant reprend les outils des domaines du hub (`hub_capabilities`), un type de demande
  par domaine : montrés et ouverts aux seules personnes de `hub.owners` (jamais à Kim ni à une
  voix de pièce), avec le jeton des agrégats ; un domaine lu en entier est écarté.
- Plus de conteneur `brain` : l'assistant tourne en natif sur le Mac et fait aussi le
  classement du matin (`classify`, jeton `brain`, même modèle résident). Les jetons restent
  chiffrés par age (`brain.enc.yaml`). À retirer de `deploy/.env` : `,brain` dans
  `COMPOSE_PROFILES`, `HUB_BRAIN_SECRETS`, `HUB_BRAIN_MODEL`.

### Recherche, liens et constats (chantier S9)

- `/api/search` fusionne les domaines par rang : chaque résultat dit son domaine, son rang dans
  ce domaine et le passage trouvé ; un domaine aux scores plus grands ne prend plus toute la
  page.
- Lier deux objets de deux domaines passe par une carte : type de proposition `core/link`,
  réversible d'un geste (`core/unlink`). `core.db` gagne le journal chaîné, `applied_proposals`
  et `events` (migration `0008_core_ledger`), contrôlés par `hub verify`.
- `GET /api/observations` réunit les constats de chaque domaine ; l'accueil et les liens des
  notifications y lisent les sentinelles de la finance (`/api/finance/alerts` retirée).

### Documentation (chantier S14)

- `vision.md`, `docs/architecture.md` (anneaux, Double Sas, boîte d'entrée, finance en
  sous-contextes, en schémas), `docs/ajouter-un-domaine.md`, `docs/securite.md`,
  `docs/exploitation/` (installation, Mac, versions, kit de secours, gestes réguliers),
  `hub/domains/finance/README.md` ; README réécrit en index.
- Références générées depuis le code : routes de l'API, outils de l'assistant, connecteurs
  (`docs/reference/`, `make reference`). Une référence périmée, un lien relatif cassé, ou une
  recette d'ajout de domaine que le domaine factice ne suit plus font échouer la CI.

### Finance en couches (chantier S6)

- La finance est rangée en quatre sous-contextes (registre, classement, patrimoine, sources),
  chacun en couches interface → app → infra → model ; import-linter les impose sans écart.
- L'importeur, les propositions, les lectures, les outils, la CLI, IBKR, la performance et la
  transparence des fonds sont découpés : plus aucun fichier de la finance au-delà de 400 lignes.
- Imports circulaires cassés : les bords reçoivent `port.Finance`, l'ouverture d'un compte vit
  dans le registre, la lecture des fichiers IBKR et `hub.market.v1` dans `sources/infra`.
- `public.py` : la seule lecture de la finance permise aux autres domaines (agrégats).
- Aucun changement de comportement : mêmes routes, commandes et outils ; une base d'avant,
  reconstruite par `hub finance rebuild`, se compare sans écart.

### App modulaire (chantier S5)

- La coquille de l'app (`shell.js`, `sources.js`) monte les domaines d'après leurs manifestes :
  barre d'onglets, blocs de l'accueil, rubriques de Sources et réglages, actions. La finance
  devient un module comme un autre (`finance.js`, rubriques dans `settings.js`).
- Le manifeste gagne `home` (bloc d'accueil) et `module` (module du domaine) ; un domaine qui
  reprend un écran de la coquille ou d'un autre domaine est refusé au démarrage.
- Écrans identiques à 375 px avant et après (captures comparées, chaque rubrique comprise).

### Sauvegarde et exploitation sans liste en dur (chantier S7)

- `hub ops databases` et `hub ops litestream` : les bases (core, puis chaque domaine monté)
  viennent du registre. `deploy.sh` écrit `deploy/litestream.local.yml` à chaque déploiement
  et le monte dans Litestream ; `deploy/litestream.yml` (le défaut) est vérifié par la CI.
- `restore-test.sh` restaure chaque base de la liste, et plus seulement `core.db`.
- Le contrôle de santé de `deploy.sh` exige `"status":"ok"` (core et chaque domaine monté),
  plus seulement une réponse.
- `deploy/tailscale-acl.hujson` : la politique Tailscale versionnée (seul le propriétaire
  atteint le port 443 du hub).

### Boîte d'entrée par domaine (chantier S4)

- `hub watch-inbox` (service `importer`) confie chaque fichier posé à la racine de `inbox/` au
  domaine qui le réclame (importeurs du manifeste) : il part dans `inbox/<domaine>/`, puis
  chaque domaine traite son dossier (`Domain.process_inbox`). Un fichier réclamé par personne
  reste à la racine ; un nom déjà pris devient `nom-2`.
- Les collecteurs déposent dans `inbox/<domaine de leur connecteur>/` ; le catalogue sait de
  quel domaine vient chaque connecteur.
- L'archive chiffrée de la finance vit dans `archive/finance/` ; la migration déplace une fois
  `archive/AAAA/` et `archive/duplicates/` (les chemins gardés en base restent valables).
- `hub finance watch-inbox` lit désormais `inbox/finance/`.

### Intégrité générique (chantier S3)

- `hub.kernel.chain` (empreinte versionnée, maillon) et `hub.core.integrity` (`Ledger` :
  ajout, vérification, `applied_proposals`, `events`, aides de migration `schema()` et
  `append_only()`) : un domaine neuf a son registre d'ajout seul sans le réécrire.
- La finance s'en sert : `ledger.append` et `ledger.verify` délèguent au cœur, ses champs
  hachés restent dans `hashing.FIELDS`. Même tête de chaîne qu'avant (test de référence).
- Le domaine factice tient ses propositions et événements dans le registre commun ; `hub
  verify` le rejoue.

### Jetons à date de fin, par domaine (chantier S8)

- Chaque jeton a une date de fin (`--days`, 90 par défaut, 366 au plus) ; un jeton fini est
  refusé. Migration `core` 0007 : les jetons existants reçoivent un an depuis leur création.
- `hub token rotate ID` : nouveau secret, mêmes portées, l'ancien révoqué.
- La tâche de nuit prévient par ntfy 14 jours avant la fin, une fois par jeton, avec la
  commande à lancer (pour un service collecteur : recréer son fichier de secrets).
- Le raccourci `brain` n'ouvre plus que les agrégats ; `brain=finance` ajoute lecture et
  propositions des domaines nommés. Les jetons déjà créés gardent leurs portées.
- Les commandes `hub token …` passent dans `hub/cli_tokens.py`.

### Contrat de domaine v2 (chantier S2)

- Manifeste d'un domaine (`hub.core.manifest`) : onglets, cartes d'accueil, rubriques de
  réglages et module des cartes à valider pour l'app ; importeurs (les fichiers de la boîte
  d'entrée qu'il réclame) ; connecteurs ; tables protégées ; consignes pour l'assistant. Les
  constats arrivent par `Domain.observations()` (la finance y verse ses alertes).
- `GET /api/domains` : les domaines actifs et leurs manifestes, pour la coquille de l'app (S5).
  `GET /api/tools` donne aussi les consignes de chaque domaine à l'assistant.
- `HUB_DOMAINS` (`*` par défaut) choisit les domaines montés : un domaine éteint n'a ni base,
  ni route, ni onglet, ni connecteur. Un nom inconnu empêche le démarrage.
- `hub verify` contrôle que chaque table protégée garde ses triggers d'ajout seul.
- Un manifeste invalide (identifiant, module, extension) est refusé à l'enregistrement.

## [0.12.0] · 2026-10-29

### Le cœur ne nomme plus aucune source (chantier S1, seconde partie)

- Le catalogue des connecteurs, les modules par pays (3e pilier en Suisse) et la reprise des
  connexions d'avant G4 passent de `hub/core` à `hub/domains/finance` (`connectors.py`,
  `legacy_connections.py`). Le cœur les lit par trois points d'entrée du paquet
  (`hub.connectors`, `hub.country_modules`, `hub.connection_imports`) via
  `registry.contributions`. Aucun changement de comportement ni de schéma.
- La liaison d'un consentement vaut pour tout connecteur de méthode `open_banking`, plus
  seulement `enable_banking`.
- `tests/test_core_is_generic.py` : un nom de banque, de source ou de notion financière dans
  `hub/core` fait échouer la CI.

### Noyau, plateforme et cœur séparés (chantier S1, première partie)

- `hub/kernel` (argent, URN, horloge, JSON canonique, texte) et `hub/platform` (SQLite,
  migrations, réglages, secrets, journaux, planificateur) sortent de `hub/core`. Déplacements
  seuls, sans changement de comportement ; le lanceur de migrations devient
  `hub.platform.migrations`.
- Import-linter : les étages domaines → cœur → plateforme → noyau ne s'importent que vers le
  bas ; le noyau n'importe aucune bibliothèque d'E/S, la plateforme ni le cœur ni HTTP.

### App web testée et instance d'essai (chantier S13, suite)

- `scripts/demo_data.py` : un an de relevés camt.053 fictifs pour deux comptes, bibliothèque
  standard seulement.
- `tests/web/test_app_mobile.py` : l'app dans Chromium à 375 px, première passkey par un
  authentificateur virtuel, cinq écrans sans erreur ni défilement horizontal ; captures en
  artefact de la CI.
- Lint de l'app par Biome (`biome.json`) et tests des modules par `node --test` (`make web`).
  Deux affectations dans une expression corrigées (`perf.js`, `wealth.js`).
- `deploy/trial.sh` (`make trial`) : instance d'essai jetable, données fictives créées par la
  version en place puis migrées et vérifiées par la nouvelle. `make deploy` la lance avant de
  toucher aux bases ; la CI la lance sur l'image arm64.

### Versions publiées et CI/CD (chantier S13)

- Une seule version, celle de `pyproject.toml` : `hub.__version__` la lit, `/api/health` la
  rend, et l'instantané OpenAPI ne la fige plus. `make release VERSION=X.Y.Z` prépare la PR de
  version (pyproject, `uv.lock`, section du CHANGELOG) ; `make tag` pose le tag sur main.
- Workflow `Release` sur un tag `vX.Y.Z` : barrières de la CI, images linux/arm64 poussées sur
  GHCR avec SBOM et provenance, analyse Trivy, release GitHub avec notes et empreintes.
- `make deploy TAG=vX.Y.Z` tire les images publiées (clone sur le tag, version de l'image
  vérifiée) ; `HUB_BUILD=1` ou un autre tag construit sur le Mac comme avant.
- CI : migration depuis la dernière version taguée sur bases et relevé fictifs
  (`make upgrade-test`), cohérence de la version, `pip-audit` (`make audit`).
- Dependabot : une PR groupée par semaine pour Python, les actions et les images du compose.
- `docs/exploitation/versions.md`, décision D-015.

### Garde-fous du socle (chantier S0)

- Cinq contrats import-linter de plus décrivent l'architecture visée : un noyau pur, une
  plateforme sans métier, un cœur sans FastAPI ni Typer, des modules purs dans la finance, et une
  interface que personne n'importe. Les écarts d'aujourd'hui sont listés dans `pyproject.toml`
  et ne peuvent que disparaître (`unmatched_ignore_imports_alerting = "error"`).
- `tests/test_file_size.py` : 400 lignes au plus par fichier Python ou JavaScript de `hub/` ;
  les 23 fichiers plus longs sont listés avec leur taille, qui ne peut que baisser.
- `tests/test_log_safety.py` : un nom d'événement fixe, aucune clé interdite, jamais `str(exc)`
  dans un journal (5 écarts listés dans les collecteurs). Le filtre refuse aussi `description`,
  `merchant`, `question`, `answer` et `prompt`.
- `docs/glossaire.md` et `docs/decisions.md`.

### Historique des wallets ETH malgré les limites des sources publiques

- Ethereum : historique par Routescan (sans clé) au lieu de Blockscout, qui coupe après dix
  appels. Arbitrum, Base et Polygon : Etherscan V2 avec une clé gratuite (`etherscan_key`,
  champ « Clé Etherscan » dans l'app) ; sans clé, `needs_key` dans le détail, sans échec.
- Chaque réseau est relu en entier une fois (mémoire `<compte>@<réseau>`, `<compte>@solana`).
- Pause entre deux pages d'historique et entre deux cours CoinGecko sans clé ; un refus (429,
  « rate limit ») est réessayé après 10, 30 puis 60 secondes.
- Coinbase : la conversion ETH2 → ETH (`retail_eth2_deprecation`) est interne.
- Réseau BNB Smart Chain (`bsc` : BNB, USDC, USDT, ETH) ; un réseau refusé par l'offre gratuite
  d'Etherscan est signalé (`unsupported`) sans bloquer les autres.
- Portefeuille ATOM (Cosmos Hub) : disponible, staking, retraits en cours, récompenses, et
  historique des transactions.

### Collectes en parallèle

- Les services collecteurs lancent chaque run dans son fil : un run lent (market, 17 minutes
  le 29/10 à cause de mempool.space) ne retarde plus les autres connexions ni leurs
  actualisations. Une connexion n'a jamais deux runs à la fois.

### Un portefeuille crypto s'ajoute dans « Cours et cryptos »

- « Cours et cryptos » (`market`) est une connexion unique (`single`) : en créer une deuxième
  est refusé (`connection.single`), car un portefeuille ajouté ainsi restait sans adresse. Dans
  l'app, choisir ce connecteur quand il existe ouvre ses réglages avec un nouveau portefeuille à
  remplir (« Ajouter un portefeuille »).
- « Nom affiché de la connexion » : le nom de la connexion, pas celui d'un portefeuille.

### Actualiser une connexion depuis l'app

- « Actualiser » sur chaque connexion et « Tout actualiser » (Réglages › Connexions) : un run
  complet hors horaire, lancé dans la minute par le service collecteur (`POST
  /api/collectors/<id>/refresh`, `POST /api/collectors/refresh`). Seulement pour une connexion
  prête et active (`collector.not_enabled` sinon). La ligne montre « actualisation en cours »,
  puis l'issue et l'heure du dernier passage ; l'app relit ses chiffres après l'import.
- Les limites des sources restent dans les flux : push BCF à valider, quatre synchros par jour
  pour Enable Banking (« quota du jour atteint »).
- Horaires par défaut : cours, portefeuilles et plateformes crypto toutes les 4 heures de 06:15
  à 22:15 (au lieu d'une fois par jour).
- Migration core `0006_collector_refresh` (`collector_state.run_requested_at`).

### Écritures crypto natives pour chaque connecteur

- Règle : un connecteur crypto apporte ses écritures, pas seulement ses soldes. `runner(fetch,
  history)` exige une lecture d'historique et un test refuse un connecteur crypto ou une chaîne
  de portefeuille qui n'en a pas.
- Coinbase : transactions de tous les portefeuilles (achats, ventes, conversions, envois avec
  frais de réseau, récompenses, virements), à la valeur donnée par Coinbase.
- KuCoin : grand livre par tranches de 24 heures, un an (ce que KuCoin garde).
- Portefeuilles ETH (Blockscout, jetons suivis et gaz) et SOL (RPC) : leurs transactions au
  registre, reliées aux plateformes par le txId. Le solde passé n'est pas reconstitué.
- Portefeuille ETH multi-réseau : `networks` (Ethereum, Arbitrum, Base, Polygon), soldes et
  historique sur chacun ; cases « Réseaux » dans l'app. Jetons de staking (`staking_tokens`,
  Kiln cbwsETH) comptés comme de l'ETH à leur valeur sous-jacente.
- Socle commun `exchanges/history.py` ; une jambe d'opération peut porter sa valeur
  (`value`, `value_currency`).

### Binance : récompenses Earn relues

- Les historiques de récompenses Simple Earn refusent une période de plus de 30 jours
  (`-6021`) : fenêtres de 29 jours. Les récompenses manquées depuis la v0.9.9 sont relues une
  fois depuis la première opération (mémoire `rewards_since`, `first_day`).

### Dettes dans le patrimoine : crédit, hypothèque, leasing, prêt étudiant

- Nouvelles tables `debts` et `debt_balances` (migration `0016_debts`). Une dette part d'un
  solde à une date, ou du versement reçu du prêteur choisi dans le Journal (« Créer une dette
  depuis ce versement »).
- Son solde baisse de chaque paiement de sa catégorie (depuis son compte s'il est choisi), quel
  que soit le montant : une mensualité qui change suit d'elle-même. Intérêts courus au taux
  annuel s'il y en a un ; un relevé du prêteur (`record_debt_balance`) remplace le calcul à
  partir de sa date. Mensualité et échéance facultatives : sans mensualité, la fin projetée suit
  les derniers paiements. Une dette se marque soldée ou se rouvre.
- Le patrimoine est net : enveloppe `dettes`, clé `debt:<id>` dans `by_account`, ligne « Dettes »
  dans l'écran Patrimoine (détail : remboursé, paiements, fin projetée). Un remboursement compte
  comme versement, seuls les intérêts font baisser le patrimoine. `GET /finance/debts`, carte
  « Dettes » dans les réglages, propositions `save_debt` et `record_debt_balance` (Face ID).

### Diagramme de flux du budget plus lisible

- Les flux ne se croisent plus : revenus (du plus gros au plus petit) et groupes sont empilés dans le même ordre, et chaque revenu remplit les groupes dans l'ordre Fixes, Variables, Épargne, Reste. Un petit revenu (remboursement) ne s'étale plus en filets vers tous les groupes.
- Une couleur par groupe, de la source jusqu'aux postes : flux, barre du groupe et barres de ses postes. Les Fixes passent en bleu pour ne plus ressembler au Reste gris (même couleur dans l'historique des mois).
- Toucher un revenu n'allume que les groupes et postes qu'il alimente vraiment.

### Historique Binance dans le Journal, mouvements crypto reliés entre mes comptes

- Le collecteur Binance lit, en plus des soldes, les dépôts et retraits crypto (txId, adresse),
  les virements en monnaie, les achats par carte, les ordres exécutés, les conversions, les
  récompenses Simple Earn, les distributions et les petits soldes convertis en BNB
  (`binance_history.py`). Premier passage complet ou rien, ensuite trois jours de recouvrement.
- Ces opérations deviennent des écritures du compte `crypto:binance` en devise de base, codes
  `EXCHANGE/…` (règles système, migration `0015_exchange_journal`), et des mouvements de parts
  (`exchange.py`). Clôtures Binance et change BCE déposés avec l'historique.
- Un envoi ou une arrivée crypto est relié à l'autre côté sur un autre de mes comptes (Ledger,
  Binance, SwissBorg) par le txId, sinon la quantité, à cinq jours près (`links.py`) : le second
  prend la valeur du premier et la paire passe avant les autres virements.

### Budget proposé par l'assistant, au mois ou à l'année

- `finance_propose_budget` prend `cadence` (`month` par défaut, ou `year` : `amount` est alors
  la cible annuelle, suivie en cumul depuis janvier). Un budget complet se propose d'un coup et
  se valide d'un seul Face ID.

### « À classer » : dépenses et entrées à confirmer séparées

- En tête de « À classer », un sélecteur « À classer / À confirmer » (avec leur nombre) montre
  soit les écritures sans catégorie, soit celles classées d'office par la règle « tout le
  reste », au lieu de les mettre bout à bout.

### Achats uniques : une carte par catégorie

- `categorize_entries` : une catégorie pour quelques écritures choisies (30 au plus), une seule
  carte. L'outil `finance_propose_categories` la propose (16 outils Finance) ;
  `finance_to_review` prend `offset` pour parcourir toute la file.
- IA locale : `hub-brain direct` classe les commerçants vus une seule fois, sans créer de
  règle ; les cartes se déplient dans « À valider » pour décocher une écriture.
- `HUB_PROPOSALS_PER_HOUR` (deploy/.env) règle la limite de cartes par heure et par jeton ;
  `catchup --limit` va au-delà de 50 quand elle est relevée.

### Classer plus vite : commerçant lu dans le libellé, revenus à confirmer, rattrapage par l'IA

- Les paiements par carte BCF (« Paiement jj.mm.aaaa hh:mm COMMERÇANTVILLE Numéro de carte… »,
  l'ancien format « Paiement - COMMERÇANT, VILLE - … », Maestro, remboursements), les retraits
  et TWINT n'ont pas de vraie contrepartie : le commerçant est lu dans le libellé (ville et
  numéro de magasin coupés, `merchant.py`). « À classer » groupe par commerçant au lieu d'un
  groupe par achat, l'écriture le donne (`merchant`) comme titre et motif de « Toujours ».
- Un crédit classé par la règle « tout le reste » (« Autres revenus ») revient dans « À classer »
  sous « À confirmer » (`guess` dans `/finance/review`).
- `categorize_rest` : les dépenses encore sans catégorie d'avant une date prennent une catégorie
  d'un coup (« Classer d'un coup tout l'ancien… »).
- « Toujours » peut se limiter au compte de l'écriture (« Seulement depuis ce compte ») ; la
  règle seule est proposée quand elle classe aussi l'écriture, ce qui évitait « a changé
  entre-temps ».
- Packs v2 : `base` reconnaît le salaire par le code bancaire `PMNT/RCDT/SALA`, ajoute
  « Intérêts et dividendes », « Ventes d'occasion », « Aides et allocations » et « Divers » ;
  `ch` connaît plus d'enseignes. « À classer » propose la mise à jour (`install_pack`).
- IA locale : `hub-brain catchup` propose une règle par commerçant de la file (50 au plus, sous
  la limite de 60 propositions par heure), à valider ensemble dans « À valider ».
  `finance_propose_rule` prend `direction` ; ses règles ont la priorité 10.

### Poches Revolut : virement reconnu après une recharge du même montant

- Quand la BCF recharge le compte Revolut puis que l'argent part le jour même vers une poche,
  le même montant apparaît deux fois en débit et l'appariement renonçait. Les paires compte ↔
  poche (même établissement, un jour d'écart, seuls candidats entre eux) sont maintenant
  trouvées d'abord, et ce qu'elles expliquent ne rend plus la recharge BCF ambiguë.

### Poches et enveloppes : virements, règle d'un compte, budget annuel

- Les mouvements entre deux comptes du même établissement (le compte Revolut et ses poches),
  de même montant, à un jour d'écart au plus et sans autre candidat, sont appariés comme
  virements, même sans IBAN ni code de virement.
- Un virement apparié passe avant une règle « tout le reste » (motif vide, comme « tout crédit
  restant → Autres revenus ») : il est montré et compté comme « Virement entre mes comptes »
  (vue `v_entry_shown`, migration finance 0014). Une catégorie choisie ou posée par une règle
  précise reste la sienne. Les deux côtés quittent aussi « À classer ».
- Règle d'un compte (`create_rule` avec `account_id`, motif vide permis) : dans les réglages
  d'un compte, « Dépenses de ce compte » range toutes ses sorties dans une catégorie (une poche
  Vacances), celles déjà importées comme les prochaines. `/finance/accounts` donne
  `spend_rule`.
- Budget annuel : `set_budget` accepte `cadence` (`month` ou `year`, table `budget_cadence`).
  Une catégorie suivie à l'année est comparée au cumul depuis janvier (`yearly` dans les lignes
  du budget), sort du budget et du reste à vivre du mois (`budgeted_expenses`) et n'alerte
  qu'au dépassement annuel. Dans l'app : « Par mois / Par an » dans la fiche d'une catégorie.
- Catégories « Voiture : crédit » (fixe) et « Voiture : frais » (variable : entretien, assurance, impôt et vignette).

### Mois budgétaire, création du budget et journal revu

- Réglage « Le mois commence le » (1 à 28, `GET/POST /finance/settings`, table
  `budget_period` dans la migration 0013) : budget, flux, tendance, projection, sentinelles et
  outils découpent les mois à partir de ce jour. Après le 15, le mois porte le nom de sa fin.
  Le Budget affiche alors les dates exactes sous le mois.
- « Créer mon budget » : une cible par catégorie de dépense, proposée d'après la moyenne des
  3 derniers mois et arrondie à la dizaine, modifiable, validée en une fois avec Face ID.
- Journal : panneau de filtres (compte, catégorie, période, montant), tri par plus gros
  montant, puces des filtres actifs ; la recherche se combine aux filtres et se pagine
  (`/finance/entries` accepte `min_minor`, `max_minor`, `q`, `sort`).
- « À classer » : chaque groupe montre ses comptes, ses dates, la fourchette des montants et
  les libellés bancaires, et se déplie sur ses dernières écritures.

### Comptes : fraîcheur juste et réglages dans l'app

- La fraîcheur d'un compte vient de sa dernière donnée (écriture, position, ordre ou solde de
  clôture) et de son dernier import, y compris pour les comptes sans relevé bancaire (Revolut,
  SwissBorg, Ledger, titres) et les sous-comptes IBKR. « Comptes à rafraîchir » de l'accueil
  suit la même règle et ignore les comptes jamais alimentés ou masqués.
- Réglages d'un compte, validés avec Face ID (proposition `edit_account`, migration finance
  0013) : nom, objectif, disponibilité, catégorie imposée à tout le compte, masquage. Un compte
  masqué sort du patrimoine et de l'accueil, sans rien effacer. La carte « Comptes » des
  réglages liste la fraîcheur et ouvre ces réglages ; le détail d'un compte aussi.

### Construction des images plus rapide

- Les images hub et collector ne copient plus `hub/web` : une retouche du front ne
  reconstruit que l'image web. Seul le paquet hub est recompilé en bytecode à chaque
  version, plus tout l'environnement Python.
- `make deploy` ne finit plus en erreur sur macOS : une apostrophe dans `${…:-…}` cassait
  le bash 3.2 du Mac après le déploiement.

### Hub générique, G6 — première installation

- `make init` (`hub init` dans un conteneur jetable, seul Docker requis) : clé age en 0400,
  `secrets.enc.yaml` avec un mot de passe restic tiré au hasard et jamais affiché, dossiers
  montés, `deploy/.env` écrit depuis `.env.example`. Ne remplace rien de ce qui existe.
- `HUB_COUNTRY` : pays d'une instance sans profil, qui choisit le pack de règles d'une base
  neuve (CH par défaut, rien ne change pour une instance existante).
- Le premier `make deploy` affiche le code d'inscription de la première passkey.
- App : carte « Premiers pas » sur l'accueil (passkey de secours, profil, règles, première
  connexion, premier compte), qui remplace le texte « Pas encore de données ». Les packs de
  règles du pays s'installent par une proposition `install_pack` validée avec Face ID ;
  `GET /api/finance/rules/packs` les liste.
- Guide générique [docs/exploitation/installation.md](docs/exploitation/installation.md) ; `docs/exploitation/mac.md` reste pour ce
  qui est propre au Mac.

### Cryptos au registre — SwissBorg et portefeuille BTC

- Chaque ligne du relevé SwissBorg devient une opération du compte `crypto:swissborg` en CHF
  (dépôt, retrait, achat, vente, rendement, frais) et un mouvement de parts : prix de revient,
  rendements et frais comme pour IBKR. Codes `SWISSBORG/…` déclarés dans `institutions`,
  règles système par la migration `0011_crypto_journal`. Le coût d'une crypto vient de ses
  opérations quand il y en a, sinon de la valeur à l'arrivée.
- Portefeuille BTC : le collecteur `market` dépose ses transactions (toutes au premier passage,
  mémoire `btc_txs`, ensuite la dernière page de chaque adresse) ; chacune devient une
  opération du compte (`CRYPTO/RECEIVE`, `CRYPTO/SEND`, `CRYPTO/FEE`) et un mouvement de
  parts. Une arrivée de la quantité nette d'un retrait SwissBorg prend sa valeur et s'apparie
  avec lui comme un virement entre mes comptes.
- `fin imports replay <source>` : réapplique depuis l'archive les documents déjà importés d'une
  source après une évolution de l'importeur.

### Hub générique — G5 : écrans Connexions et Comptes

- Onglet Sources, carte **Connexions** (remplace « Collecteurs ») : ajouter une connexion du
  catalogue, régler son nom, son horaire, ses réglages et ses portefeuilles, remplacer ses
  identifiants (chiffrés à la saisie, jamais réaffichés), la retirer. Désactiver, Réactiver et
  Contrôler restent.
- Consentement Enable Banking depuis l'app : `POST /api/collectors/{id}/link` ; le service
  `collector-api` ouvre l'autorisation dans la minute, dans un fil à part, et remonte l'adresse
  (`PUT /api/collectors/{id}/link-url`, portée `collector`) que l'app affiche ; la liaison est
  déclarée comme un contrôle. Migration core `0005_collector_link`.
- Portefeuilles crypto : réglage `wallets` de la connexion `market` (adresses et clés
  publiques, vérifiées, clé privée refusée) au lieu des secrets ; `hub connections import`
  (donc `make deploy`) les sort des secrets une fois. La clé CoinGecko reste un secret.
- Carte **Comptes** : comptes attendus par des relevés (`GET /api/finance/accounts/pending`,
  sans montant), portefeuilles et plateformes sans compte, créés par une proposition
  `create_account` validée avec Face ID. Un compte Revolut s'ouvre au solde déduit de sa
  reprise. `/api/finance/accounts` donne `external_ref`.
- Les fichiers de l'app sont servis en `Cache-Control: no-cache` et le service worker recharge
  sa copie depuis le serveur : après un déploiement, Safari ne mélange plus un ancien module et
  un nouveau (l'app restait sur « Chargement… »).
- Notifications et page de retour renvoient vers l'app au lieu du terminal.

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
- `hub/domains/finance/registre/model/institutions.py` déclare les codes d'opération VIAC et IBKR et leur rôle
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
