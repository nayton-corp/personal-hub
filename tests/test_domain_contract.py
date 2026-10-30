"""Un domaine factice apparaît dans l'API, la recherche, la santé et la nuit sans toucher au
cœur ; le registre refuse ce qui ne respecte pas le contrat."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.domain import ProposalKind
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.support.demo_domain import AddItem, AddItemHandler, DemoDomain


def _add_item(demo: DemoDomain, name: str) -> int:
    with demo.engine().begin() as conn:
        return int(
            conn.execute(
                text(
                    "INSERT INTO items (name, created_at) VALUES "
                    "(:n, '2026-10-27T10:00:00.000Z') RETURNING seq"
                ),
                {"n": name},
            ).scalar_one()
        )


def test_search_resolve_links(
    client: TestClient,
    make_token,
    hub: HubContext,  # type: ignore[no-untyped-def]
    demo: DemoDomain,
) -> None:
    seq = _add_item(demo, "abonnement cff")
    token = make_token("demo:read")
    r = client.get("/api/search?q=cff", headers=bearer(token))
    assert r.json()["items"] == [
        {
            "domain": "demo",
            "rank": 1,
            "urn": f"hub:demo:item:{seq}",
            "title": "abonnement cff",
            "date": "2026-10-27",
            "excerpt": "abonnement cff",
        }
    ]
    assert client.get("/api/search?q=ab", headers=bearer(token)).status_code == 422
    r = client.get(f"/api/resolve?urn=hub:demo:item:{seq}", headers=bearer(token))
    assert r.json()["href"] == f"/demo/items/{seq}"
    assert (
        client.get("/api/resolve?urn=hub:demo:item:999", headers=bearer(token)).status_code == 404
    )
    assert client.get("/api/resolve?urn=bad", headers=bearer(token)).status_code == 422
    assert client.get("/api/resolve?urn=hub:other:x:1", headers=bearer(token)).status_code == 404
    assert (
        client.get(
            f"/api/resolve?urn=hub:demo:item:{seq}", headers=bearer(make_token("demo:aggregates"))
        ).status_code
        == 403
    )
    other = _add_item(demo, "billet")
    with hub.core.engine.begin() as conn:
        for active in (1, 0, 1):
            conn.execute(
                text(
                    "INSERT INTO links (from_urn, to_urn, rel, active, created_by, created_at) "
                    "VALUES (:a, :b, 'pays', :act, 'system:test', 'x')"
                ),
                {"a": f"hub:demo:item:{seq}", "b": f"hub:demo:item:{other}", "act": active},
            )
        conn.execute(
            text(
                "INSERT INTO links (from_urn, to_urn, rel, active, created_by, created_at) "
                "VALUES (:a, 'hub:ghost:x:1', 'same_as', 1, 'system:test', 'x')"
            ),
            {"a": f"hub:demo:item:{seq}"},
        )
    r = client.get(f"/api/links?urn=hub:demo:item:{other}", headers=bearer(token)).json()
    assert r["outgoing"] == []
    assert [(x["rel"], x["other"]["title"]) for x in r["incoming"]] == [("pays", "abonnement cff")]
    r = client.get(f"/api/links?urn=hub:demo:item:{seq}", headers=bearer(token)).json()
    assert [(x["rel"], x["other"]) for x in r["outgoing"]][1] == ("same_as", None)


def test_registry_rules(settings: Settings, tmp_path: Path) -> None:
    demo = DemoDomain(tmp_path)
    reg = Registry([demo])
    assert reg.names() == ["demo"]
    assert len(reg) == 1
    assert "demo:read" in reg.all_scopes()
    with pytest.raises(ValueError, match="déjà"):
        reg.add(DemoDomain(tmp_path / "b"))
    with pytest.raises(TypeError):
        reg.add(object())  # type: ignore[arg-type]
    rogue = DemoDomain(tmp_path / "c")
    rogue.name = "rogue"  # type: ignore[misc]
    with pytest.raises(ValueError, match="hors du domaine"):
        reg.add(rogue)
    with pytest.raises(Problem):
        reg.get("ghost")
    assert Registry.discover(settings).names() == [
        "agenda",
        "finance",
    ]  # point d'entrée hub.domains


def test_reversible_kind_needs_inverse() -> None:
    with pytest.raises(ValueError, match="inverse"):
        ProposalKind(params_model=AddItem, handler=AddItemHandler(), reversible=True)


def test_degraded_health(client: TestClient, demo: DemoDomain) -> None:
    demo.path.unlink()
    r = client.get("/api/health").json()
    assert r["status"] == "degraded"
    assert r["domains"]["demo"]["db"] == "missing"


def test_mcp_tools_are_declared(demo: DemoDomain) -> None:
    (tool,) = demo.mcp_tools()
    assert tool.scope == "demo:read"
