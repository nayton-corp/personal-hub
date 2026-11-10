"""Étape 0 du refactoring : l'étalon des agrégats (`hub finance golden`) fige ce que l'app
affiche à une date et nomme chaque écart au centime, sans jamais écrire une écriture, un
libellé ni un IBAN."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from hub.domains.finance import golden
from hub.domains.finance.domain import FinanceDomain
from hub.domains.finance.sources.infra.files import Incoming
from tests.factories.camt import IBAN, Tx
from tests.finance.conftest import D, ready_account
from tests.finance.test_double_sas import load
from tests.finance.test_wealth import add_ref, market_doc

AS_OF = date(2026, 10, 27)
runner = CliRunner()


def btc(on: str, price: str) -> dict[str, str]:
    return {
        "instrument": "BTC",
        "kind": "crypto",
        "on_date": on,
        "price": price,
        "currency": "CHF",
        "source": "coingecko",
    }


def dataset(finance: FinanceDomain) -> None:
    """Un compte bancaire avec deux écritures, un portefeuille de 0,5 BTC coté."""
    ready_account(finance, 100_000)
    load(
        finance,
        [
            Tx("42.00", True, D, counterparty="Zorglub Fictif"),
            Tx("2500.00", False, date(2026, 10, 2), counterparty="Employeur Fictif SA"),
        ],
    )
    add_ref(finance, "crypto:ledger-btc", "crypto", "Ledger")
    balance = {"account": "crypto:ledger-btc", "instrument": "BTC", "on_date": "2026-10-26"}
    doc = market_doc(prices=[btc("2026-10-26", "90000")], balances=[{**balance, "quantity": "0.5"}])
    finance.importer.process([Incoming("market.json", doc)])
    finance.refresh_snapshots(force=True)


def test_the_golden_is_stable_and_free_of_words(finance: FinanceDomain, tmp_path: Path) -> None:
    dataset(finance)
    found = golden.build(finance.engine(), AS_OF)
    path = golden.save(found, tmp_path / "g.json")
    text = path.read_text()
    for word in ("Zorglub", "Employeur", "Compte privé", "Ledger", "BCF", IBAN, "CH93"):
        assert word not in text, word
    again = golden.load(path)
    assert again.digest == found.digest
    assert again.sections["valuation"]["by_envelope"]["crypto"] == 4_500_000
    assert again.sections["counts"]["entries"] == 3  # l'ouverture et deux écritures
    assert again.sections["holdings"]["items"][0]["value"] == 4_500_000
    assert {"valuation", "performance", "reconcile", "budget", "snapshots"} <= set(again.sections)
    result = golden.check(finance.engine(), again)
    assert result.ok, result.public()


def test_check_names_each_difference(finance: FinanceDomain) -> None:
    dataset(finance)
    found = golden.build(finance.engine(), AS_OF)
    # un nouveau cours change la valeur du portefeuille, pas le registre ni le budget
    finance.importer.process(
        [Incoming("m2.json", market_doc(prices=[btc("2026-10-27", "100000")]))]
    )
    result = golden.check(finance.engine(), found)
    assert not result.ok
    public = result.public()
    assert {"valuation", "holdings", "counts"} <= set(public["by_section"])
    paths = {d.path for d in result.differences}
    assert "valuation/by_envelope/crypto" in paths
    assert "counts/prices" in paths
    # le compte et les instantanés depuis ce jour valent plus ; le budget ne bouge pas
    assert any(p.startswith("accounts/") and p.endswith("/value") for p in paths)
    assert any(p.startswith("snapshots/") and p.endswith("/net_worth") for p in paths)
    assert not any(p.startswith("budget/") for p in paths)
    example = next(d for d in result.differences if d.path == "valuation/by_envelope/crypto")
    assert (example.before, example.after) == (4_500_000, 5_000_000)


def test_a_table_added_since_the_golden_is_not_a_difference(finance: FinanceDomain) -> None:
    dataset(finance)
    found = golden.build(finance.engine(), AS_OF)
    older = golden.Golden(
        found.as_of,
        found.created_at,
        "0.0.1",
        {
            **found.sections,
            "counts": {k: v for k, v in found.sections["counts"].items() if k != "prices"},
        },
    )
    assert golden.check(finance.engine(), older).ok


def test_a_performance_figure_added_since_the_golden_is_not_a_difference(
    finance: FinanceDomain,
) -> None:
    """Une photo prise avant le plus haut et le plus bas de la courbe (0.18.0) reste comparable,
    et un chiffre qu'elle connaît reste surveillé."""
    dataset(finance)
    found = golden.build(finance.engine(), AS_OF)
    perf = found.sections["performance"]
    assert perf["extremes"]["high"]["value"] >= perf["extremes"]["low"]["value"]
    before = {k: v for k, v in perf.items() if k != "extremes"}
    older = golden.Golden(
        found.as_of, found.created_at, "0.17.0", {**found.sections, "performance": before}
    )
    assert golden.check(finance.engine(), older).ok
    moved = {**before, "contributions": {"moved": True}}
    changed = golden.Golden(
        found.as_of, found.created_at, "0.17.0", {**found.sections, "performance": moved}
    )
    assert not golden.check(finance.engine(), changed).ok


def test_load_refuses_a_foreign_or_tampered_file(finance: FinanceDomain, tmp_path: Path) -> None:
    foreign = tmp_path / "x.json"
    foreign.write_text("{}")
    with pytest.raises(golden.GoldenError):
        golden.load(foreign)
    broken = tmp_path / "y.json"
    broken.write_text("{")
    with pytest.raises(golden.GoldenError):
        golden.load(broken)
    dataset(finance)
    path = golden.save(golden.build(finance.engine(), AS_OF), tmp_path / "g.json")
    raw = json.loads(path.read_text())
    raw["sections"]["valuation"]["net_worth"] += 1
    path.write_text(json.dumps(raw))
    with pytest.raises(golden.GoldenError, match="modifié"):
        golden.load(path)


def run(app: typer.Typer, *args: str) -> tuple[int, str]:
    result = runner.invoke(app, list(args))
    return result.exit_code, result.stdout


def test_cli_save_then_check(finance: FinanceDomain, tmp_path: Path) -> None:
    dataset(finance)
    app = finance.cli()
    assert app is not None
    assert run(app, "golden", "check")[0] == 2  # aucun étalon encore
    code, out = run(
        app, "golden", "save", "--out", str(tmp_path / "g.json"), "--as-of", "2026-10-27"
    )
    assert code == 0, out
    info = json.loads(out)
    assert info["as_of"] == "2026-10-27"
    assert "performance" in info["sections"]
    code, out = run(app, "golden", "check", str(tmp_path / "g.json"))
    assert code == 0, out
    assert json.loads(out)["ok"] is True
    assert run(app, "golden", "save", "--as-of", "pas-une-date")[0] == 2
    # sans chemin : le dernier étalon du dossier de sauvegarde
    code, out = run(app, "golden", "save", "--as-of", "2026-10-27")
    assert code == 0
    assert json.loads(out)["path"].endswith("golden/finance-2026-10-27.json")
    finance.importer.process(
        [Incoming("m2.json", market_doc(prices=[btc("2026-10-27", "100000")]))]
    )
    code, out = run(app, "golden", "check")
    assert code == 1
    report = json.loads(out)
    assert report["differences"] > 0
    assert report["by_section"]["valuation"] >= 1
    assert report["examples"][0]["path"]
