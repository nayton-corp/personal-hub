"""L1-10 : routes Finance, portées autorisées et refusées, pagination, recherche, dépôt."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
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
from tests.finance.conftest import (
    D,
    finance_settings,
    ready_account,
    rows,
    simple_stmt,
    without_seed_rules,
)


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
    without_seed_rules(domain)
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
    assert f["last_data"] == "2026-10-04"
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
    credits = client.get("/api/finance/entries?direction=in", headers=h).json()["items"]
    debits = client.get("/api/finance/entries?direction=out", headers=h).json()["items"]
    assert credits
    assert debits
    assert all(e["amount"]["minor"] > 0 for e in credits)
    assert all(e["amount"]["minor"] < 0 for e in debits)
    assert client.get("/api/finance/entries?direction=both", headers=h).status_code == 422
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
    g = groups[0]
    assert {k: g[k] for k in ("counterparty", "count", "total", "direction")} == {
        "counterparty": "jean exemple",
        "count": 2,
        "total": {"minor": -4000, "currency": "CHF", "display": "-40.00"},
        "direction": "debit",
    }
    assert len(g["entry_ids"]) == 2  # de quoi proposer une recatégorisation par écriture
    # de quoi décider sans ouvrir chaque écriture : comptes, période, fourchette, échantillon
    assert len(g["accounts"]) == 1
    assert g["first_date"] <= g["last_date"]
    assert abs(g["min"]["minor"]) <= abs(g["max"]["minor"])
    assert [s["id"] for s in g["samples"]] == g["entry_ids"]
    hits = client.get("/api/finance/search?q=EMPLOYEUR", headers=h).json()["items"]
    assert [x["counterparty"] for x in hits] == ["Employeur Fictif SA"]
    assert client.get("/api/finance/search?q=%20%20a%20%20", headers=h).status_code == 422
    # recherche transverse du cœur et résolution d'URN
    core = client.get("/api/search?q=employeur", headers=h).json()["items"]
    assert core[0]["domain"] == "finance"
    ref = client.get(f"/api/resolve?urn={core[0]['urn']}", headers=h).json()
    assert ref["href"].startswith("/finance/entries/")


def test_placeholder_counterparty_is_hidden(
    client: TestClient, ctx: HubContext, fin: FinanceDomain
) -> None:
    # BCF écrit « NOTPROVIDED » à la place du nom pour les paiements par carte et TWINT
    without_seed_rules(fin)
    ready_account(fin, 100_000)
    stmt = Stmt(
        opening=Decimal("1000.00"),
        opening_date=D,
        entries=[
            Tx("12.50", True, D, counterparty="NOTPROVIDED", label="Migros Fictif"),
            Tx("3.00", True, D, counterparty="NOTPROVIDED", label="Parking Fictif"),
            Tx("4.00", True, D, counterparty="Not Provided", label="Kiosque Fictif"),
        ],
    )
    fin.importer.process([Incoming("a.xml", camt053(stmt))])
    # le registre garde la valeur de la banque : elle entre dans la clé de dédoublonnage
    stored = rows(fin, "SELECT DISTINCT counterparty FROM entries WHERE kind = 'movement'")
    assert sorted(str(r[0]) for r in stored) == ["NOTPROVIDED", "Not Provided"]
    h = token(ctx, "brain")
    items = client.get("/api/finance/entries", headers=h).json()["items"]
    assert {e["counterparty"] for e in items if e["kind"] == "movement"} == {None}
    groups = client.get("/api/finance/review", headers=h).json()["groups"]
    assert sorted(g["counterparty"] for g in groups) == [
        "kiosque fictif",
        "migros fictif",
        "parking fictif",
    ]


def test_review_groups_card_payments_by_merchant(
    client: TestClient, ctx: HubContext, fin: FinanceDomain
) -> None:
    """Le commerçant est lu dans le libellé de carte BCF (la contrepartie est vide ou le nom du
    titulaire) ; un crédit classé par la règle « tout le reste » reste à confirmer ; l'ancien se
    classe d'un coup."""
    from hub.domains.finance.cli import propose_and_accept

    ready_account(fin, 100_000)
    with begin_immediate(fin.engine()) as conn:  # la règle « tout le reste » des crédits
        conn.execute(text("UPDATE rules SET active = 1 WHERE pattern = '' AND direction='credit'"))
    stmt = Stmt(
        opening=Decimal("1000.00"),
        opening_date=D,
        entries=[
            Tx(
                "12.50",
                True,
                D,
                counterparty="NOTPROVIDED",
                label="Paiement 02.10.2026 12:01 Zorglub Market Fribourg Numéro de carte: 1",
            ),
            Tx(
                "8.20",
                True,
                D,
                counterparty="NOTPROVIDED",
                label="Paiement 03.10.2026 18:44 Zorglub Market Bulle Numéro de carte: 1",
            ),
            Tx(
                "5.00",
                True,
                D,
                counterparty="Titulaire Fictif",
                label="Paiement - BIDULE SHOP, LAUSANNE - 10:00:00 - N° carte xxxx1234",
            ),
            Tx("50.00", False, D, counterparty="Ami Fictif", label="Crédit Ami Fictif"),
        ],
    )
    fin.importer.process([Incoming("a.xml", camt053(stmt))])
    h = token(ctx, "brain")
    groups = {
        g["counterparty"]: g for g in client.get("/api/finance/review", headers=h).json()["groups"]
    }
    assert groups["zorglub market"]["count"] == 2
    assert groups["zorglub market"]["guess"] is None
    assert "bidule shop" in groups
    assert "titulaire fictif" not in groups
    # crédit inconnu : « Autres revenus » d'office, à confirmer, après ce qui est sans catégorie
    assert groups["ami fictif"]["guess"] == "autres-revenus"
    order = [
        g["counterparty"] for g in client.get("/api/finance/review", headers=h).json()["groups"]
    ]
    assert order[-1] == "ami fictif"
    entries = client.get("/api/finance/entries", headers=h).json()["items"]
    assert {e["merchant"] for e in entries if e["kind"] == "movement"} >= {"zorglub market"}
    # « Toujours » sur le commerçant : la règle retrouve les deux achats
    done = propose_and_accept(
        fin,
        "create_rule",
        {
            "pattern": "zorglub market",
            "direction": "debit",
            "category_id": "loisirs",
            "priority": 4,
        },
    )
    assert done["changed"] == 2
    # tout ce qui reste d'avant une date, d'un coup (ici, la dernière dépense sans catégorie)
    after = (D + timedelta(days=1)).isoformat()
    rest = propose_and_accept(
        fin, "categorize_rest", {"before": after, "direction": "debit", "category_id": "loisirs"}
    )
    assert rest["changed"] == 1
    left = [
        g["counterparty"] for g in client.get("/api/finance/review", headers=h).json()["groups"]
    ]
    assert left == ["ami fictif"]


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
    assert r["domains"]["finance"] == {"db": "ok", "schema_version": 16, "ok": True}
    events = loaded.events_since(0, 10)
    assert [e.type for e in events] == ["entries.appended", "import.applied"]
    assert loaded.applied([]) == {}
    assert loaded.applied(["p"]) == {}
    assert loaded.resolve("hub:finance:nothing:1") is None
    (acc,) = client.get("/api/finance/accounts", headers=token(ctx, "brain")).json()["items"]
    assert loaded.resolve(f"hub:finance:account:{acc['id']}") is not None
    assert loaded.resolve(events[1].urn) is not None
    assert len(loaded.mcp_tools()) == 16  # lot 7, puis la catégorisation par lot


