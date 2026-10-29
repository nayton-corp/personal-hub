# Domaine Finance (code)

Le domaine vu de l'utilisateur : [docs/finance.md](../../../docs/finance.md). Ici, le code :
quatre sous-contextes, chacun en couches, et les bords du domaine. La décision :
[D-019](../../../docs/decisions.md).

## Les sous-contextes

| Sous-contexte | Ce qu'il tient | Lit |
|---|---|---|
| `registre` | comptes et catégories, écritures, journal chaîné, ouverture d'un compte, lectures du journal, export CSV | — |
| `classement` | règles et packs, catégorisation et ses propositions, totaux par catégorie, revue, budget, abonnements, sentinelles | registre |
| `patrimoine` | instruments, cours et positions, valorisation, dettes, instantanés, virements appariés, performance, transparence des fonds | classement, registre |
| `sources` | import camt.053, VIAC, Revolut, IBKR, marché et plateformes crypto, positions à la main, SwissBorg ; boîte d'entrée, reprises, catalogue des connecteurs | patrimoine, classement, registre |

Un sous-contexte n'importe que ceux de sa colonne « Lit ».

## Les couches d'un sous-contexte

- `interface` : routes HTTP (`api.py`), commandes `hub finance …` (`cli.py`), outils de
  l'assistant (`tools.py`). Chacune déclare un `Host` : ce qu'elle attend du domaine.
- `app` : cas d'usage, SQL, types de proposition (`*_kinds.py`). Ni FastAPI ni Typer.
- `infra` : formats externes et fichiers (camt.053, Flex Query IBKR, `hub.market.v1`,
  compositions de fonds, archive chiffrée). Ni base ni HTTP.
- `model` : types et calculs purs (empreintes, périodes, clés de dédoublonnage, instruments,
  rendements). Ni SQL, ni HTTP, ni module du cœur qui en porte.

## Au-dessus des sous-contextes

- `domain.py` : `FinanceDomain`, le contrat de domaine (`hub.core.domain.Domain`).
- `manifest.py` : ce que la finance apporte à l'app, à la boîte d'entrée et à l'assistant.
- `api.py`, `cli.py`, `tools.py` : assemblent les interfaces des sous-contextes.
- `handlers.py` : les types de proposition, réunis pour le cœur.
- `rebuild.py`, `compare.py` : reconstruction du registre par rejeu, comparaison de deux bases.
- `port.py` : `Finance`, ce que ces bords attendent du domaine (ils n'importent pas
  `domain.py`).
- `public.py` : la seule lecture permise aux autres domaines, des agrégats.
- `migrations/` : Alembic de `finance.db`.

Les contrats import-linter de `pyproject.toml` imposent ces règles, sans écart.
