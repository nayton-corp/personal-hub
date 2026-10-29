"""Chantier S9 : une recherche sur deux domaines fusionnée par rang, avec passage et
provenance ; un lien entre deux domaines créé par une carte ; les constats de chaque domaine
réunis par `GET /api/observations`."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from hub.api.app import create_app
from hub.core import links, maintenance, proposals, search
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Hit
from hub.core.manifest import Manifest
from hub.core.registry import Registry
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.support.demo_domain import DemoDomain
from tests.support.soft_authenticator import SoftAuthenticator
from tests.test_accept import sign
from tests.test_passkeys import ORIGIN, _code, _register

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)


class OtherDomain(DemoDomain):
    """Un second domaine, aux scores sur une tout autre échelle."""

    name = "other"
    scopes = frozenset({"other:read", "other:propose", "other:aggregates"})

    def manifest(self) -> Manifest:
        return Manifest(description="Un autre domaine factice.")

    def search(self, q: str, limit: int, scopes: frozenset[str]) -> list[Hit]:
        return [
            Hit(h.urn, h.title, h.date, h.score // 2, h.excerpt)
            for h in super().search(q, limit, scopes)
        ]


def add(domain: DemoDomain, name: str) -> str:
    with domain.engine().begin() as conn:
        seq = conn.execute(
            text(
                "INSERT INTO items (name, created_at) VALUES (:n, '2026-10-27T10:00:00.000Z') "
                "RETURNING seq"
            ),
            {"n": name},
        ).scalar_one()
    return f"hub:{domain.name}:item:{seq}"


@pytest.fixture
def two(settings: Settings) -> Iterator[tuple[HubContext, DemoDomain, OtherDomain]]:
    demo, other = DemoDomain(settings.paths.data), OtherDomain(settings.paths.data)
    hub = HubContext.build(settings, Registry([demo, other]))
    hub.migrate_all()
    yield hub, demo, other
    hub.dispose()


@pytest.fixture
def api(two: tuple[HubContext, DemoDomain, OtherDomain]) -> Iterator[TestClient]:
    with TestClient(create_app(two[0]), base_url="https://hub.example.ts.net") as c:
        yield c


def test_fusion_keeps_ranks_not_raw_scores() -> None:
    a = [Hit("hub:a:x:1", "a1", "2026-10-01", 9000), Hit("hub:a:x:2", "a2", "2026-10-02", 8000)]
    b = [Hit("hub:b:x:1", "b1", "2026-10-03", 2), Hit("hub:b:x:2", "b2", None, 1)]
    found = search.fuse({"a": a, "b": b}, 10)
    assert [f.hit.title for f in found] == ["b1", "a1", "a2", "b2"]
    assert [(f.domain, f.rank) for f in found[:2]] == [("b", 1), ("a", 1)]
    assert len(search.fuse({"a": a, "b": b}, 1)) == 1


def test_excerpt_centres_on_the_match() -> None:
    long = "Paiement carte " + "x" * 100 + " abonnement CFF demi-tarif " + "y" * 100
    cut = search.excerpt([None, long], "cff", width=40)
    assert cut is not None
    assert "CFF" in cut
    assert cut.startswith("…")
    assert cut.endswith("…")
    assert search.excerpt(["court"], "absent") == "court"
    assert search.excerpt([None, "  "], "cff") is None


def test_search_over_two_domains_no_longer_favours_the_shortest(
    api: TestClient, two: tuple[HubContext, DemoDomain, OtherDomain], make_token
) -> None:  # type: ignore[no-untyped-def]
    _, demo, other = two
    for name in ("cff", "cff b", "cff bc"):
        add(demo, name)
    for name in ("abonnement cff demi-tarif", "carte journalière cff"):
        add(other, name)
    token = make_token("demo:read", "other:read")
    items = api.get("/api/search?q=cff", headers=bearer(token)).json()["items"]
    # les scores bruts de « demo » écrasent ceux de « other » ; la fusion alterne les domaines
    assert [(i["domain"], i["rank"]) for i in items] == [
        ("demo", 1),
        ("other", 1),
        ("demo", 2),
        ("other", 2),
        ("demo", 3),
    ]
    assert items[1]["excerpt"] == "carte journalière cff"
    only = api.get("/api/search?q=cff", headers=bearer(make_token("other:read"))).json()
    assert {i["domain"] for i in only["items"]} == {"other"}


def test_a_link_between_two_domains_goes_through_a_card(
    api: TestClient, two: tuple[HubContext, DemoDomain, OtherDomain]
) -> None:
    hub, demo, other = two
    phone = SoftAuthenticator("hub.example.ts.net", ORIGIN)
    assert _register(api, phone, _code(hub)).status_code == 200
    a, b = add(demo, "facture du vélo"), add(other, "vélo")
    r = api.post(
        "/api/proposals",
        json={"domain": "core", "kind": "link", "params": {"from_urn": a, "to_urn": b}},
    )
    assert r.status_code == 201, r.text
    card = r.json()
    assert card["preview"]["summary"] == "Lier « facture du vélo » et « vélo »"
    assert api.get(f"/api/links?urn={a}").json()["outgoing"] == []  # rien avant le Face ID
    signed = sign(api, phone, [card["id"]])
    r = api.post("/api/proposals/accept", json={"proposal_ids": [card["id"]], **signed})
    assert r.json()["results"][0]["status"] == "applied", r.text
    (out,) = api.get(f"/api/links?urn={a}").json()["outgoing"]
    assert (out["to_urn"], out["rel"], out["other"]["title"]) == (b, "about", "vélo")
    assert api.get(f"/api/links?urn={b}").json()["incoming"][0]["from_urn"] == a
    assert maintenance.verify(hub).checks["core.ledger"] == "ok"
    # l'inverse délie, d'un geste
    signed = sign(api, phone, [card["id"]], action="revert")
    r = api.post(f"/api/proposals/{card['id']}/revert", json=signed)
    assert r.status_code == 200, r.text
    assert api.get(f"/api/links?urn={a}").json()["outgoing"] == []


def test_a_link_needs_two_existing_objects_the_token_can_read(
    api: TestClient, two: tuple[HubContext, DemoDomain, OtherDomain], make_token
) -> None:  # type: ignore[no-untyped-def]
    hub, demo, other = two
    a, b = add(demo, "reçu"), add(other, "objet")
    with pytest.raises(Exception, match="introuvable"):
        proposals.create(hub, APP, "core", "link", {"from_urn": a, "to_urn": "hub:other:item:999"})
    with pytest.raises(Exception, match="lui-même"):
        proposals.create(hub, APP, "core", "link", {"from_urn": a, "to_urn": a})
    with pytest.raises(Exception):  # noqa: B017, PT011 - « reverts » est réservé
        proposals.create(hub, APP, "core", "link", {"from_urn": a, "to_urn": b, "rel": "reverts"})
    body = {"domain": "core", "kind": "link", "params": {"from_urn": a, "to_urn": b}}
    blind = bearer(make_token("demo:read", "core:propose"))
    assert api.post("/api/proposals", json=body, headers=blind).status_code == 403
    both = bearer(make_token("demo:read", "other:read", "core:propose"))
    r = api.post("/api/proposals", json=body, headers=both)
    assert r.status_code == 201, r.text
    assert r.json()["tier"] == "human"
    assert links.owner(hub, "core").name == "core"


def test_observations_gather_every_domain(
    api: TestClient, two: tuple[HubContext, DemoDomain, OtherDomain], make_token
) -> None:  # type: ignore[no-untyped-def]
    _, demo, _other = two
    seen = api.get("/api/observations", headers=bearer(make_token("demo:read"))).json()
    assert [(o["domain"], o["kind"]) for o in seen["items"]] == [("demo", "empty")]
    everyone = bearer(make_token("demo:read", "other:read"))
    seen = api.get("/api/observations", headers=everyone).json()
    assert sorted(o["domain"] for o in seen["items"]) == ["demo", "other"]
    seen = api.get("/api/observations?domain=other", headers=everyone).json()
    assert [o["domain"] for o in seen["items"]] == ["other"]
    add(demo, "plein")
    seen = api.get("/api/observations", headers=everyone).json()
    assert [o["domain"] for o in seen["items"]] == ["other"]
    blind = bearer(make_token("demo:aggregates", "other:aggregates"))
    assert api.get("/api/observations", headers=blind).json() == {"items": []}
