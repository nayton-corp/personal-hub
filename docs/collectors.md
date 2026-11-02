# Collecteurs : connexions, BCF, VIAC, Enable Banking, IBKR, cours et plateformes crypto

Les collecteurs déposent les exports officiels dans `~/PersonalHub/inbox/`, où l'importeur les
traite comme un fichier déposé à la main. Depuis G4 (« hub générique »), ce que l'instance
collecte est une liste de **connexions** gardée dans `core.db` : chaque connexion est l'usage
d'un connecteur du catalogue (déclaré par la finance dans `hub/domains/finance/sources/app/connectors.py`, lu par le cœur au point d'entrée `hub.connectors`), avec un identifiant (`bcf`,
`revolut`, `n26`…), un nom, un horaire, des réglages sans secret et des secrets chiffrés.
Deux services les exécutent :

| Service | Connecteurs | Ce qu'il voit |
|---|---|---|
| `collector-browser` | `bcf`, `viac` : navigateur sans tête | la boîte d'entrée, son volume (profils des navigateurs, mémoire), son jeton |
| `collector-api` | `enable_banking`, `ibkr`, `market`, `binance`, `kucoin`, `coinbase` : API, sans navigateur | idem |

| Connecteur | Comment | Horaire par défaut (fuseau de l'instance) | Ce qu'il dépose |
|---|---|---|---|
| `bcf` | connexion avec validation push dans l'app BCF | 07:30 du lundi au vendredi | export camt.053 depuis J-10, « déjà téléchargées » coché |
| `viac` | profil gardé dans le volume | dimanche 09:00 | avis PDF nouveaux de la liste Documents, et un rapport tous les 6 jours |
| `enable_banking` | API Enable Banking (PSD2), une banque européenne par connexion | 07:15, 13:15, 19:15 | un `revolut-<empreinte>.json` par compte, seulement s'il a changé |
| `ibkr` | Flex Web Service d'IBKR (jeton en lecture seule) | 06:45 du mardi au samedi | le relevé Flex XML de la veille |
| `market` | API publiques (BCE, CoinGecko, mempool.space, nœuds Ethereum et Solana publics, Yahoo facultatif) | toutes les 4 h, de 06:15 à 22:15 | un `market.json` : change, cours, soldes des portefeuilles |
| `binance`, `kucoin`, `coinbase` | API officielle, clé en lecture seule | toutes les 4 h, de 06:20, 06:22, 06:24 à 22:2x | un `<plateforme>.json` : soldes de la plateforme (Binance : et ses opérations) |

Chaque minute, un service demande au hub ses connexions prêtes (`GET
/api/collectors/runner/<service>`) : leurs secrets arrivent chiffrés et ne sont déchiffrés
qu'au moment du run, dans le conteneur. Chaque run tourne dans son propre fil : un run lent
(le collecteur `market` peut dépasser un quart d'heure quand mempool.space traîne) ne retarde
pas les autres connexions, et une connexion n'a jamais deux runs à la fois (son horaire ou
son actualisation attend la fin du run en cours). L'API chiffre les secrets à la saisie et ne les relit
jamais ; ni l'app ni `hub connections list` ne les affichent. Une connexion à qui il manque ses
secrets n'est pas lancée.

Ce qu'un collecteur voit : la boîte d'entrée, le volume de son service et les secrets de la
connexion qu'il exécute. Il ne lit jamais les bases et ne remonte au hub que l'issue de chaque
passage (`ok`, `nothing_new`, `auth_error`…), le nombre de fichiers et une étape ou un nom de
sélecteur, jamais un montant ni un texte de page. Un fichier qui n'a pas la forme attendue
(camt.053 ou zip de camt.053, PDF complet, JSON `hub.revolut.v1`, relevé Flex, JSON
`hub.market.v1`) part dans `inbox/quarantine/` au lieu d'être déposé.

## Gérer les connexions

**Depuis l'app** (onglet Sources, carte **Connexions**) : « Ajouter » choisit un connecteur du
catalogue, un nom et un identifiant ; « Régler » change le nom, l'horaire (cron, vide pour
celui du catalogue), les réglages, les portefeuilles, et remplace les identifiants (tapés une
fois, chiffrés aussitôt, jamais réaffichés). Pour une banque Enable Banking, « Lier le compte »
demande un consentement : le service `collector-api` ouvre l'autorisation dans la minute,
l'app affiche « Ouvrir la banque pour valider », et la reprise de l'historique démarre au
retour. La carte **Comptes** liste les comptes que des relevés attendent (Revolut par Enable
Banking, portefeuilles, plateformes) et les crée par une proposition validée avec Face ID ;
un compte Revolut s'ouvre au solde déduit de sa reprise, comme `fin revolut add-account`.

