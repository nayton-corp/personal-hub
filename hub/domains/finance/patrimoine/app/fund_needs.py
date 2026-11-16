"""Fonds dont le hub veut la composition (collecteur « market », funds.py) : les fonds détenus à
la date, hors crypto, avec la date de leur dernière composition connue.

Un fonds se reconnaît à son type (`fund`, `etf`) ou à son nom (« ETF », « UCITS », « Fund »,
« Fonds », « Index ») : un courtier range souvent un ETF parmi les actions (IBKR). Seuls ces
ISIN quittent le hub : une action détenue en direct n'a pas de composition à chercher.

Pour les frais courants (collecteur « market », fees.py), chaque fonds porte aussi le jour de
son dernier TER relevé (`ter_since`) et si le TER a été saisi à la main (`ter_by_user` : le
collecteur ne le cherche pas).

Une composition « stable » tient dans une seule case par dimension (un fonds d'or, un fonds
immobilier suisse) : elle ne change pas, le collecteur ne la cherche plus.
"""

from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import valuation
from hub.kernel.text import normalize

FUND_KINDS = ("fund", "etf")
FUND_WORDS = re.compile(r"\b(etf|ucits|fund|fonds|index|indice|tracker)\b")


def is_fund(kind: str | None, name: str | None) -> bool:
    if kind == "crypto":
        return False
    return kind in FUND_KINDS or FUND_WORDS.search(normalize(name or "")) is not None


def held_funds(conn: Connection, on_date: str) -> list[str]:
    """Les ISIN des fonds détenus à la date, dans les comptes qui ne sont pas des crypto."""
    positions = valuation.Positions(conn)
    crypto = {r[0] for r in conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'"))}
    meta = {
        r[0]: (r[1], r[2]) for r in conn.execute(text("SELECT isin, kind, name FROM instruments"))
    }
    held = {
        x.isin
        for account_id in positions.accounts - crypto
        for x in positions.lines(account_id, on_date)
        if x.quantity
    }
    return sorted(i for i in held if is_fund(*meta.get(i, (None, None))))


def known(conn: Connection) -> dict[str, tuple[str, bool]]:
    """{ISIN : (date de la dernière composition, stable)}, lignes du fonds mises à part."""
    latest: dict[tuple[str, str], tuple[str, list[str]]] = {}
    for isin, dim, on, weight in conn.execute(
        text(
            "SELECT isin, dimension, on_date, weight FROM compositions "
            "WHERE dimension != 'holding' ORDER BY isin, dimension, on_date"
        )
    ):
        current = latest.get((isin, dim))
        if current is None or on > current[0]:
            latest[(isin, dim)] = (on, [weight])
        elif on == current[0]:
            current[1].append(weight)
    out: dict[str, tuple[str, bool]] = {}
    for (isin, _dim), (on, weights) in latest.items():
        whole = len(weights) == 1 and Decimal(weights[0]) == 1
        since, stable = out.get(isin, (on, True))
        out[isin] = (max(since, on), stable and whole)
    return out


def fee_dates(conn: Connection) -> tuple[dict[str, str], set[str]]:
    """({ISIN : jour du dernier TER relevé}, ISIN dont le TER a été saisi à la main)."""
    seen_on: dict[str, str] = {}
    by_user: set[str] = set()
    for isin, source, at in conn.execute(text("SELECT isin, source, created_at FROM fund_fees")):
        if source == "user":
            by_user.add(str(isin))
        else:
            seen_on[str(isin)] = max(seen_on.get(str(isin), ""), str(at)[:10])
    return seen_on, by_user


def needs(conn: Connection, on_date: str) -> list[dict[str, str | bool | None]]:
    seen = known(conn)
    fees_seen, by_user = fee_dates(conn)
    return [
        {
            "isin": isin,
            "since": seen[isin][0] if isin in seen else None,
            "stable": seen[isin][1] if isin in seen else False,
            "ter_since": fees_seen.get(isin),
            "ter_by_user": isin in by_user,
        }
        for isin in held_funds(conn, on_date)
    ]
