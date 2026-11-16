"""Versements vers une plateforme (IBKR, SwissBorg…), lus du côté de la banque : le virement
qui part d'un compte bancaire vers la plateforme. Ils arrivent tout seuls avec les relevés de la
banque, même quand la plateforme n'a pas d'API (SwissBorg) et que son relevé n'est déposé qu'à
la main de temps en temps.

Une plateforme est un établissement qui tient un compte de titres ou de crypto ; la cible d'un
versement régulier est son premier compte de titres ou de crypto (`account:<id>`). Un virement
vers elle est une écriture d'un compte bancaire d'un autre établissement dont le texte nomme la
plateforme ; un virement venu d'elle (un retrait) compte comme une vente."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

# le nom d'une plateforme dans le texte d'un virement, quand il diffère de son établissement
ALIASES = {"ibkr": r"interactive ?brokers|\bibkr\b"}


@dataclass(frozen=True)
class Platform:
    account_id: str
    institution: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class Move:
    on: str
    minor: int  # positif : versé vers la plateforme ; négatif : retiré
    currency: str


def platforms(conn: Connection) -> list[Platform]:
    """Une cible par établissement de titres ou de crypto (pas un 3a, lu par ses versements)."""
    seen: dict[str, Platform] = {}
    for account_id, institution in conn.execute(
        text(
            "SELECT id, institution FROM accounts WHERE kind IN ('securities', 'crypto') "
            "AND closed_on IS NULL ORDER BY created_at, id"
        )
    ):
        key = str(institution).strip().casefold()
        if not key or key in seen:
            continue
        pattern = ALIASES.get(key, rf"\b{re.escape(key)}\b")
        seen[key] = Platform(str(account_id), str(institution), re.compile(pattern))
    return list(seen.values())


def find(conn: Connection, account_id: str) -> Platform | None:
    return next((p for p in platforms(conn) if p.account_id == account_id), None)


def moves(conn: Connection, platform: Platform, since: str, until: str) -> list[Move]:
    """Les virements entre un compte bancaire et la plateforme, de `since` à `until`."""
    out = []
    for on, minor, ccy, words in conn.execute(
        text(
            "SELECT e.booking_date, e.amount_minor, e.currency, e.search_text FROM entries e "
            "JOIN accounts a ON a.id = e.account_id WHERE a.kind = 'cash' "
            "AND lower(a.institution) != :inst AND e.kind = 'movement' AND e.amount_minor != 0 "
            "AND e.booking_date >= :s AND e.booking_date <= :d"
        ),
        {"inst": platform.institution.casefold(), "s": since, "d": until},
    ):
        if platform.pattern.search(str(words or "")):
            out.append(Move(str(on), -int(minor), str(ccy)))
    return out


def dated(rows: list[Move]) -> tuple[list[tuple[date, int, str]], list[date]]:
    """(versements, jours de retrait)."""
    paid = [(date.fromisoformat(m.on), m.minor, m.currency) for m in rows if m.minor > 0]
    back = [date.fromisoformat(m.on) for m in rows if m.minor < 0]
    return paid, back
