"""Valeur du patrimoine à une date, par enveloppe, en CHF (tickets L2-01, L2-02 et L4-06).

La valeur d'un compte est son solde au registre (écritures, ouverture comprise), sauf pour un
compte de titres (VIAC) : ses parts à la date, fois le dernier cours connu. Les parts sont
celles du dernier rapport, plus les achats et ventes des avis postérieurs ; sans aucun cours,
le compte garde son solde au registre et est signalé dans `missing_prices`.

Les versements cumulés sont toutes les écritures, sauf le rendement et les frais des
placements (codes VIAC/INCOME et VIAC/FEE) : un achat de titres est un mouvement interne, un
versement au 3a un apport, un dividende un effet marché. L'effet marché est la différence
entre la valeur et les versements. Un compte dans une autre devise est converti au dernier
cours de `fx_rates` connu à la date ; sans cours, il est laissé de côté et signalé dans
`missing_fx`.
"""

from __future__ import annotations

import bisect
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.core.money import DECIMAL_CONTEXT, Money

BASE = "CHF"
# enveloppes de by_envelope_json (spécification, section 2), tirées du type de compte
ENVELOPES = {"cash": "cash", "pension": "pilier3a", "securities": "ibkr", "crypto": "crypto"}
ENVELOPE_ORDER = ("cash", "pilier3a", "ibkr", "crypto")
# versements : toutes les écritures sauf le rendement et les frais des placements
DEPOSITS_SQL = (
    "sum(CASE WHEN bank_tx_code LIKE 'VIAC/INCOME%' OR bank_tx_code = 'VIAC/FEE' "
    "THEN 0 ELSE amount_minor END)"
)


@dataclass(frozen=True)
class Account:
    id: str
    kind: str
    currency: str
    liquid: bool

    @property
    def envelope(self) -> str:
        return ENVELOPES[self.kind]


@dataclass
class Valuation:
    on_date: str
    net_worth: int = 0
    deposits: int = 0
    liquid: int = 0
    by_envelope: dict[str, int] = field(default_factory=lambda: dict.fromkeys(ENVELOPE_ORDER, 0))
    missing_fx: list[str] = field(default_factory=list)
    missing_prices: list[str] = field(default_factory=list)  # ISIN sans cours à la date


@dataclass(frozen=True)
class Line:
    """Une position valorisée d'un compte de titres."""

    account_id: str
    isin: str
    quantity: Decimal
    price: Decimal | None
    price_date: str | None
    value: int  # centimes CHF ; 0 sans cours


class Positions:
    """Parts, rapports et cours de tous les comptes de titres, lus une fois par calcul."""

    def __init__(self, conn: Connection) -> None:
        self.trades: dict[str, list[tuple[str, str, Decimal]]] = {}
        for account_id, on, isin, qty in conn.execute(
            text("SELECT account_id, trade_date, isin, quantity FROM trades ORDER BY trade_date")
        ):
            self.trades.setdefault(account_id, []).append((on, isin, Decimal(qty)))
        # rapports : account -> [(date, {isin: (parts, valeur)})] triés
        snaps: dict[str, dict[str, dict[str, tuple[Decimal, int]]]] = {}
        for account_id, on, isin, qty, value in conn.execute(
            text("SELECT account_id, on_date, isin, quantity, value_minor FROM holdings")
        ):
            snaps.setdefault(account_id, {}).setdefault(on, {})[isin] = (Decimal(qty), int(value))
        self.reports = {a: sorted(by_date.items()) for a, by_date in snaps.items()}
        # cours : à date égale, celui du rapport (source triée en dernier) l'emporte
        self.prices: dict[str, list[tuple[str, Decimal]]] = {}
        for isin, on, price in conn.execute(
            text("SELECT isin, on_date, price FROM prices ORDER BY on_date, source")
        ):
            self.prices.setdefault(isin, []).append((on, Decimal(price)))
        self._dates = {i: [d for d, _ in p] for i, p in self.prices.items()}

    @property
    def accounts(self) -> set[str]:
        return set(self.trades) | set(self.reports)

    def price(self, isin: str, on_date: str) -> tuple[str, Decimal] | None:
        k = bisect.bisect_right(self._dates.get(isin, []), on_date)
        return self.prices[isin][k - 1] if k else None

    def lines(self, account_id: str, on_date: str) -> list[Line]:
        with localcontext(DECIMAL_CONTEXT):
            base: dict[str, tuple[Decimal, int]] = {}
            since = ""
            for d, held in self.reports.get(account_id, []):
                if d <= on_date:
                    base, since = held, d
            qty = {isin: q for isin, (q, _v) in base.items()}
            moved = set()
            for d, isin, q in self.trades.get(account_id, []):
                if since < d <= on_date:
                    qty[isin] = qty.get(isin, Decimal(0)) + q
                    moved.add(isin)
            out = []
            for isin in sorted(qty):
                if qty[isin] == 0:
                    continue
                known = self.price(isin, on_date)
                if known is None:
                    out.append(Line(account_id, isin, qty[isin], None, None, 0))
                    continue
                d, price = known
                if isin in base and isin not in moved and d <= since:
                    value = base[isin][1]  # valeur du rapport, au centime près
                else:
                    value = Money.from_decimal(qty[isin] * price, BASE).minor
                out.append(Line(account_id, isin, qty[isin], price, d, value))
            return out


