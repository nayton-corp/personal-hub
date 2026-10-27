# Domaine Finance : registre BCF

Ce que font les lots 1 à 3, et comment reprendre ton historique BCF et tes règles sur le Mac.
Toutes les commandes passent par le conteneur `importer`, le seul qui voit la boîte d'entrée :

```
alias hubc='HUB_TAG=$(cat deploy/.current-tag) docker compose --env-file deploy/.env -f deploy/compose.yaml'
alias fin='hubc run --rm --no-deps importer hub finance'
```

## Ce qui tourne

- `importer` surveille `~/PersonalHub/inbox/` toutes les 30 s (`hub finance watch-inbox`).
  Un `.xml` camt.053 (.001.04 ou .001.08) ou un `.zip` de relevés y est validé contre le XSD
  ISO 20022, rapproché, puis appliqué s'il n'y a aucune anomalie. Le fichier est ensuite
  chiffré avec ta clé age vers le volume `archive` et retiré de la boîte d'entrée.
- Un relevé avec une anomalie reste « en attente » (`needs_review`) sans rien écrire. Les
  motifs, en liste fermée : `unknown_account`, `no_opening`, `before_opening`,
  `internal_check_failed` (OPBD + écritures ≠ CLBD), `ledger_check_failed` (solde du registre
  ≠ CLBD, souvent un mois manquant), `checkpoint_conflict`, `near_duplicate`,
  `grouped_not_split`, `unknown_currency`, `currency_mismatch`, `missing_balance`.
  Un relevé en attente est rejoué de lui-même quand un autre relevé s'applique, ou à la main
  avec `fin imports retry`.
- `hub verify` (chaque nuit et avant/après chaque migration) recalcule la chaîne du journal et
  l'empreinte de chaque ligne (`verify-ledger`).

## L'app (lot 2)

L'app (Accueil, Patrimoine, Budget, Journal, Sources) lit uniquement les routes de
`/api/finance` ; chaque chiffre est calculé côté serveur, en centimes.

| Route | Ce qu'elle donne |
|---|---|
| `kpis?month=` | patrimoine net et variations (1 mois, depuis le 31 décembre), revenus, dépenses, épargne, reste à vivre, jours restants, liquidités, mois couverts, taux d'épargne 3 mois, comptes périmés, à catégoriser, marge 3a |
| `networth/history?from=&to=` | instantanés : patrimoine, versements cumulés, valeur par enveloppe |
| `flows?month=` | revenus → fixe, variable, épargne → catégories, et le reste sur compte |
| `budget?month=&period=m\|q` | réel et cible par catégorie de dépense, dépassements, reste à vivre |
| `budget/totals?month=&period=m\|q` | revenus, dépenses fixes et variables, épargne, placements, taux |
| `budget/months?month=&months=6` | les mêmes totaux, mois par mois (graphique Tendance) |
| `export.csv?from=&to=` | journal complet en CSV (session passkey seulement) |

- **Mois.** Le mois affiché est toujours un paramètre ; l'app part du mois civil à Zurich.
  `period=q` couvre les trois mois complets avant le mois choisi. Un mois futur est refusé.
- **Sans catégorie.** Les règles (lot 3) catégorisent à l'import ; ce qui reste sans
  catégorie compte en dépense variable si c'est négatif, en revenu sinon, sous le nom
  « À catégoriser », jusqu'à ce que tu le catégorises.
- **Portée aggregates.** Une catégorie de moins de 3 écritures sur la période rejoint
  « Autres » (flux, budget, résumé).
- **Instantanés.** Une ligne par fin de mois depuis la première écriture, plus une pour
  aujourd'hui, recalculées en entier chaque nuit et après chaque import appliqué (un relevé
  ancien corrige donc aussi les mois passés). Au lot 2, la valeur d'un compte est son solde
  et l'effet marché est nul ; les positions VIAC et IBKR arrivent au lot 4.
- **3e pilier.** Plafond 2026 : 7'258 CHF. Une autre valeur se règle dans `settings.toml`,
  section `[finance]`, clé `pillar3a_cap_minor` (en centimes).

## Reprendre l'historique (L1-11)

Décision du 27/10/2026 : tout ce que la BCF fournit en camt.053, sans importeur « ancien
format ».

1. Dans l'e-banking BCF, regarde jusqu'à quelle date l'export camt.053 remonte, puis exporte
   tous les relevés de chaque compte depuis cette date (un fichier par mois, ou un `.zip`).
2. Dépose-les dans `~/PersonalHub/inbox/history/` (un sous-dossier : la surveillance ne le lit
   pas).
