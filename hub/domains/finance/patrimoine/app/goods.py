"""Biens hors comptes : logement, véhicule, objet de valeur, prêt accordé (migration 0028).

Un bien n'a ni relevé ni cours. Sa valeur à une date part de la dernière valeur saisie
(`good_value_records`, en ajout seul ; la dernière posée pour un même jour fait foi), puis suit
la variation annuelle du bien s'il en a une, composée jour par jour : -15 % par an pour une
voiture, rien pour un logement que l'on réestime à la main. Elle ne descend pas sous zéro ; un
bien clos (vendu, donné, remboursé) vaut zéro dès sa date de clôture.

Le patrimoine ajoute cette valeur, convertie dans la devise de base (enveloppe « biens », clé
`good:<id>`). Elle compte comme un versement : une estimation n'est ni un gain ni une perte de
placement, le rendement n'en dépend pas.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from sqlalchemy import Connection, text

from hub.kernel.clock import now_iso
from hub.kernel.ids import new_id
from hub.kernel.money import DECIMAL_CONTEXT, Money

KINDS = ("home", "vehicle", "object", "loan", "other")
KIND_LABEL = {
    "home": "Logement",
    "vehicle": "Véhicule",
    "object": "Objet de valeur",
    "loan": "Prêt accordé",
    "other": "Autre bien",
}
KEY_PREFIX = "good:"  # clé d'un bien dans by_account


def key(good_id: str) -> str:
    return f"{KEY_PREFIX}{good_id}"


@dataclass(frozen=True)
class Good:
    id: str
    name: str
    kind: str
    currency: str
    yearly_change: Decimal | None  # -0.15 : perd 15 % par an ; None : valeur fixe
    closed_on: str | None


def load(conn: Connection) -> list[Good]:
    rows = conn.execute(
        text(
            "SELECT id, name, kind, currency, yearly_change, closed_on FROM goods ORDER BY name, id"
        )
    ).fetchall()
    return [Good(r[0], r[1], r[2], r[3], Decimal(r[4]) if r[4] else None, r[5]) for r in rows]


def stated_values(conn: Connection) -> list[tuple[str, str, int]]:
    """(bien, jour, valeur) : la dernière valeur posée pour un même jour fait foi."""
    last: dict[tuple[str, str], int] = {}
    for good_id, on, amount in conn.execute(
        text(
            "SELECT good_id, on_date, amount_minor FROM good_value_records ORDER BY created_at, id"
        )
    ):
        last[(str(good_id), str(on))] = int(amount)
    return sorted((g, on, a) for (g, on), a in last.items())


def record_value(
    conn: Connection, good_id: str, on_date: str, amount_minor: int, proposal_id: str | None
) -> None:
    """Une valeur saisie, ajoutée ; une seconde à la même date s'ajoute et fait foi."""
    conn.execute(
        text(
            "INSERT INTO good_value_records (id, good_id, on_date, amount_minor, proposal_id, "
            "created_at) VALUES (:id, :g, :on, :a, :p, :at)"
        ),
        {
            "id": new_id(),
            "g": good_id,
            "on": on_date,
            "a": amount_minor,
            "p": proposal_id,
            "at": now_iso(),
        },
    )


@dataclass
class Book:
    """Biens et valeurs saisies, lus une fois par calcul."""

    goods: list[Good]
    stated: dict[str, list[tuple[str, int]]] = field(default_factory=dict)

    @classmethod
    def read(cls, conn: Connection) -> Book:
        book = cls(load(conn))
        for good_id, on, amount in stated_values(conn):
            book.stated.setdefault(good_id, []).append((on, amount))
        return book

    def last_stated(self, good: Good, on_date: str) -> tuple[str, int] | None:
        start = None
        for on, amount in self.stated.get(good.id, []):
            if on <= on_date:
                start = (on, amount)
        return start

    def value(self, good: Good, on_date: str) -> int | None:
        """None avant la première valeur saisie : le bien n'existe pas encore."""
        start = self.last_stated(good, on_date)
        if start is None:
            return None
        if good.closed_on is not None and good.closed_on <= on_date:
            return 0
        since, stated = start
        if not good.yearly_change:
            return stated
        days = (date.fromisoformat(on_date) - date.fromisoformat(since)).days
        with localcontext(DECIMAL_CONTEXT):
            factor = max(Decimal(0), 1 + good.yearly_change) ** (Decimal(days) / Decimal(365))
            value = (Decimal(stated) * factor).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
        return max(0, int(value))


def _money(minor: int | None, currency: str) -> object:
    return None if minor is None else Money(minor, currency).to_api()


def items(conn: Connection, today: str) -> list[dict[str, object]]:
    """Les biens et leur valeur aujourd'hui, pour l'app."""
    book = Book.read(conn)
    out: list[dict[str, object]] = []
    for g in book.goods:
        last = book.last_stated(g, today)
        out.append(
            {
                "id": g.id,
                "key": key(g.id),
                "name": g.name,
                "kind": g.kind,
                "currency": g.currency,
                # variation annuelle en %, texte décimal ('-15') ; None : valeur fixe
                "yearly_change_pct": (
                    format((g.yearly_change * 100).normalize(), "f") if g.yearly_change else None
                ),
                "closed_on": g.closed_on,
                "value": _money(book.value(g, today) or 0, g.currency),
                "stated": _money(last[1], g.currency) if last else None,
                "stated_on": last[0] if last else None,
                "values": [
                    {"on_date": on, "amount": _money(a, g.currency)}
                    for on, a in book.stated.get(g.id, [])
                ],
            }
        )
    return out
