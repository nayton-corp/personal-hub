"""Paliers d'approbation (S11) : le type déclare son palier par défaut, la personne le change
(`hub proposals policy`) ; un modèle qui ne dit pas « pas de texte externe » reste à la carte."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from hub import cli
from hub.core import policies, proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import ProposalKind
from hub.platform.settings import get_settings
from tests.support.demo_domain import AddItem, AddItemHandler, DemoDomain

APP = Principal("passkey:test", frozenset({"app"}), is_app=True)
MODEL = Principal("token:t", frozenset({"demo:propose"}))


@pytest.fixture
def auto(demo: DemoDomain) -> DemoDomain:
    kinds = dict(demo.proposal_kinds)
    kinds["add_auto"] = ProposalKind(AddItem, AddItemHandler(), ai_allowed=True, tier="auto")
    demo.proposal_kinds = kinds
    return demo


def items(demo: DemoDomain) -> list[str]:
    with demo.engine().connect() as conn:
        return [r[0] for r in conn.execute(text("SELECT name FROM items ORDER BY seq"))]


def test_a_kind_declares_its_default_tier(hub: HubContext, auto: DemoDomain) -> None:
    p, _ = proposals.create(hub, APP, "demo", "add_auto", {"name": "lait"})
    assert (p.tier, p.status) == ("auto", "applied")
    assert items(auto) == ["lait"]
    p, _ = proposals.create(hub, APP, "demo", "add_item", {"name": "pain"})
    assert (p.tier, p.status) == ("human", "pending")


def test_a_model_stays_at_the_card_unless_it_says_no_external_text(
    hub: HubContext, auto: DemoDomain
) -> None:
    p, _ = proposals.create(hub, MODEL, "demo", "add_auto", {"name": "œufs"})
    assert (p.tier, p.status) == ("human", "pending")
    p, _ = proposals.create(hub, MODEL, "demo", "add_auto", {"name": "beurre"}, external_text=False)
    assert (p.tier, p.status) == ("auto", "applied")


def test_the_person_overrides_and_resets_the_tier(hub: HubContext, auto: DemoDomain) -> None:
    with hub.core.engine.begin() as conn:
        policies.set_tier(conn, "demo", "add_auto", "human")
        assert policies.tier(conn, "demo", "add_auto", "auto") == "human"
        policies.set_tier(conn, "demo", "add_auto", None)
        assert policies.tier(conn, "demo", "add_auto", "auto") == "auto"
        with pytest.raises(ValueError, match="palier inconnu"):
            policies.set_tier(conn, "demo", "add_auto", "sometimes")


def test_policy_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_PATHS__DATA", str(tmp_path / "data"))
    get_settings.cache_clear()
    runner = CliRunner()
    try:
        assert runner.invoke(cli.app, ["db", "upgrade"]).exit_code == 0
        out = runner.invoke(cli.app, ["proposals", "policy", "finance"])
        assert out.exit_code == 0, out.output
        assert "finance/categorize_entries" in out.output
        args = ["proposals", "policy", "finance", "categorize_entries"]
        out = runner.invoke(cli.app, [*args, "auto_digest"])
        assert "auto_digest  (défaut : human)" in out.output
        assert "(défaut" not in runner.invoke(cli.app, [*args, "default"]).output
        assert runner.invoke(cli.app, [*args, "parfois"]).exit_code == 1
        nope = ["proposals", "policy", "finance", "nope", "auto"]
        assert runner.invoke(cli.app, nope).exit_code == 1
    finally:
        get_settings.cache_clear()
