"""L3-02 et L3-04 côté API : types de proposition Finance, conflits, inverses, imports en
attente, validation par passkey qui met à jour les totaux."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.domains.finance import ledger
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.importer import Incoming
from tests.factories.camt import IBAN, IBAN_2, Stmt, Tx, camt053
from tests.finance.conftest import finance_settings, ready_account, rows
from tests.finance.test_finance_api import token
from tests.support.soft_authenticator import SoftAuthenticator
from tests.test_passkeys import ORIGIN, _code, _register

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)
D = date(2026, 10, 1)


@pytest.fixture
def ctx(tmp_path: Path) -> Iterator[HubContext]:
    s = finance_settings(tmp_path)
    hub = HubContext.build(s, Registry([FinanceDomain(s)]))
    hub.migrate_all()
    yield hub
    hub.dispose()


@pytest.fixture
def fin(ctx: HubContext) -> FinanceDomain:
    d = ctx.registry.get("finance")
    assert isinstance(d, FinanceDomain)
    return d


@pytest.fixture
def client(ctx: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(ctx), base_url="https://hub.example.ts.net") as c:
        yield c


@pytest.fixture
def phone(client: TestClient, ctx: HubContext) -> SoftAuthenticator:
    auth = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    assert _register(client, auth, _code(ctx)).status_code == 200
    return auth


def load(
    fin: FinanceDomain, txs: list[Tx], opening: str = "1000.00", on: date = D, **kw: Any
) -> None:
    data = camt053(Stmt(Decimal(opening), on, txs, **kw))
    fin.importer.process([Incoming(f"{kw.get('stmt_id', 's')}.xml", data)])


def entry_id(fin: FinanceDomain, counterparty: str) -> str:
    ((value,),) = rows(fin, "SELECT id FROM entries WHERE counterparty = :c", c=counterparty)
    return str(value)


def current(fin: FinanceDomain, counterparty: str) -> tuple[Any, ...]:
    return rows(
        fin,
        "SELECT vc.category_id, vc.source FROM entries e LEFT JOIN v_entry_category vc "
        "ON vc.entry_seq = e.seq WHERE e.counterparty = :c",
        c=counterparty,
    )[0]


def create(ctx: HubContext, kind: str, params: dict[str, Any]) -> proposals.Proposal:
    p, _ = proposals.create(ctx, APP, "finance", kind, params)
    return p


def accept(ctx: HubContext, p: proposals.Proposal) -> proposals.Outcome:
    return proposals.accept_one(ctx, APP, p, None)


def signed_accept(
    client: TestClient, phone: SoftAuthenticator, ids: list[str]
) -> list[dict[str, Any]]:
    ch = client.post("/api/approvals/challenge", json={"proposal_ids": ids}).json()
    r = client.post(
        "/api/proposals/accept",
        json={
            "proposal_ids": ids,
            "challenge_id": ch["challenge_id"],
            "assertion": phone.sign(ch["options"]),
        },
    )
    assert r.status_code == 200, r.text
    results: list[dict[str, Any]] = r.json()["results"]
    return results


# --- recategorize (critère d'acceptation de L3-04) --------------------------------------------


def test_suggested_recategorization_updates_totals(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, phone: SoftAuthenticator
) -> None:
    acc = ready_account(fin)
    with fin.engine().begin() as conn:
        conn.execute(text("UPDATE accounts SET budget_account = 1 WHERE id = :i"), {"i": acc.id})
    load(fin, [Tx("120.00", True, D, counterparty="Zorglub Fictif", label="Achat")])
    review = client.get("/api/finance/review").json()["groups"]
    assert review[0]["counterparty"] == "zorglub fictif"
    before = client.get("/api/finance/summary?month=2026-10").json()
    assert before["uncategorized"]["minor"] == -12_000
    # le « brain » propose, l'iPhone valide
    brain = token(ctx, "brain")
    r = client.post(
        "/api/proposals",
        json={
            "domain": "finance",
            "kind": "recategorize",
            "params": {
                "entry_id": entry_id(fin, "Zorglub Fictif"),
                "category_id": "loisirs",
                "suggested": True,
            },
        },
        headers=brain,
    )
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["preview"]["summary"] == "1 écriture → Loisirs et sport (-120.00 CHF)"
    (res,) = signed_accept(client, phone, [card["id"]])
    assert res["status"] == "applied"
    after = client.get("/api/finance/summary?month=2026-10").json()
    assert after["uncategorized"]["minor"] == 0
    lines = {x["category"]: x["total"]["minor"] for x in after["by_category"]}
    assert lines["loisirs"] == -12_000
    assert current(fin, "Zorglub Fictif") == ("loisirs", "suggestion_accepted")
    assert client.get("/api/finance/review").json()["groups"] == []
    assert fin.verify_ledger().ok


def test_recategorize_split_and_revert(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, phone: SoftAuthenticator
) -> None:
    ready_account(fin)
    load(fin, [Tx("100.00", True, D, counterparty="Migros Fictif")])
    eid = entry_id(fin, "Migros Fictif")
    assert current(fin, "Migros Fictif") == ("alimentation", "rule")
    bad = {"entry_id": eid, "category_id": "shopping"}
    with pytest.raises(Problem):
        create(
            ctx,
            "recategorize",
            bad
            | {
                "lines": [
                    {"category_id": "shopping", "amount_minor": -1},
                    {"category_id": "alimentation", "amount_minor": -2},
                ]
            },
        )
    with pytest.raises(Problem):
        create(ctx, "recategorize", bad | {"category_id": "nope"})
    with pytest.raises(Problem):
        create(ctx, "recategorize", {"entry_id": "e00", "category_id": "shopping"})
    split = [
        {"category_id": "shopping", "amount_minor": -7_000},
        {"category_id": "alimentation", "amount_minor": -3_000},
    ]
    p = create(ctx, "recategorize", bad | {"lines": split})
    assert "ventilée en 2" in p.preview["summary"]
    out = accept(ctx, p)
    assert out.result is not None
    assert out.result["previous_category"] == "alimentation"
    alloc = rows(
        fin,
        "SELECT category_id, amount_minor FROM v_entry_allocation ORDER BY amount_minor",
    )
    assert ("shopping", -7_000) in alloc
    assert ("alimentation", -3_000) in alloc
    # inverse d'un geste, signé
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, p.id)
    ch = client.post(
        "/api/approvals/challenge", json={"proposal_ids": [p.id], "action": "revert"}
    ).json()
    body = {"challenge_id": ch["challenge_id"], "assertion": phone.sign(ch["options"])}
    r = client.post(f"/api/proposals/{p.id}/revert", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["results"][0]["status"] == "applied"
    assert current(fin, "Migros Fictif") == ("alimentation", "user")
    # une seconde annulation est refusée
    r = client.post(f"/api/proposals/{p.id}/revert", json=body)
    assert (r.status_code, r.json()["type"]) == (409, "proposal.not_reversible")


def test_first_categorization_has_no_inverse(ctx: HubContext, fin: FinanceDomain) -> None:
    ready_account(fin)
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")])
    p = create(
        ctx, "recategorize", {"entry_id": entry_id(fin, "Zorglub Fictif"), "category_id": "divers"}
    )
    accept(ctx, p)
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, p.id)
    with pytest.raises(Problem) as exc:
        proposals.inverse_of(ctx, p)
    assert exc.value.type == "proposal.not_reversible"


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.integers(1, 50_000), min_size=2, max_size=6))
def test_split_lines_sum_to_the_entry(
    ctx: HubContext, fin: FinanceDomain, parts: list[int]
) -> None:
    """Propriété : la ventilation somme toujours au montant de l'écriture."""
    if not rows(fin, "SELECT 1 FROM accounts"):
        ready_account(fin, 10_000_000)
        load(fin, [Tx("5000.00", True, D, counterparty="Grand Achat Fictif")], opening="100000.00")
    eid = entry_id(fin, "Grand Achat Fictif")
    total = -500_000
    amounts = [-x for x in parts[:-1]]
    rest = total - sum(amounts)
    if rest >= 0:
        return
    lines = [{"category_id": "divers", "amount_minor": a} for a in [*amounts, rest]]
    accept(
        ctx, create(ctx, "recategorize", {"entry_id": eid, "category_id": "divers", "lines": lines})
    )
    ((alloc,),) = rows(
        fin,
        "SELECT sum(amount_minor) FROM v_entry_allocation WHERE amount_minor < 0 "
        "AND entry_seq = (SELECT seq FROM entries WHERE id = :i)",
        i=eid,
    )
    assert alloc == total


