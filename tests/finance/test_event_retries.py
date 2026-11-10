"""Audit du 10/11, N1 et N3 : une notification que ntfy ne prend pas est renvoyée, un événement
fautif est mis de côté après quelques essais, et la file de son domaine continue."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from hub.core import notify, proposal_events
from hub.core.context import HubContext
from hub.core.notify import Message
from hub.domains.finance.domain import FinanceDomain
from tests.finance.test_app_reads import (  # noqa: F401 - fixtures
    client,
    ctx,
    fin,
    set_budget,
    year,
)


def held(ctx: HubContext) -> list[tuple[str, str, int]]:  # noqa: F811
    with ctx.core.engine.connect() as conn:
        return [
            (r[0], r[1], r[2])
            for r in conn.execute(
                text("SELECT type, status, attempts FROM event_retries ORDER BY seq")
            )
        ]


@pytest.fixture
def alerts(year: FinanceDomain) -> int:  # noqa: F811
    set_budget(year, "restaurants", 8_000)
    return len(year.run_sentinels())  # deux alertes de budget, donc deux notifications


def test_a_notification_ntfy_did_not_take_is_sent_again(
    alerts: int,
    ctx: HubContext,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Message] = []
    up = False
    monkeypatch.setattr(notify, "topic", lambda _settings: "sujet")
    monkeypatch.setattr(ctx.notifier, "send", lambda msg: calls.append(msg) is None and up)
    assert proposal_events.sync_events(ctx)["notified"] == 0
    assert len(calls) == 1  # ntfy ne répond pas : la seconde n'est pas essayée ce passage-ci
    assert held(ctx) == [("notify.request", "waiting", 1)] * alerts
    up = True
    assert proposal_events.sync_events(ctx)["notified"] == alerts
    assert held(ctx) == []
    assert proposal_events.sync_events(ctx)["notified"] == 0  # une fois, pas deux


def test_without_ntfy_nothing_waits(alerts: int, ctx: HubContext) -> None:  # noqa: F811
    assert proposal_events.sync_events(ctx)["notified"] == 0
    assert held(ctx) == []


def test_a_notification_waits_one_day_at_most(
    alerts: int,
    ctx: HubContext,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notify, "topic", lambda _settings: "sujet")
    monkeypatch.setattr(ctx.notifier, "send", lambda _msg: False)
    for _ in range(proposal_events.MAX_ATTEMPTS + 2):  # le nombre d'essais ne compte pas
        proposal_events.sync_events(ctx)
    assert {status for _type, status, _n in held(ctx)} == {"waiting"}
    with ctx.core.engine.begin() as conn:
        conn.execute(text("UPDATE event_retries SET created_at = '2026-01-01T00:00:00.000Z'"))
    proposal_events.sync_events(ctx)
    assert {status for _type, status, _n in held(ctx)} == {"set_aside"}


def test_a_faulty_event_is_set_aside_and_the_queue_goes_on(
    alerts: int,
    ctx: HubContext,  # noqa: F811
    year: FinanceDomain,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[Message] = []
    monkeypatch.setattr(ctx.notifier, "send", lambda msg: sent.append(msg) is None)

    def boom(_hub: HubContext, _payload: dict[str, object]) -> int:
        raise RuntimeError("événement illisible")

    monkeypatch.setattr(proposal_events, "_notify", boom)
    assert proposal_events.sync_events(ctx)["notified"] == 0
    assert held(ctx) == [("notify.request", "waiting", 1)] * alerts
    with ctx.core.engine.connect() as conn:  # le curseur a avancé : la file n'est pas bloquée
        cursor = conn.execute(text("SELECT cursor FROM event_cursors")).scalar_one()
    assert cursor == year.events_since(0, 500)[-1].seq
    for _ in range(proposal_events.MAX_ATTEMPTS - 1):
        proposal_events.sync_events(ctx)
    assert held(ctx) == [("notify.request", "set_aside", proposal_events.MAX_ATTEMPTS)] * alerts
    assert [m.title for m in sent] == ["Hub : un événement mis de côté"] * alerts
    assert "RuntimeError" not in sent[0].body
    assert "illisible" not in sent[0].body
    proposal_events.sync_events(ctx)  # mis de côté : plus aucun essai
    assert len(sent) == alerts