def accounts(conn: Connection) -> list[Account]:
    rows = conn.execute(
        text("SELECT id, kind, currency, liquid FROM accounts ORDER BY institution, name, id")
    ).fetchall()
    return [Account(r[0], r[1], r[2], bool(r[3])) for r in rows]


class FxTable:
    """Cours vers CHF par devise, triés par date ; lus une fois par calcul."""

    def __init__(self, conn: Connection, currencies: Sequence[str]) -> None:
        self._rates: dict[str, list[tuple[str, Decimal]]] = {}
        for ccy in sorted(set(currencies) - {BASE}):
            rows = conn.execute(
                text(
                    "SELECT on_date, rate FROM fx_rates WHERE base = :b AND quote = :q "
                    "ORDER BY on_date, source"
                ),
                {"b": ccy, "q": BASE},
            ).fetchall()
            self._rates[ccy] = [(r[0], Decimal(r[1])) for r in rows]

    def to_base(self, minor: int, currency: str, on_date: str) -> int | None:
        if currency == BASE:
            return minor
        known = [rate for d, rate in self._rates.get(currency, []) if d <= on_date]
        if not known:
            return None
        with localcontext(DECIMAL_CONTEXT):
            amount = Money(minor, currency).to_decimal() * known[-1]
        return Money.from_decimal(amount, BASE).minor


def account_value(
    positions: Positions, account_id: str, balance: int, on_date: str
) -> tuple[int, list[str]]:
    """(valeur en devise du compte, ISIN sans cours) ; le solde hors comptes de titres."""
    if account_id not in positions.accounts:
        return balance, []
    lines = positions.lines(account_id, on_date)
    missing = [x.isin for x in lines if x.price is None]
    if lines and len(missing) == len(lines):
        return balance, missing
    return sum(x.value for x in lines), missing


def _value(
    accts: Sequence[Account],
    balances: dict[str, tuple[int, int]],
    fx: FxTable,
    positions: Positions,
    on_date: str,
) -> Valuation:
    out = Valuation(on_date)
    for a in accts:
        balance, deposits = balances.get(a.id, (0, 0))
        held, missing = account_value(positions, a.id, balance, on_date)
        value = fx.to_base(held, a.currency, on_date)
        cost = fx.to_base(deposits, a.currency, on_date)
        if value is None or cost is None:
            out.missing_fx.append(a.id)
            continue
        out.missing_prices += missing
        out.net_worth += value
        out.deposits += cost
        out.by_envelope[a.envelope] += value
        if a.liquid:
            out.liquid += value
    out.missing_prices = sorted(set(out.missing_prices))
    return out


def value_at(conn: Connection, on_date: str) -> Valuation:
    """Calcul direct à une date : sert aux chiffres clés et de référence aux instantanés."""
    accts = accounts(conn)
    rows = conn.execute(
        text(
            "SELECT account_id, sum(amount_minor), " + DEPOSITS_SQL + " FROM entries "  # noqa: S608
            "WHERE booking_date <= :d GROUP BY account_id"
        ),
        {"d": on_date},
    ).fetchall()
    fx = FxTable(conn, [a.currency for a in accts])
    balances = {r[0]: (int(r[1]), int(r[2])) for r in rows}
    return _value(accts, balances, fx, Positions(conn), on_date)


def series(conn: Connection, dates: Sequence[str]) -> list[Valuation]:
    """Même calcul que `value_at`, en un seul passage sur les sommes journalières."""
    accts = accounts(conn)
    fx = FxTable(conn, [a.currency for a in accts])
    positions = Positions(conn)
    daily = conn.execute(
        text(
            "SELECT booking_date, account_id, sum(amount_minor), " + DEPOSITS_SQL + " FROM entries "  # noqa: S608
            "GROUP BY booking_date, account_id ORDER BY booking_date"
        )
    ).fetchall()
    balances: dict[str, tuple[int, int]] = {}
    out = []
    i = 0
    for d in sorted(dates):
        while i < len(daily) and daily[i][0] <= d:
            b, c = balances.get(daily[i][1], (0, 0))
            balances[daily[i][1]] = (b + int(daily[i][2]), c + int(daily[i][3]))
            i += 1
        out.append(_value(accts, dict(balances), fx, positions, d))
    return out