# --- règles ---------------------------------------------------------------------------------


def test_create_rule_conflict_when_an_import_lands(ctx: HubContext, fin: FinanceDomain) -> None:
    """Critère de L3-02 : import inséré entre aperçu et validation -> 409 et nouvelle révision."""
    ready_account(fin)
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")], stmt_id="S1")
    p = create(
        ctx, "create_rule", {"pattern": "zorglub", "category_id": "loisirs", "direction": "debit"}
    )
    assert p.preview["details"]["count"] == 1
    closing = Decimal("990.00")
    load(
        fin,
        [Tx("15.00", True, date(2026, 10, 5), counterparty="Zorglub Fictif Bis")],
        opening=str(closing),
        on=date(2026, 10, 5),
        stmt_id="S2",
    )
    with pytest.raises(Problem) as exc:
        accept(ctx, p)
    assert exc.value.type == "conflict.state_changed"
    assert exc.value.extra["proposal"]["revision"] == 2
    assert exc.value.extra["proposal"]["preview"]["details"]["count"] == 2
    with ctx.core.engine.connect() as conn:
        p = proposals.get(conn, p.id)
    out = accept(ctx, p)
    assert out.result is not None
    assert out.result["changed"] == 2
    assert current(fin, "Zorglub Fictif Bis")[0] == "loisirs"
    rule_id = out.result["rule_id"]
    assert rule_id.startswith("user-")
    # les écritures suivantes sont catégorisées à l'import
    load(
        fin,
        [Tx("5.00", True, date(2026, 10, 9), counterparty="Zorglub Ter")],
        opening="975.00",
        on=date(2026, 10, 9),
        stmt_id="S3",
    )
    assert current(fin, "Zorglub Ter")[0] == "loisirs"
    # désactiver : les catégorisations faites restent, les nouvelles ne suivent plus
    d = create(ctx, "disable_rule", {"rule_id": rule_id})
    assert d.preview["details"]["categorizations_kept"] == 3
    accept(ctx, d)
    load(
        fin,
        [Tx("4.00", True, date(2026, 10, 12), counterparty="Zorglub Quater")],
        opening="970.00",
        on=date(2026, 10, 12),
        stmt_id="S4",
    )
    assert current(fin, "Zorglub Quater")[0] is None
    assert current(fin, "Zorglub Ter")[0] == "loisirs"
    with pytest.raises(Problem):
        create(ctx, "disable_rule", {"rule_id": rule_id})
    with pytest.raises(Problem):
        create(ctx, "disable_rule", {"rule_id": "system-transfer-own"})
    with pytest.raises(Problem):
        create(ctx, "create_rule", {"pattern": "a", "category_id": "loisirs"})
    iban = create(
        ctx,
        "create_rule",
        {"field": "counterparty_iban", "pattern": IBAN_2, "category_id": "loisirs"},
    )
    assert "CH56…009" in iban.preview["summary"]


