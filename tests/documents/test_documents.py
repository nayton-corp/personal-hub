"""Domaine Documents (S12) : reprise de la bibliothèque de Domia, archive chiffrée dont la base
se reconstruit, index local, part « foyer », propositions, et lien vers une écriture de la
finance par `core/link`."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from hub.api.app import create_app
from hub.core import maintenance, proposals, tools
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.domains.documents.domain import DocumentsDomain, ref_of
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.sources.infra.files import Incoming
from hub.platform.settings import Settings
from tests.conftest import bearer
from tests.factories.camt import camt053
from tests.factories.viac import real_pdf
from tests.finance.conftest import finance_settings, ready_account, rows, simple_stmt
from tests.finance.test_finance_api import app_session

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)
TODAY = date(2026, 10, 30)
CARD = """\
name: Lave-linge
room: buanderie
brand: Exemple
model: WM14N2
bought_at: 2021-03-01
couleur: blanc
maintenance:
  - what: nettoyer le filtre
    every: 1 mois
    last: 2026-09-01
documents:
  - lave-linge/notice.md
"""


def library(root: Path) -> Path:
    """Une bibliothèque de Domia fictive : une fiche, sa notice, un bail, une photo à trier."""
    (root / "lave-linge").mkdir(parents=True)
    (root / "à-trier").mkdir()
    (root / "lave-linge.yaml").write_text(CARD, encoding="utf-8")
    (root / "lave-linge" / "notice.md").write_text(
        "# Notice\n\nCode erreur E24 : la vidange est bouchée, nettoyer le filtre.\n",
        encoding="utf-8",
    )
    (root / "bail.txt").write_text("Bail à loyer : préavis de trois mois.", encoding="utf-8")
    (root / "à-trier" / "photo.jpg").write_bytes(b"\xff\xd8 pas une vraie photo")
    return root


@pytest.fixture
def dsettings(tmp_path: Path) -> Settings:
    return finance_settings(tmp_path)


def mount(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> DocumentsDomain:
    domain = DocumentsDomain(settings)
    monkeypatch.setattr(domain, "today", lambda: TODAY)
    return domain


@pytest.fixture
def documents(dsettings: Settings, monkeypatch: pytest.MonkeyPatch) -> DocumentsDomain:
    return mount(dsettings, monkeypatch)


@pytest.fixture
def hub(dsettings: Settings, documents: DocumentsDomain) -> Iterator[HubContext]:
    ctx = HubContext.build(dsettings, Registry([documents, FinanceDomain(dsettings)]))
    ctx.migrate_all()
    yield ctx
    ctx.dispose()


@pytest.fixture
def imported(hub: HubContext, documents: DocumentsDomain, tmp_path: Path) -> DocumentsDomain:
    found = documents.import_library(library(tmp_path / "Bibliothèque"))
    assert found == {"ignored_fields": 1, "cards": 1, "documents": 2}
    return documents


def test_the_library_is_taken_over_once(imported: DocumentsDomain, tmp_path: Path) -> None:
    again = imported.import_library(tmp_path / "Bibliothèque")
    assert again == {"ignored_fields": 1, "same": 1, "duplicates": 2}  # rejouable
    card = imported.card_view("lave-linge", household_only=True)
    assert card is not None
    assert (card["model"], card["bought_at"]) == ("WM14N2", "2021-03-01")
    assert "couleur" not in card
    assert [f["file_name"] for f in card["files"]] == ["notice.md"]
    found = imported.find("E24", 5, household_only=True)
    (hit,) = found["passages"]
    assert (hit["cite"], hit["card_id"]) == ("notice", "lave-linge")
    assert imported.find("wm14", 5, household_only=True)["cards"][0]["card_id"] == "lave-linge"
    assert imported.counts() == {"cards": 1, "documents": 2, "household": 2, "maintenance_due": 1}
    (seen,) = imported.observations(5)
    assert (seen.kind, seen.on_date) == ("maintenance_due", "2026-10-01")
    assert seen.title == "Entretien : Lave-linge (nettoyer le filtre)"


def test_the_base_rebuilds_from_its_archive(
    hub: HubContext, imported: DocumentsDomain, dsettings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert imported.compare()["ok"] is True
    archive = dsettings.paths.archive_of("documents")
    assert b"E24" not in b"".join(p.read_bytes() for p in archive.rglob("*.age"))  # chiffrée
    before = imported.overview()
    imported.engine().dispose()
    imported.path.unlink()
    back = mount(dsettings, monkeypatch)
    back.migrate()
    assert back.rebuild() == {"cards": 1, "documents": 2, "marks": 2, "passages": 2}
    assert back.overview() == before
    assert back.find("préavis", 5, household_only=True)["passages"][0]["cite"] == "bail"
    with pytest.raises(FileExistsError):
        back.rebuild()  # jamais par-dessus une base vivante
    assert back.compare()["ok"] is True
    back.engine().dispose()


def test_the_inbox_keeps_documents_private(hub: HubContext, imported: DocumentsDomain) -> None:
    inbox = imported.settings.paths.inbox_of("documents")
    inbox.mkdir(parents=True)
    (inbox / "garantie.pdf").write_bytes(real_pdf("Garantie Exemple\nvalable jusqu'en 2028"))
    (inbox / "note.md").write_text("Code du portail : voir la garantie", encoding="utf-8")
    (inbox / "film.mov").write_bytes(b"x")
    assert imported.process_inbox() == {"added": 2, "ignored": 1}
    assert sorted(p.name for p in inbox.iterdir()) == ["film.mov"]
    assert imported.find("garantie", 5, household_only=True)["passages"] == []
    private = imported.find("garantie", 5, household_only=False)["passages"]
    assert {p["title"] for p in private} == {"garantie", "note"}
    assert any(p["page"] == 1 for p in private)  # le PDF garde ses pages
    assert imported.counts()["household"] == 2


def test_cards_and_marks_go_through_proposals(hub: HubContext, imported: DocumentsDomain) -> None:
    model = Principal("token:t", frozenset({"documents:household", "documents:propose"}))
    out = tools.call(
        hub,
        model,
        "documents",
        "documents_propose_card",
        {"card_id": "lave-linge", "fields": {"serial": "S-1", "name": None}},
    )
    assert out["status"] == "pending"
    p = proposals.load_many(hub, [out["proposal_id"]])[0]
    assert p.preview["summary"] == "Fiche « Lave-linge » : serial"
    assert proposals.accept(hub, APP, [p], None)[0].status == "applied"
    assert imported.card_view("lave-linge", True)["serial"] == "S-1"  # type: ignore[index]
    with pytest.raises(Exception, match=r"validation\.params"):
        tools.call(
            hub, model, "documents", "documents_propose_card", {"card_id": "x", "fields": {"z": 1}}
        )
    doc = imported.find("préavis", 5, household_only=False)["passages"][0]["document_id"]
    m, _ = proposals.create(
        hub, APP, "documents", "mark_household", {"document_id": doc, "household": False}
    )
    assert m.preview["summary"] == "« bail » réservé aux propriétaires"
    assert proposals.accept(hub, APP, [m], None)[0].status == "applied"
    assert imported.counts()["household"] == 1
    (m,) = proposals.load_many(hub, [m.id])
    assert proposals.revert(hub, APP, m, None).status == "applied"  # d'un geste
    assert imported.counts()["household"] == 2
    assert imported.compare()["ok"] is True  # chaque effet est archivé
    report = maintenance.verify(hub)
    assert report.checks["documents.verify"] == "ok", report.checks


def test_tools_see_the_household_part_only(
    hub: HubContext, imported: DocumentsDomain, make_token
) -> None:  # type: ignore[no-untyped-def]
    inbox = imported.settings.paths.inbox_of("documents")
    inbox.mkdir(parents=True)
    (inbox / "salaire.txt").write_text("Fiche de salaire filtre", encoding="utf-8")
    imported.process_inbox()
    household = Principal("token:h", frozenset({"documents:household"}))
    names = {t.name for t in tools.visible_tools(household, imported)}
    assert "documents_search" in names
    assert "documents_counts" not in names
    found = tools.call(hub, household, "documents", "documents_search", {"q": "filtre"})
    assert {p["title"] for p in found["passages"]} == {"notice"}
    reader = Principal("token:r", frozenset({"documents:read"}))
    found = tools.call(hub, reader, "documents", "documents_search", {"q": "filtre"})
    assert {p["title"] for p in found["passages"]} == {"notice", "salaire"}
    card = tools.call(hub, household, "documents", "documents_card", {"card_id": "lave-linge"})
    assert card["name"] == "Lave-linge"
    (due,) = tools.call(hub, household, "documents", "documents_maintenance_due", {})
    assert due["since"] == "2026-10-01"
    numbers = Principal("token:a", frozenset({"documents:aggregates"}))
    assert [t.name for t in tools.visible_tools(numbers, imported)] == ["documents_counts"]
    assert make_token("documents:household")  # une portée que les jetons connaissent


def test_a_document_links_to_a_finance_entry(
    hub: HubContext, imported: DocumentsDomain, dsettings: Settings
) -> None:
    finance = hub.registry.get("finance")
    ready_account(finance)  # type: ignore[arg-type]
    finance.importer.process([Incoming("a.xml", camt053(simple_stmt()))])  # type: ignore[attr-defined]
    entry = rows(finance, "SELECT id FROM entries ORDER BY id LIMIT 1")[0][0]  # type: ignore[arg-type]
    doc = imported.find("préavis", 5, household_only=False)["passages"][0]["document_id"]
    a, b = f"hub:documents:document:{doc}", f"hub:finance:entry:{entry}"
    p, _ = proposals.create(hub, APP, "core", "link", {"from_urn": a, "to_urn": b})
    assert p.preview["summary"].startswith("Lier « bail » et ")
    assert proposals.accept(hub, APP, [p], None)[0].status == "applied"
    with TestClient(create_app(hub), base_url="https://hub.example.ts.net") as client:
        app_session(hub, client)
        (out,) = client.get(f"/api/links?urn={a}").json()["outgoing"]
        assert out["to_urn"] == b
        card = f"hub:documents:card:{ref_of('lave-linge')}"
        assert client.get(f"/api/resolve?urn={card}").json()["title"] == "Lave-linge"
        hits = client.get("/api/search?q=E24").json()
        assert hits["items"][0]["urn"].startswith("hub:documents:document:")
        assert client.get("/api/documents/overview").json()["maintenance_due"] == 1
        token = bearer(_token(hub, "documents:aggregates"))
        assert client.get("/api/documents/counts", headers=token).json()["cards"] == 1
        assert client.get("/api/documents/search?q=E24", headers=token).status_code == 403


def _token(hub: HubContext, *scopes: str) -> str:
    from hub.core import tokens

    with hub.core.engine.begin() as conn:
        return tokens.create(conn, "t", list(scopes), "system:test", days=30)[1]


def test_the_cli(hub: HubContext, imported: DocumentsDomain, tmp_path: Path) -> None:
    cli = imported.cli()
    assert cli is not None
    runner = CliRunner()
    assert runner.invoke(cli, ["status"]).exit_code == 0
    assert runner.invoke(cli, ["rebuild", "--check"]).exit_code == 0
    assert runner.invoke(cli, ["rebuild"]).exit_code == 1  # la base vit
    assert '"passages": 2' in runner.invoke(cli, ["index"]).output
    assert runner.invoke(cli, ["import-library", str(tmp_path / "absent")]).exit_code == 1
    shutil.rmtree(imported.settings.paths.archive_of("documents") / "records" / "marks")
    assert imported.verify().detail["not_archived"] == {"marks": 2}
    assert runner.invoke(cli, ["rebuild", "--check"]).exit_code == 0  # rattrapées d'abord
    assert imported.verify().detail["not_archived"] == {}
