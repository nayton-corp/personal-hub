"""Valeur du patrimoine à une date, par enveloppe, en CHF (tickets L2-01, L2-02, L4-06 et lot 6).

La valeur d'un compte est son solde au registre (écritures, ouverture comprise), sauf pour un
compte qui porte des positions (VIAC, IBKR, portefeuille crypto, placements saisis à la main) :
ses parts à la date, fois le dernier cours connu, converti en CHF au cours de change de la date.
Les parts sont celles du dernier relevé de positions, plus les achats et ventes postérieurs ;
sans aucun cours, le compte garde son solde au registre et est signalé dans `missing_prices`.
Un compte à positions est tenu en CHF : sa valeur est toujours en CHF.

Les versements cumulés sont toutes les écritures, sauf le rendement, les frais et les
mouvements internes d'un courtier (codes VIAC/INCOME, VIAC/FEE, IBKR/TRADE, IBKR/FX,
IBKR/INCOME, IBKR/FEE) et les paiements catégorisés « Achats et ventes de titres » ou
« Crypto » : ce paiement achète une position tenue hors registre (actions Revolut, cryptos chez
SwissBorg ou sur une Ledger), il ne sort pas du patrimoine. Un versement au 3a ou à IBKR est
un apport, un dividende un effet marché. L'effet marché est la différence entre la valeur et
les versements. Un compte dans une autre devise est
converti au dernier cours de `fx_rates` connu à la date ; sans cours, il est laissé de côté et
signalé dans `missing_fx`.
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
ENVELOPES = {"cash": "cash", "pension": "pilier3a", "securities": "titres", "crypto": "crypto"}
ENVELOPE_ORDER = ("cash", "pilier3a", "titres", "crypto")
# hors versements : rendement, frais et mouvements internes des courtiers (préfixes de code)
NOT_DEPOSITS = ("VIAC/INCOME", "VIAC/FEE", "IBKR/TRADE", "IBKR/FX", "IBKR/INCOME", "IBKR/FEE")
# achats de positions tenues hors registre : actions Revolut, cryptos (virements vers SwissBorg…)
OFF_LEDGER_PURCHASES = ("transfer-titres", "crypto")
CRYPTO_PURCHASE = "crypto"
_CODES = " OR ".join(f"e.bank_tx_code LIKE '{c}%'" for c in NOT_DEPOSITS)
_PURCHASES = ", ".join(f"'{c}'" for c in OFF_LEDGER_PURCHASES)
DEPOSITS_SQL = (
    f"sum(CASE WHEN {_CODES} OR vc.category_id IN ({_PURCHASES}) THEN 0 ELSE e.amount_minor END)"
)
CATEGORY_JOIN = "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq"


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
    missing_prices: list[str] = field(default_factory=list)  # instruments sans cours à la date


@dataclass(frozen=True)
class Line:
    """Une position valorisée d'un compte à positions."""

    account_id: str
    isin: str
    quantity: Decimal
    price: Decimal | None  # dans `currency` ; None sans cours ou sans change
    price_date: str | None
    value: int  # centimes CHF ; 0 sans cours
    currency: str = BASE  # devise du cours


class FxTable:
    """Cours vers CHF par devise, triés par date ; lus une fois par calcul."""

    def __init__(self, conn: Connection, currencies: Sequence[str] | None = None) -> None:
        if currencies is None:
            currencies = list(conn.execute(text("SELECT code FROM currencies")).scalars())
        self._rates: dict[str, list[tuple[str, Decimal]]] = {}
        self._dates: dict[str, list[str]] = {}
        for ccy in sorted(set(currencies) - {BASE}):
            rows = conn.execute(
                text(
                    "SELECT on_date, rate FROM fx_rates WHERE base = :b AND quote = :q "
                    "ORDER BY on_date, source"
                ),
                {"b": ccy, "q": BASE},
            ).fetchall()
            self._rates[ccy] = [(r[0], Decimal(r[1])) for r in rows]
            self._dates[ccy] = [r[0] for r in rows]

    def rate(self, currency: str, on_date: str) -> Decimal | None:
        if currency == BASE:
            return Decimal(1)
        k = bisect.bisect_right(self._dates.get(currency, []), on_date)
        return self._rates[currency][k - 1][1] if k else None

    def convert(self, amount: Decimal, currency: str, on_date: str) -> int | None:
        """Montant décimal dans `currency` → centimes CHF, ou None sans cours."""
        rate = self.rate(currency, on_date)
        if rate is None:
            return None
        with localcontext(DECIMAL_CONTEXT):
            return Money.from_decimal(amount * rate, BASE).minor

    def to_base(self, minor: int, currency: str, on_date: str) -> int | None:
        if currency == BASE:
            return minor
        return self.convert(Money(minor, currency).to_decimal(), currency, on_date)