def test_rule_never_takes_a_human_decision(ctx: HubContext, fin: FinanceDomain) -> None:
    ready_account(fin)
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")])
    accept(
        ctx,
        create(
            ctx,
            "recategorize",
            {"entry_id": entry_id(fin, "Zorglub Fictif"), "category_id": "cadeaux"},
        ),
    )
    p = create(ctx, "create_rule", {"pattern": "zorglub", "category_id": "loisirs", "priority": 1})
    assert p.preview["details"]["count"] == 0
    out = accept(ctx, p)
    assert out.result is not None
    assert out.result["changed"] == 0
    assert current(fin, "Zorglub Fictif") == ("cadeaux", "user")


# --- budget, notes, catégories, comptes ------------------------------------------------------


def test_set_budget_and_inverse(client: TestClient, ctx: HubContext, fin: FinanceDomain) -> None:
    p = create(
        ctx,
        "set_budget",
        {"category_id": "alimentation", "monthly_minor": 60_000, "valid_from": "2026-10-01"},
    )
    assert p.preview["summary"] == "Budget Alimentation : 600.00 CHF par mois, dès 2026-10"
    accept(ctx, p)
    q = create(
        ctx,
        "set_budget",
        {"category_id": "alimentation", "monthly_minor": 50_000, "valid_from": "2026-10-01"},
    )
    assert "avant 600.00 CHF" in q.preview["summary"]
    accept(ctx, q)
    with ctx.core.engine.connect() as conn:
        q = proposals.get(conn, q.id)
    kind, params = proposals.inverse_of(ctx, q)
    assert (kind, params["monthly_minor"]) == ("set_budget", 60_000)
    proposals.revert(ctx, APP, q, None)
    assert rows(fin, "SELECT monthly_minor FROM budgets ORDER BY seq DESC LIMIT 1") == [(60_000,)]
    with pytest.raises(Problem):
        create(ctx, "set_budget", {"category_id": "salaire", "monthly_minor": 1})
    default = create(ctx, "set_budget", {"category_id": "loisirs", "monthly_minor": 1})
    assert default.preview["details"]["valid_from"] == fin.today().replace(day=1).isoformat()


