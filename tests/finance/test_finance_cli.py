"""L1-12 et commandes `hub finance …` : comptes, catégories, imports, reprise, verify-ledger."""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from hub import cli as hub_cli
from hub.core.settings import get_settings
from hub.domains.finance.domain import FinanceDomain
from tests.factories.camt import IBAN, camt053
from tests.finance.conftest import simple_stmt
from tests.finance.test_importer import _folder, _months

runner = CliRunner()


@pytest.fixture
def app(finance: FinanceDomain) -> typer.Typer:
    sub = finance.cli()
    assert sub is not None
    return sub


def run(app: typer.Typer, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.stdout


def test_accounts_and_categories(app: typer.Typer) -> None:
    code, out = run(app, "accounts", "add", "Compte privé", "--iban", IBAN, "--budget")
    assert code == 0, out
    account_id = json.loads(out.splitlines()[0])["id"]
    assert json.loads(out.splitlines()[0])["iban"] == "CH93…957"
    assert run(app, "accounts", "add", "Encore", "--iban", IBAN)[0] == 1  # déjà connu
    assert run(app, "accounts", "add", "Sans clé")[0] == 1
    assert run(app, "accounts", "add", "X", "--iban", "pas un iban")[0] == 1
    assert run(app, "accounts", "add", "X", "--external-ref", "viac-1", "--kind", "bad")[0] == 1
    assert run(app, "accounts", "add", "X", "--external-ref", "v", "--currency", "XXX")[0] == 1
    code, out = run(app, "accounts", "add", "VIAC", "--external-ref", "viac-1", "--kind", "pension")
    assert code == 0
    code, out = run(app, "accounts", "list")
    assert "CH93…957" in out
    assert "budget" in out
    assert "viac-1" in out
    assert IBAN not in out
    assert run(app, "accounts", "open", account_id, "--on", "2026-09-30", "--amount", "10")[0] == 0
    assert run(app, "accounts", "open", account_id, "--on", "2026-09-30", "--amount", "1")[0] == 1
    assert run(app, "accounts", "open", "nope", "--on", "2026-09-30", "--amount", "1")[0] == 1

    assert run(app, "categories", "add", "cupra", "Voiture", "--group", "variable")[0] == 0
    assert run(app, "categories", "add", "cupra", "Voiture", "--group", "variable")[0] == 1
    assert run(app, "categories", "add", "Bad Slug", "x", "--group", "variable")[0] == 1
    assert run(app, "categories", "add", "ok-slug", "x", "--group", "nope")[0] == 1
    assert "cupra" in run(app, "categories", "list")[1]


def test_watch_inbox_once_and_imports(app: typer.Typer, finance: FinanceDomain) -> None:
    inbox = finance.settings.paths.inbox
    inbox.mkdir(parents=True)
    path = inbox / "a.xml"
    path.write_bytes(camt053(simple_stmt()))
    old = time.time() - 60
    os.utime(path, (old, old))
    code, out = run(app, "watch-inbox", "--once")
    assert code == 0
    assert json.loads(out)["needs_review"] == 1  # compte inconnu
    assert "needs_review" in run(app, "imports", "list")[1]
    # ajouter le compte rejoue l'import ; il manque encore l'ouverture
    code, out = run(app, "accounts", "add", "Privé", "--iban", IBAN)
    assert json.loads(out.splitlines()[1]) == {"retried": 1, "applied": 0}
    account_id = json.loads(out.splitlines()[0])["id"]
    run(app, "accounts", "open", account_id, "--on", "2026-09-30", "--amount", "1000")
    code, out = run(app, "imports", "retry")
    assert json.loads(out) == {"retried": 1, "applied": 1, "still_needs_review": 0}
    assert "applied" in run(app, "imports", "list", "--status", "applied")[1]
    code, out = run(app, "verify-ledger")
    assert code == 0
    assert json.loads(out)["ok"] is True
    assert json.loads(run(app, "rebuild-fts")[1])["rebuilt"] == ["entries_fts", "notes_fts"]


def test_import_history_command(app: typer.Typer, tmp_path: Path) -> None:
    run(app, "accounts", "add", "Privé", "--iban", IBAN)
    months = _months(date(2016, 1, 1), 3)
    folder = _folder(tmp_path, [months[0], months[2]])
    code, out = run(app, "import-history", str(folder))
    assert code == 1
    assert json.loads(out)["error"] == "historique discontinu"
    good = _folder(tmp_path / "ok", months)
    code, out = run(app, "import-history", str(good))
    assert code == 0, out
    report = json.loads(out)
    assert report["accounts"][0]["entries"] == 6
    assert IBAN not in out
    (tmp_path / "data" / "finance.history.lock").touch()
    assert run(app, "import-history", str(good))[0] == 1


def test_verify_ledger_fails_on_outdated_base(tmp_path: Path) -> None:
    from tests.finance.conftest import finance_settings

    d = FinanceDomain(finance_settings(tmp_path))
    sub = d.cli()
    assert sub is not None
    assert run(sub, "verify-ledger")[0] == 2
    assert not d.health().ok
    assert d.verify().db == "missing"


def test_hub_main_mounts_finance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HUB_PATHS__DATA", str(tmp_path / "data"))
    monkeypatch.setattr("sys.argv", ["hub", "finance", "--help"])
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc:
            hub_cli.main()
        assert exc.value.code == 0
    finally:
        get_settings.cache_clear()
