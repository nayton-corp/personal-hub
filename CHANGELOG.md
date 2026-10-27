# Journal des changements

## [Non publié]

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
