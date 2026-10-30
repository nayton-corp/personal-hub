# Décisions

Les choix qui engagent le hub, un par entrée, du plus récent au plus ancien. Une décision ne
s'efface pas : une décision contraire s'ajoute et dit laquelle elle remplace. Les mots sont ceux
du [glossaire](glossaire.md).

Format : **contexte** (pourquoi la question s'est posée), **décision**, **conséquence** (ce qui
change ou ce qu'on s'interdit).

## D-024 · L'agenda ne copie rien : il lit et écrit par le pont (30.10.2026)

- **Contexte** : Rappels et Calendrier sont déjà synchronisés par iCloud sur tous les appareils
  du foyer ; une copie dans le hub divergerait.
- **Décision** : le domaine Agenda lit au pont EventKit (sur le Mac, joint par
  `host.docker.internal`) et n'écrit que par des propositions à effet externe : ajouter un
  rappel, un événement, cocher. Jamais de suppression. Sa base ne tient que la trace des envois
  (`sent`), pour l'idempotence et la réconciliation. La liste de courses passe au palier `auto`.
- **Conséquence** : le Mac en veille, l'agenda se dit indisponible sans que la santé du hub
  baisse. Le domaine est monté sans une ligne du cœur : paquet, point d'entrée, module de l'app.

## D-023 · Le palier par défaut vient du type, la personne le change (30.10.2026)

- **Contexte** : `approval_policies` existait, vide et sans commande pour la remplir : tout
  passait par une carte, même un article de plus sur la liste de courses.
- **Décision** : un type de proposition déclare son palier par défaut (`ProposalKind.tier`,
  `human` sauf mention) ; `hub proposals policy [DOMAINE [TYPE [PALIER|default]]]` les montre
  et les change (`hub.core.policies`). Un jeton qui ne déclare pas `external_text = false`
  reste à la carte, quel que soit le palier.
- **Conséquence** : la liste de courses de l'agenda passe au palier `auto` ; tout autre effet
  externe reste à la carte. Les commandes `hub proposals …` quittent `hub/cli.py`
  (`hub/cli_proposals.py`).

## D-022 · Plus de conteneur pour l'IA locale (30.10.2026)

- **Contexte** : le conteneur `brain` joignait Ollama par `host.docker.internal` et chargeait son
  propre modèle (qwen3:32b) à côté de celui de l'assistant de Domia : deux gros modèles qui se
  chassaient de la mémoire du Mac.
- **Décision** : l'assistant (`assistant/`) tourne en natif sur le Mac et fait le travail du
  brain : la conversation avec le jeton des agrégats, le classement du matin
  (`hub.classify_at`) avec le jeton `brain` et le même modèle résident, la passerelle MCP. Les
  jetons restent dans `brain.enc.yaml`, chiffré par age. `hub.brain` reste une bibliothèque du
  hub, que l'assistant installe à côté de lui ; `hub-brain` reste pour les gestes à la main.
- **Conséquence** : le service `brain`, son volume, `deploy/brain-crontab` et la section
  `[brain]` de `deploy/settings.toml` disparaissent ; le profil compose `brain` n'existe plus.

## D-021 · L'assistant de Domia devient celui du hub, en paquet à part (30.10.2026)

- **Contexte** : deux assistants (celui de Domia, mesuré au banc, et le brain du hub), deux
  modèles qui se chassent de la mémoire du Mac. Domia est un produit pour d'autres foyers : un
  foyer sans hub ne doit pas perdre son assistant.
- **Décision** : l'assistant arrive dans `assistant/` tel quel, avec ses tests, son banc et le
  pont Rappels/Calendrier. Il reste un paquet à part (`domia_assistant`, ses dépendances et sa
  CI), utilisable avec Domia seul ; les outils du hub s'y ajoutent comme un module. Le contrat
  avec l'API de Domia est figé dans `domia_assistant/contract/` (`DOMIA_VERSION` : la plus
  ancienne version lue) et repris par `make domia-contract`. Les prénoms d'exemple deviennent
  ceux des tests.
- **Conséquence** : l'assistant du dépôt de Domia reste en service jusqu'à ce que celui-ci
  passe le banc ; la bascule consiste à changer l'adresse que Domia relaie, le retour arrière à
  la remettre.

