"""Comptes Revolut (lot 5) : ceux que des relevés en attente nomment sans qu'ils existent, et leur
ouverture depuis le premier relevé."""

from __future__ import annotations

from sqlalchemy import text

from hub.domains.finance.registre.app import catalog
from hub.domains.finance.registre.app.opening import open_account
from hub.domains.finance.registre.model.errors import ImportRefused
from hub.domains.finance.registre.model.statements import (
    ParsedStatement,
)
from hub.domains.finance.sources.app.importer import ImportService
from hub.domains.finance.sources.infra import revolut
from hub.platform import secrets
from hub.platform.db import begin_immediate


def revolut_pending(service: ImportService) -> dict[str, list[tuple[str, ParsedStatement]]]:
    """Relevés Revolut en attente, par clé de compte (`revolut:CHF`), relus depuis l'archive."""
    with service.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT DISTINCT i.id, i.source, i.archive_path FROM imports i "
                "JOIN import_statements s ON s.import_id = i.id "
                "WHERE s.status = 'needs_review' AND i.source IN (:eb, :csv) "
                "ORDER BY i.received_at"
            ),
            {"eb": revolut.EB_SOURCE, "csv": revolut.CSV_SOURCE},
        ).fetchall()
    out: dict[str, list[tuple[str, ParsedStatement]]] = {}
    for import_id, source, archive_path in rows:
        try:
            pf = revolut.parse(source, service.archiver.load(archive_path))
        except (revolut.RevolutError, secrets.SecretsError, OSError, ImportRefused):
            continue
        for st in pf.statements:
            if st.account_ref is not None:
                out.setdefault(st.account_ref, []).append((import_id, st))
    return out


def open_revolut(service: ImportService, account: catalog.Account) -> tuple[bool, list[str]]:
    """Ouvre un compte Revolut avec le solde déduit du plus ancien relevé en attente (la reprise
    complète faite à la liaison), puis rejoue ses relevés. Renvoie (ouvert, imports rejoués)."""
    pending = revolut_pending(service).get(account.external_ref or "", [])
    with_opening = [(i, st) for i, st in pending if st.derived_opening is not None]
    if not with_opening:
        return False, [i for i, _ in pending]
    _import_id, oldest = min(
        with_opening,
        key=lambda x: (x[1].derived_opening.on_date, x[0]),  # type: ignore[union-attr]
    )
    opening = oldest.derived_opening
    assert opening is not None  # noqa: S101
    with begin_immediate(service.engine) as conn:
        open_account(conn, account.id, opening.on_date, opening.amount_minor, account.currency)
    ids = sorted({i for i, _ in pending})
    service.retry_needs_review(ids)
    return True, ids