Un portefeuille crypto (Ledger, MetaMask, Coinbase Wallet…) n'est pas une connexion : il
s'ajoute dans les réglages de « Cours et cryptos », section Portefeuilles. Cette connexion est
unique ; « Ajouter » sur ce connecteur ouvre ses réglages avec un portefeuille à remplir.

**Actualiser** : hors de son horaire, « Actualiser » sur une connexion (ou « Tout actualiser »
en tête de la carte) demande un run complet que le service lance dans la minute (`POST
/api/collectors/<id>/refresh`, `POST /api/collectors/refresh`). Seule une connexion prête et
active s'actualise : une connexion suspendue passe d'abord par « Contrôler » puis
« Réactiver ». La ligne affiche « actualisation en cours » jusqu'à ce que le run soit déclaré,
puis l'app relit ses chiffres, une fois tout de suite et une fois après l'import (la boîte
d'entrée passe toutes les 30 secondes). Les limites de chaque source restent celles de son
flux :

- BCF : chaque run demande la validation push dans l'app BCF (trois minutes) ;
- Enable Banking (Revolut) : quatre synchronisations par jour au plus (`max_syncs_per_day`),
  trois prises par l'horaire ; au-delà, le run finit en « quota du jour atteint » ;
- VIAC : un code 2FA demandé au milieu d'un run le fait échouer, comme à l'horaire ;
- soldes crypto (portefeuilles et plateformes) : un run de plus dans la journée met le solde
  du jour à jour tout de suite. Le registre reste en ajout seul : le relevé du matin est
  gardé, une ligne s'ajoute pour ce qui a bougé (une crypto partie passe à zéro) et, à date
  égale, la plus récente fait foi. Les rapports de positions (VIAC, IBKR, saisie) gardent un
  relevé par jour.

Les cours et plateformes crypto, sans limite de synchro, passent toutes les 4 heures (06:15,
10:15, 14:15, 18:15, 22:15, et quelques minutes après pour les plateformes) : leurs nouvelles
opérations arrivent dans la journée. Un horaire réglé à la main reste celui de la connexion.

**Depuis le terminal**, pour le dépannage :

Les commandes supposent l'alias `hubc` de [mac.md](exploitation/mac.md) et partent du clone du dépôt
(`~/personal-hub/personal-hub`). `hub` se lance dans le conteneur `scheduler`, qui a la clé age :

```
hubc run --rm --no-deps scheduler hub connections catalog      # connecteurs, secrets et réglages attendus
hubc run --rm --no-deps scheduler hub connections list         # connexions, sans secret
hubc run --rm --no-deps scheduler hub connections add n26 enable_banking --label N26 \
  --settings '{"aspsp_name": "N26", "aspsp_country": "DE"}'
hubc run --rm -it --no-deps scheduler hub connections secrets n26   # champs demandés, masqués
hubc run --rm --no-deps scheduler hub connections set n26 --schedule "0 8 * * *"
hubc run --rm --no-deps scheduler hub connections set n26 --default-schedule
hubc run --rm --no-deps scheduler hub connections remove n26
```

Des secrets sur plusieurs lignes (une clé privée PEM) se donnent en YAML par l'entrée
standard, sans passer par un fichier en clair : `hubc run --rm -T --no-deps scheduler hub
connections secrets revolut --file -`, colle le YAML puis Ctrl-D. `set --settings` remplace
tous les réglages de la connexion. `secrets` remplace toujours
tous les secrets de la connexion. L'app fait la même chose par `GET|POST
/api/collectors/connections`, `PATCH …/{id}`, `PUT …/{id}/secrets` et `DELETE …/{id}`.

Les réglages d'un connecteur (`hub connections catalog`) s'ajoutent à ceux du service dans
`deploy/settings.toml` (`[collectors]`, `[collectors.market]`) et les remplacent pour cette
connexion seulement.

## Reprise d'une installation d'avant G4

Avant G4, chaque collecteur avait son conteneur, son jeton et son fichier
`<nom>.enc.yaml` dans `HUB_COLLECTOR_SECRETS`. `make deploy` fait la reprise seul, et elle peut
se relancer sans risque :

1. la migration `0004_connections` crée une connexion par collecteur déjà connu (`revolut`
   devient une connexion « revolut » du connecteur `enable_banking`, Revolut, Lituanie : son
   URL de retour ne change pas) ;
2. `hub connections import` reprend les secrets de chaque `<nom>.enc.yaml` (sans l'ancien jeton)
   et les horaires de `[collectors] schedules`, puis écrit `collector-api.enc.yaml` et
   `collector-browser.enc.yaml` avec un jeton neuf pour chaque service ;
3. les anciens volumes (`hub_collector-<nom>`) sont copiés dans ceux des deux services : profils
   des navigateurs, session Enable Banking, empreintes déjà vues.

Ensuite, `hubc up -d collector-browser collector-api` remplace les huit anciens conteneurs.
Les anciens jetons `collector-<nom>` restent valides pour permettre un retour arrière ; une fois
la nouvelle version validée, révoque-les (`hub token list`, puis `hub token revoke <id>`) et
efface les anciens fichiers `<nom>.enc.yaml`.

## Quand ça casse

La table des échecs de la spécification (section 8) est appliquée par le hub :

| Issue | Effet |
|---|---|
| `ok`, `nothing_new` | remet le compteur à zéro |
| `auth_pending_timeout` (push ou lien non validé à temps) | alerte une fois par jour, jamais de suspension |
| `site_unavailable` | alerte au 3e de suite |
| `selector_missing`, `invalid_file`, `unknown` | alerte ; suspendu (« dégradé ») au 2e de suite |
| `auth_error` (refus, session VIAC expirée, consentement Revolut fini) | suspendu tout de suite, alerte urgente |

Un collecteur suspendu ne tourne plus à l'heure prévue. Dans l'app, onglet **Sources**, carte
**Collecteurs** : « Contrôler » demande un passage de contrôle (connexion et sélecteurs, sans
téléchargement) que le conteneur lance dans la minute ; s'il réussit, « Réactiver » apparaît.
« Désactiver » arrête un collecteur actif. Le retour à l'état actif reste toujours manuel.

Les alertes passent par ntfy, avec des textes génériques (« Collecte BCF : action requise »).
Toucher l'alerte ouvre Réglages › Connexions (`/#sources`).
Le sujet ntfy vaut un mot de passe : il vit dans `secrets.enc.yaml`, section `ntfy`.

Pour comprendre un sélecteur manquant : `hubc run --rm collector-browser hub-collector run bcf
--diagnose` garde des captures d'écran dans le volume du service (purgées après 7 jours).
Si la banque a changé sa page, seul `hub/collectors/<banque>/selectors.toml` est à adapter.

## Mise en place (une fois)

Les commandes supposent l'alias `hubc` de [mac.md](exploitation/mac.md) et partent du clone du dépôt
(`~/personal-hub/personal-hub`). Les étapes 3 et suivantes se font aussi dans l'app (carte
Connexions), sauf les premiers passages qui demandent un code tapé au terminal.

