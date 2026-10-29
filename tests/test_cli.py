"""CLI : migrations, jetons (montrés une fois), code d'amorçage, nuit, vérification, sauvegarde."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hub import cli
from hub.platform.settings import get_settings

runner = CliRunner()


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUB_PATHS__DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HUB_PATHS__BACKUP", str(tmp_path / "backup"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def run(*args: str) -> tuple[int, str]:
    result = runner.invoke(cli.app, list(args))
    return result.exit_code, result.stdout


def test_full_cycle(tmp_path: Path) -> None:
    code, _ = run("token", "list")
    assert code == 2  # base pas encore migrée
    assert run("verify")[0] == 1
    code, out = run("db", "upgrade")
    assert code == 0
    assert json.loads(out)["core"] == "0007_token_expiry"
    assert json.loads(run("db", "status")[1])["core"]["current"] is True

    code, out = run("token", "create", "brain-mac", "--scope", "brain=finance", "--days", "30")
    assert code == 0
    secret = out.strip().splitlines()[-1]
    assert secret.startswith("hub_")
    code, out = run("token", "list")
    assert "brain-mac" in out
    assert "finance:propose" in out
    assert "actif    fin " in out
    assert secret not in out
    token_id = out.split()[0]
    code, out = run("token", "rotate", token_id)
    assert code == 0
    assert out.strip().splitlines()[-1] != secret
    assert run("token", "rotate", token_id)[0] == 1  # l'ancien est révoqué
    token_id = run("token", "list")[1].splitlines()[-1].split()[0]
    assert run("token", "revoke", token_id)[0] == 0
    assert run("token", "revoke", token_id)[0] == 1
    assert run("token", "create", "x", "--scope", "app")[0] == 1
    assert run("token", "create", "x", "--scope", "brain", "--days", "400")[0] != 0

    code, out = run("auth", "bootstrap-code")
    assert code == 0
    assert len(out.strip()) == 20

    assert json.loads(run("nightly")[1])["expired"] == 0
    assert json.loads(run("reconcile")[1]) == {"applied": 0, "released": 0}
    code, out = run("verify")
    assert code == 0
    assert json.loads(out)["checks"]["core"] == "ok"
    assert json.loads(out)["checks"]["finance.verify"] == "ok"  # verify-ledger
    code, out = run("backup", "--stamp", "test")
    assert code == 0
    assert json.loads(out)["files"] == ["core-test.db", "finance-test.db"]
    assert (tmp_path / "backup" / "core-test.db").exists()


def test_serve_refuses_outdated_base() -> None:
    assert run("serve")[0] == 2


def test_backup_restore_roundtrip(tmp_path: Path) -> None:
    run("db", "upgrade")
    secret = run("token", "create", "keep", "--scope", "brain")[1].strip().splitlines()[-1]
    assert run("backup", "--stamp", "before")[0] == 0
    run("token", "create", "lost", "--scope", "aggregates")
    assert "lost" in run("token", "list")[1]
    code, out = run("restore", "before")
    assert code == 0
    assert json.loads(out)["restored"] == ["core", "finance"]
    listed = run("token", "list")[1]
    assert "keep" in listed
    assert "lost" not in listed
    assert secret not in listed
    assert run("restore", "nope")[0] == 1
