"""Documents VIAC reçus (ticket L4-05) : le PDF lu en avis d'opération ou en rapport, puis
appliqué au registre dans la transaction de l'import."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import Connection

from hub.domains.finance.sources.app import viac as viac_apply
from hub.domains.finance.sources.app.outcomes import StatementOutcome
from hub.domains.finance.sources.app.statements import (
    _set_statement,
)
from hub.domains.finance.sources.infra.viac import notice as viac_notice
from hub.domains.finance.sources.infra.viac import report as viac_report
from hub.domains.finance.sources.model.viac import Notice, Report


@dataclass(frozen=True)
class ViacDoc:
    """Un document VIAC lu : un avis ou un rapport."""

    notice: Notice | None = None
    report: Report | None = None

    @property
    def on_date(self) -> str:
        if self.notice is not None:
            return self.notice.value_date
        assert self.report is not None  # noqa: S101
        return self.report.on_date

    @property
    def order(self) -> tuple[str, int]:
        """Même jour : versements, puis achats et ventes, puis le reste, rapports en dernier."""
        if self.notice is None:
            return self.on_date, 9
        rank = {"deposit": 0, "withdrawal": 0, "sell": 1, "buy": 2}
        return self.on_date, rank.get(self.notice.kind, 3)

    def statements(self) -> list[tuple[int, str | None, str | None]]:
        """Lignes de `import_statements` : (rang, OPBD, CLBD). Un avis : liquidités (0) et
        titres (1) s'il s'agit d'un achat ou d'une vente ; un rapport : deux par portefeuille."""
        if self.notice is not None:
            on = self.notice.value_date
            return [(i, on, on) for i in range(2 if self.notice.is_trade else 1)]
        assert self.report is not None  # noqa: S101
        on = self.report.on_date
        return [(i, None, on) for i in range(2 * len(self.report.portfolios))]


def read_viac(text_of: Callable[[bytes], str], data: bytes) -> ViacDoc | str:
    """Le document lu, ou le type du document ignoré (« attestation », « statement »)."""
    txt = text_of(data)
    kind = viac_notice.classify(txt)
    if kind == "report":
        return ViacDoc(report=viac_report.parse(txt))
    if kind == "notice":
        return ViacDoc(notice=viac_notice.parse(txt))
    return kind


def apply_viac(
    conn: Connection, import_id: str, doc: ViacDoc, indexes: set[int] | None = None
) -> list[StatementOutcome]:
    """Applique un document VIAC (ou, pour un rapport, ses portefeuilles en attente)."""
    out: list[StatementOutcome] = []
    if doc.notice is not None:
        r = viac_apply.apply_notice(conn, import_id, doc.notice)
        status: Literal["applied", "needs_review"] = (
            "applied" if r.status == "applied" else "needs_review"
        )
        main = StatementOutcome(import_id, 0, status, r.reasons, r.new, r.duplicates)
        _set_statement(conn, import_id, 0, r.cash_id, main)
        out.append(main)
        if doc.notice.is_trade:
            _set_statement(
                conn, import_id, 1, r.titles_id, StatementOutcome(import_id, 1, status, r.reasons)
            )
        return out
    assert doc.report is not None  # noqa: S101
    for k, p in enumerate(doc.report.portfolios):
        if indexes is not None and not {2 * k, 2 * k + 1} & indexes:
            continue
        r = viac_apply.apply_portfolio(conn, import_id, doc.report.on_date, p)
        status = "applied" if r.status == "applied" else "needs_review"
        cash = StatementOutcome(import_id, 2 * k, status, r.reasons, 0, 0)
        titles = StatementOutcome(import_id, 2 * k + 1, status, r.reasons, r.new, r.duplicates)
        _set_statement(conn, import_id, 2 * k, r.cash_id, cash)
        _set_statement(conn, import_id, 2 * k + 1, r.titles_id, titles)
        out += [cash, titles]
    return out


VIAC_NOTICE = "viac_notice"
VIAC_REPORT = "viac_report"
VIAC_OTHER = "viac_other"  # attestation, relevé récapitulatif ou PDF refusé
VIAC_SOURCES = frozenset({VIAC_NOTICE, VIAC_REPORT, VIAC_OTHER})