1. **Sujet ntfy.** Installe ntfy sur le téléphone, choisis un sujet long et aléatoire
   (`openssl rand -hex 16`), abonne-toi, puis ajoute-le au fichier de secrets principal :
   ```
   { age -d -i ~/.config/hub/age.key ~/.config/hub/secrets.enc.yaml; \
     printf 'ntfy:\n  topic: "%s"\n' "<ton-sujet>"; } \
     | age -r "$(age-keygen -y ~/.config/hub/age.key)" -o ~/.config/hub/secrets.enc.yaml.new \
     && mv ~/.config/hub/secrets.enc.yaml.new ~/.config/hub/secrets.enc.yaml
   ```
2. **Les deux services** : `hub connections import` écrit leurs fichiers de secrets
   (`collector-api.enc.yaml`, `collector-browser.enc.yaml`, chacun avec son jeton) dans
   `HUB_COLLECTOR_SECRETS` (`deploy/.env`, par exemple `~/.config/hub/collectors/`) :
   ```
   mkdir -p ~/.config/hub/collectors && chmod 700 ~/.config/hub/collectors
   hubc run --rm --no-deps -v ~/.config/hub/collectors:/import scheduler \
     hub connections import /import
   ```
   Sur une installation neuve, le dossier est vide : seuls les deux fichiers sont écrits.
   `make deploy` le relance à chaque version, sans rien remplacer.
3. **Les connexions** (`bcf` et `viac` ici ; les autres plus bas) :
   ```
   hubc run --rm --no-deps scheduler hub connections add bcf bcf
   hubc run --rm -it --no-deps scheduler hub connections secrets bcf    # contract, password
   hubc run --rm --no-deps scheduler hub connections add viac viac
   hubc run --rm -it --no-deps scheduler hub connections secrets viac   # email, password
   ```