def test_add_note_is_searchable(ctx: HubContext, fin: FinanceDomain) -> None:
    ready_account(fin)
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")])
    eid = entry_id(fin, "Zorglub Fictif")
    p = create(ctx, "add_note", {"entry_id": eid, "text": "Anniversaire de Léa"})
    out = accept(ctx, p)
    assert out.result is not None
    assert out.result["entry_id"] == eid
    hits = rows(fin, "SELECT rowid FROM notes_fts WHERE notes_fts MATCH '\"anniversaire\"'")
    assert len(hits) == 1
    again = create(ctx, "add_note", {"entry_id": eid, "text": "Anniversaire de Léa"})
    assert again.id != p.id  # la première est appliquée : une nouvelle carte


def test_create_category_and_account_kinds(
    client: TestClient, ctx: HubContext, fin: FinanceDomain
) -> None:
    c = create(ctx, "create_category", {"id": "voiture", "name": "Voiture", "grp": "variable"})
    assert accept(ctx, c).status == "applied"
    with pytest.raises(Problem):
        create(ctx, "create_category", {"id": "voiture", "name": "Encore", "grp": "variable"})
    assert "voiture" in {
        c["id"]
        for c in client.get("/api/finance/categories", headers=token(ctx, "brain")).json()["items"]
    }
    # un modèle ne crée ni compte ni catégorie
    r = client.post(
        "/api/proposals",
        json={
            "domain": "finance",
            "kind": "create_account",
            "params": {"institution": "BCF", "name": "x", "iban": IBAN},
        },
        headers=token(ctx, "brain"),
    )
    assert (r.status_code, r.json()["type"]) == (403, "proposal.kind_not_allowed")
    with pytest.raises(Problem):
        create(ctx, "create_account", {"institution": "BCF", "name": "Sans clé"})
    v = create(
        ctx,
        "create_account",
        {"institution": "VIAC", "name": "3a", "kind": "pension", "external_ref": "viac-1"},
    )
    accept(ctx, v)
    with pytest.raises(Problem):
        create(
            ctx, "create_account", {"institution": "VIAC", "name": "3a", "external_ref": "viac-1"}
        )


def test_create_account_replays_waiting_statements(ctx: HubContext, fin: FinanceDomain) -> None:
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")])
    assert rows(fin, "SELECT status FROM imports") == [("needs_review",)]
    # compte inconnu : rien qu'une validation puisse lever, donc aucune carte apply_import
    proposals.sync_events(ctx)
    with ctx.core.engine.connect() as conn:
        assert proposals.list_by_status(conn, "pending") == []
    p = create(ctx, "create_account", {"institution": "BCF", "name": "Privé", "iban": IBAN})
    assert p.preview["details"]["waiting_statements"] == 1
    assert "relancé" in p.preview["summary"]
    accept(ctx, p)
    reasons = rows(fin, "SELECT reasons_json FROM import_statements")
    assert reasons == [('["no_opening"]',)]  # relancé ; il manque encore l'ouverture
    with pytest.raises(Problem):
        create(ctx, "create_account", {"institution": "BCF", "name": "Encore", "iban": IBAN})


# --- imports en attente ----------------------------------------------------------------------


