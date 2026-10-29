"""Chantier S3 : la chaîne du registre ne bouge pas quand son code passe au cœur. Les lignes
ci-dessous, toutes datées à la main, donnent toujours la même tête de journal."""

from __future__ import annotations

from sqlalchemy import text

from hub.domains.finance import ledger
from hub.domains.finance.domain import FinanceDomain
from hub.platform.db import begin_immediate
from hub.platform.settings import Settings

AT = "2026-10-01T08:00:00.000Z"
# tête calculée avant le déplacement vers hub.core.integrity (chantier S3)
HEAD = "29f5439c54e696245190c37ad0d46d9712fff92498fe93215f1775a68db758c9"


def test_the_chain_head_is_stable(settings: Settings) -> None:
    finance = FinanceDomain(settings)
    finance.migrate(seed=False)
    with begin_immediate(finance.engine()) as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (id, name, institution, kind, currency, created_at) "
                "VALUES ('acc', 'Courant', 'Banque', 'cash', 'CHF', :at)"
            ),
            {"at": AT},
        )
        for i, amount in enumerate((-1250, 620000, -4590)):
            ledger.append_entry(
                conn,
                ledger.NewEntry(
                    account_id="acc",
                    booking_date=f"2026-10-0{i + 1}",
                    amount_minor=amount,
                    currency="CHF",
                    dedup_key=f"k{i}",
                    counterparty="Migros" if amount < 0 else "Employeur",
                    label="Achat",
                ),
                created_at=AT,
            )
        ledger.append(
            conn,
            "events",
            {
                "type": "entries.appended",
                "urn": "hub:finance:import:x",
                "payload_json": "{}",
                "created_at": AT,
            },
        )
        ledger.append(
            conn,
            "applied_proposals",
            {"proposal_id": "p1", "kind": "add_note", "result_json": "{}", "applied_at": AT},
        )
    with finance.engine().connect() as conn:
        head = conn.execute(text("SELECT chain_hash FROM journal ORDER BY seq DESC")).first()
        result = ledger.verify(conn)
    assert result.ok, result.errors
    assert result.links == 5
    assert head is not None
    assert head[0] == HEAD
    finance.engine().dispose()
