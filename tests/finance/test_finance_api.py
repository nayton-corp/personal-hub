"""L1-10 : routes Finance, portées autorisées et refusées, pagination, recherche, dépôt."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import sessions, tokens
from hub.core.auth import SESSION_COOKIE
from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.registry import Registry
from hub.domains.finance import ledger
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import OTHER_IBAN, Stmt, Tx, camt053
from tests.finance.conftest import D, finance_settings, ready_account, simple_stmt


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[HubContext]:
    settings = finance_settings(tmp_path)
    hub = HubContext.build(settings, Registry([FinanceDomain(settings)]))
    hub.migrate_all()
    yield hub
    hub.dispose()


@pytest.fixture
def fin(ctx: HubContext) -> FinanceDomain:
    domain = ctx.registry.get("finance")
    assert isinstance(domain, FinanceDomain)
    return domain


@pytest.fixture
def client(ctx: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx), base_url="https://hub.example.ts.net") as c:
        yield c


def token(ctx: HubContext, *scopes: str) -> dict[str, str]:
    with ctx.core.engine.begin() as conn:
        _info, secret = tokens.create(conn, "t", list(scopes), "system:test")
    return {"Authorization": f"Bearer {secret}"}


def app_session(ctx: HubContext, client: TestClient) -> None:
    with ctx.core.engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO passkeys (credential_id, public_key, sign_count, created_at) "
                "VALUES ('cred', x'00', 0, 'x')"
            )
        )
        _s, cookie = sessions.create(conn, "cred", 12)
    client.cookies.set(SESSION_COOKIE, cookie)


@pytest.fixture
def loaded(fin: FinanceDomain) -> FinanceDomain:
    ready_account(fin, 100_000)
    entries = [
        Tx("20.00", True, D, label="TWINT", counterparty="Jean Exemple"),
        Tx("20.00", True, D, label="TWINT", counterparty="Jean Exemple"),
        Tx("2500.00", False, date(2026, 10, 2), counterparty="Employeur Fictif SA"),
        Tx("85.30", True, date(2026, 10, 3), counterparty="Épicerie du Coin", label="Achat"),
        Tx("300.00", True, date(2026, 10, 4), counterparty_iban=OTHER_IBAN),
    ]
    fin.importer.process([Incoming("a.xml", camt053(Stmt(Decimal("1000.00"), D, entries)))])
    with begin_immediate(fin.engine()) as conn:
        seqs = conn.execute(text("SELECT seq, amount_minor FROM entries")).fetchall()
        for seq, amount in seqs:
            cat = "salaire" if amount == 250_000 else "alimentation" if amount < 0 else None
            if cat:
                ledger.append(
                    conn,
                    "categorizations",
                    {
                        "entry_seq": seq,
                        "category_id": cat,
                        "source": "user",
                        "rule_id": None,
                        "proposal_id": None,
                        "created_at": "x",
                    },
                )
    return fin


def test_scopes(client: TestClient, ctx: HubContext, loaded: FinanceDomain) -> None:
    brain = token(ctx, "brain")
    agg = token(ctx, "aggregates")
    other = token(ctx, "core:collector")
    for path in ("/accounts", "/summary?month=2026-10", "/categories", "/freshness", "/budget"):
        assert client.get(f"/api/finance{path}", headers=agg).status_code == 200, path
    for path in ("/entries", "/review", "/search?q=jean"):
        assert client.get(f"/api/finance{path}", headers=brain).status_code == 200, path
        assert client.get(f"/api/finance{path}", headers=agg).status_code == 403, path
    assert client.get("/api/finance/accounts", headers=other).status_code == 403
    assert client.get("/api/finance/accounts").status_code == 401
    assert client.post("/api/finance/imports?name=a.xml", headers=brain).status_code == 403


def test_accounts_and_freshness(client: TestClient, ctx: HubContext, loaded: FinanceDomain) -> None:
    (a,) = client.get("/api/finance/accounts", headers=token(ctx, "brain")).json()["items"]
    assert a["iban"] == "CH93…957"
    assert a["balance"] == {"minor": 307470, "currency": "CHF", "display": "3074.70"}
    assert a["last_clbd"]["gap"]["minor"] == 0
    (f,) = client.get("/api/finance/freshness", headers=token(ctx, "aggregates")).json()["items"]
    assert f["last_clbd"]["on_date"] == "2026-10-04"
    assert f["last_import"] is not None


def test_entries_pagination_and_detail(
    client: TestClient, ctx: HubContext, loaded: FinanceDomain
) -> None:
    h = token(ctx, "brain")
    page = client.get("/api/finance/entries?limit=2", headers=h).json()
    assert [e["booking_date"] for e in page["items"]] == ["2026-10-04", "2026-10-03"]
    seen = [e["id"] for e in page["items"]]
    while page["next_cursor"]:
        page = client.get(
            f"/api/finance/entries?limit=2&cursor={page['next_cursor']}", headers=h
        ).json()
        seen += [e["id"] for e in page["items"]]
    assert len(seen) == len(set(seen)) == 6  # ouverture comprise
    r = client.get("/api/finance/entries?uncategorized=true", headers=h).json()
    assert [e["amount"]["minor"] for e in r["items"]] == []  # tout est catégorisé sauf l'ouverture
    r = client.get("/api/finance/entries?category=salaire&from=2026-10-02&to=2026-10-02", headers=h)
    (salary,) = r.json()["items"]
    assert salary["category"] == {"id": "salaire", "source": "user"}
    detail = client.get(f"/api/finance/entries/{salary['id']}", headers=h).json()
    assert detail["categorizations"][0]["category_id"] == "salaire"
    assert detail["notes"] == detail["corrections"] == []
    assert client.get("/api/finance/entries/nope", headers=h).status_code == 404
    assert client.get("/api/finance/entries?cursor=bad", headers=h).status_code == 422
    assert client.get("/api/finance/entries?limit=500", headers=h).status_code == 422


def test_summary_budget_trend(client: TestClient, ctx: HubContext, loaded: FinanceDomain) -> None:
    brain = client.get("/api/finance/summary?month=2026-10", headers=token(ctx, "brain")).json()
    assert brain["income"]["minor"] == 250_000
    assert brain["expenses"]["minor"] == 4_000 + 8_530 + 30_000
    by_cat = {c["category"]: c["count"] for c in brain["by_category"]}
    assert by_cat == {"alimentation": 4, "salaire": 1}
    agg = client.get("/api/finance/summary?month=2026-10", headers=token(ctx, "aggregates")).json()
    # moins de 3 écritures : regroupé dans « Autres » pour la portée aggregates
    assert {c["category"] for c in agg["by_category"]} == {"alimentation", "autres"}
    assert (
        client.get("/api/finance/summary?month=2026-13", headers=token(ctx, "brain")).status_code
        == 422
    )
    t = client.get(
        "/api/finance/trend?months=3&month=2026-11&category=alimentation",
        headers=token(ctx, "aggregates"),
    ).json()
    assert [(p["month"], p["total"]["minor"]) for p in t["series"]] == [
        ("2026-09", 0),
        ("2026-10", -42_530),
        ("2026-11", 0),
    ]
    all_expenses = client.get(
        "/api/finance/trend?months=1&month=2026-10", headers=token(ctx, "brain")
    )
    assert all_expenses.json()["series"][0]["total"]["minor"] == -42_530
    b = client.get("/api/finance/budget?month=2026-10", headers=token(ctx, "brain")).json()
    assert {line["category"]: line["target"] for line in b["lines"]}["alimentation"] is None


def test_review_and_search(client: TestClient, ctx: HubContext, fin: FinanceDomain) -> None:
    ready_account(fin, 100_000)
    fin.importer.process([Incoming("a.xml", camt053(simple_stmt("1000.00")))])
    h = token(ctx, "brain")
    groups = client.get("/api/finance/review", headers=h).json()["groups"]
    assert groups[0] == {
        "counterparty": "jean exemple",
        "count": 2,
        "total": {"minor": -4000, "currency": "CHF", "display": "-40.00"},
    }
    hits = client.get("/api/finance/search?q=EMPLOYEUR", headers=h).json()["items"]
    assert [x["counterparty"] for x in hits] == ["Employeur Fictif SA"]
    assert client.get("/api/finance/search?q=%20%20a%20%20", headers=h).status_code == 422
    # recherche transverse du cœur et résolution d'URN
    core = client.get("/api/search?q=employeur", headers=h).json()["items"]
    assert core[0]["domain"] == "finance"
    ref = client.get(f"/api/resolve?urn={core[0]['urn']}", headers=h).json()
    assert ref["href"].startswith("/finance/entries/")


def test_upload_and_import_detail(client: TestClient, ctx: HubContext, fin: FinanceDomain) -> None:
    app_session(ctx, client)
    ready_account(fin, 100_000)
    data = camt053(simple_stmt("1000.00"))
    r = client.post("/api/finance/imports?name=releve.xml", content=data)
    assert r.status_code == 202
    (item,) = r.json()["items"]
    assert item["status"] == "applied"
    again = client.post("/api/finance/imports?name=releve.xml", content=data)
    assert again.status_code == 409
    assert again.json()["type"] == "import.duplicate_file"
    bad = client.post("/api/finance/imports?name=x.xml", content=b"<x/>")
    assert bad.status_code == 422
    assert client.post("/api/finance/imports?name=x.exe", content=b"x").status_code == 422
    assert client.post("/api/finance/imports?name=x.xml", content=b"").status_code == 422
    detail = client.get(f"/api/finance/imports/{item['import_id']}").json()
    assert detail["statements"][0]["new"] == 3
    assert detail["stats"]["new"] == 3
    assert client.get("/api/finance/imports/nope").status_code == 404
    fin.importer.lock_file.touch()
    busy = client.post("/api/finance/imports?name=y.xml", content=data + b" ")
    assert busy.status_code == 503


def test_health_and_events(client: TestClient, ctx: HubContext, loaded: FinanceDomain) -> None:
    r = client.get("/api/health").json()
    assert r["domains"]["finance"] == {"db": "ok", "schema_version": 3, "ok": True}
    events = loaded.events_since(0, 10)
    assert [e.type for e in events] == ["entries.appended", "import.applied"]
    assert loaded.applied([]) == {}
    assert loaded.applied(["p"]) == {}
    assert loaded.resolve("hub:finance:nothing:1") is None
    (acc,) = client.get("/api/finance/accounts", headers=token(ctx, "brain")).json()["items"]
    assert loaded.resolve(f"hub:finance:account:{acc['id']}") is not None
    assert loaded.resolve(events[1].urn) is not None
    assert loaded.mcp_tools() == []
