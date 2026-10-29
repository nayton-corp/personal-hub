"""Dettes : crédit, hypothèque, leasing, prêt étudiant, carte de crédit (migration 0016).

Une dette n'a pas de relevé. Son solde à une date part du dernier solde constaté
(`debt_balances` : l'ouverture, puis un relevé du prêteur), gagne les intérêts courus jour par
jour au taux annuel de la dette (sur 365 jours, sans capitalisation entre deux paiements), puis
baisse de chaque paiement : les écritures de la catégorie de la dette, depuis son compte de
paiement s'il est donné, dans la devise de la dette. Un remboursement reçu dans cette catégorie
(montant positif) la remonte. Le solde ne descend pas sous zéro ; une dette close vaut zéro dès
sa date de clôture.

Le patrimoine retranche le solde, converti dans la devise de base (enveloppe « dettes ») ; il
compte aussi comme versement, de sorte qu'un remboursement ne passe pas pour un effet marché :
seuls les intérêts font baisser le patrimoine.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.kernel.clock import now_iso
from hub.kernel.money import DECIMAL_CONTEXT, Money

KINDS = ("loan", "mortgage", "leasing", "student", "credit", "other")
KIND_LABEL = {
    "loan": "Crédit",
    "mortgage": "Hypothèque",
    "leasing": "Leasing",
    "student": "Prêt étudiant",
    "credit": "Carte de crédit",
    "other": "Autre dette",
}
KEY_PREFIX = "debt:"  # clé d'une dette dans by_account
MAX_PROJECTION_MONTHS = 600


def key(debt_id: str) -> str:
    return f"{KEY_PREFIX}{debt_id}"


@dataclass(frozen=True)
class Debt:
    id: str
    name: str
    lender: str
    kind: str
    currency: str
    original_minor: int | None
    rate: Decimal  # annuel, 0 sans intérêt
    payment_minor: int | None
    ends_on: str | None
    category_id: str | None
    account_id: str | None
    closed_on: str | None


@dataclass
class State:
    """Une dette à une date ; montants en unités mineures de sa devise."""

    balance: int
    since: str  # date du solde constaté de départ
    stated: int  # ce solde
    paid: int = 0  # paiements depuis
    interest: int = 0  # intérêts courus depuis
    payments: int = 0
    last_payment: str | None = None


def _rate(value: str | None) -> Decimal:
    return Decimal(value) if value else Decimal(0)


def load(conn: Connection) -> list[Debt]:
    rows = conn.execute(
        text(
            "SELECT id, name, lender, kind, currency, original_minor, rate, payment_minor, "
            "ends_on, category_id, account_id, closed_on FROM debts ORDER BY name, id"
        )
    ).fetchall()
    return [
        Debt(
            r[0],
            r[1],
            r[2],
            r[3],
            r[4],
            r[5],
            _rate(r[6]),
            r[7],
            r[8],
            r[9],
            r[10],
            r[11],
        )
        for r in rows
    ]


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _minor(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


@dataclass
class Book:
    """Dettes, soldes constatés et paiements, lus une fois par calcul."""

    debts: list[Debt]
    stated: dict[str, list[tuple[str, int]]] = field(default_factory=dict)
    paid: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

    @classmethod
    def read(cls, conn: Connection) -> Book:
        book = cls(load(conn))
        for debt_id, on, amount in conn.execute(
            text("SELECT debt_id, on_date, amount_minor FROM debt_balances ORDER BY on_date")
        ):
            book.stated.setdefault(debt_id, []).append((on, int(amount)))
        for d in book.debts:
            if d.category_id is None:
                continue
            rows = conn.execute(
                text(
                    "SELECT booking_date, sum(amount_minor) FROM v_entry_allocation "
                    "WHERE category_id = :c AND currency = :ccy "
                    "AND (:a IS NULL OR account_id = :a) "
                    "GROUP BY booking_date ORDER BY booking_date"
                ),
                {"c": d.category_id, "ccy": d.currency, "a": d.account_id},
            ).fetchall()
            # un débit paie la dette : montant positif
            book.paid[d.id] = [(r[0], -int(r[1])) for r in rows if int(r[1])]
        return book

    def state(self, debt: Debt, on_date: str) -> State | None:
        """None avant le premier solde constaté : la dette n'existe pas encore."""
        start = None
        for on, amount in self.stated.get(debt.id, []):
            if on <= on_date:
                start = (on, amount)
        if start is None:
            return None
        since, stated = start
        out = State(stated, since, stated)
        if debt.closed_on is not None and debt.closed_on <= on_date:
            out.balance = 0
            return out
        with localcontext(DECIMAL_CONTEXT):
            bal = Decimal(stated)
            interest = Decimal(0)
            last = since
            for on, amount in self.paid.get(debt.id, []):
                if on <= since:
                    continue
                if on > on_date:
                    break
                accrued = bal * debt.rate * _days(last, on) / 365
                bal += accrued
                interest += accrued
                bal = max(Decimal(0), bal - amount)
                out.paid += amount
                out.payments += 1
                out.last_payment = on
                last = on
            accrued = bal * debt.rate * _days(last, on_date) / 365
            bal += accrued
            interest += accrued
        out.balance = _minor(bal)
        out.interest = _minor(interest)
        return out

    def balance(self, debt: Debt, on_date: str) -> int | None:
        s = self.state(debt, on_date)
        return s.balance if s else None


