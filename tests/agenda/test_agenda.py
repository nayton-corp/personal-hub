"""Domaine Agenda (S11) contre un faux pont Rappels/Calendrier : monté sans une ligne du cœur,
lectures au pont, ajouts et cases cochées par propositions à effet externe (idempotentes,
réconciliées), liste de courses au palier automatique, jamais de suppression."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import maintenance, proposals, tools
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.agenda.domain import AgendaDomain, id_of, ref_of
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.finance.test_finance_api import app_session

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)
TODAY = date(2026, 10, 30)


class FakeBridge:
    """Le pont (`assistant/eventkit`), en mémoire : ses routes, ses refus, aucune suppression."""

    def __init__(self) -> None:
        self.up = True
        self.allowed = True
        self.reminders = [
            {"id": "r1", "title": "Lait", "list": "Courses", "done": False, "due": None},
            {
                "id": "r2",
                "title": "Payer l'assurance",
                "list": "Rappels",
                "done": False,
                "due": "2026-10-28",
                "notes": "police ménage",
            },
        ]
        self.events = [
            {
                "id": "E1:X1",
                "title": "Dentiste",
                "start": "2026-11-02T09:00",
                "end": "2026-11-02T09:30",
                "calendar": "Maison",
            },
        ]
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        if not self.up:
            raise urllib.error.URLError("refused")
        parsed = urllib.parse.urlparse(url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        parts = [urllib.parse.unquote(p) for p in parsed.path.strip("/").split("/")]
        self.calls.append((method, parsed.path))
        body = json.loads(data) if data else {}
        if parts == ["health"]:
            return 200, json.dumps({"reminders": self.allowed, "calendar": self.allowed}).encode()
        if not self.allowed:
            return 403, b'{"error": "Rappels non autoris\\u00e9s"}'
        if method == "GET" and parts == ["reminders"]:
            found = [
                r
                for r in self.reminders
                if (query.get("list") in (None, r["list"]))
                and (query.get("done") == "1" or not r["done"])
            ]
            return 200, json.dumps(found).encode()
        if method == "POST" and parts == ["reminders"]:
            item = {
                "id": f"r{len(self.reminders) + 1}",
                "list": body.get("list") or "Rappels",
                "done": False,
                "due": body.get("due"),
                **body,
            }
            self.reminders.append(item)
            return 201, json.dumps(item).encode()
        if method == "POST" and parts[0] == "reminders" and parts[2] == "complete":
            for r in self.reminders:
                if r["id"] == parts[1]:
                    r["done"] = True
                    return 200, json.dumps(r).encode()
            return 404, b'{"error": "introuvable"}'
        if method == "GET" and parts == ["events"]:
            return 200, json.dumps(self.events).encode()
        if method == "POST" and parts == ["events"]:
            item = {"id": f"E{len(self.events) + 1}:X", **body}
            self.events.append(item)
            return 201, json.dumps(item).encode()
        return 404, b'{"error": "route inconnue"}'


@pytest.fixture
def bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def agenda(settings: Settings, bridge: FakeBridge, monkeypatch: pytest.MonkeyPatch) -> AgendaDomain:
    domain = AgendaDomain(settings, bridge)
    monkeypatch.setattr(domain, "today", lambda: TODAY)
    return domain


@pytest.fixture
def hub(settings: Settings, agenda: AgendaDomain) -> Iterator[HubContext]:
    ctx = HubContext.build(settings, Registry([agenda]))
    ctx.migrate_all()
    yield ctx
    ctx.dispose()


@pytest.fixture
def client(hub: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(hub), base_url="https://hub.example.ts.net") as c:
        app_session(hub, c)
        yield c


def test_the_home_lists_only_late_or_todays_reminders(
    client: TestClient, bridge: FakeBridge
) -> None:
    def due(rid: str, on: str) -> dict[str, object]:
        return {"id": rid, "title": rid, "list": "Rappels", "done": False, "due": on}

    bridge.reminders += [due("plus tard", "2026-12-01"), due("aujourd'hui", TODAY.isoformat())]
    o = client.get("/api/agenda/overview").json()
    assert [r["title"] for r in o["reminders"]] == ["Payer l'assurance", "aujourd'hui"]
    assert (o["open_reminders"], o["overdue"]) == (3, 1)  # « Lait » est une course


def test_reads_go_to_the_bridge(client: TestClient, bridge: FakeBridge) -> None:
    o = client.get("/api/agenda/overview").json()
    assert o["available"] is True
    assert [e["title"] for e in o["events"]] == ["Dentiste"]
    assert [r["title"] for r in o["reminders"]] == ["Payer l'assurance"]
    assert [s["title"] for s in o["shopping"]] == ["Lait"]
    assert o["overdue"] == 1
    counts = client.get("/api/agenda/counts").json()
    assert (counts["events"], counts["open_reminders"], counts["overdue"]) == (1, 1, 1)
    bridge.up = False
    assert client.get("/api/agenda/overview").json()["available"] is False
    assert client.get("/api/agenda/upcoming").json()["available"] is False
    assert client.get("/api/health").json()["domains"]["agenda"]["ok"] is True  # le Mac peut dormir


def test_aggregates_see_numbers_only(client: TestClient, make_token) -> None:  # type: ignore[no-untyped-def]
    token = bearer(make_token("agenda:aggregates"))
    assert client.get("/api/agenda/overview", headers=token).status_code == 403
    assert client.get("/api/agenda/counts", headers=token).json()["shopping"] == 1


def test_a_reminder_goes_through_a_card_once(hub: HubContext, bridge: FakeBridge) -> None:
    p, _ = proposals.create(
        hub, APP, "agenda", "add_reminder", {"title": "Vignette", "due": "2026-12-01"}
    )
    assert (p.tier, p.status) == ("human", "pending")
    assert p.preview["summary"] == "Rappel « Vignette » pour le 2026-12-01"
    assert not any(r["title"] == "Vignette" for r in bridge.reminders)
    (out,) = proposals.accept(hub, APP, [p], None)
    assert out.status == "applied"
    assert [r["title"] for r in bridge.reminders].count("Vignette") == 1
    # la même clé rejouée ne rajoute rien
    kind = hub.registry.get("agenda").proposal_kinds["add_reminder"]
    params = kind.params_model.model_validate(p.params)
    assert kind.handler.apply(params, f"{p.id}:1").status == "ok"  # type: ignore[call-arg, union-attr]
    assert [r["title"] for r in bridge.reminders].count("Vignette") == 1


def test_shopping_is_automatic_and_an_event_waits(hub: HubContext, bridge: FakeBridge) -> None:
    p, _ = proposals.create(hub, APP, "agenda", "add_shopping", {"title": "Beurre"})
    assert (p.tier, p.status) == ("auto", "applied")
    assert bridge.reminders[-1]["list"] == "Courses"
    e, _ = proposals.create(
        hub,
        APP,
        "agenda",
        "add_event",
        {"title": "Garage", "start": "2026-11-05T08:00", "end": "2026-11-05T09:00"},
    )
    assert (e.tier, e.status) == ("human", "pending")
    with pytest.raises(Exception, match=r"validation\.params"):  # la fin précède le début
        proposals.create(
            hub,
            APP,
            "agenda",
            "add_event",
            {"title": "x", "start": "2026-11-05T09:00", "end": "2026-11-05T08:00"},
        )


def test_ticking_off_and_a_refusal(hub: HubContext, bridge: FakeBridge) -> None:
    p, _ = proposals.create(
        hub, APP, "agenda", "complete_reminder", {"reminder_id": "r2", "title": "Payer l'assurance"}
    )
    assert proposals.accept(hub, APP, [p], None)[0].status == "applied"
    assert bridge.reminders[1]["done"] is True
    bridge.allowed = False
    q, _ = proposals.create(hub, APP, "agenda", "add_reminder", {"title": "Refusé"})
    out = proposals.accept(hub, APP, [q], None)[0]
    assert out.status == "failed"
    assert "non autoris" in out.result["error"]  # type: ignore[index]
    assert not any(m == "DELETE" for m, _ in bridge.calls)


def test_an_unknown_send_is_reconciled_with_the_bridge(hub: HubContext, bridge: FakeBridge) -> None:
    bridge.up = False
    p, _ = proposals.create(hub, APP, "agenda", "add_reminder", {"title": "Pneus"})
    assert proposals.accept(hub, APP, [p], None)[0].status == "unknown"
    bridge.up = True
    proposals.reconcile(hub)  # jamais parti : échec, pas appliqué
    with hub.core.engine.connect() as conn:
        assert proposals.get(conn, p.id).status == "failed"
    # parti mais réponse perdue : le pont le montre, la réconciliation l'applique
    q, _ = proposals.create(hub, APP, "agenda", "add_reminder", {"title": "Vidange"})
    real = bridge.__call__

    def lost(method: str, url: str, data: bytes | None) -> tuple[int, bytes]:
        real(method, url, data)
        raise urllib.error.URLError("coupé")

    agenda = hub.registry.get("agenda")
    agenda.bridge.transport = lost  # type: ignore[attr-defined]
    assert proposals.accept(hub, APP, [q], None)[0].status == "unknown"
    agenda.bridge.transport = real  # type: ignore[attr-defined]
    proposals.reconcile(hub)
    with hub.core.engine.connect() as conn:
        assert proposals.get(conn, q.id).status == "applied"
    assert [r["title"] for r in bridge.reminders].count("Vidange") == 1


def test_tools_search_resolve_and_observations(hub: HubContext, make_token) -> None:  # type: ignore[no-untyped-def]
    agenda = hub.registry.get("agenda")
    names = {t.name for t in agenda.mcp_tools()}
    assert {"agenda_upcoming", "agenda_counts", "agenda_add_shopping"} <= names
    model = Principal("token:t", frozenset({"agenda:aggregates", "agenda:propose"}))
    assert {t.name for t in tools.visible_tools(model, agenda)} >= {
        "agenda_counts",
        "agenda_add_shopping",
    }
    assert "agenda_upcoming" not in {t.name for t in tools.visible_tools(model, agenda)}
    out = tools.call(hub, model, "agenda", "agenda_add_shopping", {"title": "Pain"})
    assert out["status"] == "pending"  # un modèle reste à la carte (texte externe possible)
    (hit,) = agenda.search("dent", 10, frozenset({"app"}))
    assert hit.title == "Dentiste"
    assert id_of(hit.urn.rsplit(":", 1)[1]) == "E1:X1"
    ref = agenda.resolve(hit.urn)
    assert ref is not None
    assert ref.date == "2026-11-02"
    (found,) = agenda.search("ménage", 10, frozenset({"app"}))
    assert found.excerpt == "police ménage"
    assert agenda.resolve(f"hub:agenda:reminder:{ref_of('absent')}") is None
    (seen,) = agenda.observations(5)
    assert (seen.kind, seen.title) == ("overdue", "1 rappel en retard")


def test_verify_and_the_cli(hub: HubContext, bridge: FakeBridge) -> None:
    report = maintenance.verify(hub)
    assert report.checks["agenda.verify"] == "ok", report.checks
    assert report.checks["agenda.protected"] == "ok"
    agenda = hub.registry.get("agenda")
    assert agenda.bridge_status() == {"bridge": "ok", "reminders": True, "calendar": True}  # type: ignore[attr-defined]
    with agenda.engine().connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM sent")).scalar_one() == 0
    from typer.testing import CliRunner

    cli = agenda.cli()
    assert cli is not None
    assert CliRunner().invoke(cli, ["status"]).exit_code == 0
    bridge.up = False
    assert CliRunner().invoke(cli, ["status"]).exit_code == 1
