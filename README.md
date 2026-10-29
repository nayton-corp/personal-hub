# Personal Hub

Un hub personnel, auto-hébergé : les données de sa vie (la finance d'abord, puis l'agenda, les
documents, la maison) tenues sur sa propre machine, avec un assistant qui propose et ne fait
jamais rien sans validation. Pourquoi et dans quel ordre : [vision.md](vision.md).

État : le domaine **Finance** tourne (comptes BCF, VIAC, Revolut, IBKR, cryptos, dettes,
budget, patrimoine) sur le Mac ; le **socle** (contrat de domaine, app modulaire, finance en
couches, intégrité et boîte d'entrée génériques) est en place pour accueillir les domaines
suivants. Les changements : [CHANGELOG.md](CHANGELOG.md).

## Lire

| Pour | Lire |
|---|---|
| comprendre comment c'est construit | [docs/architecture.md](docs/architecture.md) (avec les schémas) |
| les mots du hub, les choix datés | [docs/glossaire.md](docs/glossaire.md), [docs/decisions.md](docs/decisions.md) |
| ajouter un domaine | [docs/ajouter-un-domaine.md](docs/ajouter-un-domaine.md) |
| la sécurité | [docs/securite.md](docs/securite.md) |
| installer, déployer, sauvegarder | [docs/exploitation/](docs/exploitation/README.md) |
| la finance (usage), et son code | [docs/finance.md](docs/finance.md), [hub/domains/finance/README.md](hub/domains/finance/README.md) |
| les collecteurs, l'IA locale | [docs/collectors.md](docs/collectors.md), [docs/brain.md](docs/brain.md) |
| l'assistant (voix, maison, outils du hub) | [assistant/README.md](assistant/README.md) |
| routes, outils de l'assistant, connecteurs (générés) | [docs/reference/](docs/reference/) |

## Règles qui ne se discutent pas

- Aucune donnée réelle dans le dépôt, la CI ni les tests : des données fictives générées par
  du code. `scripts/check_no_data.sh` et gitleaks le vérifient à chaque commit.
- Montants en entiers (centimes) avec leur devise, jamais de flottant (test dédié).
- Tables protégées en ajout seul, journal chaîné, `hub verify` chaque nuit.
- Les journaux ne contiennent jamais de montant, libellé, IBAN, solde ni contrepartie.
- Rien ne s'écrit sans proposition validée (Double Sas) ; Claude ne lit que des agrégats.
- Les frontières des anneaux et les 400 lignes par fichier sont imposées par import-linter et
  `tests/test_file_size.py` : une règle qui échoue se corrige dans le code.

## Arborescence

```
hub/kernel/         noyau pur : Money, URN, horloge, JSON canonique, chaîne (ni base ni réseau)
hub/platform/       plateforme : SQLite, migrations, réglages, secrets, journaux filtrés, cron
hub/core/           cœur : accès (passkeys, jetons), propositions, contrat de domaine et
                    manifeste, registre, intégrité, boîte d'entrée, connexions, tâches de fond
hub/api/            application FastAPI et routes du cœur
hub/domains/        domaines, isolés par import-linter ; finance/ : registre, classement,
                    patrimoine, sources (chacun interface → app → infra → model)
hub/web/            l'app (PWA) : coquille (shell.js) et modules des domaines
hub/collectors/     collecteurs : robots et clients d'API qui déposent des fichiers
hub/brain/          IA locale : passerelle MCP, assistant et suggestions (`hub-brain`)
assistant/          l'assistant venu de Domia (paquet à part) : voix, maison, pont Rappels
hub/cli*.py         commande `hub`
deploy/             compose, Caddy, Tailscale, Litestream, crontab, deploy.sh
docs/               architecture, sécurité, exploitation, domaines, références générées
scripts/            données fictives, références, publication
tests/              pytest, Hypothesis, Playwright à 375 px ; domaine factice
```

## Développement

```
uv sync --frozen && uv run pre-commit install   # ou : make install
make check                                       # ruff, mypy --strict, import-linter, tests
make dev                                         # API + app sur http://localhost:8710
make web                                         # lint et tests des modules de l'app (Node 22)
```

En développement, les passkeys exigent `localhost` ou HTTPS : `make dev` sert l'app sur
`http://localhost:8710` (données dans `./var`, ignoré par git). Un changement voulu du contrat
d'API se valide avec `make openapi` ; une route, un outil ou un connecteur nouveau, avec
`make reference`.

## Commande `hub`

| Commande | Rôle |
|---|---|
| `hub init --config DIR --home DIR` | première installation : clé age, secrets, dossiers, `deploy/.env` (`make init`) |
| `hub db upgrade` · `hub db status` | migrations de `core.db` puis des domaines |
| `hub token create NOM -s brain=finance --days 90` · `list` · `rotate ID` · `revoke ID` | jetons à portée et à date de fin, montrés une seule fois |
| `hub auth bootstrap-code` | code à usage unique pour inscrire la première passkey |
| `hub serve` | API, un seul worker |
| `hub watch-inbox` | range `inbox/` par domaine, puis chaque domaine traite son dossier |
| `hub verify` | intégrité de chaque base, triggers des tables protégées, chaîne du journal |
| `hub backup [--restic]` · `hub restore STAMP` | copies `.backup` vérifiées, restic, restauration |
| `hub nightly` · `hub reconcile` | expirations, purges, réconciliation des propositions, nuit des domaines |
| `hub connections …` · `hub profile …` · `hub proposals …` | connexions des collecteurs, profil, propositions |
| `hub ops databases` · `hub ops litestream` | bases montées et configuration de la réplication |
| `hub scheduler deploy/crontab` | tâches planifiées du conteneur `scheduler` |
| `hub finance …` | comptes, catégories, règles, imports, reprises, reconstruction ([docs/finance.md](docs/finance.md)) |
| `hub-brain mcp` · `ask` · `suggest` · `check` | IA locale ([docs/brain.md](docs/brain.md)) |

Portées d'un jeton : `brain` (= `*:aggregates`), `brain=finance,agenda` (en plus, lecture et
propositions des domaines nommés), `aggregates` (= `*:aggregates`), `collector`
(= `core:collector`), ou une portée qualifiée (`finance:read`). La portée `app` n'existe que
par une session passkey.
