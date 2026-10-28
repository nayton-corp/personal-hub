"""Bot BCF contre la fausse banque : flux Playwright complet, types d'échec, dépôt atomique."""

from __future__ import annotations

from pathlib import Path

import pytest

from hub.collectors.bcf import flow
from hub.collectors.runtime import execute
from tests.collectors.conftest import FakeHub
from tests.collectors.fakebank import Bank


def inbox_files(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("*") if p.is_file())


def test_export_lands_atomically_in_inbox(make_env, bank: Bank, fake_hub: FakeHub) -> None:  # type: ignore[no-untyped-def]
    bank.push_ms = 4_000  # le temps de valider sur le téléphone : la notification part
    env = make_env("bcf")
    result = execute(env, "run")
    assert (result.outcome, result.files) == ("ok", 1)
    files = inbox_files(env.inbox_root)
    assert len(files) == 1
    assert files[0].name.endswith("bcf-camt053.xml")
    assert not list((env.inbox_root / ".tmp").iterdir())
    # J-10, mouvements déjà exportés, camt.053 de tous les comptes
    assert bank.exports == [
        {"format": "CAMT053", "all": "allAccounts", "fetched": "1", "since": "17/10/2026"}
    ]
    assert fake_hub.notified == ["bcf:auth_pending"]
    assert fake_hub.runs == [("bcf", "run", "ok")]
    assert "/logout" in bank.calls


def test_same_file_twice_is_nothing_new(make_env) -> None:  # type: ignore[no-untyped-def]
    assert execute(make_env("bcf"), "run").outcome == "ok"
    second = execute(make_env("bcf"), "run")
    assert second.outcome == "nothing_new"
    assert len(inbox_files(make_env("bcf").inbox_root)) == 1


def test_nothing_to_export(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    bank.export = "nothing"
    assert execute(make_env("bcf"), "run").outcome == "nothing_new"


def test_form_text_is_not_mistaken_for_nothing_to_export(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    # sur le vrai site, le formulaire contient déjà « pas de mouvement » avant le clic
    bank.form_hint = True
    assert execute(make_env("bcf"), "run").outcome == "ok"
    bank.export = "nothing"
    assert execute(make_env("bcf"), "run").outcome == "nothing_new"


def test_invalid_file_goes_to_quarantine(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    bank.export = "bad"
    env = make_env("bcf")
    result = execute(env, "run")
    assert (result.outcome, result.detail) == ("invalid_file", "export.file")
    assert inbox_files(env.inbox_root) == []
    assert len(list((env.inbox_root / "quarantine").iterdir())) == 1


def test_refused_password_is_auth_error_without_push(
    make_env, bank: Bank, fake_hub: FakeHub
) -> None:  # type: ignore[no-untyped-def]
    bank.login = "refused"
    result = execute(make_env("bcf"), "run")
    assert (result.outcome, result.detail) == ("auth_error", "login.refused")
    assert fake_hub.notified == []


def test_push_not_validated(make_env, bank: Bank, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    bank.login = "never"
    monkeypatch.setattr(flow, "LOGIN_SECONDS", 2)
    result = execute(make_env("bcf"), "run")
    assert result.outcome == "auth_pending_timeout"


def test_missing_secret_is_auth_error(make_env) -> None:  # type: ignore[no-untyped-def]
    result = execute(make_env("bcf", creds={"contract": "1"}), "run")
    assert (result.outcome, result.detail) == ("auth_error", "secret:password")


def test_changed_site_names_the_missing_selector(
    make_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    changed = tmp_path / "selectors.toml"
    changed.write_text(flow.SELECTORS.read_text().replace("'Exporter')", "'Exporter les données')"))
    monkeypatch.setattr(flow, "SELECTORS", changed)
    result = execute(make_env("bcf"), "run")
    assert (result.outcome, result.detail) == ("selector_missing", "export.button")


def test_click_outside_whitelist_fails(
    make_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    narrowed = tmp_path / "selectors.toml"
    narrowed.write_text(flow.SELECTORS.read_text().replace('"export.download", ', ""))
    monkeypatch.setattr(flow, "SELECTORS", narrowed)
    result = execute(make_env("bcf"), "run")
    assert (result.outcome, result.detail) == ("unknown", "whitelist:export.download")


def test_check_downloads_nothing(make_env, bank: Bank) -> None:  # type: ignore[no-untyped-def]
    env = make_env("bcf")
    result = execute(env, "check")
    assert result.outcome == "ok"
    assert bank.exports == []
    assert inbox_files(env.inbox_root) == []


def test_unreachable_site(make_env) -> None:  # type: ignore[no-untyped-def]
    env = make_env("bcf", urls={"bcf.url": "http://127.0.0.1:9/login"})
    result = execute(env, "run")
    assert result.outcome == "site_unavailable"


def test_diagnose_writes_screenshots(
    make_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    changed = tmp_path / "selectors.toml"
    changed.write_text(flow.SELECTORS.read_text().replace("#findatepick_0_text", "#autre"))
    monkeypatch.setattr(flow, "SELECTORS", changed)
    env = make_env("bcf")
    env.diagnose = True
    result = execute(env, "run")
    assert result.detail == "export.date_from"
    assert list((env.cfg.diag / "bcf").glob("*.png"))