def record_balance(
    conn: Connection,
    debt_id: str,
    on_date: str,
    amount_minor: int,
    source: str,
    proposal_id: str | None,
    entry_id: str | None = None,
) -> None:
    """Un solde constaté ; un second à la même date remplace le premier."""
    conn.execute(
        text(
            "INSERT INTO debt_balances (debt_id, on_date, amount_minor, source, entry_id, "
            "proposal_id, created_at) VALUES (:d, :on, :a, :s, :e, :p, :at) "
            "ON CONFLICT (debt_id, on_date) DO UPDATE SET amount_minor = excluded.amount_minor, "
            "source = excluded.source, entry_id = excluded.entry_id, "
            "proposal_id = excluded.proposal_id, created_at = excluded.created_at"
        ),
        {
            "d": debt_id,
            "on": on_date,
            "a": amount_minor,
            "s": source,
            "e": entry_id,
            "p": proposal_id,
            "at": now_iso(),
        },
    )


RECENT_PAYMENTS = 3


def usual_payment(book: Book, debt: Debt, on_date: str) -> int | None:
    """La mensualité qui sert à la projection : celle de la dette si elle est donnée, sinon la
    moyenne des derniers paiements (une mensualité qui change suit d'elle-même)."""
    if debt.payment_minor:
        return debt.payment_minor
    recent = [a for on, a in book.paid.get(debt.id, []) if on <= on_date and a > 0]
    recent = recent[-RECENT_PAYMENTS:]
    return sum(recent) // len(recent) if recent else None


def _add_month(d: date) -> date:
    y, m = d.year + (d.month == 12), d.month % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def projected_end(debt: Debt, balance: int, from_date: str, payment: int | None) -> str | None:
    """Mois du dernier paiement si `payment` continue chaque mois ; None sans mensualité, ou
    si elle ne couvre pas les intérêts."""
    if balance <= 0 or not payment:
        return None
    with localcontext(DECIMAL_CONTEXT):
        bal = Decimal(balance)
        monthly = debt.rate / 12
        d = date.fromisoformat(from_date)
        for _ in range(MAX_PROJECTION_MONTHS):
            d = _add_month(d)
            bal += bal * monthly
            bal -= payment
            if bal <= 0:
                return d.isoformat()[:7]
    return None


def values(
    book: Book, on_date: str, to_base: Callable[[int, str, str], int | None]
) -> tuple[dict[str, int], list[str]]:
    """({clé: valeur négative dans la devise de base}, dettes sans change) à une date.
    `to_base(minor, currency, on_date)` convertit, None sans cours."""
    out: dict[str, int] = {}
    missing: list[str] = []
    for d in book.debts:
        b = book.balance(d, on_date)
        if b is None:
            continue
        v = to_base(b, d.currency, on_date)
        if v is None:
            missing.append(key(d.id))
            continue
        out[key(d.id)] = -v
    return out, missing


def _money(minor: int | None, currency: str) -> dict[str, Any] | None:
    return None if minor is None else Money(minor, currency).to_api()


def items(conn: Connection, today: str) -> list[dict[str, Any]]:
    """Les dettes et leur état aujourd'hui, pour l'app (des agrégats, aucune écriture)."""
    book = Book.read(conn)
    names: dict[str, str] = dict(conn.execute(text("SELECT id, name FROM categories")).fetchall())
    accounts: dict[str, str] = dict(conn.execute(text("SELECT id, name FROM accounts")).fetchall())
    out = []
    for d in book.debts:
        s = book.state(d, today)
        balance = s.balance if s else 0
        usual = usual_payment(book, d, today)
        out.append(
            {
                "id": d.id,
                "key": key(d.id),
                "name": d.name,
                "lender": d.lender,
                "kind": d.kind,
                "currency": d.currency,
                "original": _money(d.original_minor, d.currency),
                # taux annuel en %, texte décimal ('2.5') ; None sans intérêt
                "rate_pct": format((d.rate * 100).normalize(), "f") if d.rate else None,
                "payment": _money(d.payment_minor, d.currency),
                "ends_on": d.ends_on,
                "category_id": d.category_id,
                "category_name": names.get(d.category_id) if d.category_id else None,
                "account_id": d.account_id,
                "account_name": accounts.get(d.account_id) if d.account_id else None,
                "closed_on": d.closed_on,
                "balance": _money(balance, d.currency),
                "stated": _money(s.stated, d.currency) if s else None,
                "stated_on": s.since if s else None,
                "paid_since": _money(s.paid, d.currency) if s else None,
                "interest_since": _money(s.interest, d.currency) if s else None,
                "payments_since": s.payments if s else 0,
                "last_payment": s.last_payment if s else None,
                "usual_payment": _money(usual, d.currency),
                "projected_end": projected_end(d, balance, today, usual) if s else None,
                "balances": [
                    {"on_date": on, "amount": _money(a, d.currency)}
                    for on, a in book.stated.get(d.id, [])
                ],
            }
        )
    return out
