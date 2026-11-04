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


# --- audit C3 : les dépenses dans une autre devise -------------------------------------------


def eur_card(domain: FinanceDomain) -> None:
    """Une carte Revolut en euros, compte de budget : deux restaurants en octobre 2026, un change
    EUR→CHF connu seulement depuis le 10."""
    with begin_immediate(domain.engine()) as conn:
        a = catalog.add_account(
            conn,
            institution="Revolut",
            name="EUR",
            currency="EUR",
            external_ref="rev-eur",
            budget_account=True,
        )
        opening.open_account(conn, a.id, "2026-09-30", 50_000, "EUR")
        for on, amount in (("2026-10-05", -2_000), ("2026-10-20", -1_000)):
            seq, _ = ledger.append_entry(
                conn,
                ledger.NewEntry(
                    account_id=a.id,
                    booking_date=on,
                    amount_minor=amount,
                    currency="EUR",
                    counterparty="Trattoria Fictive",
                    dedup_key=ledger.dedup_hash(f"eur|{on}|{amount}"),
                ),
            )
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": seq,
                    "category_id": "restaurants",
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": None,
                    "created_at": "x",
                },
            )
        conn.execute(
            text(
                "INSERT INTO fx_rates (on_date, base, quote, rate, source) "
                "VALUES ('2026-10-10', 'EUR', 'CHF', '0.95', 'snb')"
            )
        )


def test_foreign_currency_expenses_count_at_the_day_rate(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    brain = token(ctx, "brain=finance")
    before = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    eur_card(year)
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    spent = {x["category"]: minor(x["spent"]) for x in b["lines"]}
    was = {x["category"]: minor(x["spent"]) for x in before["lines"]}
    # 10 EUR à 0,95 le 20 : 9,50 CHF de plus ; le 5, sans change, est laissé de côté et dit
    assert spent["restaurants"] == was["restaurants"] + 950
    assert b["missing_fx"] == [{"currency": "EUR", "on_date": "2026-10-05", "count": 1}]
    s = client.get("/api/finance/summary?month=2026-10", headers=brain).json()
    assert s["missing_fx"] == b["missing_fx"]
    assert minor(s["expenses"]) == minor(before["expenses"]) + 950
    trend = client.get(
        "/api/finance/trend?category=restaurants&months=1&month=2026-10", headers=brain
    ).json()
    assert minor(trend["series"][0]["total"]) == -(was["restaurants"] + 950)


# --- audit M3 : l'état, le rythme et la projection viennent du serveur -----------------------


def test_budget_state_pace_and_projection_come_from_the_server(
    client: TestClient,  # noqa: F811
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
) -> None:
    from hub.domains.finance.classement.app import sentinels
    from tests.finance.test_app_reads import set_budget

    brain = token(ctx, "brain=finance")
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    lines = {x["category"]: x for x in b["lines"]}
    assert (b["current"], b["pace"]) == (True, "0.8710")  # le 27 sur 31 jours
    # fixes en entier (1 500), variables au rythme (250 × 27/31) : 98,16 % attendus à ce jour
    assert b["expected"] == "0.9816"
    assert b["state"] == {
        "kind": "over",
        "over_by": {"minor": 18_000, "currency": "CHF", "display": "180.00"},
    }
    assert (lines["alimentation"]["state"], minor(lines["alimentation"]["rest"])) == (
        "over",
        -5_000,
    )
    assert lines["logement"]["state"] == "paid"
    assert (lines["restaurants"]["state"], lines["restaurants"]["rest"]) == ("untracked", None)
    assert minor(lines["restaurants"]["projected"]) == 8_000 * 31 // 27  # au prorata du mois
    assert minor(lines["logement"]["projected"]) == 150_000  # une fixe payée ne grandit plus
    assert minor(b["projection"]) == sum(minor(x["projected"]) for x in b["lines"])
    # la même règle que les sentinelles : une cible sur les restaurants devient « probable »
    set_budget(year, "restaurants", 8_000)  # 80 dépensés le 27 : 91,85 projetés, +10 % passés
    b = client.get("/api/finance/budget?month=2026-10", headers=brain).json()
    line = {x["category"]: x for x in b["lines"]}["restaurants"]
    with year.engine().connect() as conn:
        p = {
            x.category: x for x in sentinels.budget_projection(conn, "2026-10", date(2026, 10, 27))
        }
    assert (line["state"], line["over"]) == ("likely_over", False)
    assert (p["restaurants"].likely_over, p["restaurants"].projected) == (
        True,
        minor(line["projected"]),
    )
    # un mois clos n'a ni rythme ni projection
    past = client.get("/api/finance/budget?month=2026-09", headers=brain).json()
    assert (past["current"], past["pace"], past["expected"], past["projection"]) == (
        False,
        None,
        None,
        None,
    )
    assert past["state"]["kind"] in ("closed_ok", "closed_over")
    assert all(x["projected"] is None for x in past["lines"])
