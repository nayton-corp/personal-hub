"""L4-08 : reconstruction du registre par rejeu et comparaison."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.registry import Registry
from hub.domains.finance import ledger, rebuild
from hub.domains.finance.domain import FinanceDomain
from tests.factories import viac as v
from tests.factories.camt import Tx
from tests.finance.conftest import D, finance_settings, ready_account, rows
from tests.finance.test_double_sas import accept, create, entry_id, load
from tests.finance.test_viac import open_portfolio, send


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
    d.importer.pdf_text = v.fake_text
    return d


def target_for(fin: FinanceDomain, tmp_path: Path) -> FinanceDomain:
    paths = fin.settings.paths.model_copy(update={"data": tmp_path / "rebuilt"})
    target = FinanceDomain(fin.settings.model_copy(update={"paths": paths}))
    target.importer.pdf_text = v.fake_text
    return target


def history(ctx: HubContext, fin: FinanceDomain) -> None:
    ready_account(fin)
    load(
        fin,
        [
            Tx("42.00", True, D, counterparty="Zorglub Fictif"),
            Tx("2500.00", False, date(2026, 10, 2), counterparty="Employeur Fictif SA"),
        ],
    )
    eid = entry_id(fin, "Zorglub Fictif")
    accept(ctx, create(ctx, "recategorize", {"entry_id": eid, "category_id": "loisirs"}))
    accept(ctx, create(ctx, "add_note", {"entry_id": eid, "text": "Cadeau"}))
    accept(
        ctx,
        create(
            ctx,
            "set_budget",
            {"category_id": "alimentation", "monthly_minor": 60_000, "valid_from": "2026-10-01"},
        ),
    )
    accept(
        ctx, create(ctx, "create_category", {"id": "voiture", "name": "Voiture", "grp": "variable"})
    )
    open_portfolio(fin)
    send(fin, v.deposit(date(2026, 3, 2), "1000.00"), v.buy(date(2026, 3, 5), "9.5", "950.00"))
    folio = v.Folio("VIAC1", cash="50.00", positions=[v.Pos("9.5", "1045.00")])
    send(fin, v.report(date(2026, 6, 30), [folio]), v.attestation(2025, "7258.00"))


def test_rebuild_reproduces_the_ledger(ctx: HubContext, fin: FinanceDomain, tmp_path: Path) -> None:
    history(ctx, fin)
    target = target_for(fin, tmp_path)
    applied = rebuild.applied_proposals(fin.engine(), ctx.core.engine)
    assert {p.kind for p in applied} == {
        "recategorize",
        "add_note",
        "set_budget",
        "create_category",
    }
    report = rebuild.rebuild(fin, target, applied)
    assert report.ok, report.public()
    assert (report.epoch, report.proposals) == (2, 3)
    assert report.skipped == {"reference": 1}
    diff = rebuild.compare(fin.engine(), target.engine())
    assert diff.ok, diff.public()
    assert diff.checks["entries"]["source"] == 8  # 2 BCF + 3 VIAC + 3 ouvertures
    assert diff.checks["holdings"]["rebuilt"] == 1
    assert target.verify_ledger().ok
    epochs = rows(target, "SELECT DISTINCT epoch FROM journal")
    assert epochs == [(2,)]
    # mêmes identifiants : les propositions de core.db pointent toujours au bon endroit
    assert rows(target, "SELECT proposal_id FROM applied_proposals ORDER BY rowid") == [
        (p.proposal_id,) for p in applied if p.kind != "create_category"
    ]
    target.engine().dispose()


def test_compare_finds_differences(ctx: HubContext, fin: FinanceDomain, tmp_path: Path) -> None:
    history(ctx, fin)
    target = target_for(fin, tmp_path)
    rebuild.rebuild(fin, target, rebuild.applied_proposals(fin.engine(), ctx.core.engine))
    eid = entry_id(fin, "Employeur Fictif SA")
    with begin_immediate(target.engine()) as conn:
        seq = conn.execute(text("SELECT seq FROM entries WHERE id = :i"), {"i": eid}).scalar_one()
        ledger.append(
            conn,
            "notes",
            {
                "entry_seq": seq,
                "text": "x",
                "search_text": "x",
                "proposal_id": None,
                "created_at": "t",
            },
        )
    diff = rebuild.compare(fin.engine(), target.engine())
    assert not diff.ok
    assert diff.checks["notes"]["differences"] == 1
    assert diff.checks["notes"]["examples"] == [eid]
    assert diff.checks["balances"]["differences"] == 0
    target.engine().dispose()


def test_rebuild_refuses_a_filled_target(
    ctx: HubContext, fin: FinanceDomain, tmp_path: Path
) -> None:
    history(ctx, fin)
    target = target_for(fin, tmp_path)
    target.migrate()
    ready_account(target)
    report = rebuild.rebuild(fin, target, [])
    assert not report.ok
    assert report.error == "la base cible n'est pas vide"
    target.engine().dispose()


def test_missing_params_fail_the_rebuild(
    ctx: HubContext, fin: FinanceDomain, tmp_path: Path
) -> None:
    history(ctx, fin)
    applied = [
        rebuild.Applied(p.proposal_id, p.kind, p.applied_at, None)
        for p in rebuild.applied_proposals(fin.engine(), ctx.core.engine)
        if p.kind == "add_note"
    ]
    target = target_for(fin, tmp_path)
    report = rebuild.rebuild(fin, target, applied)
    assert not report.ok
    assert report.skipped == {"params_missing": 1}
    target.engine().dispose()