def test_apply_import_card_validates_the_gap(
    client: TestClient, ctx: HubContext, fin: FinanceDomain, phone: SoftAuthenticator
) -> None:
    a = ready_account(fin, 100_000)  # ouvert au 30 septembre à 1000
    octo = camt053(
        Stmt(
            Decimal("900.00"),
            D,
            [Tx("50.00", True, date(2026, 10, 3), counterparty="Migros Fictif")],
        )
    )
    # octobre annonce 900 d'ouverture : le registre dit 1000 -> en attente, carte demandée
    fin.importer.process([Incoming("oct.xml", octo)])
    assert rows(fin, "SELECT status FROM imports") == [("needs_review",)]
    listed = client.get("/api/proposals").json()["items"]
    (card,) = [p for p in listed if p["kind"] == "apply_import"]
    assert card["preview"]["details"]["reasons"] == ["ledger_check_failed"]
    assert card["preview"]["details"]["count"] == 1
    assert card["expires_at"] > card["created_at"]
    import_id = card["params"]["import_id"]
    assert client.get(f"/api/finance/imports/{import_id}").json()["proposal_id"] == card["id"]
    # la tâche de nuit redemande la carte : pas de doublon
    fin.nightly()
    assert proposals.sync_events(ctx)["requested"] == 0
    (res,) = signed_accept(client, phone, [card["id"]])
    assert res["status"] == "applied", res
    assert res["result"]["new"] == 1
    assert rows(fin, "SELECT status, stats_json LIKE '%ledger_check_failed%' FROM imports") == [
        ("applied", 1)
    ]
    assert current(fin, "Migros Fictif")[0] == "alimentation"  # règles appliquées aussi
    assert fin.verify_ledger().ok
    assert a.id


def test_apply_import_becomes_obsolete_when_the_gap_fills(
    ctx: HubContext, fin: FinanceDomain
) -> None:
    acc = ready_account(fin, 100_000)
    sept = camt053(
        Stmt(
            Decimal("1000.00"),
            D,
            [Tx("100.00", True, date(2026, 10, 3), counterparty="Coop Fictif")],
            stmt_id="A",
        )
    )
    octo = camt053(
        Stmt(
            Decimal("900.00"),
            date(2026, 10, 10),
            [Tx("50.00", True, date(2026, 10, 12), counterparty="Migros Fictif")],
            stmt_id="B",
        )
    )
    fin.importer.process([Incoming("b.xml", octo)])
    proposals.sync_events(ctx)
    with ctx.core.engine.connect() as conn:
        (card,) = proposals.list_by_status(conn, "pending")
    # le relevé manquant arrive : le second s'applique seul, la carte devient sans objet
    fin.importer.process([Incoming("a.xml", sept)])
    assert rows(fin, "SELECT status FROM imports ORDER BY received_at") == [
        ("applied",),
        ("applied",),
    ]
    assert proposals.sync_events(ctx)["obsoleted"] == 1
    with ctx.core.engine.connect() as conn:
        assert proposals.get(conn, card.id).status == "obsolete"
    assert acc.id


def test_apply_import_refusals(ctx: HubContext, fin: FinanceDomain) -> None:
    with pytest.raises(Problem) as exc:
        create(ctx, "apply_import", {"import_id": "01NOPE000000000000000000"})
    assert exc.value.type == "import.not_found"
    ready_account(fin)
    load(fin, [Tx("10.00", True, D, counterparty="Zorglub Fictif")])
    ((import_id,),) = rows(fin, "SELECT id FROM imports")
    with pytest.raises(Problem) as exc:
        create(ctx, "apply_import", {"import_id": import_id})
    assert exc.value.type == "import.not_applicable"


def test_events_record_applied_proposals(ctx: HubContext, fin: FinanceDomain) -> None:
    p = create(ctx, "create_category", {"id": "jardin", "name": "Jardin", "grp": "variable"})
    accept(ctx, p)
    assert fin.applied([p.id]) == {p.id: {"category_id": "jardin"}}
    types = [e.type for e in fin.events_since(0, 50)]
    assert "proposal.applied" in types
    with pytest.raises(Exception, match=r"ledger\.append_only"), fin.engine().begin() as conn:
        conn.execute(text("DELETE FROM applied_proposals"))
    assert ledger
