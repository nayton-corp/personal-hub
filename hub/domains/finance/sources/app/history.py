"""Reprises d'historique : un dossier de relevés camt.053, VIAC ou IBKR importé d'un bloc, dans
l'ordre des dates, et les comptes Revolut en attente d'ouverture."""

from __future__ import annotations

import itertools
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from hub.domains.finance.patrimoine.model.instruments import DocumentError
from hub.domains.finance.registre.app import catalog
from hub.domains.finance.registre.app.opening import open_account
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.registre.model.statements import (
    Balance,
    ParsedFile,
    ParsedStatement,
)
from hub.domains.finance.sources.app import viac as viac_apply
from hub.domains.finance.sources.app.importer import ImportService
from hub.domains.finance.sources.app.outcomes import StatementOutcome
from hub.domains.finance.sources.app.viac_docs import VIAC_REPORT, ViacDoc, read_viac
from hub.domains.finance.sources.infra import camt as parser
from hub.domains.finance.sources.infra import ibkr_flex
from hub.domains.finance.sources.infra.files import Incoming, expand, safe_name, sha256
from hub.domains.finance.sources.infra.viac import ViacError
from hub.kernel.text import mask_iban
from hub.platform.db import begin_immediate


@dataclass
class HistoryReport:
    ok: bool
    accounts: list[dict[str, Any]] = field(default_factory=list)
    batch: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    missing: list[dict[str, str]] = field(default_factory=list)  # périodes manquantes
    warnings: list[str] = field(default_factory=list)  # écarts signalés, non bloquants

    def public(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error": self.error,
            "missing": self.missing,
            "warnings": self.warnings,
            "accounts": self.accounts,
            "batch": self.batch,
        }


@contextmanager
def _locked(lock_file: Path) -> Any:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_file.touch(exist_ok=False)
    except FileExistsError:
        raise ImportRefused("busy.retry", "une reprise d'historique est déjà en cours") from None
    try:
        yield
    finally:
        lock_file.unlink(missing_ok=True)


def _day_before(iso_date: str) -> str:
    return (date.fromisoformat(iso_date) - timedelta(days=1)).isoformat()


def import_history(service: ImportService, folder: Path) -> HistoryReport:
    """`hub finance import-history <dossier>` : trie, vérifie la continuité avant d'écrire, ouvre
    chaque compte au relevé le plus ancien, puis applique tout. Un trou arrête tout."""
    with _locked(service.lock_file):
        files: dict[str, Incoming] = {}
        for p in sorted(folder.iterdir()):
            if p.is_file() and p.suffix.lower() in {".xml", ".zip"}:
                for f in expand(p.name, p.read_bytes()):
                    files.setdefault(sha256(f.data), f)
        parsed: list[tuple[Incoming, ParsedFile]] = []
        # un fichier déjà reçu (déposé d'abord dans l'inbox) et resté en attente fait partie de
        # la reprise : il compte pour l'ouverture, puis il est rejoué depuis l'archive
        waiting: list[str] = []
        waiting_parsed: list[ParsedFile] = []
        for f in files.values():
            digest = sha256(f.data)
            import_id = service._waiting(digest) if service._known(digest) else None
            if service._known(digest) and import_id is None:
                continue  # déjà appliqué
            try:
                pf = parser.parse(f.data)
            except parser.CamtError as exc:
                return HistoryReport(ok=False, error=f"{exc.code} : {safe_name(f.name)}")
            if import_id is None:
                parsed.append((f, pf))
            else:
                waiting.append(import_id)
                waiting_parsed.append(pf)

        by_iban: dict[str, list[_Span]] = {}
        for pf in [pf for _f, pf in parsed] + waiting_parsed:
            for s in pf.statements:
                if s.iban is None or s.opening is None or s.closing is None:
                    return HistoryReport(ok=False, error="relevé sans IBAN ou sans soldes")
                by_iban.setdefault(s.iban, []).append(_Span(s, s.opening, s.closing))

        report = HistoryReport(ok=True)
        openings: list[tuple[catalog.Account, _Span]] = []
        with service.engine.connect() as conn:
            for iban, spans in sorted(by_iban.items()):
                account = catalog.account_by_iban(conn, iban)
                if account is None:
                    return HistoryReport(ok=False, error=f"compte inconnu : {mask_iban(iban)}")
                if conn.execute(
                    text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": account.id}
                ).first():
                    return HistoryReport(
                        ok=False, error=f"registre déjà ouvert pour {mask_iban(iban)}"
                    )
                spans.sort(key=lambda x: (x.opening.on_date, x.closing.on_date))
                for prev, nxt in itertools.pairwise(spans):
                    # CLBD d'un relevé = OPBD du suivant ; deux relevés qui se recouvrent sont
                    # laissés au dédoublonnage
                    overlap = nxt.opening.on_date <= prev.closing.on_date
                    if not overlap and nxt.opening.amount_minor != prev.closing.amount_minor:
                        report.missing.append(
                            {
                                "account": mask_iban(iban) or "",
                                "from": prev.closing.on_date,
                                "to": nxt.opening.on_date,
                            }
                        )
                openings.append((account, spans[0]))
        if report.missing:
            report.ok = False
            report.error = "historique discontinu"
            return report

        for account, oldest in openings:
            first = min([e.booking_date for e in oldest.stmt.entries] + [oldest.opening.on_date])
            with begin_immediate(service.engine) as conn:
                open_account(
                    conn,
                    account.id,
                    _day_before(first),
                    oldest.opening.amount_minor,
                    account.currency,
                )
        batch = service.process(f for f, _ in parsed)
        if waiting:
            batch.statements = _settle(service, batch.statements, waiting)
        report.batch = batch.counters()
        report.ok = report.batch["needs_review"] == 0 and report.batch["rejected_files"] == 0
        with service.engine.connect() as conn:
            for account, _oldest in openings:
                row = conn.execute(
                    text(
                        "SELECT count(*), min(booking_date), max(booking_date) FROM entries "
                        "WHERE account_id = :a AND kind = 'movement'"
                    ),
                    {"a": account.id},
                ).one()
                report.accounts.append(
                    {
                        "account": mask_iban(account.iban),
                        "statements": len(by_iban[account.iban or ""]),
                        "entries": row[0],
                        "from": row[1],
                        "to": row[2],
                    }
                )
        return report


