"""Documents du lot 6 que reçoit l'importeur, à côté des relevés camt.053, Revolut et VIAC :
relevés IBKR (Flex Query), cours du marché et soldes crypto, positions saisies à la main,
compositions de fonds.

Chacun se reconnaît à son contenu (et, pour une liste de lignes d'émetteur, à l'ISIN du nom de
fichier, gardé dans la source de l'import), se relit depuis l'archive par sa source, et
s'applique relevé par relevé dans la transaction de l'importeur.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection

from hub.domains.finance import ibkr, lookthrough, manual, market
from hub.domains.finance.assets import DocumentError, Result

Rows = list[tuple[int, str | None, str | None]]


@dataclass(frozen=True)
class Handler:
    name: str
    rank: int  # même date : les cours avant les relevés qui les utilisent
    detect: Callable[[str, bytes], str | None]
    parse: Callable[[str, bytes], Any]
    apply: Callable[[Connection, str, Any, set[int] | None], list[tuple[int, Result]]]

    def owns(self, source: str) -> bool:
        return source == self.name or source.startswith(f"{self.name}:")


def _ibkr_apply(
    conn: Connection, import_id: str, doc: ibkr.FlexFile, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    return [
        (st.index, ibkr.apply_statement(conn, import_id, st))
        for st in sorted(doc.statements, key=lambda s: (s.from_date, s.index))
        if indexes is None or st.index in indexes
    ]


HANDLERS: tuple[Handler, ...] = (
    Handler(
        market.SOURCE,
        0,
        lambda _n, d: market.SOURCE if market.is_market(d) else None,
        lambda _s, d: market.parse(d),
        market.apply,
    ),
    Handler(lookthrough.SOURCE, 1, lookthrough.detect, lookthrough.parse, lookthrough.apply),
    Handler(
        manual.SOURCE,
        2,
        lambda _n, d: manual.SOURCE if manual.is_positions(d) else None,
        lambda _s, d: manual.parse(d),
        manual.apply,
    ),
    Handler(
        ibkr.SOURCE,
        3,
        lambda _n, d: ibkr.SOURCE if ibkr.is_flex(d) else None,
        lambda _s, d: ibkr.parse(d),
        _ibkr_apply,
    ),
)


@dataclass(frozen=True)
class Doc:
    """Un document lu, prêt à s'appliquer."""

    source: str
    handler: Handler
    payload: Any

    @property
    def on_date(self) -> str:
        return str(self.payload.on_date)

    @property
    def order(self) -> tuple[str, int]:
        return self.on_date, self.handler.rank

    def rows(self) -> Rows:
        rows: Rows = self.payload.rows()
        return rows


def handler_for(source: str) -> Handler | None:
    return next((h for h in HANDLERS if h.owns(source)), None)


def detect(name: str, data: bytes) -> str | None:
    for h in HANDLERS:
        source = h.detect(name, data)
        if source:
            return source
    return None


def read(source: str, data: bytes) -> Doc:
    h = handler_for(source)
    if h is None:
        raise DocumentError(f"source inconnue : {source}")
    return Doc(source, h, h.parse(source, data))


SOURCES_PREFIXES = tuple(h.name for h in HANDLERS)
