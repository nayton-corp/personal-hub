"""Relecture des imports depuis l'archive chiffrée (section 4) : un relevé en attente se rejoue
après un compte ajouté ou une ouverture, se force après validation d'une carte `apply_import`,
les documents d'une source se réappliquent après une évolution de son importeur, et un import
resté « staged » (processus arrêté entre la mise en attente et l'application) est repris.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta

from sqlalchemy import Connection, Engine, text

from hub.domains.finance.patrimoine.model.instruments import DocumentError
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.registre.model.statements import (
    ParsedFile,
)
from hub.domains.finance.sources.app import documents
from hub.domains.finance.sources.app.outcomes import StatementOutcome
from hub.domains.finance.sources.app.statements import (
    Plan,
    apply_statement,
    finish,
    plan_statement,
    source_of,
)
from hub.domains.finance.sources.app.viac_docs import (
    VIAC_SOURCES,
    ViacDoc,
    read_viac,
)
from hub.domains.finance.sources.infra import camt as parser
from hub.domains.finance.sources.infra import revolut
from hub.domains.finance.sources.infra.files import Archiver
from hub.domains.finance.sources.infra.viac import ViacError
from hub.kernel.clock import iso, now_iso, utcnow
from hub.platform import secrets
from hub.platform.db import begin_immediate
from hub.platform.logging import get_logger

log = get_logger("hub.finance.import")


Staged = ParsedFile | ViacDoc | documents.Doc
# un import « staged » depuis plus longtemps n'est plus en cours d'application : son processus
# s'est arrêté (redémarrage, base occupée) et personne ne le reprendra sans nous
STALE_STAGED = timedelta(minutes=10)


class Rework:
    """Relecture et rejeu, mêlés à `ImportService` : l'archive, le lecteur de PDF et
    `apply_all` viennent du service."""

    engine: Engine
    archiver: Archiver
    pdf_text: Callable[[bytes], str]
    apply_all: Callable[..., list[StatementOutcome]]
    _finish: Callable[[str], None]
    stale_staged: timedelta = STALE_STAGED

    def _claim_staged(self, stale: timedelta) -> list[tuple[str, str, str]]:
        """Les imports « staged » assez anciens, réservés pour ce passage : leur horodatage
        est avancé dans la même transaction, un autre processus attendra donc à son tour."""
        cutoff = iso(utcnow() - stale)
        with begin_immediate(self.engine) as conn:
            rows = conn.execute(
                text(
                    "SELECT id, archive_path, source FROM imports WHERE status = 'staged' "
                    "AND updated_at <= :c AND archive_path IS NOT NULL ORDER BY received_at"
                ),
                {"c": cutoff},
            ).fetchall()
            for r in rows:
                conn.execute(
                    text("UPDATE imports SET updated_at = :at WHERE id = :i"),
                    {"at": now_iso(), "i": r[0]},
                )
        return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]

    def resume_staged(self, stale: timedelta | None = None) -> list[StatementOutcome]:
        """Reprend les imports interrompus entre la mise en attente et l'application (audit du
        10/11, I1). Relus depuis l'archive chiffrée : les relevés encore « pending » d'un fichier
        de banque, le document entier sinon (ce qui est déjà au registre est un doublon)."""
        files: dict[str, Staged] = {}
        docs: dict[str, Staged] = {}
        only: set[tuple[str, int]] = set()
        claimed = self._claim_staged(self.stale_staged if stale is None else stale)
        for import_id, archive_path, source in claimed:
            try:
                staged = self.reread(source, self.archiver.load(archive_path))
            except (
                ImportRefused,
                secrets.SecretsError,
                OSError,
                ViacError,
                DocumentError,
                parser.CamtError,
                revolut.RevolutError,
            ) as exc:
                # reste « staged » : le contrôle de santé le compte et alerte
                log.warning(
                    "import.resume_unavailable", import_id=import_id, error=type(exc).__name__
                )
                continue
            if not isinstance(staged, ParsedFile):
                docs[import_id] = staged
                continue
            with self.engine.connect() as conn:
                pending = set(
                    conn.execute(
                        text(
                            "SELECT stmt_index FROM import_statements WHERE import_id = :i "
                            "AND status = 'pending'"
                        ),
                        {"i": import_id},
                    ).scalars()
                )
            if pending:
                files[import_id] = staged
                only |= {(import_id, x) for x in pending}
            else:  # arrêté après le dernier relevé : il ne manque que le statut
                self._finish(import_id)
        outcomes: list[StatementOutcome] = []
        if files:
            outcomes += self.apply_all(files, only)
        if docs:
            outcomes += self.apply_all(docs)
        if files or docs:
            log.info("import.resumed", imports=len(files) + len(docs), statements=len(outcomes))
        return outcomes

    def parsed(self, conn: Connection, import_id: str) -> ParsedFile:
        """Relit un import (camt.053 ou Revolut) depuis son archive chiffrée."""
        row = conn.execute(
            text("SELECT archive_path, source FROM imports WHERE id = :i"), {"i": import_id}
        ).first()
        if row is None or not row[0]:
            raise ImportRefused("import.not_found", "import inconnu")
        try:
            staged = self.reread(row[1], self.archiver.load(row[0]))
        except (secrets.SecretsError, OSError) as exc:
            raise ImportRefused("import.archive_unavailable", "archive illisible") from exc
        if not isinstance(staged, ParsedFile):
            raise ImportRefused("import.not_applicable", "document sans relevé")
        return staged

    def review_plan(self, conn: Connection, import_id: str) -> list[tuple[int, Plan]]:
        """Relevés en attente d'un import et ce que leur validation écrirait (lecture seule).
        Un document VIAC n'a rien à forcer : il attend un compte ou une ouverture."""
        source = source_of(conn, import_id) or ""
        if source in VIAC_SOURCES or documents.handler_for(source) is not None:
            return []
        waiting = set(
            conn.execute(
                text(
                    "SELECT stmt_index FROM import_statements WHERE import_id = :i "
                    "AND status = 'needs_review'"
                ),
                {"i": import_id},
            ).scalars()
        )
        if not waiting:
            return []
        pf = self.parsed(conn, import_id)
        return [(st.index, plan_statement(conn, st)) for st in pf.statements if st.index in waiting]

    def force(self, conn: Connection, import_id: str, proposal_id: str) -> list[StatementOutcome]:
        """`apply_import` validé : applique les relevés en attente malgré les anomalies
        acceptables, dans la transaction de l'appelant."""
        waiting = {i for i, _ in self.review_plan(conn, import_id)}
        pf = self.parsed(conn, import_id)
        outcomes = [
            apply_statement(conn, import_id, st, force=True, proposal_id=proposal_id)
            for st in pf.statements
            if st.index in waiting
        ]
        finish(conn, import_id)
        return outcomes

    def retry_needs_review(
        self, import_ids: Sequence[str] | None = None, *, quiet: bool = False
    ) -> list[StatementOutcome]:
        """Rejoue les relevés en attente depuis l'archive chiffrée (après une ouverture, un
        compte ajouté ou un relevé manquant arrivé entre-temps)."""
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT s.import_id, s.stmt_index, i.archive_path, i.source "
                    "FROM import_statements s "
                    "JOIN imports i ON i.id = s.import_id WHERE s.status = 'needs_review' "
                    "ORDER BY i.received_at"
                )
            ).fetchall()
        wanted = [r for r in rows if import_ids is None or r[0] in import_ids]
        if not wanted:
            return []
        staged: dict[str, Staged] = {}
        only = set()
        for import_id, index, archive_path, source in wanted:
            if import_id not in staged:
                try:
                    staged[import_id] = self.reread(source, self.archiver.load(archive_path))
                except (
                    ImportRefused,
                    secrets.SecretsError,
                    OSError,
                    ViacError,
                    DocumentError,
                ) as exc:
                    if quiet:
                        log.warning("import.retry_unavailable", error=type(exc).__name__)
                        return []
                    if isinstance(exc, ImportRefused):
                        raise
                    raise ImportRefused("import.archive_unavailable", "archive illisible") from exc
            only.add((import_id, index))
        return self.apply_all(staged, only)

    def replay(self, source: str) -> list[StatementOutcome]:
        """Réapplique les documents déjà lus d'une source (après une évolution de son
        importeur) depuis l'archive chiffrée ; ce qui est déjà au registre est un doublon."""
        if documents.handler_for(source) is None:
            raise ImportRefused("import.not_applicable", f"source {source[:40]}")
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, archive_path FROM imports WHERE source = :s "
                    "AND status IN ('applied', 'needs_review') ORDER BY received_at"
                ),
                {"s": source},
            ).fetchall()
        staged: dict[str, Staged] = {}
        for import_id, archive_path in rows:
            try:
                staged[import_id] = self.reread(source, self.archiver.load(archive_path))
            except (secrets.SecretsError, OSError, DocumentError) as exc:
                raise ImportRefused("import.archive_unavailable", "archive illisible") from exc
        return self.apply_all(staged)

    def reread(self, source: str, data: bytes) -> Staged:
        """Relit un fichier archivé selon sa source."""
        if documents.handler_for(source) is not None:
            return documents.read(source, data)
        if source in VIAC_SOURCES:
            doc = read_viac(self.pdf_text, data)
            if isinstance(doc, str):
                raise ImportRefused("import.not_applicable", f"document {doc}")
            return doc
        if source in revolut.SOURCES:
            return revolut.parse(source, data)
        return parser.parse(data)