## D-020 · Recherche fusionnée par rang ; liens et constats tenus par le cœur (30.10.2026)

- **Contexte** : `/api/search` triait les résultats de tous les domaines sur leurs scores bruts,
  qui ne se comparent pas (bm25 de la finance, qui préfère les libellés courts, contre l'échelle
  d'un autre domaine) : un domaine pouvait occuper toute la page. Les liens n'avaient pas de
  geste pour se créer, et les alertes de la finance avaient leur route à elles.
- **Décision** : chaque domaine classe ses résultats ; le cœur ne garde que le rang de chacun
  dans son domaine et les fusionne (Reciprocal Rank Fusion, k = 60, en entiers). Un résultat
  dit son domaine, son rang et le passage trouvé. Le cœur tient ses propres types de
  proposition, `core/link` et son inverse `core/unlink`, appliqués dans `core.db` (qui gagne le
  journal chaîné, `applied_proposals` et `events`) ; un jeton ne lie que des objets qu'il lit,
  avec `core:propose`. `GET /api/observations` réunit les constats des domaines lisibles ; les
  sentinelles de la finance y passent, `/api/finance/alerts` disparaît.
- **Conséquence** : le premier résultat de chaque domaine passe avant le second de tous. Un
  constat exige la lecture du domaine (il peut nommer une contrepartie). `hub verify` contrôle
  aussi le journal de `core.db`.

## D-019 · La finance en quatre sous-contextes, chacun en couches (29.10.2026)

- **Contexte** : 45 modules à plat, douze au-delà de 400 lignes (l'importeur 1 424, les
  propositions 1 281), des imports circulaires (`domain` ↔ `api`, importeur ↔ IBKR) cachés
  dans des fonctions.
- **Décision** : registre, classement (et budget), patrimoine, sources ; chacun en `interface`
  → `app` → `infra` (formats et fichiers, sans base) → `model` (pur). Un sous-contexte n'importe
  que ceux d'après lui : sources → patrimoine → classement → registre. Les bords du domaine
  (`api`, `cli`, `tools`, `handlers`, `rebuild`) reçoivent un `port.Finance` au lieu de
  `FinanceDomain` ; un autre domaine ne lit que `public.py`.
- **Conséquence** : quatre contrats import-linter, sans écart ; plus aucun fichier de la finance
  au-delà de 400 lignes. Une base construite avant le découpage, reconstruite après par
  `hub finance rebuild`, se compare sans écart.

## D-018 · L'app est une coquille qui monte les modules des domaines (29.10.2026)

- **Contexte** : `finance.js` était à la fois la coquille et la finance : un nouveau domaine
  aurait dû toucher la navigation, la barre d'onglets et la page des réglages.
- **Décision** : `shell.js` (navigation, onglets, feuilles) et `sources.js` (page des
  réglages, rubriques affichage, profil, sécurité, état du hub) ne nomment aucun domaine. Ils
  lisent `/api/domains` et chargent les modules du manifeste : onglets, bloc d'accueil
  (`home`), rubriques, module du domaine (`module` : démarrage, rendu commun, liens des
  notifications). Un onglet ou une rubrique sans balisage reçoit une page générique. Les
  manifestes du dernier lancement restent dans le navigateur pour démarrer hors ligne.
- **Conséquence** : un domaine ajoute un onglet sans changer la coquille (test du domaine
  factice). Ses écrans et ses rubriques ne reprennent ni ceux de la coquille ni ceux d'un
  autre domaine (refusé au démarrage).

## D-017 · Un jeton a toujours une date de fin (29.10.2026)

- **Contexte** : un jeton de l'assistant volé lisait la finance sans limite de temps, et le
  raccourci `brain` ouvrait le détail de la finance par défaut.
- **Décision** : date de fin obligatoire (1 à 366 jours, 90 par défaut ; un an pour les jetons
  d'avant et ceux des services collecteurs), alerte ntfy 14 jours avant, `hub token rotate`.
  `brain` n'ouvre que `*:aggregates` ; `brain=finance,agenda` ajoute lecture et propositions des
  domaines nommés.
- **Conséquence** : un jeton fini est refusé (401) ; renouveler le jeton du brain fait partie
  de l'exploitation, et l'alerte dit quelle commande lancer.

## D-016 · Le manifeste d'un domaine, v2 (29.10.2026)

- **Contexte** : l'app, la boîte d'entrée et l'assistant connaissaient la finance par son nom.
- **Décision** : chaque domaine déclare un manifeste (`hub.core.manifest`) : onglets, cartes
  d'accueil, rubriques de réglages, module des cartes à valider, fichiers qu'il réclame,
  connecteurs qui le nourrissent, tables en ajout seul, consignes pour l'assistant ; ses
  constats passent par `observations()`. `HUB_DOMAINS` choisit les domaines montés. Le
  catalogue des connecteurs reste un point d'entrée (`hub.connectors`) : les services
  collecteurs le lisent sans monter de domaine ; le manifeste en nomme seulement les entrées.
- **Conséquence** : `hub verify` contrôle les triggers des tables protégées ; un manifeste
  invalide est refusé au démarrage ; la coquille de l'app (S5) et la boîte d'entrée par
  domaine (S4) lisent le manifeste au lieu d'une liste en dur.

## D-015 · Une version publiée se déploie depuis son image (29.10.2026)

- **Contexte** : les images se construisaient sur le Mac à chaque déploiement (jusqu'à 20 min),
  sans version ni tag : rien ne disait ce qui tournait.
- **Décision** : la version de `pyproject.toml` est la seule ; un tag `vX.Y.Z` sur main publie
  les images sur GHCR après toutes les barrières, et `make deploy` tire l'image de ce tag, le
  clone placé sur le même commit.
- **Conséquence** : une image publiée ne se reconstruit pas ; la version de l'image est
  vérifiée avant le déploiement. Construire sur le Mac reste possible (`HUB_BUILD=1`).

## D-014 · Les contrats d'architecture listent leurs écarts (29.10.2026)

- **Contexte** : le découpage visé (noyau, plateforme, cœur, domaines en couches) n'existe pas
  encore, et l'attendre pour poser les règles laisserait le code dériver.
- **Décision** : les contrats import-linter, le test des 400 lignes et le test des journaux
  décrivent la cible dès maintenant ; les écarts d'aujourd'hui sont listés dans le dépôt.
- **Conséquence** : une liste d'écarts ne peut que rétrécir (un écart corrigé doit en sortir).
  Un nouvel écart se corrige dans le code, jamais dans la règle.

## D-013 · Les seuils de risque appartiennent au domaine (29.10.2026)

- **Contexte** : passer les petites actions répétitives en automatique, pour éviter la fatigue
  de validation, demande un plafond (un montant pour la finance).
- **Décision** : chaque domaine lit ses seuils dans sa propre configuration et rend un verdict
  de risque. Le cœur ne connaît ni montant ni plafond, il applique le palier.
- **Conséquence** : aucune notion de montant dans le cœur. Ne passent jamais en automatique :
  un effet externe, une suppression, un changement de règle ou de budget, une action sans inverse.

## D-012 · Le modèle choisit et rédige, le code calcule et croise (29.10.2026)

- **Contexte** : un modèle local de 24 à 32 milliards de paramètres calcule et joint mal, et
  peut être lent.
- **Décision** : tout chiffre vient d'un outil ; un croisement entre domaines est une lecture
  écrite en code ; une demande lourde devient une tâche en arrière-plan. Le routage passe par
  quatre niveaux, du code sans modèle au gros modèle chargé à la demande.
- **Conséquence** : le code vérifie chaque nombre d'une réponse. Le banc d'essai décide du
  modèle, jamais l'impression.

## D-011 · Le socle d'abord, Domia ensuite (29.10.2026)

- **Contexte** : le hub n'a qu'un domaine, et plusieurs pièces sont taillées pour la finance.
- **Décision** : construire d'abord un socle propre (contrats, CI/CD, découpage, contrat de
  domaine v2), remonter dans le hub ce qui vient de Domia (assistant, bibliothèque, agenda,
  constats), puis seulement brancher Domia.
- **Conséquence** : l'ordre des chantiers S0 à S14 du plan « Socle du hub ».

## D-010 · Domia reste un service à part, branché par un domaine « maison » (29.10.2026)

- **Contexte** : Domia pilote la maison en temps réel, pour tout le foyer, au-dessus de Home
  Assistant.
- **Décision** : Domia garde sa boucle, sa loi et ses écrans sur le Pi. Le hub le lit par un
  domaine adaptateur `maison`, en agrégats. Les gestes du quotidien vont directement de
  l'assistant à Domia.
- **Conséquence** : Domia reste le seul à parler à Home Assistant et à la météo.

## D-009 · Un seul assistant, celui de Domia, dans le dépôt du hub (29.10.2026)

- **Contexte** : le brain du hub et l'assistant de Domia font chacun une partie du travail.
- **Décision** : l'assistant de Domia (voix, mémoire, banc d'essai, routage) devient l'assistant
  unique. Il vit dans ce dépôt et s'installe en natif sur le Mac.
- **Conséquence** : le brain est remplacé au chantier S10. La bibliothèque devient le domaine
  Documents, le pont Rappels et Calendrier le domaine Agenda.

## D-008 · Deux dépôts, une version (29.10.2026)

- **Contexte** : il fallait choisir entre un dépôt par domaine et un seul dépôt.
- **Décision** : `personal-hub` contient le hub, ses domaines et l'assistant ; `domia` reste à
  part. Le hub porte une seule version SemVer ; un domaine ne se déploie pas seul, il s'active
  ou non par instance.
- **Conséquence** : Domia a ses propres versions et déclare la version minimale du contrat qu'il
  attend du hub.

## D-007 · Déployer à la main, sur un tag (29.10.2026)

- **Contexte** : la machine de production est le Mac de la maison.
- **Décision** : la CI construit et publie les images ; le déploiement reste manuel, sur un tag,
  après un « oui déploie vX » explicite.
- **Conséquence** : aucun déploiement automatique, même sur une CI verte.

## D-006 · Un hub par personne (28.10.2026)

- **Contexte** : le hub doit pouvoir servir à quelqu'un d'autre que son premier utilisateur.
- **Décision** : une instance par personne, avec son profil (pays, devise, modules), ses
  connexions et ses packs de règles. Rien de taillé pour un foyer dans le code.
- **Conséquence** : `hub init` et le profil d'instance ; aucun nom ni lieu propre dans le code.

## D-005 · Toutes les opérations crypto au registre (28.10.2026)

- **Contexte** : les soldes seuls ne disent ni d'où vient un actif ni ce qu'il a coûté.
- **Décision** : chaque connecteur crypto apporte ses écritures, et pas seulement ses soldes.
- **Conséquence** : les arrivées sont appariées aux retraits de même quantité.

## D-004 · Sauvegardes sur le Mac (27.10.2026)

- **Contexte** : pas de disque externe pour l'instant.
- **Décision** : réplique Litestream et dépôt restic dans `~/PersonalHub/backup/`.
- **Conséquence** : aucune copie hors de la machine ; la question reste ouverte (chantier S7).

## D-003 · Tout sur le Mac d'abord (27.10.2026)

- **Contexte** : le Pi n'est pas prêt.
- **Décision** : phase 1 sur le Mac, en conteneurs (Docker Desktop), avec Ollama en natif pour
  le GPU. La migration vers le Pi est repoussée, sans date.
- **Conséquence** : le Mac doit rester allumé ; le hub ne répond pas quand il dort.

## D-002 · Claude ne lit que des agrégats (27.10.2026)

- **Contexte** : des données financières personnelles.
- **Décision** : un modèle hors de la maison ne voit jamais une transaction, seulement des
  totaux (portée `*:aggregates`, petits totaux fondus).
- **Conséquence** : les tests et la CI n'utilisent que des données fictives.

## D-001 · Un registre en ajout seul (27.10.2026)

- **Contexte** : un historique financier doit rester vérifiable.
- **Décision** : montants en centimes avec leur devise ; triggers qui refusent la modification
  et la suppression ; chaîne d'empreintes vérifiée chaque nuit.
- **Conséquence** : une correction s'ajoute, elle ne réécrit rien.
