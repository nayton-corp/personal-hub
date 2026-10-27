"""Valeur du patrimoine à une date, par enveloppe, en CHF (tickets L2-01 et L2-02).

Au lot 2, la valeur d'un compte est son solde au registre (écritures, ouverture comprise), et
les versements cumulés égalent cette valeur : l'effet marché est nul tant que les positions
(lot 4) ne valorisent pas les comptes de titres et de prévoyance. Un compte dans une autre
devise est converti au dernier cours de `fx_rates` connu à la date ; sans cours, il est laissé
de côté et signalé dans `missing_fx`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, localcontext

from sqlalchemy import Connection, text

from hub.core.money import DECIMAL_CONTEXT, Money

BASE = "CHF"
# enveloppes de by_envelope_json (spécification, section 2), tirées du type de compte
ENVELOPES = {"cash": "cash", "pension": "pilier3a", "securities": "ibkr", "crypto": "crypto"}
ENVELOPE_ORDER = ("cash", "pilier3a", "ibkr", "crypto")


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


def _value(
    accts: Sequence[Account], balances: dict[str, int], fx: FxTable, on_date: str
) -> Valuation:
    out = Valuation(on_date)
    for a in accts:
        value = fx.to_base(balances.get(a.id, 0), a.currency, on_date)
        if value is None:
            out.missing_fx.append(a.id)
            continue
        out.net_worth += value
        out.deposits += value  # coût = valeur tant que les positions n'existent pas (lot 4)
        out.by_envelope[a.envelope] += value
        if a.liquid:
            out.liquid += value
    return out


def value_at(conn: Connection, on_date: str) -> Valuation:
    """Calcul direct à une date : sert aux chiffres clés et de référence aux instantanés."""
    accts = accounts(conn)
    rows = conn.execute(
        text(
            "SELECT account_id, sum(amount_minor) FROM entries WHERE booking_date <= :d "
            "GROUP BY account_id"
        ),
        {"d": on_date},
    ).fetchall()
    fx = FxTable(conn, [a.currency for a in accts])
    return _value(accts, {r[0]: int(r[1]) for r in rows}, fx, on_date)


def series(conn: Connection, dates: Sequence[str]) -> list[Valuation]:
    """Même calcul que `value_at`, en un seul passage sur les sommes journalières."""
    accts = accounts(conn)
    fx = FxTable(conn, [a.currency for a in accts])
    daily = conn.execute(
        text(
            "SELECT booking_date, account_id, sum(amount_minor) FROM entries "
            "GROUP BY booking_date, account_id ORDER BY booking_date"
        )
    ).fetchall()
    balances: dict[str, int] = {}
    out = []
    i = 0
    for d in sorted(dates):
        while i < len(daily) and daily[i][0] <= d:
            balances[daily[i][1]] = balances.get(daily[i][1], 0) + int(daily[i][2])
            i += 1
        out.append(_value(accts, balances, fx, d))
    return out