3. Crée chaque compte, avec son IBAN :
   ```
   fin accounts add "BCF privé" --iban CH… --budget --liquid
   fin accounts add "BCF épargne" --iban CH… --liquid
   fin accounts list
   ```
4. Lance la reprise :
   ```
   fin import-history /srv/hub/inbox/history
   ```
   Elle trie les relevés par compte et par date, vérifie que chaque CLBD égale l'OPBD du
   relevé suivant **avant d'écrire quoi que ce soit**, crée le solde d'ouverture de chaque
   compte (veille du relevé le plus ancien), puis applique tout. Pendant ce temps, la boîte
   d'entrée et le dépôt par l'API sont en pause. La sortie ne contient que des compteurs et des
   IBAN masqués ; un trou affiche la période manquante et n'écrit rien.
5. Vérifie : `fin verify-ledger`, `fin imports list --status needs_review` (doit être vide),
   puis supprime le dossier `history/` du Mac (les originaux sont archivés chiffrés).

La reprise n'est possible qu'une fois par compte : dès qu'un compte a des écritures, un relevé
plus ancien est refusé (`before_opening`). Revenir plus loin demanderait une reconstruction
(lot 4).

## Catégories et Double Sas (lot 3)

**Règles.** Chaque écriture importée reçoit la catégorie de la règle active qui la reconnaît,
la plus prioritaire d'abord (priorité la plus basse, puis identifiant). Une règle ne touche
jamais une écriture que tu as catégorisée toi-même. Les règles de `bcf_aggregate.py` sont
déjà en base (préfixe `seed-`) ; reprends en plus ton fichier de règles, une fois :

```
mkdir -p ~/PersonalHub/inbox/rules
cp ~/Downloads/viac_out/bcf_rules.json ~/PersonalHub/inbox/rules/
fin rules import-legacy /srv/hub/inbox/rules/bcf_rules.json
rm -r ~/PersonalHub/inbox/rules
```

La sortie ne donne que des compteurs (règles ajoutées, gardées, désactivées, catégories
créées, écritures catégorisées). Une règle `seed-` ou `legacy-` absente du fichier est
désactivée ; tes IBAN propres sont ignorés (les virements internes ont leurs règles
système). `fin rules list [--all]` montre les règles, `fin rules run` les rejoue.

**Double Sas.** Rien ne change au registre sans une proposition validée. L'app montre
« À valider » sur l'Accueil : coche, puis un seul Face ID valide tout le lot. Le défi signé
porte la révision et l'empreinte de chaque proposition ; si un import change ce qu'une
proposition toucherait entre l'aperçu et la validation, elle revient avec une nouvelle
révision (409) et rien n'est appliqué. Dans le Journal, le filtre « À catégoriser » groupe
les écritures par contrepartie : « Ces N écritures » les recatégorise, « Toujours » crée une
règle qui sert aussi aux prochains imports.

| Proposition | Effet | Inverse |
|---|---|---|
| `recategorize` | catégorie d'une écriture (ou ventilation en lignes) | oui |
| `create_rule` · `disable_rule` | règle, appliquée tout de suite à ce qu'elle peut toucher | — |
| `set_budget` | cible mensuelle d'une catégorie de dépense, dès le 1er du mois | oui |
| `add_note` | note sur une écriture | — |
| `apply_import` | applique un relevé en attente dont les motifs se forcent | — |
| `create_account` · `create_category` | comptes et catégories (le CLI passe par là) | — |

Un relevé en attente pour un motif qui se force (`ledger_check_failed`, `near_duplicate`…)
devient une carte `apply_import` à valider ; il est rejoué avant d'appliquer. Depuis le Mac,
`hubc run --rm --no-deps importer hub proposals list|show|accept|reject` fait la même chose
sans Face ID (le terminal du Mac vaut validation).

## Autres commandes

| Commande | Rôle |
|---|---|
| `fin accounts add|list|open` | comptes (`add` passe par une proposition `create_account`) ; `open` crée un solde d'ouverture à la main |
| `fin categories add|list` | catégories, créées par une proposition `create_category` |
| `fin rules list [--all]` · `fin rules run` · `fin rules import-legacy FICHIER` | règles de catégorisation |
| `fin imports list [--status …]` · `fin imports retry [ID…]` | suivi et rejeu des imports |
| `fin watch-inbox --once` | un passage de la boîte d'entrée |
| `fin verify-ledger` | chaîne et empreintes, code 1 au moindre écart |
| `fin rebuild-fts` | index de recherche, après une restauration |
