"""Dettes (migration 0016) : départ à la main ou depuis le versement reçu, paiements appariés par
catégorie, intérêts, soldes constatés, clôture, et patrimoine net."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.errors import Problem
from hub.domains.finance import debts, ledger, valuation
from hub.domains.finance.domain import FinanceDomain
from tests.factories.camt import Tx
from tests.finance.conftest import ready_account, rows
from tests.finance.test_double_sas import accept, client, create, ctx, fin, load
from tests.finance.test_finance_api import token

__all__ = ["client", "ctx", "fin"]  # fixtures
D = date(2026, 10, 1)
LENDER = "Prêteur Fictif"


def categorize(fin: FinanceDomain, counterparty: str, category: str) -> None:
    with begin_immediate(fin.engine()) as conn:
        for (seq,) in conn.execute(
            text("SELECT seq FROM entries WHERE counterparty = :c AND amount_minor < 0"),
            {"c": counterparty},
        ).fetchall():
            ledger.append(
                conn,
                "categorizations",
                {
                    "entry_seq": seq,
                    "category_id": category,
                    "source": "user",
                    "rule_id": None,
                    "proposal_id": None,
                    "created_at": "x",
                },
            )


@pytest.fixture
def loan(fin: FinanceDomain, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """5000 reçus du prêteur le 1er octobre, puis deux mensualités différentes."""
    monkeypatch.setattr(fin, "today", lambda: date(2026, 10, 31))
    a = ready_account(fin)
    load(
        fin,
        [
            Tx("5000.00", False, D, counterparty=LENDER),
            Tx("300.00", True, date(2026, 10, 5), counterparty=LENDER),
            Tx("250.00", True, date(2026, 10, 20), counterparty=LENDER),
            Tx("40.00", True, date(2026, 10, 21), counterparty="Kiosque Fictif"),
        ],
    )
    categorize(fin, LENDER, "voiture-credit")
    ((credit,),) = rows(
        fin, "SELECT id FROM entries WHERE counterparty = :c AND amount_minor > 0", c=LENDER
    )
    return {"account_id": a.id, "entry_id": credit}


def save(ctx: HubContext, params: dict[str, Any]) -> dict[str, Any]:
    out = accept(ctx, create(ctx, "save_debt", params))
    assert out.result is not None
    return out.result


def listed(client: TestClient, ctx: HubContext) -> list[dict[str, Any]]:
    r = client.get("/api/finance/debts", headers=token(ctx, "brain"))
    assert r.status_code == 200
    return list(r.json()["items"])


def test_debt_from_the_received_payment(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, loan: dict[str, Any]
) -> None:
    p = create(
        ctx,
        "save_debt",
        {
            "name": "Crédit voiture",
            "lender": LENDER,
            "kind": "loan",
            "opening_entry_id": loan["entry_id"],
            "category_id": "voiture-credit",
            "account_id": loan["account_id"],
        },
    )
    assert p.preview["summary"] == (
        f"Nouvelle dette « Crédit voiture » (Crédit, {LENDER}) : 5000.00 CHF au 2026-10-01"
    )
    accept(ctx, p)
    (d,) = listed(client, ctx)
    assert d["balance"]["minor"] == 500_000 - 30_000 - 25_000
    assert (d["original"]["minor"], d["stated_on"]) == (500_000, "2026-10-01")
    assert (d["payments_since"], d["last_payment"]) == (2, "2026-10-20")
    # sans mensualité donnée, la projection suit les derniers paiements (moyenne)
    assert d["payment"] is None
    assert d["usual_payment"]["minor"] == 27_500
    assert d["projected_end"] == "2028-03"  # 4450 / 275 : 17 mois
    # patrimoine net : 1000 + 5000 - 300 - 250 - 40, moins la dette ; le remboursement est un
    # versement, pas un effet marché
    with fin.engine().connect() as conn:
        v = valuation.value_at(conn, "2026-10-31")
        before = valuation.value_at(conn, "2026-09-30")
    assert v.by_envelope["dettes"] == -445_000
    assert v.by_account[f"debt:{d['id']}"] == -445_000
    assert v.net_worth == 541_000 - 445_000
    assert v.net_worth - v.deposits == before.net_worth - before.deposits
    # les instantanés suivent : une dette créée relance le calcul
    hist = client.get("/api/finance/networth/history", headers=token(ctx, "brain")).json()
    assert hist["items"][-1]["by_envelope"]["dettes"]["minor"] == -445_000


def test_payment_changes_statement_and_close(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, loan: dict[str, Any]
) -> None:
    out = save(
        ctx,
        {
            "name": "Prêt",
            "lender": LENDER,
            "kind": "other",
            "balance_minor": 600_000,
            "balance_on": "2026-10-10",
            "category_id": "voiture-credit",
            "payment_minor": 20_000,
        },
    )
    debt_id = out["debt_id"]
    # le paiement du 5 précède le départ : seul celui du 20 compte
    (d,) = listed(client, ctx)
    assert (d["balance"]["minor"], d["original"]["minor"]) == (575_000, 600_000)
    assert d["usual_payment"]["minor"] == 20_000  # mensualité donnée
    assert d["projected_end"] == "2029-03"
    # mensualité qui change, échéance posée puis retirée
    save(ctx, {"debt_id": debt_id, "payment_minor": 35_000, "ends_on": "2028-12-31"})
    save(ctx, {"debt_id": debt_id, "ends_on": ""})
    (d,) = listed(client, ctx)
    assert (d["payment"]["minor"], d["ends_on"]) == (35_000, None)
    # relevé du prêteur : le calcul repart de là
    accept(
        ctx,
        create(
            ctx,
            "record_debt_balance",
            {"debt_id": debt_id, "on_date": "2026-10-25", "amount_minor": 400_000},
        ),
    )
    (d,) = listed(client, ctx)
    assert (d["balance"]["minor"], d["stated_on"], d["payments_since"]) == (
        400_000,
        "2026-10-25",
        0,
    )
    assert len(d["balances"]) == 2
    # soldée
    p = create(ctx, "save_debt", {"debt_id": debt_id, "closed_on": "2026-10-30"})
    assert p.preview["summary"] == "Dette « Prêt » close au 2026-10-30"
    accept(ctx, p)
    (d,) = listed(client, ctx)
    assert d["balance"]["minor"] == 0
    with fin.engine().connect() as conn:
        assert valuation.value_at(conn, "2026-10-31").by_envelope["dettes"] == 0
        assert valuation.value_at(conn, "2026-10-29").by_envelope["dettes"] == -400_000
        assert valuation.value_at(conn, "2026-10-09").by_envelope["dettes"] == 0


def test_refusals(ctx: HubContext, fin: FinanceDomain, loan: dict[str, Any]) -> None:
    base = {"name": "Prêt", "lender": LENDER, "kind": "loan"}
    for bad in (
        base,  # pas de départ
        {**base, "balance_minor": 100, "balance_on": "2026-10-01", "opening_entry_id": "e1"},
        {**base, "balance_minor": 0, "balance_on": "2026-10-01"},
        {**base, "balance_minor": 100, "balance_on": "2026-10-01", "category_id": "inconnue"},
        {**base, "balance_minor": 100, "balance_on": "2026-10-01", "account_id": "inconnu"},
        {**base, "opening_entry_id": "e00"},
        {"debt_id": "inconnue", "name": "x"},
    ):
        with pytest.raises((Problem, ValueError)):
            create(ctx, "save_debt", bad)
    debt_id = save(ctx, {**base, "balance_minor": 100, "balance_on": "2026-10-01"})["debt_id"]
    for bad in (
        {"debt_id": debt_id, "name": "Prêt"},  # rien ne change
        {"debt_id": debt_id, "balance_minor": 5},
    ):
        with pytest.raises((Problem, ValueError)):
            create(ctx, "save_debt", bad)


def test_interest_accrues_between_payments() -> None:
    d = debts.Debt(
        "d1",
        "Hypothèque",
        "Banque",
        "mortgage",
        "CHF",
        None,
        Decimal("0.0365"),
        None,
        None,
        "logement",
        None,
        None,
    )
    book = debts.Book([d], {"d1": [("2025-01-01", 1_000_000)]}, {"d1": [("2025-07-02", 100_000)]})
    # 182 jours à 3,65 % : 18 200 d'intérêts, puis le paiement
    mid = book.state(d, "2025-07-02")
    assert mid is not None
    assert (mid.balance, mid.interest) == (1_018_200 - 100_000, 18_200)
    assert book.balance(d, "2024-12-31") is None
    end = book.state(d, "2026-01-01")
    assert end is not None
    assert end.balance == 918_200 + 16_803  # 183 jours
    # une mensualité qui ne couvre pas les intérêts ne finit jamais
    assert debts.projected_end(d, 918_200, "2026-01-01", 1_000) is None
    assert debts.projected_end(d, 0, "2026-01-01", 1_000) is None


def test_recategorized_payment_reaches_the_history(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, loan: dict[str, Any]
) -> None:
    save(
        ctx,
        {
            "name": "Crédit voiture",
            "lender": LENDER,
            "kind": "loan",
            "opening_entry_id": loan["entry_id"],
            "category_id": "voiture-credit",
        },
    )
    h = token(ctx, "brain")

    def owed() -> int:
        items = client.get("/api/finance/networth/history", headers=h).json()["items"]
        return int(items[-1]["by_envelope"]["dettes"]["minor"])

    assert owed() == -445_000
    # un paiement classé après coup compte dès la lecture suivante, sans import ni nuit
    categorize(fin, "Kiosque Fictif", "voiture-credit")
    assert owed() == -441_000
