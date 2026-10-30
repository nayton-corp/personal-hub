"""Documents du lot 6 que reçoit l'importeur, à côté des relevés camt.053, Revolut et VIAC :
relevés IBKR (Flex Query), cours du marché et soldes crypto, positions saisies à la main,
relevés SwissBorg, compositions de fonds.

Chacun se reconnaît à son contenu (et, pour une liste de lignes d'émetteur, à l'ISIN du nom de
fichier, gardé dans la source de l'import), se relit depuis l'archive par sa source, et
s'applique relevé par relevé dans la transaction de l'importeur.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Connection

from hub.domains.finance.patrimoine.app import lookthrough
from hub.domains.finance.patrimoine.infra import composition
from hub.domains.finance.patrimoine.model.instruments import DocumentError, Result
from hub.domains.finance.sources.app import ibkr, manual, market, swissborg
from hub.domains.finance.sources.app.outcomes import StatementOutcome
from hub.domains.finance.sources.app.statements import (
    _set_statement,
)
from hub.domains.finance.sources.infra import ibkr_flex, market_file

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
    conn: Connection, import_id: str, doc: ibkr_flex.FlexFile, indexes: set[int] | None
) -> list[tuple[int, Result]]:
    return [
        (st.index, ibkr.apply_statement(conn, import_id, st))
        for st in sorted(doc.statements, key=lambda s: (s.from_date, s.index))
        if indexes is None or st.index in indexes
    ]


HANDLERS: tuple[Handler, ...] = (
    Handler(
        market_file.SOURCE,
        0,
        lambda _n, d: market_file.SOURCE if market_file.is_market(d) else None,
        lambda _s, d: market_file.parse(d),
        market.apply,
    ),
    Handler(composition.SOURCE, 1, composition.detect, composition.parse, lookthrough.apply),
    Handler(
        manual.SOURCE,
        2,
        lambda _n, d: manual.SOURCE if manual.is_positions(d) else None,
        lambda _s, d: manual.parse(d),
        manual.apply,
    ),
    Handler(
        swissborg.SOURCE, 2, swissborg.detect, lambda _s, d: swissborg.parse(d), swissborg.apply
    ),
    Handler(
        ibkr_flex.SOURCE,
        3,
        lambda _n, d: ibkr_flex.SOURCE if ibkr_flex.is_flex(d) else None,
        lambda _s, d: ibkr_flex.parse(d),
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


def apply_doc(
    conn: Connection, import_id: str, doc: Doc, indexes: set[int] | None = None
) -> list[StatementOutcome]:
    """Applique un document du lot 6, relevé par relevé."""
    out = []
    for index, r in doc.handler.apply(conn, import_id, doc.payload, indexes):
        status: Literal["applied", "needs_review"] = (
            "applied" if r.status == "applied" else "needs_review"
        )
        o = StatementOutcome(import_id, index, status, sorted(r.reasons), r.new, r.duplicates)
        _set_statement(conn, import_id, index, r.account_id, o)
        out.append(o)
    return out
