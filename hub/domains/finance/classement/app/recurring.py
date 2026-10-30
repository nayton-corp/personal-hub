"""Abonnements et paiements réguliers (lot 6), et leurs prochaines échéances.

Les débits des comptes du budget sont regroupés par contrepartie normalisée (sans chiffres ni
ponctuation : « Netflix.com 12345 » et « NETFLIX.COM 67890 » vont ensemble). Un groupe est
récurrent quand ses derniers paiements (douze au plus) tombent à un rythme régulier
(hebdomadaire, mensuel, trimestriel, semestriel ou annuel : écart médian dans la plage du
rythme, et trois écarts sur quatre au moins dans la tolérance) pour des montants proches (trois
sur quatre à 20 % de la médiane). Il en faut trois, deux pour un rythme annuel. L'échéance
suivante est le dernier paiement plus le rythme ; un abonnement dont l'échéance est passée de
plus d'une tolérance est réputé arrêté.

Les virements, l'épargne et les écritures appariées ne comptent pas. La table est dérivée :
recalculée en entier avec les instantanés.
"""

from __future__ import annotations

import itertools
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.registre.model.amounts import money
from hub.kernel.clock import now_iso
from hub.kernel.money import DECIMAL_CONTEXT, Money
from hub.kernel.text import normalize

WINDOW = 12
MIN_FOR_AGGREGATES = 3  # comme les résumés : moins de 3, regroupé dans « Autres »
MIN_COUNT = 3
HISTORY_DAYS = 3 * 366
# rythme : (écart médian minimal, maximal, tolérance d'un écart, mois ajoutés ou jours)
CADENCES: dict[str, tuple[int, int, int, int, int]] = {
    "weekly": (6, 8, 2, 0, 7),
    "monthly": (26, 35, 6, 1, 0),
    "quarterly": (80, 100, 12, 3, 0),
    "semiannual": (165, 195, 20, 6, 0),
    "yearly": (340, 390, 25, 12, 0),
}
PER_MONTH = {  # montant mensuel équivalent
    "weekly": Decimal(52) / 12,
    "monthly": Decimal(1),
    "quarterly": Decimal(1) / 3,
    "semiannual": Decimal(1) / 6,
    "yearly": Decimal(1) / 12,
}
PLACEHOLDERS = {"notprovided", "not provided", "n/a", "na", "unknown", "inconnu"}
_NOISE = re.compile(r"[^a-z ]+")
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class Pay:
    seq: int
    account_id: str
    on: date
    amount: int
    currency: str
    counterparty: str | None
    label: str
    category: str | None


@dataclass(frozen=True)
class Series:
    key: str
    account_id: str
    label: str
    category_id: str | None
    cadence: str
    amount: int
    last_amount: int
    currency: str
    count: int
    first: date
    last: date
    next: date
    active: bool
    last_seq: int


def display(counterparty: str | None, label: str) -> str:
    """La contrepartie, sauf si la banque n'en donne pas (« NOTPROVIDED ») : le libellé."""
    if counterparty and normalize(counterparty) not in PLACEHOLDERS:
        return counterparty.strip()
    return label.strip()


def merchant_key(counterparty: str | None, label: str) -> str:
    """Les mots sans chiffre (une référence change à chaque paiement), sans ponctuation."""
    words = [w for w in normalize(display(counterparty, label)).split() if not _DIGIT.search(w)]
    clean = _NOISE.sub(" ", " ".join(words)).split()
    return " ".join(w for w in clean if len(w) > 1)[:40]


def add_months(d: date, months: int) -> date:
    index = d.year * 12 + d.month - 1 + months
    y, m = divmod(index, 12)
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    raise ValueError("date impossible")  # pragma: no cover


def step(d: date, cadence: str) -> date:
    _lo, _hi, _tol, months, days = CADENCES[cadence]
    return add_months(d, months) if months else d + timedelta(days=days)


def _cadence(gaps: list[int]) -> str | None:
    median = statistics.median(gaps)
    for name, (lo, hi, tol, _m, _d) in CADENCES.items():
        if lo <= median <= hi:
            ok = sum(lo - tol <= g <= hi + tol for g in gaps)
            return name if ok * 4 >= len(gaps) * 3 else None
    return None


def detect(pays: list[Pay], today: date) -> Series | None:
    pays = sorted(pays, key=lambda p: (p.on, p.seq))[-WINDOW:]
    if len(pays) < 2:
        return None
    gaps = [(b.on - a.on).days for a, b in itertools.pairwise(pays)]
    if any(g == 0 for g in gaps):
        return None  # plusieurs paiements le même jour : des achats, pas un abonnement
    cadence = _cadence(gaps)
    if cadence is None or len(pays) < (2 if cadence == "yearly" else MIN_COUNT):
        return None
    amounts = [-p.amount for p in pays]
    median = int(statistics.median(amounts))
    close = sum(abs(a - median) * 5 <= median for a in amounts)
    if median <= 0 or close * 4 < len(amounts) * 3:
        return None
    last = pays[-1]
    nxt = step(last.on, cadence)
    tolerance = CADENCES[cadence][2]
    return Series(
        key="",
        account_id=last.account_id,
        label=display(last.counterparty, last.label)[:80] or "Paiement régulier",
        category_id=last.category,
        cadence=cadence,
        amount=-median,
        last_amount=last.amount,
        currency=last.currency,
        count=len(pays),
        first=pays[0].on,
        last=last.on,
        next=nxt,
        active=nxt + timedelta(days=tolerance) >= today,
        last_seq=last.seq,
    )