def test_viac_pdf_upload_and_holdings(
    client: TestClient, ctx: HubContext, fin: FinanceDomain
) -> None:
    from tests.factories import viac as v
    from tests.finance.test_viac import open_portfolio

    app_session(ctx, client)
    fin.importer.pdf_text = v.fake_text
    open_portfolio(fin)
    for name, txt in (
        ("versement.pdf", v.deposit(date(2026, 3, 2), "1000.00")),
        ("achat.pdf", v.buy(date(2026, 3, 5), "9.5", "950.00")),
    ):
        r = client.post(f"/api/finance/imports?name={name}", content=v.fake_pdf(txt))
        assert r.status_code == 202
        assert r.json()["items"][0]["status"] == "applied"
    bad = client.post("/api/finance/imports?name=x.pdf", content=b"%PDF-1.4\nautre")
    assert bad.status_code == 422
    h = client.get("/api/finance/holdings?on=2026-03-31", headers=token(ctx, "aggregates"))
    assert h.status_code == 200
    assert h.json()["value"]["minor"] == 95000
    assert (
        client.get("/api/finance/holdings?on=31.03.2026", headers=token(ctx, "brain")).status_code
        == 422
    )


def test_pending_accounts_then_created_from_a_proposal(
    ctx: HubContext, fin: FinanceDomain, client: TestClient
) -> None:
    """G5 : l'app liste les comptes que des relevés attendent (sans montant), puis la création
    validée ouvre un compte Revolut au solde déduit, comme `fin revolut add-account`."""
    from hub.domains.finance.cli import propose_and_accept
    from tests.finance.test_revolut import FIRST, drop, eb_file

    drop(fin, "revolut-a.json", eb_file(FIRST, full=True))
    reader = token(ctx, "finance:read")
    r = client.get("/api/finance/accounts/pending", headers=reader)
    assert r.status_code == 200
    assert r.json()["items"] == [
        {
            "ref": "revolut:CHF",
            "institution": "Revolut",
            "kind": "cash",
            "currency": "CHF",
            "imports": 1,
            "entries": 2,
            "from": "2026-10-20",
            "to": "2026-10-21",
            "can_open": True,
        }
    ]
    assert "1250" not in r.text
    assert (
        client.get(
            "/api/finance/accounts/pending", headers=token(ctx, "finance:aggregates")
        ).status_code
        == 403
    )
    propose_and_accept(
        fin,
        "create_account",
        {
            "institution": "Revolut",
            "name": "Revolut CHF",
            "currency": "CHF",
            "external_ref": "revolut:CHF",
            "liquid": True,
            "budget_account": True,
        },
    )
    with fin.engine().connect() as conn:
        total = conn.execute(text("SELECT sum(amount_minor) FROM entries")).scalar_one()
    assert total == 18750
    assert client.get("/api/finance/accounts/pending", headers=reader).json()["items"] == []
    accounts = client.get("/api/finance/accounts", headers=reader).json()["items"]
    assert accounts[0]["external_ref"] == "revolut:CHF"


