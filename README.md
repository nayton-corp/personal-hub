# Personal Hub

Registre financier personnel, auto-hébergé. Le domaine Finance vient en premier ; le cœur
(accès, propositions, trace) est commun à tous les domaines. Le plan de référence et la
spécification d'implémentation vivent dans le document « Personal Hub — plan de
développement » ; ce dépôt en suit les tickets, lot par lot.

État : **lot 1 (Registre BCF)**. Le domaine Finance importe les relevés camt.053 dans un
registre en ajout seul ; voir [docs/finance.md](docs/finance.md).

## Règles qui ne se discutent pas

- Aucune donnée réelle dans le dépôt, dans la CI ni dans les tests : uniquement des fixtures
  générées par du code. `scripts/check_no_data.sh` et gitleaks le vérifient à chaque commit.
- Montants en entiers (unités mineures) + devise, jamais de flottant (test dédié).
- Tables protégées en ajout seul : déclencheurs anti `UPDATE`/`DELETE`, `recursive_triggers`
  actif, `INSERT OR REPLACE` interdit (lint des migrations et du code).
- Les journaux ne contiennent jamais de montant, libellé, IBAN, solde ni contrepartie.

## Arborescence

```
hub/core/           cœur : réglages, Money, journaux filtrés, erreurs problem+json, base core.db,
                    jetons, passkeys, propositions, contrat de domaine, registre, tâches de fond
hub/core/migrations Alembic de core.db (SQL explicite, pas de downgrade)
hub/api/            application FastAPI et routes du cœur
hub/domains/        domaines, isolés par import-linter ; finance/ : registre, camt.053, API
hub/web/            coquille de l'app (PWA), servie par Caddy
hub/brain/          IA locale : passerelle MCP, assistant et suggestions (`hub-brain`), sur le Mac
hub/cli.py          commande `hub`
deploy/             compose, Caddy, Tailscale, Litestream, crontab, deploy.sh
docs/               installation, mise en route sur le Mac, domaine Finance, kit de secours,
                    glossaire (les mots du hub) et décisions (les choix qui l'engagent)
tests/              pytest, Hypothesis ; domaine factice et authentificateur WebAuthn logiciel
```

## Développement

```
uv sync --frozen && uv run pre-commit install   # ou : make install
make check                                       # ruff, mypy --strict, import-linter, tests
make dev                                         # API + app sur http://localhost:8710
```

En développement, les passkeys exigent `localhost` ou HTTPS : `make dev` sert l'app sur
`http://localhost:8710` (données dans `./var`, ignoré par git).

Un changement voulu du contrat d'API se valide avec `make openapi`, puis relecture du diff de
`tests/openapi.snapshot.json`.

## Commande `hub`

| Commande | Rôle |
|---|---|
| `hub init --config DIR --home DIR` | première installation : clé age, secrets, dossiers, `deploy/.env` (`make init`) |
| `hub db upgrade` · `hub db status` | migrations de `core.db` puis des domaines |
| `hub token create NOM -s brain` · `list` · `revoke ID` | jetons à portée, montrés une seule fois |
| `hub auth bootstrap-code` | code à usage unique pour inscrire la première passkey |
| `hub serve` | API, un seul worker |
| `hub verify` | `integrity_check` de chaque base, puis `verify-ledger` |
| `hub finance …` | comptes, catégories, imports, reprise d'historique ([docs/finance.md](docs/finance.md)) |
| `hub backup [--restic]` · `hub restore STAMP` | copies `.backup` vérifiées, restic, restauration |
| `hub nightly` · `hub reconcile` | expirations, purges, réconciliation des propositions |
| `hub scheduler deploy/crontab` | tâches planifiées du conteneur `scheduler` |
| `hub-brain mcp` · `ask` · `suggest` · `check` | IA locale, conteneur `brain` ([docs/brain.md](docs/brain.md)) |

Portées d'un jeton : `brain` (= `finance:read finance:propose`), `aggregates`
(= `*:aggregates`), `collector` (= `core:collector`), ou une portée qualifiée. La portée `app`
n'existe que par une session passkey.

## Exploitation

Installer son propre hub (un hub par personne) : [docs/installation.md](docs/installation.md),
`make init` puis `make deploy`. Phase 1 : tout tourne sur le Mac en conteneurs, voir
[docs/mac.md](docs/mac.md). Le Pi arrivera avec les mêmes images et le même
`deploy/compose.yaml`.
