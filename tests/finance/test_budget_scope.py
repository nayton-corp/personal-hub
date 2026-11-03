"""Comptes suivis par le budget : un compte hors budget (l'épargne) n'y entre que par ses dépenses
catégorisées, pour que des impôts payés depuis l'épargne comptent dans Impôts."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core.context import HubContext
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.registre.app import catalog, ledger, opening
from hub.domains.finance.sources.infra.files import Incoming
from hub.platform.db import begin_immediate
from tests.factories.camt import IBAN_2, Stmt, Tx, camt053
from tests.finance.test_app_reads import (  # noqa: F401  (fixtures)
    client,
    ctx,
    fin,
    minor,
    year,
)
from tests.finance.test_finance_api import token


def savings_with_taxes(domain: FinanceDomain) -> None:
    """Un compte d'épargne hors budget : un acompte d'impôts (catégorisé), un intérêt et un
    débit sans catégorie, en octobre 2026."""
    with begin_immediate(domain.engine()) as conn:
        a = catalog.add_account(
            conn, institution="BCF", name="Épargne", iban=IBAN_2, liquid=True, budget_account=False
        )
        opening.open_account(conn, a.id, "2025-11-30", 2_000_000, "CHF")
    txs = [
        Tx("300.00", True, date(2026, 10, 10), counterparty="Administration fiscale"),
        Tx("10.00", False, date(2026, 10, 15), counterparty="Intérêts"),
        Tx("40.00", True, date(2026, 10, 16), counterparty="Débit inconnu"),
    ]
    stmt = Stmt(Decimal("20000.00"), date(2026, 10, 1), txs, iban=IBAN_2, stmt_id="EP-2026-10")
    domain.importer.process([Incoming("ep.xml", camt053(stmt))])
    with begin_immediate(domain.engine()) as conn:
        seq = conn.execute(
            text("SELECT seq FROM entries WHERE counterparty = 'Administration fiscale'")
        ).scalar_one()
        ledger.append(
            conn,
            "categorizations",
            {
                "entry_seq": seq,
                "category_id": "impots",
                "source": "user",
                "rule_id": None,
                "proposal_id": None,
                "created_at": "x",
            },
        )


def test_taxes_paid_from_savings_count_in_budget(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    before = client.get("/api/finance/budget/totals?month=2026-10", headers=brain).json()
    savings_with_taxes(year)
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    lines = {line["category"]: line for line in b["lines"]}
    assert minor(lines["impots"]["spent"]) == 30_000
    assert lines["impots"]["group"] == "fixed"
    after = client.get("/api/finance/budget/totals?month=2026-10", headers=brain).json()
    # l'acompte s'ajoute aux dépenses fixes ; l'intérêt et le débit sans catégorie restent dehors
    assert minor(after["fixed"]) == minor(before["fixed"]) + 30_000
    assert minor(after["variable"]) == minor(before["variable"])
    assert minor(after["income"]) == minor(before["income"])
    trend = client.get(
        "/api/finance/trend?category=impots&months=2&month=2026-10", headers=brain
    ).json()
    assert [minor(p["total"]) for p in trend["series"]] == [0, -30_000]