def test_rule_packs_listed_then_installed_from_a_proposal(
    ctx: HubContext, fin: FinanceDomain, client: TestClient
) -> None:
    """G6 : les premiers pas proposent les packs du pays quand aucune règle n'est active ; la
    proposition validée les installe."""
    from hub.domains.finance.cli import propose_and_accept

    with begin_immediate(fin.engine()) as conn:
        conn.execute(text("DELETE FROM rules WHERE id LIKE 'pack-ch-%'"))
        conn.execute(text("DELETE FROM rule_packs WHERE name = 'ch'"))
    reader = token(ctx, "finance:read")
    body = client.get("/api/finance/rules/packs", headers=reader).json()
    assert body["suggested"] == ["base", "ch"]
    assert body["active_rules"] == 0
    found = {p["name"]: p for p in body["items"]}
    assert found["base"]["installed"] == found["base"]["version"]
    assert found["ch"]["installed"] is None
    assert found["ch"]["country"] == "CH"
    assert found["ch"]["rules"] > 0
    assert (
        client.get("/api/finance/rules/packs", headers=token(ctx, "finance:aggregates")).status_code
        == 403
    )
    result = propose_and_accept(fin, "install_pack", {"name": "ch"})
    assert result["added"] == found["ch"]["rules"]
    body = client.get("/api/finance/rules/packs", headers=reader).json()
    assert {p["name"]: p["installed"] for p in body["items"]}["ch"] == found["ch"]["version"]
    assert body["active_rules"] == found["ch"]["rules"]


def test_install_pack_refuses_an_unknown_pack(fin: FinanceDomain) -> None:
    import typer

    from hub.domains.finance.cli import propose_and_accept

    with pytest.raises(typer.Exit):
        propose_and_accept(fin, "install_pack", {"name": "atlantide"})