class Positions:
    """Parts, relevés de positions et cours de tous les comptes à positions, lus une fois."""

    def __init__(self, conn: Connection, fx: FxTable | None = None) -> None:
        self.fx = fx or FxTable(conn)
        self.trades: dict[str, list[tuple[str, str, Decimal]]] = {}
        for account_id, on, isin, qty in conn.execute(
            text(
                "SELECT account_id, trade_date, isin, quantity FROM trades ORDER BY trade_date, seq"
            )
        ):
            self.trades.setdefault(account_id, []).append((on, isin, Decimal(qty)))
        # relevés : account -> [(date, {isin: (parts, valeur, devise)})] triés
        snaps: dict[str, dict[str, dict[str, tuple[Decimal, int, str]]]] = {}
        for account_id, on, isin, qty, value, ccy in conn.execute(
            text("SELECT account_id, on_date, isin, quantity, value_minor, currency FROM holdings")
        ):
            snaps.setdefault(account_id, {}).setdefault(on, {})[isin] = (
                Decimal(qty),
                int(value),
                str(ccy),
            )
        self.reports = {a: sorted(by_date.items()) for a, by_date in snaps.items()}
        # cours : à date égale, la source triée en dernier l'emporte (rapport VIAC sur l'avis)
        self.prices: dict[str, list[tuple[str, Decimal, str]]] = {}
        for isin, on, price, ccy in conn.execute(
            text("SELECT isin, on_date, price, currency FROM prices ORDER BY on_date, source")
        ):
            self.prices.setdefault(isin, []).append((on, Decimal(price), str(ccy)))
        self._dates = {i: [d for d, _p, _c in p] for i, p in self.prices.items()}

    @property
    def accounts(self) -> set[str]:
        return set(self.trades) | set(self.reports)

    def price(self, isin: str, on_date: str) -> tuple[str, Decimal, str] | None:
        k = bisect.bisect_right(self._dates.get(isin, []), on_date)
        return self.prices[isin][k - 1] if k else None

    def quantities(
        self, account_id: str, on_date: str
    ) -> tuple[dict[str, Decimal], dict[str, tuple[Decimal, int, str]], str, set[str]]:
        """(parts par instrument, dernier relevé, sa date, instruments bougés depuis)."""
        with localcontext(DECIMAL_CONTEXT):
            base: dict[str, tuple[Decimal, int, str]] = {}
            since = ""
            for d, held in self.reports.get(account_id, []):
                if d <= on_date:
                    base, since = held, d
            qty = {isin: q for isin, (q, _v, _c) in base.items()}
            moved = set()
            for d, isin, q in self.trades.get(account_id, []):
                if since < d <= on_date:
                    qty[isin] = qty.get(isin, Decimal(0)) + q
                    moved.add(isin)
        return qty, base, since, moved

    def lines(self, account_id: str, on_date: str) -> list[Line]:
        qty, base, since, moved = self.quantities(account_id, on_date)
        out = []
        with localcontext(DECIMAL_CONTEXT):
            for isin in sorted(qty):
                if qty[isin] == 0:
                    continue
                known = self.price(isin, on_date)
                if known is None:
                    out.append(Line(account_id, isin, qty[isin], None, None, 0))
                    continue
                d, price, ccy = known
                if isin in base and isin not in moved and d == since:
                    # valeur du relevé, au centime près, convertie au change de la date
                    _q, reported, rccy = base[isin]
                    value = self.fx.to_base(reported, rccy, on_date)
                else:
                    value = self.fx.convert(qty[isin] * price, ccy, on_date)
                if value is None:  # cours sans change vers CHF
                    out.append(Line(account_id, isin, qty[isin], None, d, 0, ccy))
                    continue
                out.append(Line(account_id, isin, qty[isin], price, d, value, ccy))
        return out


def accounts(conn: Connection) -> list[Account]:
    rows = conn.execute(
        text("SELECT id, kind, currency, liquid FROM accounts ORDER BY institution, name, id")
    ).fetchall()
    return [Account(r[0], r[1], r[2], bool(r[3])) for r in rows]


def held(
    positions: Positions, account_id: str, currency: str, balance: int, on_date: str
) -> tuple[int, str, list[str]]:
    """(valeur, sa devise, instruments sans cours) : les positions en CHF, sinon le solde au
    registre dans la devise du compte."""
    if account_id not in positions.accounts:
        return balance, currency, []
    lines = positions.lines(account_id, on_date)
    missing = [x.isin for x in lines if x.price is None]
    if not lines or len(missing) == len(lines):
        return balance, currency, missing
    return sum(x.value for x in lines), BASE, missing


def account_value(
    positions: Positions, account_id: str, balance: int, on_date: str
) -> tuple[int, list[str]]:
    """(valeur, instruments sans cours) d'un compte tenu en CHF s'il a des positions."""
    value, _ccy, missing = held(positions, account_id, BASE, balance, on_date)
    return value, missing


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
        amount, ccy, missing = held(positions, a.id, a.currency, balance, on_date)
        value = fx.to_base(amount, ccy, on_date)
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
            f"SELECT e.account_id, sum(e.amount_minor), {DEPOSITS_SQL} FROM entries e "  # noqa: S608
            f"{CATEGORY_JOIN} WHERE e.booking_date <= :d GROUP BY e.account_id"
        ),
        {"d": on_date},
    ).fetchall()
    fx = FxTable(conn)
    balances = {r[0]: (int(r[1]), int(r[2])) for r in rows}
    return _value(accts, balances, fx, Positions(conn, fx), on_date)


def series(conn: Connection, dates: Sequence[str]) -> list[Valuation]:
    """Même calcul que `value_at`, en un seul passage sur les sommes journalières."""
    accts = accounts(conn)
    fx = FxTable(conn)
    positions = Positions(conn, fx)
    daily = conn.execute(
        text(
            f"SELECT e.booking_date, e.account_id, sum(e.amount_minor), {DEPOSITS_SQL} "  # noqa: S608
            f"FROM entries e {CATEGORY_JOIN} "
            "GROUP BY e.booking_date, e.account_id ORDER BY e.booking_date"
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
