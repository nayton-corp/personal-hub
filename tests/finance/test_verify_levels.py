"""Audit du 10/11, V1 : l'intégrité bloque, un écart entre deux calculs avertit. Et un import
resté en plan remonte dans la santé du domaine (I1)."""

import pytest
from sqlalchemy import text

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.patrimoine.app import checks
from hub.domains.finance.sources.infra.files import Incoming
from tests.factories.camt import camt053
from tests.finance.conftest import ready_account, simple_stmt


def test_a_gap_between_two_calculations_warns_without_failing_verify(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance)
    assert finance.verify().warnings == ()
    monkeypatch.setattr(checks, "figures", lambda _conn, _on: (False, {"crypto": {"ok": False}}))
    health = finance.verify()
    assert health.ok  # une mise à jour, même de sécurité, n'est pas bloquée par un calcul
    assert health.warnings == ("figures.crypto_gap",)
    assert health.detail["figures"] == {"crypto": {"ok": False}}


def test_a_broken_chain_still_fails_verify(finance: FinanceDomain) -> None:
    ready_account(finance)
    finance.importer.process([Incoming("a.xml", camt053(simple_stmt()))])
    with finance.engine().begin() as conn:
        conn.execute(text("DROP TRIGGER IF EXISTS entries_no_update"))
        triggers = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'entries'")
        ).scalars()
        for name in list(triggers):
            conn.execute(text(f'DROP TRIGGER "{name}"'))
        conn.execute(text("UPDATE entries SET amount_minor = amount_minor + 1 WHERE seq = 2"))
    assert not finance.verify().ok


def test_an_import_left_staged_for_an_hour_shows_in_health(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance)

    def stop(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(finance.importer, "apply_all", stop)
        with pytest.raises(KeyboardInterrupt):
            finance.importer.process([Incoming("a.xml", camt053(simple_stmt()))])
    assert finance.health().warnings == ()  # tout juste reçu : la reprise va passer
    with finance.engine().begin() as conn:
        conn.execute(text("UPDATE imports SET received_at = '2026-01-01T00:00:00.000Z'"))
    assert finance.health().warnings == ("imports.stuck",)
    assert finance.health().ok
