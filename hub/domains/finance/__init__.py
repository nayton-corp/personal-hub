"""Domaine Finance : registre en ajout seul, classement et budget, patrimoine, sources.

Quatre sous-contextes, chacun en couches `interface` (routes, commandes, outils de l'assistant)
→ `app` (cas d'usage, SQL) → `infra` (formats et fichiers, sans base) → `model` (pur) :

- `registre` : comptes, écritures, journal chaîné, lectures du journal, export ;
- `classement` : règles, packs, catégorisation, budget, revue, abonnements, sentinelles ;
- `patrimoine` : instruments, cours, valorisation, dettes, performance, transparence des fonds ;
- `sources` : import camt.053, VIAC, Revolut, IBKR, crypto, positions à la main, reprises.

Un sous-contexte n'importe que ceux d'après lui dans cet ordre : sources → patrimoine →
classement → registre. Au-dessus : `domain` (le contrat de domaine), ses bords (`api`, `cli`,
`tools`, `handlers`, `rebuild`), `port` (ce que les bords attendent du domaine) et `public`
(la seule lecture permise aux autres domaines). `pyproject.toml` (import-linter) l'impose.
"""

from hub.domains.finance.domain import FinanceDomain, create

__all__ = ["FinanceDomain", "create"]