def _pays(conn: Connection, today: date) -> list[Pay]:
    since = (today - timedelta(days=HISTORY_DAYS)).isoformat()
    budget = list(conn.execute(text("SELECT id FROM accounts WHERE budget_account = 1")).scalars())
    if not budget:
        budget = list(conn.execute(text("SELECT id FROM accounts WHERE kind = 'cash'")).scalars())
    if not budget:
        return []
    marks = ",".join(f":a{i}" for i in range(len(budget)))
    rows = conn.execute(
        text(
            "SELECT e.seq, e.account_id, e.booking_date, e.amount_minor, e.currency, "  # noqa: S608
            "e.counterparty, e.label, vc.category_id FROM entries e "
            "LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq "
            "LEFT JOIN categories c ON c.id = vc.category_id "
            f"WHERE e.kind = 'movement' AND e.amount_minor < 0 AND e.account_id IN ({marks}) "
            "AND e.booking_date >= :since "
            "AND (c.grp IS NULL OR c.grp NOT IN ('transfer', 'savings')) "
            "AND e.seq NOT IN (SELECT debit_seq FROM transfer_links)"
        ),
        {"since": since, **{f"a{i}": a for i, a in enumerate(budget)}},
    ).fetchall()
    return [
        Pay(int(r[0]), r[1], date.fromisoformat(r[2]), int(r[3]), r[4], r[5], r[6] or "", r[7])
        for r in rows
    ]


def refresh(conn: Connection, today: date) -> int:
    """Recalcule toute la table dans la transaction de l'appelant ; renvoie le nombre trouvé."""
    groups: dict[tuple[str, str, str], list[Pay]] = defaultdict(list)
    for p in _pays(conn, today):
        key = merchant_key(p.counterparty, p.label)
        if key:
            groups[(key, p.account_id, p.currency)].append(p)
    found = []
    for (key, account_id, ccy), pays in sorted(groups.items()):
        s = detect(pays, today)
        if s is not None:
            found.append((f"{key}|{account_id}|{ccy}", s))
    at = now_iso()
    conn.execute(text("DELETE FROM recurring"))
    if found:
        conn.execute(
            text(
                "INSERT INTO recurring (key, account_id, label, category_id, cadence, "
                "amount_minor, last_minor, currency, occurrences, first_date, last_date, "
                "next_date, active, last_seq, computed_at) VALUES (:key, :a, :label, :cat, :cad, "
                ":amount, :last_amount, :ccy, :n, :first, :last, :next, :active, :seq, :at)"
            ),
            [
                {
                    "key": k,
                    "a": s.account_id,
                    "label": s.label,
                    "cat": s.category_id,
                    "cad": s.cadence,
                    "amount": s.amount,
                    "last_amount": s.last_amount,
                    "ccy": s.currency,
                    "n": s.count,
                    "first": s.first.isoformat(),
                    "last": s.last.isoformat(),
                    "next": s.next.isoformat(),
                    "active": int(s.active),
                    "seq": s.last_seq,
                    "at": at,
                }
                for k, s in found
            ],
        )
    return len(found)


def monthly(amount: int, currency: str, cadence: str) -> int:
    """Coût mensuel équivalent, positif."""
    with localcontext(DECIMAL_CONTEXT):
        value = abs(Money(amount, currency).to_decimal()) * PER_MONTH[cadence]
    return Money.from_decimal(value, currency).minor


def listing(conn: Connection, today: date, *, aggregates_only: bool) -> dict[str, Any]:
    """Abonnements actifs triés par échéance, total mensuel par devise ; pour la portée
    `aggregates`, seulement les totaux par catégorie (aucune contrepartie)."""
    rows = conn.execute(
        text(
            "SELECT r.label, r.category_id, c.name, r.cadence, r.amount_minor, r.last_minor, "
            "r.currency, r.occurrences, r.last_date, r.next_date, r.active, a.name, e.id "
            "FROM recurring r JOIN accounts a ON a.id = r.account_id "
            "JOIN entries e ON e.seq = r.last_seq "
            "LEFT JOIN categories c ON c.id = r.category_id ORDER BY r.next_date, r.label"
        )
    ).fetchall()
    active = [r for r in rows if r[10]]
    counts: dict[str, int] = defaultdict(int)
    for r in active:
        counts[r[1] or "a-categoriser"] += 1
    totals: dict[str, int] = defaultdict(int)
    by_category: dict[tuple[str, str], int] = defaultdict(int)
    for r in active:
        m = monthly(int(r[4]), r[6], r[3])
        totals[r[6]] += m
        cat = r[1] or "a-categoriser"
        if aggregates_only and counts[cat] < MIN_FOR_AGGREGATES:
            cat = "autres"  # un total ne doit pas révéler un paiement
        by_category[(cat, r[6])] += m
    horizon = (today + timedelta(days=30)).isoformat()
    hidden = aggregates_only and len(active) < MIN_FOR_AGGREGATES
    out: dict[str, Any] = {
        "as_of": today.isoformat(),
        "count": len(active),
        "monthly_total": [] if hidden else [money(v, ccy) for ccy, v in sorted(totals.items())],
        "by_category": []
        if hidden
        else [
            {"category": cat, "monthly": money(v, ccy)}
            for (cat, ccy), v in sorted(by_category.items(), key=lambda kv: kv[1])
        ],
        "due_30d": sum(1 for r in active if r[9] <= horizon),
    }
    if aggregates_only:
        return out
    out["items"] = [
        {
            "label": r[0],
            "category": r[1],
            "category_name": r[2],
            "cadence": r[3],
            "amount": money(r[4], r[6]),
            "last_amount": money(r[5], r[6]),
            "monthly": money(monthly(int(r[4]), r[6], r[3]), r[6]),
            "occurrences": r[7],
            "last_date": r[8],
            "next_date": r[9],
            "active": bool(r[10]),
            "account": r[11],
            "last_entry_id": r[12],
        }
        for r in rows
    ]
    return out
