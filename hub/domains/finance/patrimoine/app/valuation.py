"""Valeur du patrimoine à une date, par enveloppe, dans la devise de base (HUB_CURRENCY, CHF par
défaut ; tickets L2-01, L2-02, L4-06 et lot 6) : une lecture de la série (model/engine.py), le
seul calcul de la valeur (audit C2).

La valeur d'un compte est son solde au registre (écritures, ouverture comprise), sauf pour un
compte qui porte des positions (VIAC, IBKR, portefeuille crypto, placements saisis à la main) :
ses parts à la date, fois le dernier cours connu, converti dans la devise de base au cours de
change de la date (model/positions.py). Sans aucun cours, le compte garde son solde au registre et
est signalé dans `missing_prices`. Un compte à positions est tenu dans la devise de base.

Les versements cumulés (ledger_sums.py) sont convertis au change de leur jour (audit M1).
L'effet marché est la différence entre la valeur et les versements. Un compte dans une autre
devise sans cours de change à la date est laissé de côté et signalé dans `missing_fx`.

Les dettes (debts.py) sont retranchées : enveloppe « dettes », clé `debt:<id>` dans
`by_account`, et versement de même montant (un remboursement n'est pas un effet marché).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection

from hub.domains.finance.patrimoine.app import perf_lines
from hub.domains.finance.patrimoine.app.ledger_sums import (
    CATEGORY_JOIN as CATEGORY_JOIN,
)
from hub.domains.finance.patrimoine.app.ledger_sums import (
    CRYPTO_PURCHASE as CRYPTO_PURCHASE,
)
from hub.domains.finance.patrimoine.app.ledger_sums import (
    NOT_DEPOSITS as NOT_DEPOSITS,
)
from hub.domains.finance.patrimoine.app.ledger_sums import (
    OFF_LEDGER_PURCHASES as OFF_LEDGER_PURCHASES,
)
from hub.domains.finance.patrimoine.app.market_data import FxTable as FxTable
from hub.domains.finance.patrimoine.app.market_data import Line as Line
from hub.domains.finance.patrimoine.app.market_data import Positions as Positions
from hub.domains.finance.patrimoine.model import engine
from hub.domains.finance.patrimoine.model.engine import ABSENT, ENVELOPE_ORDER, ENVELOPES, Account

__all__ = [
    "ABSENT",
    "CATEGORY_JOIN",
    "CRYPTO_PURCHASE",
    "ENVELOPES",
    "ENVELOPE_ORDER",
    "NOT_DEPOSITS",
    "OFF_LEDGER_PURCHASES",
    "Account",
    "FxTable",
    "Line",
    "Positions",
    "Valuation",
    "account_value",
    "accounts",
    "held",
    "read",
    "series",
    "value_at",
]


@dataclass
class Valuation:
    on_date: str
    net_worth: int = 0
    deposits: int = 0
    liquid: int = 0
    by_envelope: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ENVELOPE_ORDER, 0))
    by_account: dict[str, int] = field(default_factory=dict)  # dans la devise de base
    missing_fx: list[str] = field(default_factory=list)
    missing_prices: list[str] = field(default_factory=list)  # instruments sans cours à la date


def accounts(conn: Connection) -> list[Account]:
    return list(perf_lines.accounts(conn))


def held(
    positions: Positions, account_id: str, currency: str, balance: int, on_date: str
) -> tuple[int, str, list[str]]:
    """(valeur, sa devise, instruments sans cours) : les positions dans la devise de base,
    sinon le solde au registre dans la devise du compte (la règle de la série)."""
    if account_id not in positions.accounts:
        return balance, currency, []
    lines = positions.lines(account_id, on_date)
    missing = [x.isin for x in lines if x.price is None]
    if not lines or len(missing) == len(lines):
        return balance, currency, missing
    return sum(x.value for x in lines), positions.fx.base, missing


def account_value(
    positions: Positions, account_id: str, balance: int, on_date: str
) -> tuple[int, list[str]]:
    """(valeur, instruments sans cours) d'un compte, dans la devise de base s'il a des
    positions."""
    value, _ccy, missing = held(positions, account_id, positions.fx.base, balance, on_date)
    return value, missing


def read(s: engine.Series, k: int) -> Valuation:
    """La valeur du patrimoine le jour `k` de la série : la somme de ses lignes."""
    out = Valuation(s.days[k])
    nofx = s.missing_fx.get(k, ())
    out.missing_fx = list(nofx)
    values = s.values_at(k)
    for a in s.accounts:
        if a.id in nofx:
            continue
        value = values.get(a.id, 0)
        out.net_worth += value
        out.deposits += s.deposits[a.id][k]
        out.by_envelope[a.envelope] += value
        out.by_account[a.id] = value
        if a.liquid:
            out.liquid += value
    for ln in s.lines.values():
        if ln.kind != "debt" or ln.account_id in nofx or ln.value[k] == ABSENT:
            continue
        value = ln.value[k]
        out.net_worth += value
        out.deposits += value
        out.by_envelope["dettes"] += value
        out.by_account[ln.account_id] = value
    out.missing_prices = sorted({isin for _acc, isin in s.unpriced.get(k, ())})
    return out


def value_at(conn: Connection, on_date: str) -> Valuation:
    """La valeur à une date : sert aux chiffres clés et de référence aux instantanés."""
    s = perf_lines.engine_for(conn, on_date)
    if s is None or on_date < s.days[0]:
        return Valuation(on_date)
    return read(s, s.index(on_date))


def series(conn: Connection, dates: Sequence[str]) -> list[Valuation]:
    """Même calcul que `value_at`, en une seule lecture de la série."""
    if not dates:
        return []
    s = perf_lines.engine_for(conn, max(dates))
    return [
        Valuation(d) if s is None or d < s.days[0] else read(s, s.index(d)) for d in sorted(dates)
    ]
