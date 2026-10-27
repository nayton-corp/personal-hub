"""Bot VIAC contre le faux VIAC : documents voulus, rapport, session expirée, reconnexion."""

from __future__ import annotations

from pathlib import Path

import pytest

from hub.collectors.base import Failure
from hub.collectors.runtime import execute
from hub.collectors.viac import flow
from tests.collectors.fakebank import Bank


def inbox_files(root: Path) -> list[str]:
    return sorted(p.name for p in root.glob("*") if p.is_file())


def test_downloads_new_documents_and_requests_report(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    env = make_env("viac", viac_overlap_days=0)
    env.memory.put("last_date", "2026-02-01")
    result = execute(env, "run")
    names = inbox_files(env.inbox_root)
    # l'attestation de janvier est antérieure à la date de reprise : la liste s'arrête là
    assert result.outcome == "ok"
    assert result.files == 2  # le versement et le rapport demandé
    assert any(n.endswith("viac-2026-10-03-Versement.pdf") for n in names)
    assert any(n.endswith("viac-rapport-2026-10-26.pdf") for n in names)
    assert "/report" in bank.calls


def test_second_run_downloads_nothing(make_env) -> None:  # type: ignore[no-untyped-def]
    first = make_env("viac")
    assert execute(first, "run").outcome == "ok"
    count = len(inbox_files(first.inbox_root))
    again = execute(make_env("viac"), "run")
    assert again.outcome == "nothing_new"  # documents connus, rapport demandé il y a < 6 jours
    assert len(inbox_files(first.inbox_root)) == count


def test_expired_session_is_auth_error_without_login(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    bank.viac_session = False
    result = execute(make_env("viac"), "run")
    assert (result.outcome, result.detail) == ("auth_error", "session.expired")
    assert "/api/otp" not in bank.calls


def test_check(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    env = make_env("viac")
    assert execute(env, "check").outcome == "ok"
    assert inbox_files(env.inbox_root) == []


def test_relogin_with_typed_code(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    bank.viac_session = False
    env = make_env("viac")
    assert flow.relogin(env, lambda: "123456").outcome == "ok"
    assert bank.viac_session
    assert execute(make_env("viac"), "check").outcome == "ok"


def test_relogin_with_wrong_code(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    bank.viac_session = False
    with pytest.raises(Failure) as exc:
        flow.relogin(make_env("viac"), lambda: "000000")
    assert exc.value.outcome == "auth_error"
