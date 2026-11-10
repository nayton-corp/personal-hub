"""Audit du 10/11, I1 : un import interrompu entre la mise en attente et l'application est
repris au passage suivant, au lieu de finir en doublon supprimé sans une écriture."""

import os
import time
from datetime import timedelta
from pathlib import Path

import pytest

from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.sources.infra.files import Incoming
from tests.factories.camt import camt053
from tests.finance.conftest import ready_account, rows, simple_stmt

NOW = timedelta(0)  # dans ces tests, un import « staged » est repris sans attendre


def drop(domain: FinanceDomain, name: str, data: bytes) -> Path:
    inbox = domain.settings.paths.inbox_of("finance")
    inbox.mkdir(parents=True, exist_ok=True)
    path = inbox / name
    path.write_bytes(data)
    old = time.time() - 60  # fichier « posé » depuis longtemps
    os.utime(path, (old, old))
    return path


def statuses(domain: FinanceDomain) -> list[str]:
    return [str(r[0]) for r in rows(domain, "SELECT status FROM imports ORDER BY received_at")]


def interrupt(finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch, data: bytes) -> None:
    """Le processus s'arrête juste après la mise en attente : rien n'est appliqué."""

    def stop(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    with monkeypatch.context() as m:
        m.setattr(finance.importer, "apply_all", stop)
        with pytest.raises(KeyboardInterrupt):
            finance.importer.process([Incoming("releve.xml", data)])
    assert statuses(finance) == ["staged"]
    assert rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(0,)]


def test_interrupted_import_is_resumed_from_the_archive(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance, 100_000)
    interrupt(finance, monkeypatch, camt053(simple_stmt("1000.00")))
    done = finance.importer.resume_staged(NOW)
    assert [(o.status, o.new) for o in done] == [("applied", 3)]
    assert statuses(finance) == ["applied"]
    assert rows(finance, "SELECT status FROM import_statements") == [("applied",)]
    assert finance.verify_ledger().ok
    assert finance.importer.resume_staged(NOW) == []  # rien à reprendre deux fois


def test_file_left_in_the_inbox_is_a_duplicate_of_its_resumed_import(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance, 100_000)
    data = camt053(simple_stmt("1000.00"))
    interrupt(finance, monkeypatch, data)
    path = drop(finance, "releve.xml", data)  # le fichier n'avait pas été supprimé
    monkeypatch.setattr(finance.importer, "stale_staged", NOW)
    report = finance.importer.process_inbox()
    assert not path.exists()
    assert [f.status for f in report.files] == ["duplicate"]
    assert report.counters()["new_entries"] == 3
    assert statuses(finance) == ["applied"]
    assert rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(3,)]


def test_a_fresh_staged_import_is_left_to_its_own_process(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance, 100_000)
    interrupt(finance, monkeypatch, camt053(simple_stmt("1000.00")))
    assert finance.importer.resume_staged() == []  # peut-être encore en cours ailleurs
    assert statuses(finance) == ["staged"]


def test_claim_makes_a_second_process_wait(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance, 100_000)
    interrupt(finance, monkeypatch, camt053(simple_stmt("1000.00")))
    assert len(finance.importer._claim_staged(NOW)) == 1
    assert finance.importer._claim_staged(timedelta(minutes=10)) == []


def test_interrupted_after_the_last_statement_only_needs_its_status(
    finance: FinanceDomain, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready_account(finance, 100_000)
    with monkeypatch.context() as m:
        m.setattr(finance.importer, "_finish", lambda _i: (_ for _ in ()).throw(KeyboardInterrupt))
        with pytest.raises(KeyboardInterrupt):
            finance.importer.process([Incoming("releve.xml", camt053(simple_stmt("1000.00")))])
    assert statuses(finance) == ["staged"]
    assert finance.importer.resume_staged(NOW) == []
    assert statuses(finance) == ["applied"]
    assert rows(finance, "SELECT count(*) FROM entries WHERE kind = 'movement'") == [(3,)]
