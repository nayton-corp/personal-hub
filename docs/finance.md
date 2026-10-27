# Domaine Finance : registre BCF

Ce que fait le lot 1, et comment reprendre ton historique BCF sur le Mac (ticket L1-11).
Toutes les commandes passent par le conteneur `importer`, le seul qui voit la boîte d'entrée :

```
alias hubc='docker compose --env-file deploy/.env -f deploy/compose.yaml'
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

## Autres commandes

| Commande | Rôle |
|---|---|
| `fin accounts add|list|open` | comptes ; `open` crée un solde d'ouverture à la main |
| `fin categories add|list` | catégories (17 fournies, dont `transfer-own`) |
| `fin imports list [--status …]` · `fin imports retry [ID…]` | suivi et rejeu des imports |
| `fin watch-inbox --once` | un passage de la boîte d'entrée |
| `fin verify-ledger` | chaîne et empreintes, code 1 au moindre écart |
| `fin rebuild-fts` | index de recherche, après une restauration |
