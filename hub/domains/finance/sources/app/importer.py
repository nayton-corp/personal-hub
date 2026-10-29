"""Service d'import camt.053 (tickets L1-06 et L1-13), section 4 de la spécification, et
des documents VIAC en PDF (ticket L4-05).

Réception → validation → analyse → mise en attente → rapprochement → application → archivage.
Les fichiers d'un lot sont appliqués triés par compte puis par date d'OPBD, une transaction par
relevé, jamais par lot. Rien de ce module ne journalise de contenu : des identifiants et des
compteurs seulement.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from hub.domains.finance.patrimoine.model.instruments import DocumentError
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.registre.model.statements import (
    ParsedFile,
    ParsedStatement,
)
from hub.domains.finance.sources.app import documents
from hub.domains.finance.sources.app.documents import apply_doc
from hub.domains.finance.sources.app.outcomes import BatchReport, FileOutcome, StatementOutcome
from hub.domains.finance.sources.app.rework import Rework, Staged
from hub.domains.finance.sources.app.statements import (
    apply_statement,
    finish,
)
from hub.domains.finance.sources.app.viac_docs import (
    VIAC_NOTICE,
    VIAC_OTHER,
    VIAC_REPORT,
    ViacDoc,
    apply_viac,
    read_viac,
)
from hub.domains.finance.sources.infra import camt as parser
from hub.domains.finance.sources.infra import revolut
from hub.domains.finance.sources.infra.files import Archiver, Incoming, expand, safe_name, sha256
from hub.domains.finance.sources.infra.viac import ViacError
from hub.domains.finance.sources.infra.viac import text as viac_text
from hub.kernel import canonical
from hub.kernel.clock import now_iso, utcnow
from hub.kernel.ids import new_id
from hub.platform.db import begin_immediate
from hub.platform.logging import get_logger

log = get_logger("hub.finance.import")

SOURCE = "camt053"
INBOX_SUFFIXES = frozenset({".xml", ".zip", ".pdf", ".json", ".csv", ".xlsx"})
SETTLE_SECONDS = 2  # un fichier modifié il y a moins longtemps est peut-être encore en copie


class ImportService(Rework):
    def __init__(
        self,
        engine: Engine,
        *,
        inbox: Path,
        archiver: Archiver,
        lock_file: Path,
        on_applied: Callable[[], object] | None = None,
        pdf_text: Callable[[bytes], str] = viac_text.pdftotext,
    ) -> None:
        self.engine = engine
        self.pdf_text = pdf_text
        self.inbox = inbox
        self.archiver = archiver
        self.lock_file = lock_file
        # appelé après un lot dont au moins un relevé est appliqué (instantanés, L2-01)
        self.on_applied = on_applied

    # --- réception -----------------------------------------------------------------------

    def _waiting(self, digest: str) -> str | None:
        """Import déjà reçu dont un relevé attend encore (needs_review)."""
        with self.engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT i.id FROM imports i JOIN import_statements s ON s.import_id = i.id "
                    "WHERE i.file_sha256 = :h AND s.status = 'needs_review' LIMIT 1"
                ),
                {"h": digest},
            ).first()
        return None if row is None else str(row[0])

    def _known(self, digest: str) -> bool:
        with self.engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM imports WHERE file_sha256 = :h"), {"h": digest}
            ).first()
        return row is not None

    def _record(
        self,
        f: Incoming,
        digest: str,
        status: str,
        stats: dict[str, Any],
        parsed: ParsedFile | None,
        *,
        source: str = SOURCE,
        rows: list[tuple[int, str | None, str | None]] | None = None,
    ) -> str:
        import_id = new_id()
        now = now_iso()
        stamp = utcnow().strftime("%Y/%m")
        archive_path = self.archiver.store(f.data, stamp, f"{import_id}-{safe_name(f.name)}")
        with begin_immediate(self.engine) as conn:
            conn.execute(
                text(
                    "INSERT INTO imports (id, source, file_sha256, file_name, received_at, status, "
                    "stats_json, archive_path, updated_at) VALUES (:id, :src, :h, :n, :at, :st, "
                    ":stats, :ap, :at)"
                ),
                {
                    "id": import_id,
                    "src": source,
                    "h": digest,
                    "n": safe_name(f.name),
                    "at": now,
                    "st": status,
                    "stats": canonical.dumps(stats),
                    "ap": archive_path,
                },
            )
            if rows is None:
                rows = [
                    (
                        s.index,
                        s.opening.on_date if s.opening else None,
                        s.closing.on_date if s.closing else None,
                    )
                    for s in (parsed.statements if parsed else [])
                ]
            for index, opbd, clbd in rows:
                conn.execute(
                    text(
                        "INSERT INTO import_statements (import_id, stmt_index, opbd_date, "
                        "clbd_date, status, updated_at) VALUES (:i, :x, :o, :c, 'pending', :at)"
                    ),
                    {"i": import_id, "x": index, "o": opbd, "c": clbd, "at": now},
                )
        return import_id

    def stage(self, f: Incoming) -> tuple[FileOutcome, Staged | None]:
        digest = sha256(f.data)
        if self._known(digest):
            self.archiver.store(f.data, "duplicates", f"{digest[:16]}-{safe_name(f.name)}")
            log.info("import.duplicate_file")
            return FileOutcome(f.name, None, "duplicate", "import.duplicate_file"), None
        if viac_text.is_pdf(f.data):
            return self._stage_viac(f, digest)
        extra = documents.detect(f.name, f.data)
        if extra is not None:
            return self._stage_doc(f, digest, extra)
        source = revolut.source_of(f.data) or SOURCE
        try:
            parsed = self.reread(source, f.data)
        except (parser.CamtError, revolut.RevolutError) as exc:
            stats: dict[str, Any] = {"reason": exc.code, "detail": exc.reason}
            import_id = self._record(f, digest, "rejected", stats, None, source=source)
            log.warning("import.rejected", import_id=import_id, reason=exc.code)
            return FileOutcome(f.name, import_id, "rejected", exc.code), None
        assert isinstance(parsed, ParsedFile)  # noqa: S101 - camt.053 ou Revolut
        stats = {"version": parsed.version}
        import_id = self._record(f, digest, "staged", stats, parsed, source=source)
        return FileOutcome(f.name, import_id, "staged"), parsed

    def _stage_viac(self, f: Incoming, digest: str) -> tuple[FileOutcome, Staged | None]:
        try:
            doc = read_viac(self.pdf_text, f.data)
        except ViacError as exc:
            stats: dict[str, Any] = {"reason": exc.code, "detail": exc.reason}
            import_id = self._record(f, digest, "rejected", stats, None, source=VIAC_OTHER)
            log.warning("import.rejected", import_id=import_id, reason=exc.code)
            return FileOutcome(f.name, import_id, "rejected", exc.code), None
        if isinstance(doc, str):
            stats = {"document": doc, "statements": 0, "new": 0, "duplicates": 0, "reasons": []}
            import_id = self._record(f, digest, "applied", stats, None, source=VIAC_OTHER, rows=[])
            log.info("import.ignored", import_id=import_id, document=doc)
            return FileOutcome(f.name, import_id, "ignored", f"viac.{doc}"), None
        source = VIAC_NOTICE if doc.notice is not None else VIAC_REPORT
        stats = {"document": source}
        import_id = self._record(
            f, digest, "staged", stats, None, source=source, rows=doc.statements()
        )
        return FileOutcome(f.name, import_id, "staged"), doc

    def _stage_doc(
        self, f: Incoming, digest: str, source: str
    ) -> tuple[FileOutcome, Staged | None]:
        """Document du lot 6 : IBKR, cours, positions, composition de fonds."""
        try:
            doc = documents.read(source, f.data)
        except DocumentError as exc:
            stats: dict[str, Any] = {"reason": exc.code, "detail": exc.reason}
            import_id = self._record(f, digest, "rejected", stats, None, source=source, rows=[])
            log.warning("import.rejected", import_id=import_id, reason=exc.code)
            return FileOutcome(f.name, import_id, "rejected", exc.code), None
        stats = {"document": doc.handler.name}
        import_id = self._record(f, digest, "staged", stats, None, source=source, rows=doc.rows())
        return FileOutcome(f.name, import_id, "staged"), doc

    # --- rapprochement et application ----------------------------------------------------

    def apply_all(
        self, staged: dict[str, Staged], only: set[tuple[str, int]] | None = None
    ) -> list[StatementOutcome]:
        """Applique les relevés triés par compte puis par OPBD, une transaction chacun, puis les
        documents VIAC dans l'ordre des dates, une transaction par document."""
        work = [
            (import_id, s)
            for import_id, pf in staged.items()
            if isinstance(pf, ParsedFile)
            for s in pf.statements
            if only is None or (import_id, s.index) in only
        ]
        work.sort(
            key=lambda w: (
                w[1].iban or w[1].account_ref or "",
                w[1].opening.on_date if w[1].opening else "",
                w[0],
            )
        )
        outcomes = [self._apply_statement(import_id, s) for import_id, s in work]
        docs = sorted(
            ((i, d) for i, d in staged.items() if isinstance(d, ViacDoc)),
            key=lambda w: (w[1].order, w[0]),
        )
        for import_id, doc in docs:
            indexes = None if only is None else {x for i, x in only if i == import_id}
            with begin_immediate(self.engine) as conn:
                done = apply_viac(conn, import_id, doc, indexes)
            log.info(
                "import.viac",
                import_id=import_id,
                status=sorted({o.status for o in done}),
                reasons=sorted({r for o in done for r in o.reasons}),
                new=sum(o.new for o in done),
            )
            outcomes += done
        extras = sorted(
            ((i, d) for i, d in staged.items() if isinstance(d, documents.Doc)),
            key=lambda w: (w[1].order, w[0]),
        )
        for import_id, extra in extras:
            indexes = None if only is None else {x for i, x in only if i == import_id}
            with begin_immediate(self.engine) as conn:
                done = apply_doc(conn, import_id, extra, indexes)
            log.info(
                "import.document",
                import_id=import_id,
                document=extra.handler.name,
                status=sorted({o.status for o in done}),
                reasons=sorted({r for o in done for r in o.reasons}),
                new=sum(o.new for o in done),
            )
            outcomes += done
        for import_id in sorted({o.import_id for o in outcomes}):
            self._finish(import_id)
        if self.on_applied and any(o.status == "applied" for o in outcomes):
            try:
                self.on_applied()
            except Exception as exc:  # l'import est fait ; la tâche de nuit rattrapera
                log.warning("import.after_apply_failed", error=type(exc).__name__)
        return outcomes

    def _apply_statement(self, import_id: str, st: ParsedStatement) -> StatementOutcome:
        with begin_immediate(self.engine) as conn:
            result = apply_statement(conn, import_id, st)
        log.info(
            "import.statement",
            import_id=import_id,
            stmt=st.index,
            status=result.status,
            reasons=result.reasons,
            new=result.new,
            duplicates=result.duplicates,
        )
        return result

    def _finish(self, import_id: str) -> None:
        with begin_immediate(self.engine) as conn:
            finish(conn, import_id)

    # --- boîte d'entrée ------------------------------------------------------------------

    def ready_files(self) -> list[Path]:
        if not self.inbox.is_dir():
            return []
        now = time.time()
        out = []
        for p in sorted(self.inbox.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            if p.suffix.lower() not in INBOX_SUFFIXES:
                continue
            if now - p.stat().st_mtime < SETTLE_SECONDS:
                continue
            out.append(p)
        return out

    def process(self, files: Iterable[Incoming]) -> BatchReport:
        report = BatchReport()
        staged: dict[str, Staged] = {}
        for raw in files:
            try:
                members = expand(raw.name, raw.data)
            except ImportRefused as exc:
                members = []
                report.files.append(FileOutcome(raw.name, None, "rejected", exc.code))
            for f in members:
                outcome, parsed = self.stage(f)
                report.files.append(outcome)
                if parsed is not None and outcome.import_id is not None:
                    staged[outcome.import_id] = parsed
        report.statements = self.apply_all(staged)
        if any(s.status == "applied" and s.new for s in report.statements):
            report.statements += self.retry_needs_review(quiet=True)
        return report

    def process_inbox(self) -> BatchReport:
        """Traite l'inbox jusqu'à ce qu'elle soit vide ; rien pendant une reprise d'historique."""
        total = BatchReport()
        if self.lock_file.exists():
            log.info("import.paused", reason="history")
            return total
        while paths := self.ready_files():
            incoming = [Incoming(p.name, p.read_bytes()) for p in paths]
            batch = self.process(incoming)
            for p in paths:
                p.unlink()
            total.files += batch.files
            total.statements += batch.statements
        return total

    def receive(self, name: str, data: bytes) -> BatchReport:
        """POST /api/finance/imports : même traitement que l'inbox."""
        if self.lock_file.exists():
            raise ImportRefused("busy.retry", "reprise d'historique en cours")
        return self.process([Incoming(name, data)])