4. **Déployer** : `make deploy TAG=vX`. Les collecteurs ne démarrent pas encore.
5. **Premiers passages, un par un**, en regardant le téléphone :
   ```
   hubc run --rm collector-browser hub-collector run bcf          # valide le push BCF
   hubc run --rm -it collector-browser hub-collector relogin viac # tape le code 2FA reçu
   ```
   Pour Enable Banking, voir la section suivante.
6. **Laisser tourner** : décommente `COMPOSE_PROFILES=collectors` dans `deploy/.env`, puis
   `hubc up -d`. À partir de là, `make deploy` met aussi les deux services à jour.

**VIAC : reconnexion.** VIAC ne garde la session que le temps du navigateur : chaque passage se
reconnecte avec l'e-mail et le mot de passe des secrets. Sans 2FA sur le compte, il n'y a rien
d'autre à faire. Si VIAC demande un code, le passage s'arrête en `auth_error`
(`login.otp_required`), la connexion est suspendue et tu reçois une alerte. Reconnecte-la
(le service ne la relance pas tant qu'elle est suspendue) :
```
hubc run --rm -it collector-browser hub-collector relogin viac
```
`relogin` remplit identifiant et mot de passe depuis les secrets, demande le code 2FA dans le
terminal, puis lance un contrôle ; il reste à cliquer « Réactiver » dans l'app. (La
spécification prévoyait un navigateur visible sur le Mac dont on copie le profil : un profil
Chromium de macOS ne se déchiffre pas sous Linux, d'où le code tapé dans le conteneur.)

## Une banque par Enable Banking (Revolut)

Enable Banking est le seul agrégateur PSD2 ouvert aux particuliers ; son mode « production
restreinte » est gratuit et ne lie que tes propres comptes. Une connexion `enable_banking` vise
une banque (`aspsp_name`, `aspsp_country`) ; l'exemple est Revolut, la connexion « revolut ». Chaque consentement dure au plus
180 jours. Revolut ne donne tout l'historique que dans les 5 minutes qui suivent un
consentement (90 jours ensuite) : la liaison lance la reprise complète dans la foulée.

**Test de liaison (15 min).**

1. Sur <https://enablebanking.com/cp/applications>, crée une application en production
   restreinte. Laisse le panneau générer la paire de clés et télécharge la clé privée (`.pem`).
   URL de redirection autorisée : `https://hub.<ton-tailnet>.ts.net/api/collectors/<connexion>/callback`
   (la même origine que `HUB_PUBLIC_ORIGIN`, `<connexion>` = `revolut` ici). Note
   l'identifiant de l'application.
2. Crée la connexion et donne-lui l'identifiant et la clé (colle le `.pem`, puis Ctrl-D) :
   ```
   hubc run --rm --no-deps scheduler hub connections add revolut enable_banking \
     --label Revolut --settings '{"aspsp_name": "Revolut", "aspsp_country": "LT"}'
   hubc run --rm -T --no-deps scheduler hub connections secrets revolut --file -
   ```
   ```yaml
   application_id: "…"
   private_key: |
     -----BEGIN PRIVATE KEY-----
     …
     -----END PRIVATE KEY-----
   ```
   puis efface le `.pem` téléchargé.
3. Vérifie que la banque est proposée, et sous quel pays :
   ```
   hubc run --rm collector-api hub-collector aspsps revolut --country LT
   hubc run --rm collector-api hub-collector aspsps revolut --country CH
   ```
   Si elle n'apparaît que sous un autre pays, change `aspsp_country` avec `hub connections
   set revolut --settings '{"aspsp_name": "Revolut", "aspsp_country": "…"}'`.
4. Lie le compte : dans l'app, « Régler » puis « Lier le compte » ; ou sur le Mac connecté au
   tailnet :
   ```
   hubc run --rm -it collector-api hub-collector link revolut
   ```
   Ouvre le lien affiché sur le téléphone (Tailscale actif), valide dans l'app Revolut. Le
   retour arrive sur le hub, le collecteur crée la session et dépose tout l'historique. La
   sortie liste les comptes vus (type, devise, produit) : c'est la réponse à la question
   « les pockets sont-elles des comptes séparés ? ».
5. Ouvre les comptes côté Finance. Les fichiers attendent tant que le compte n'existe pas :
   ```
   fin revolut pending                          # comptes en attente, sans montant
   fin revolut add-account revolut:CHF --name "Revolut CHF"
   ```
   `add-account` crée le compte, l'ouvre au solde déduit du fichier (solde annoncé moins les
   écritures, la veille de la première) et rejoue les imports en attente. Les autres comptes
   s'appellent `revolut:<DEVISE>:<produit>` (par exemple `revolut:EUR:savings`).
6. `hub-collector consent revolut` donne les jours de consentement restants ; 14 jours avant,
   une alerte ntfy rappelle de relancer `link revolut`. (Les anciennes commandes
   `hub-collector revolut link|aspsps|status` marchent encore.)

**Si Enable Banking ne convient pas : CSV.** Dans l'app Revolut, Relevé → Excel/CSV, puis
dépose le fichier dans `~/PersonalHub/inbox/`. Seules les lignes `COMPLETED` comptent, frais
déduits ; chaque ligne est vérifiée contre la colonne de solde. Un recouvrement avec un fichier
Enable Banking est reconnu (`near_duplicate`) et n'écrit rien deux fois. Les placements (actions,
crypto) ne passent pas par PSD2 : ils viendront au lot 6.

## IBKR par le Flex Web Service (lot 6)

1. **La requête Flex.** Client Portal → Performance & Reports → Flex Queries → Activity Flex
   Query → « + ». Nom `hub`, format XML, période « Last Business Day », dates `yyyyMMdd`.
   Sections : Account Information, Cash Report, Open Positions (niveau Summary), Trades
   (niveau Execution), Cash Transactions (niveau Detail), Conversion Rates ; toutes les
   colonnes. Note le numéro de la requête (Query ID).
2. **Le jeton.** Même page, « Flex Web Service Configuration » : active le service et génère un
   jeton (valable jusqu'à un an ; note sa date de fin). Il ne permet que de lire les relevés.
3. **La connexion** : `hub connections add ibkr ibkr`, puis `hubc run --rm -it --no-deps
   scheduler hub connections secrets ibkr` (`flex_token`, `query_id`).
4. **Contrôle** : `hubc run --rm collector-api hub-collector run ibkr --check` (demande un
   relevé sans rien déposer), puis `hubc run --rm collector-api hub-collector run ibkr`. Le
   compte doit être déclaré (`fin ibkr add-account`, voir [finance.md](finance.md)) ; sinon le
   relevé attend (`unknown_account`).

Un jeton expiré ou révoqué donne `auth_error` (codes 1011 à 1016 et 1020 d'IBKR) ; un service
occupé, `site_unavailable`, et le passage suivant réessaie.

## Cours et cryptos (lot 6)

La connexion `market` (`hub connections add market market`) n'a besoin d'aucun compte. Ses
réglages se donnent par `hub connections set market --settings '{…}'` ou, pour tout le service,
dans `deploy/settings.toml`, section `[collectors.market]` : devises (`currencies`), cryptos suivies (`crypto`, symbole → id
CoinGecko) et, pour un titre qui n'a pas d'autre source de cours, `quotes = { "<ISIN>" =
"<symbole Yahoo>" }`. Le premier passage reprend un an d'historique (la limite gratuite de
CoinGecko) ; les suivants une semaine, pour combler un jour manqué.

Les portefeuilles se règlent dans l'app (« Régler » sur « Cours et cryptos ») : un compte
`crypto:<nom>`, la crypto, et les adresses ou la clé publique étendue, une par ligne. Ce sont des
réglages de la connexion, visibles dans l'app : des adresses publiques et des clés publiques,
jamais une clé privée (refusée). Avant G5 ils vivaient dans les secrets ; `make deploy` les en
sort une fois. Seule la clé CoinGecko facultative (`coingecko_key`) reste un secret. Au
terminal, la forme est la même, dans `--settings` :
```yaml
wallets:
  - account: "crypto:ledger"         # fin crypto add-wallet ledger
    asset: "BTC"
    xpub: "xpub6…"                   # clé publique du compte (Ledger Live : Modifier le compte → Avancé)
    script: "wpkh"                   # facultatif : wpkh (bc1q), sh-wpkh (3…), pkh (1…), tr (bc1p)
  - account: "crypto:metamask"
    asset: "ETH"
    addresses: ["0x…"]
  - account: "crypto:phantom"
    asset: "SOL"
    addresses: ["Fz…"]
  - account: "crypto:coinbase-wallet"
    asset: "ETH"
    addresses: ["0x…"]
    networks: ["ethereum", "arbitrum", "base", "polygon"]   # facultatif : Ethereum seul sinon
  - account: "crypto:trust"          # plusieurs chaînes, un seul compte
    asset: "ETH"
    addresses: ["0x…"]
```
**BTC** : des adresses (`addresses`) ou la clé publique étendue d'un compte (`xpub`, `ypub`,
`zpub`). Les adresses de réception et de monnaie en sont dérivées dans le conteneur et lues une à
une sur mempool.space, jusqu'à 20 adresses jamais utilisées de suite (`gap_limit`). Une `zpub`
est Native SegWit, une `ypub` SegWit ; une `xpub` ne le dit pas (Ledger Live en donne une même
pour un compte Native SegWit), les quatre types sont alors parcourus, sauf si `script` le fixe.
Une clé privée (`xprv`…) est refusée. mempool.space refuse les requêtes trop rapprochées : le
collecteur attend une seconde entre deux adresses (`mempool_pause_seconds`) et, sur un refus
(429), réessaie après 10, 30 puis 60 secondes. Fixer `script` évite de parcourir trois types
d'adresse pour rien.

**Historique BTC.** Au premier passage d'un portefeuille BTC, ses transactions confirmées sont
relues sur mempool.space (adresses utilisées seulement) et déposées en relevés passés : un par
jour où le solde a bougé, depuis la première réception. Un virement entre deux adresses du
portefeuille s'annule ; les frais d'un envoi sont déduits. Si l'historique remonte avant la
fenêtre d'un an de CoinGecko, le même passage ajoute le change BCE depuis cette date et les
clôtures quotidiennes publiques de Binance (BTCUSDT, comptées en USD, depuis août 2017). C'est
fait une fois par compte (mémoire `btc_history`) ; en cas d'échec, le passage suivant reprend.
Les transactions elles-mêmes partent aussi dans le fichier (`transactions` : txid, jour, net,
frais payés), pour le registre : toutes au premier passage (mémoire `btc_txs`), ensuite la
dernière page de chaque adresse utilisée, une requête par adresse et par jour.
**ETH** : le solde natif et les jetons de `erc20_tokens` (USDC et USDT par défaut). Un
portefeuille qui nomme d'autres réseaux (`networks`, cases « Réseaux » dans l'app) est lu aussi
sur Arbitrum, Base, BNB Smart Chain et Polygon (`evm_networks` : nœud public, `chain_id`, jetons) : leur ETH, leur
USDC/USDT, le WETH compté comme ETH, le POL sur Polygon et le BNB sur BNB Smart Chain. Les jetons de staking de
`staking_tokens` (par défaut Kiln Native20, le « cbwsETH » de Coinbase Wallet) comptent comme
de l'ETH, à leur valeur sous-jacente (`balanceOfUnderlying` : la mise et ses récompenses). **SOL** : le
solde natif et les jetons de `spl_tokens` (USDC, USDT) ; les autres jetons, souvent du spam, sont
ignorés, et le SOL en staking n'est pas lu. **ATOM** (Cosmos Hub, adresse `cosmos1…`) : par l'API REST publique
(`cosmos_rest_url`), l'ATOM disponible, mis en jeu, en cours de retrait et les récompenses à
réclamer, le tout compté comme ATOM. Son historique vient des transactions envoyées et reçues
(`/cosmos/tx/v1beta1/txs`), variation lue dans les événements `coin_received`/`coin_spent`,
frais compris (mémoire `<compte>@cosmos`) ; une mise en jeu y est un envoi vers le staking. Les
nœuds publics élaguent leur index des transactions : s'ils n'en rendent aucune, c'est signalé
(`partial history.<nom>.cosmos:pruned`) et relu au passage suivant ; un historique complet
demande un indexeur (Mintscan, nœud d'archive), à brancher sur `cosmos_rest_url`.

**Historique ETH et SOL.** Leurs transactions partent aussi dans `transactions`, pour le
registre : ETH par l'API de Routescan (`eth_history_url`, compatible Etherscan, sans clé) — envois et arrivées d'ETH, transferts internes de contrats et jetons suivis, les frais de
gaz payés par mes adresses — et SOL par le RPC (`getSignaturesForAddress` puis
`getTransaction`), SOL natif et jetons suivis. Tout au premier passage (jusqu'à
`CHAIN_PAGES` pages par adresse, mémoire `chain_txs`), ensuite la dernière page. Un jeton et
le gaz d'une même transaction donnent deux écritures. Le solde passé, lui, n'est pas
reconstitué : la courbe de patrimoine de ces portefeuilles part du jour où ils sont branchés.
Arbitrum, Base, BNB Smart Chain et Polygon passent par l'API Etherscan V2 (`etherscan_url`, `chainid`), qui
demande une clé gratuite (etherscan.io → API Keys), une seule pour tous les réseaux : le secret
`etherscan_key` de « Cours et cryptos » (champ « Clé Etherscan » dans l'app). Sans elle, leur
solde est lu mais pas leur historique (détail `partial history.<nom>.<réseau>:needs_key`) ; il
est relu en entier dès que la clé arrive (mémoire `chain_txs` : `<compte>@<réseau>`). Un réseau hors de l'offre gratuite d'Etherscan est signalé (`:unsupported`) sans bloquer les autres. Blockscout,
essayé d'abord, coupe après dix appels sans clé et protège ses couches 2 derrière Cloudflare.
Les sources publiques limitent le débit : une pause avant chaque page d'historique
(`chain_pause_seconds`) et chaque cours CoinGecko sans clé (`coingecko_pause_seconds`), et sur
un refus (429, « rate limit ») une attente de 10, 30 puis 60 secondes avant de réessayer.
Une mise en staking apparaît comme
l'envoi d'ETH et l'arrivée des parts, comptées comme de l'ETH. Les autres jetons de staking
liquide (stETH, rETH…) ne sont pas lus : à ajouter à `staking_tokens` ou `erc20_tokens`.

Un compte est relevé en entier ou pas du tout : si une de ses adresses ne répond pas, il est
laissé de côté ce jour-là (détail `partial wallet.<nom>:…`) plutôt que de perdre une crypto. Un
portefeuille vide donne un relevé à zéro. Une autre crypto passe par le CSV de positions. Une
source facultative en panne (CoinGecko, Yahoo) n'empêche pas le dépôt du reste : le passage
est `ok` avec le détail `partial …`, et le suivant reprend la même fenêtre.

## Plateformes crypto : Binance, KuCoin, Coinbase

**Règle : un connecteur crypto apporte ses écritures.** Une plateforme ou un portefeuille ne
dépose jamais que des soldes : chaque connecteur dont les comptes sont crypto a sa lecture
d'historique (`runner(fetch, history)` exige les deux), et chaque crypto de portefeuille sa
lecture de transactions. Un test (`tests/collectors/test_crypto_history_rule.py`) refuse un
nouveau connecteur ou une nouvelle chaîne qui ne le fait pas.

Une connexion par plateforme (`binance`, `kucoin`, `coinbase`), chacune avec sa clé API **en
lecture seule** dans ses secrets (`hub connections add binance binance`, puis `hub connections
secrets binance`). Toutes les 4 heures,
après les cours (06:20, 06:22, 06:24, puis 10:2x…), il dépose un `<plateforme>.json` (`hub.market.v1`,
soldes et opérations) dont les soldes deviennent un relevé de positions du compte `crypto:<plateforme>`, valorisé avec les
cours CoinGecko du collecteur `market`. Une crypto sans cours garde sa quantité et attend son
cours : ajoute-la à `crypto` dans `[collectors.market]` (symbole → id CoinGecko).

| Plateforme | Ce qui est lu | Clé à créer |
|---|---|---|
| Binance | Spot, Funding, Simple Earn flexible et bloqué, et l'historique (ci-dessous) | Gestion des API → clé générée par le système, « Enable Reading » seul coché |
| KuCoin | tous les comptes (principal, trading…), Earn, et un an d'historique | API Management → permission « General » seule, une passphrase à toi |
| Coinbase | tous les portefeuilles, ETH en staking compris (`ETH2` compté comme ETH), et l'historique | portail CDP → clé API secrète, permission « View » seule |

| Plateforme | Secrets |
|---|---|
| Binance | `api_key`, `api_secret` ; facultatifs : `since` (AAAA-MM-JJ), `assets` (liste) |
| KuCoin | `api_key`, `api_secret`, `passphrase` |
| Coinbase | `key_name` (`organizations/…/apiKeys/…`), `private_key` (clé EC en PEM, ou Ed25519 en base64 ; par `--file -` pour garder les retours à la ligne) |

Le compte se déclare avec `fin crypto add-wallet binance` (ou `kucoin`, `coinbase`) ; le champ
`account` des secrets en choisit un autre. Contrôle : `hubc run --rm collector-api
hub-collector run binance --check` lit les soldes sans rien déposer. Une clé révoquée donne
`auth_error` et suspend cette connexion seulement.

### Historique Binance

Le collecteur Binance dépose aussi les opérations du compte (`operations` du `binance.json`),
qui deviennent des écritures du compte `crypto:binance` dans le Journal, en CHF (codes
`EXCHANGE/…`) :

| Flux de l'API | Opération | Écritures |
|---|---|---|
| `capital/deposit/hisrec`, `capital/withdraw/history` | dépôt, retrait crypto (txId, adresse, réseau) | `EXCHANGE/DEPOSIT`, `EXCHANGE/WITHDRAWAL` + frais de réseau |
| `fiat/orders` | virement en monnaie (SEPA) | `EXCHANGE/DEPOSIT` ou `WITHDRAWAL` + frais |
| `fiat/payments` | achat ou vente par carte | dépôt de la carte, échange, frais |
| `myTrades` | ordre exécuté (ses exécutions groupées) | `EXCHANGE/TRADE/BUY` et `SELL` + commission |
| `convert/tradeFlow` | conversion | `EXCHANGE/TRADE/…` |
| Simple Earn `rewardsRecord` | récompenses, une par actif et par jour terminé | `EXCHANGE/INCOME` |
| `asset/assetDividend` | airdrop, staking, Launchpool | `EXCHANGE/INCOME` |
| `asset/dribblet` | petits soldes convertis en BNB | `EXCHANGE/TRADE/…` + frais |

Premier passage : tout depuis le premier apport (`since` dans les secrets, sinon
`binance_since`, juillet 2017, pour trouver le premier dépôt), avec les clôtures Binance des
actifs aux jours de leurs opérations et le change BCE depuis la première. Il prend quelques
minutes : l'historique des retraits est limité à dix appels par minute
(`withdraw_pause_ms`). S'il manque un flux, aucune opération n'est déposée et tout est relu au
passage suivant (le compte s'ouvre la veille de sa première opération). Ensuite, trois jours
de recouvrement et les exécutions suivantes de chaque paire (mémoire `history_since`,
`trade_ids`). Une fenêtre refusée (400) est comptée dans le détail (`partial dust:skipped=1`)
sans bloquer le reste.

Valeur : une monnaie au change du jour, une crypto à son cours du jour, un stablecoin en dollar
faute de cours ; les deux côtés d'un échange prennent la valeur du côté le plus sûr (monnaie,
puis stablecoin). Une opération sans cours attend et repasse quand il arrive.

**Mouvements entre mes comptes.** Un retrait Binance qui arrive sur la Ledger, un envoi de la
Ledger vers Binance, un retrait SwissBorg vers Binance : l'autre côté est cherché sur mes autres
comptes crypto, du même txId, sinon de la même quantité (nette de frais), à cinq jours près.
Le côté enregistré en second prend la valeur du premier et les deux deviennent un virement
entre mes comptes, apparié avant tout le reste.

Hors API, donc absents : P2P, Binance Pay, contrats à terme et marge. Les paires lues sont celles
dont les deux actifs sont connus du compte (soldes, opérations) ; un actif acheté puis revendu
en entier sans jamais être déposé se liste dans le champ `assets` des secrets.

### Historique KuCoin et Coinbase

Même principe que Binance (premier passage complet ou rien, trois jours de recouvrement,
clôtures Binance et change BCE déposés avec, mouvements reliés par txId), compte
`crypto:kucoin` ou `crypto:coinbase` :

- **Coinbase** : les transactions de chaque portefeuille (`/v2/accounts/{id}/transactions`) :
  achats, ventes, conversions, envois et réceptions (txId, frais de réseau à part),
  récompenses de staking et d'intérêts, virements en monnaie. La valeur donnée par Coinbase
  (`native_amount`) l'emporte sur le cours du jour. Les mouvements vers Coinbase Pro/Advanced
  ou entre portefeuilles Coinbase sont internes.
- **KuCoin** : le grand livre (`/api/v1/accounts/ledgers`), lu par tranches de 24 heures :
  dépôts, retraits, ordres (les deux côtés regroupés), conversions, récompenses. KuCoin ne garde
  qu'**un an** : ce qui est plus ancien ne peut pas être repris. Les transferts entre comptes
  KuCoin sont internes.

Un type d'opération inconnu est compté dans le détail (`partial type.<nom>:skipped=n`) sans
bloquer le reste.

SwissBorg n'a pas d'API publique : l'argent qui y part se voit dans les virements BCF, ce qui
arrive ensuite sur la Ledger est relevé par la xpub, et le solde gardé chez SwissBorg vient de
son relevé de compte déposé de temps en temps (voir « SwissBorg » dans [finance.md](finance.md)).