def _settle(
    service: ImportService, outcomes: list[StatementOutcome], waiting: list[str]
) -> list[StatementOutcome]:
    """Rejoue les relevés en attente de la reprise jusqu'à ce que plus rien n'avance : un relevé
    déjà reçu peut précéder ou suivre les nouveaux. Rend le dernier état de chaque relevé."""
    final = {(o.import_id, o.index): o for o in outcomes}
    pending = set(waiting) | {o.import_id for o in outcomes if o.status == "needs_review"}
    while pending:
        retried = service.retry_needs_review(sorted(pending))
        for o in retried:
            before = final.get((o.import_id, o.index))
            if before is not None:
                o.new += before.new
            final[(o.import_id, o.index)] = o
        if not any(o.status == "applied" for o in retried):
            break
        pending = {o.import_id for o in retried if o.status == "needs_review"}
    return list(final.values())


@dataclass(frozen=True)
class _Span:
    stmt: ParsedStatement
    opening: Balance
    closing: Balance


def _viac_docs(service: ImportService, folder: Path) -> tuple[list[Incoming], list[ViacDoc]]:
    files: dict[str, Incoming] = {}
    for p in sorted(folder.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in {".pdf", ".zip"}:
            for f in expand(p.name, p.read_bytes()):
                if f.name.lower().endswith(".pdf"):
                    files.setdefault(sha256(f.data), f)
    fresh = [f for digest, f in files.items() if not service._known(digest)]
    docs = []
    for f in fresh:
        try:
            doc = read_viac(service.pdf_text, f.data)
        except ViacError as exc:
            raise ImportRefused(exc.code, f"{exc.reason} : {safe_name(f.name)}") from None
        if isinstance(doc, ViacDoc):
            docs.append(doc)
    return fresh, docs


def import_viac_history(service: ImportService, folder: Path) -> HistoryReport:
    """`hub finance viac import-history <dossier>` : lit tous les PDF VIAC (sous-dossiers
    compris) avant d'écrire, ouvre les deux comptes de chaque portefeuille à zéro la veille du
    plus ancien document, puis applique tout dans l'ordre des dates. Un PDF illisible ou un
    portefeuille inconnu arrête tout ; rien n'est écrit."""
    with _locked(service.lock_file):
        try:
            fresh, docs = _viac_docs(service, folder)
        except ImportRefused as exc:
            return HistoryReport(ok=False, error=f"{exc.code} : {exc.detail}")
        first: dict[str, str] = {}
        for doc in docs:
            numbers = (
                [doc.notice.portfolio]
                if doc.notice is not None
                else [p.number for p in doc.report.portfolios]  # type: ignore[union-attr]
            )
            for n in numbers:
                first[n] = min(first.get(n, doc.on_date), doc.on_date)

        pairs: list[tuple[str, catalog.Account, catalog.Account]] = []
        with service.engine.connect() as conn:
            for number in sorted(first):
                cash = catalog.account_by_ref(conn, viac_apply.cash_ref(number))
                titles = catalog.account_by_ref(conn, viac_apply.titles_ref(number))
                if cash is None or titles is None:
                    return HistoryReport(
                        ok=False,
                        error=f"portefeuille inconnu : {number} (hub finance viac add-portfolio)",
                    )
                for a in (cash, titles):
                    if conn.execute(
                        text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": a.id}
                    ).first():
                        return HistoryReport(ok=False, error=f"registre déjà ouvert : {number}")
                pairs.append((number, cash, titles))

        for number, cash, titles in pairs:
            with begin_immediate(service.engine) as conn:
                for a in (cash, titles):
                    open_account(conn, a.id, _day_before(first[number]), 0, a.currency)
        batch = service.process(fresh)
        report = HistoryReport(ok=True, batch=batch.counters())
        report.ok = report.batch["needs_review"] == 0 and report.batch["rejected_files"] == 0
        with service.engine.connect() as conn:
            for number, cash, titles in pairs:
                row = conn.execute(
                    text(
                        "SELECT count(*), min(booking_date), max(booking_date) FROM entries "
                        "WHERE account_id IN (:c, :t) AND kind = 'movement'"
                    ),
                    {"c": cash.id, "t": titles.id},
                ).one()
                count = conn.execute(
                    text("SELECT count(DISTINCT on_date) FROM holdings WHERE account_id = :t"),
                    {"t": titles.id},
                ).scalar_one()
                report.accounts.append(
                    {
                        "account": number,
                        "entries": row[0],
                        "from": row[1],
                        "to": row[2],
                        "reports": count,
                    }
                )
            # écarts relevés par les rapports : signalés, jamais bloquants
            flagged = conn.execute(
                text(
                    "SELECT s.reasons_json FROM import_statements s JOIN imports i "
                    "ON i.id = s.import_id WHERE i.source = :src AND s.reasons_json != '[]'"
                ),
                {"src": VIAC_REPORT},
            ).scalars()
            report.warnings = sorted({r for x in flagged for r in json.loads(x)})
        return report


def import_ibkr_history(service: ImportService, folder: Path) -> HistoryReport:
    """`hub finance ibkr import-history <dossier>` : lit tous les relevés Flex (sous-dossiers
    compris) avant d'écrire, vérifie que chaque compte IBKR est déclaré et pas encore ouvert,
    puis applique tout dans l'ordre des dates : le plus ancien relevé ouvre les comptes."""
    with _locked(service.lock_file):
        files: dict[str, Incoming] = {}
        for p in sorted(folder.rglob("*")):
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in {".xml", ".zip"}:
                for f in expand(p.name, p.read_bytes()):
                    if ibkr_flex.is_flex(f.data):
                        files.setdefault(sha256(f.data), f)
        fresh = [f for digest, f in files.items() if not service._known(digest)]
        spans: dict[str, list[str]] = {}
        for f in fresh:
            try:
                flex = ibkr_flex.parse(f.data)
            except DocumentError as exc:
                return HistoryReport(ok=False, error=f"{exc.code} : {safe_name(f.name)}")
            for st in flex.statements:
                spans.setdefault(st.account, []).extend([st.from_date, st.to_date])
        if not spans:
            return HistoryReport(ok=False, error="aucun relevé Flex nouveau dans ce dossier")
        with service.engine.connect() as conn:
            for number in sorted(spans):
                titles = catalog.account_by_ref(conn, ibkr_flex.titles_ref(number))
                if titles is None:
                    return HistoryReport(
                        ok=False,
                        error=f"compte IBKR inconnu : {number} (hub finance ibkr add-account)",
                    )
                if conn.execute(
                    text("SELECT 1 FROM entries WHERE account_id = :a LIMIT 1"), {"a": titles.id}
                ).first():
                    return HistoryReport(ok=False, error=f"registre déjà ouvert : {number}")
        batch = service.process(fresh)
        report = HistoryReport(ok=True, batch=batch.counters())
        report.ok = report.batch["needs_review"] == 0 and report.batch["rejected_files"] == 0
        with service.engine.connect() as conn:
            for number, dates in sorted(spans.items()):
                count = conn.execute(
                    text(
                        "SELECT count(*) FROM entries e JOIN accounts a ON a.id = e.account_id "
                        "WHERE a.external_ref LIKE :r AND e.kind = 'movement'"
                    ),
                    {"r": f"ibkr:{number}:%"},
                ).scalar_one()
                report.accounts.append(
                    {"account": number, "entries": count, "from": min(dates), "to": max(dates)}
                )
            flagged = conn.execute(
                text(
                    "SELECT s.reasons_json FROM import_statements s JOIN imports i "
                    "ON i.id = s.import_id WHERE i.source = :src AND s.reasons_json != '[]'"
                ),
                {"src": ibkr_flex.SOURCE},
            ).scalars()
            report.warnings = sorted({r for x in flagged for r in json.loads(x)})
        return report
