"""Les sommes du registre que la série lit, par jour et par compte : total des écritures,
revenus, frais et versements (SQL partagé par valuation.py, perf_lines.py et holdings.py).

Les versements sont toutes les écritures, sauf le rendement, les frais et les mouvements internes
d'un courtier (codes VIAC/INCOME, VIAC/FEE, IBKR/TRADE, IBKR/FX, IBKR/INCOME, IBKR/FEE) et les
paiements catégorisés « Achats et ventes de titres » ou « Crypto » : ce paiement achète une
position tenue hors registre (actions Revolut, cryptos chez SwissBorg ou sur une Ledger), il ne
sort pas du patrimoine. Un versement au 3a ou à IBKR est un apport, un dividende un effet marché.
"""

from __future__ import annotations

from hub.domains.finance.registre.model import institutions

# hors versements : rendement, frais et mouvements internes des courtiers (préfixes de code)
NOT_DEPOSITS = institutions.prefixes(market=True)
# achats de positions tenues hors registre : actions Revolut, cryptos (virements vers SwissBorg…)
OFF_LEDGER_PURCHASES = ("transfer-titres", "crypto")
CRYPTO_PURCHASE = "crypto"
INCOME_CATEGORIES = ("rendement", "interets-dividendes")
FEE_CATEGORIES = ("frais-placement",)
_INCOME_CODES = tuple(c.prefix for c in institutions.CODES if c.category in INCOME_CATEGORIES)
_FEE_CODES = tuple(c.prefix for c in institutions.CODES if c.category in FEE_CATEGORIES)


def _in(cats: tuple[str, ...]) -> str:
    return ", ".join(f"'{c}'" for c in cats)  # identifiants fixes, jamais une saisie


CATEGORY_JOIN = "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq"
DEPOSITS_SQL = (
    f"sum(CASE WHEN {institutions.like_any('e.bank_tx_code', NOT_DEPOSITS)} "
    f"OR vc.category_id IN ({_in(OFF_LEDGER_PURCHASES)}) THEN 0 ELSE e.amount_minor END)"
)
INCOME_SQL = (
    f"CASE WHEN vc.category_id IN ({_in(INCOME_CATEGORIES)}) OR "
    f"{institutions.like_any('e.bank_tx_code', _INCOME_CODES)} THEN e.amount_minor ELSE 0 END"
)
FEES_SQL = (
    f"CASE WHEN vc.category_id IN ({_in(FEE_CATEGORIES)}) OR "
    f"{institutions.like_any('e.bank_tx_code', _FEE_CODES)} THEN e.amount_minor ELSE 0 END"
)
# écritures du jour par compte : total, revenus, frais, versements (devise du compte)
DAILY_SQL = (
    f"SELECT e.booking_date, e.account_id, sum(e.amount_minor), sum({INCOME_SQL}), "  # noqa: S608
    f"sum({FEES_SQL}), {DEPOSITS_SQL} FROM entries e {CATEGORY_JOIN} "
    "WHERE e.booking_date <= :d GROUP BY e.booking_date, e.account_id ORDER BY e.booking_date"
)
