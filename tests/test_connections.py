"""Connexions de l'instance (chantier « hub générique », G4) : migration depuis les anciens
collecteurs, validation, secrets chiffrés jamais relus par l'API, vue des services collecteurs
et reprise des fichiers `<nom>.enc.yaml` d'avant G4."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pyrage
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from typer.testing import CliRunner

from hub import cli
from hub.api.app import create_app
from hub.collectors import base
from hub.collectors.runtime import Assigned
from hub.core import collectors, connections
from hub.core.context import HubContext
from hub.core.coredb import CORE_SCRIPT_LOCATION
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.kernel.clock import now_iso
from hub.platform import migrations, secrets
from hub.platform.settings import Secrets, Settings, get_settings
from tests.conftest import bearer, make_settings
from tests.finance.test_finance_api import app_session
from tests.support.demo_domain import DemoDomain

cli_runner = CliRunner()


def _key(tmp_path: Path) -> Path:
    key = tmp_path / "age.key"
    key.write_text(f"# clé de test\n{pyrage.x25519.Identity.generate()}\n")
    return key


@pytest.fixture
def keyed(tmp_path: Path) -> Settings:
    plain = make_settings(tmp_path)
    return plain.model_copy(
        update={"secrets": Secrets(file=tmp_path / "service.enc.yaml", age_key_file=_key(tmp_path))}
    )


@pytest.fixture
def khub(keyed: Settings) -> Iterator[HubContext]:
    ctx = HubContext.build(keyed, Registry([DemoDomain(keyed.paths.data)]))
    ctx.migrate_all()
    yield ctx
    ctx.dispose()


@pytest.fixture
def kclient(khub: HubContext) -> Iterator[TestClient]:
    with TestClient(create_app(khub), base_url="https://hub.example.ts.net") as c:
        yield c


def _token(hub: HubContext, *scopes: str) -> str:
    from hub.core import tokens

    with hub.core.engine.begin() as conn:
        return tokens.create(conn, "test", list(scopes), "system:test")[1]


def test_migration_turns_known_collectors_into_connections(tmp_path: Path) -> None:
    db = tmp_path / "core.db"
    migrations.upgrade(CORE_SCRIPT_LOCATION, db, "0003_profile")
    engine = create_engine(f"sqlite:///{db}")
    with engine.begin() as conn:
        for name in ("bcf", "revolut", "ancien"):
            conn.execute(
                text(
                    "INSERT INTO collector_state (collector, mode, since) "
                    "VALUES (:n, 'enabled', '2026-10-01T00:00:00Z')"
                ),
                {"n": name},
            )
    engine.dispose()
    migrations.upgrade(CORE_SCRIPT_LOCATION, db)
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        found = {c.id: c for c in connections.list_all(conn)}
    engine.dispose()
    assert set(found) == {"bcf", "revolut"}  # un nom inconnu n'est pas repris
    assert found["revolut"].connector == "enable_banking"
    assert found["revolut"].settings == {"aspsp_country": "LT", "aspsp_name": "Revolut"}
    assert found["bcf"].secrets is None
    assert not found["bcf"].ready


def test_create_update_and_validation(khub: HubContext) -> None:
    with khub.core.engine.begin() as conn:
        c = connections.create(
            conn,
            "n26",
            "enable_banking",
            "system:test",
            settings={"aspsp_name": "N26", "aspsp_country": "DE"},
        )
        assert (c.label, c.schedule, c.effective_schedule) == (
            "Banque européenne (Enable Banking)",
            None,
            "15 7,13,19 * * *",
        )
        assert c.spec is not None
        assert c.spec.runner == "api"
        for args, kwargs in [
            (("N26", "bcf"), {}),  # identifiant
            (("catalog", "bcf"), {}),  # segment de route réservé
            (("autre", "inconnu"), {}),
            (("autre", "enable_banking"), {"settings": {"aspsp_name": "X"}}),  # pays manquant
            (("autre", "bcf"), {"settings": {"foo": 1}}),
            (("autre", "bcf"), {"schedule": "chaque matin"}),
            (("autre", "bcf"), {"schedule": "* * * *"}),
            (("autre", "bcf"), {"label": "   "}),
        ]:
            with pytest.raises(Problem) as exc:
                connections.create(conn, *args, "system:test", **kwargs)
            assert exc.value.type == "validation.params"
        with pytest.raises(Problem) as exc:
            connections.create(conn, "n26", "bcf", "system:test")
        assert exc.value.type == "connection.exists"
        # un seul « Cours et cryptos » : un portefeuille s'ajoute dans ses réglages
        connections.create(conn, "market", "market", "system:test")
        with pytest.raises(Problem) as exc:
            connections.create(conn, "base-wallet", "market", "system:test")
        assert exc.value.type == "connection.single"
        assert "ses réglages" in str(exc.value.detail)

        c = connections.update(
            conn, "n26", "system:test", label=" N26  perso ", schedule="0 8 * * *"
        )
        assert (c.label, c.schedule) == ("N26 perso", "0 8 * * *")
        c = connections.update(conn, "n26", "system:test", default_schedule=True)
        assert c.schedule is None
        assert c.label == "N26 perso"
        with pytest.raises(Problem):
            connections.update(conn, "absente", "system:test")


def test_secrets_are_encrypted_and_only_runners_get_them(khub: HubContext) -> None:
    key = khub.settings.secrets.age_key_file
    recipient = secrets.recipient(key)
    with khub.core.engine.begin() as conn:
        connections.create(conn, "bcf", "bcf", "system:test")
        connections.create(conn, "market", "market", "system:test")
        assert [c.id for c in connections.for_runner(conn, "api")] == ["market"]  # sans secret
        assert connections.for_runner(conn, "browser") == []
        with pytest.raises(Problem):
            connections.set_secrets(conn, "bcf", {"contract": "123"}, recipient, "system:test")
        with pytest.raises(Problem):
            connections.set_secrets(
                conn, "bcf", {"contract": "1", "password": "p", "token": "t"}, recipient, "x"
            )
        c = connections.set_secrets(
            conn, "bcf", {"contract": "123", "password": "s3cret"}, recipient, "system:test"
        )
    assert c.ready
    assert c.secrets is not None
    assert b"s3cret" not in c.secrets
    public = json.dumps(c.public())
    assert "s3cret" not in public
    assert c.public()["has_secrets"] is True
    item = c.for_runner()
    assert base.open_secrets(khub.settings, item["secrets"]) == {
        "contract": "123",
        "password": "s3cret",
    }
    assert base.open_secrets(khub.settings, None) == {}


def test_api_manages_connections_without_returning_secrets(
    khub: HubContext, kclient: TestClient
) -> None:
    collector = bearer(_token(khub, "collector"))
    assert kclient.get("/api/collectors/connections", headers=collector).status_code in {401, 403}
    app_session(khub, kclient)
    r = kclient.post(
        "/api/collectors/connections",
        json={"id": "bcf", "connector": "bcf", "label": "Ma banque"},
    )
    assert r.status_code == 201, r.text
    assert (r.json()["runner"], r.json()["ready"]) == ("browser", False)
    assert (
        kclient.post(
            "/api/collectors/connections", json={"id": "bcf", "connector": "bcf"}
        ).status_code
        == 409
    )
    r = kclient.patch("/api/collectors/connections/bcf", json={"schedule": "0 6 * * 1-5"})
    assert r.json()["schedule"] == "0 6 * * 1-5"
    assert r.json()["custom_schedule"] is True
    r = kclient.put(
        "/api/collectors/connections/bcf/secrets",
        json={"values": {"contract": "42", "password": "pw-secret"}},
    )
    assert r.status_code == 200
    assert r.json()["has_secrets"] is True
    assert "pw-secret" not in r.text
    listed = kclient.get("/api/collectors/connections")
    assert [c["id"] for c in listed.json()["items"]] == ["bcf"]
    assert "pw-secret" not in listed.text
    assert kclient.get("/api/collectors").json()["items"][0]["connector"] == "bcf"

    # le service collecteur reçoit le chiffré, et seulement le sien
    assert kclient.get("/api/collectors/runner/browser").status_code in {401, 403}
    items = kclient.get("/api/collectors/runner/browser", headers=collector).json()["items"]
    assert [i["id"] for i in items] == ["bcf"]
    assert "pw-secret" not in json.dumps(items)
    assigned = Assigned.parse(items[0])
    assert assigned.schedule == "0 6 * * 1-5"
    assert base.open_secrets(khub.settings, assigned.secrets)["password"] == "pw-secret"
    assert kclient.get("/api/collectors/runner/api", headers=collector).json()["items"] == []
    assert kclient.get("/api/collectors/runner/autre", headers=collector).status_code == 422

    assert kclient.delete("/api/collectors/connections/bcf").status_code == 204
    assert kclient.delete("/api/collectors/connections/bcf").status_code == 404
    with khub.core.engine.connect() as conn:
        assert collectors.list_all(conn) == []


def _write(path: Path, key: Path, data: dict[str, object]) -> None:
    recipient = secrets.recipient(key)
    path.write_bytes(secrets.encrypt_for(recipient, yaml.safe_dump(data).encode()))


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    key = _key(tmp_path)
    monkeypatch.setenv("HUB_PATHS__DATA", str(tmp_path / "data"))
    monkeypatch.setenv("HUB_SECRETS__AGE_KEY_FILE", str(key))
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


def _cli(*args: str) -> tuple[int, str]:
    result = cli_runner.invoke(cli.app, list(args))
    return result.exit_code, result.stdout


def test_cli_imports_legacy_files_once(tmp_path: Path, cli_env: Path) -> None:
    folder = tmp_path / "old"
    folder.mkdir()
    _write(
        folder / "bcf.enc.yaml",
        cli_env,
        {"collector-bcf": {"token": "hub_ancien", "contract": "1", "password": "pw"}},
    )
    _write(
        folder / "revolut.enc.yaml",
        cli_env,
        {
            "collector-revolut": {
                "token": "hub_ancien",
                "application_id": "app",
                "private_key": "-----BEGIN",
            }
        },
    )
    _write(
        folder / "market.enc.yaml",
        cli_env,
        {
            "collector-market": {
                "token": "hub_ancien",
                "wallets": [{"name": "ledger", "xpub": "zpub"}],
            }
        },
    )
    _write(folder / "ibkr.enc.yaml", cli_env, {"collector-ibkr": {"flex_token": "x"}})
    assert _cli("db", "upgrade")[0] == 0

    code, out = _cli("connections", "import", str(folder))
    assert code == 0, out
    report = json.loads(out)
    assert sorted(report["created"]) == ["bcf", "ibkr", "market", "revolut"]
    assert sorted(report["imported"]) == ["bcf", "market", "revolut"]
    assert report["incomplete"] == ["ibkr"]  # query_id manquant
    assert report["service_files"] == ["collector-api.enc.yaml", "collector-browser.enc.yaml"]
    token = secrets.section(folder / "collector-api.enc.yaml", cli_env, "collector-api")["token"]
    assert token.startswith("hub_")
    assert (folder / "collector-api.enc.yaml").stat().st_mode & 0o777 == 0o600

    code, out = _cli("connections", "import", str(folder))
    again = json.loads(out)
    assert (again["created"], again["imported"], again["service_files"]) == ([], [], [])
    assert sorted(again["kept"]) == ["bcf", "market", "revolut"]

    listed = [json.loads(line) for line in _cli("connections", "list")[1].splitlines()]
    by_id = {c["id"]: c for c in listed}
    assert by_id["revolut"]["settings"] == {"aspsp_country": "LT", "aspsp_name": "Revolut"}
    assert by_id["revolut"]["label"] == "Revolut"
    assert by_id["ibkr"]["ready"] is False
    assert "pw" not in json.dumps(listed).replace("password", "")

    # le service lit son jeton dans son propre fichier
    settings = get_settings().model_copy(
        update={"secrets": Secrets(file=folder / "collector-api.enc.yaml", age_key_file=cli_env)}
    )
    assert base.service_token(settings, "api") == token
    assert base.service_token(settings, "browser") is None


def test_cli_add_set_secrets_remove(tmp_path: Path, cli_env: Path) -> None:
    assert _cli("db", "upgrade")[0] == 0
    assert "enable_banking" in _cli("connections", "catalog")[1]
    code, out = _cli(
        "connections",
        "add",
        "n26",
        "enable_banking",
        "--settings",
        '{"aspsp_name": "N26", "aspsp_country": "DE"}',
    )
    assert code == 0, out
    assert json.loads(out)["ready"] is False
    assert _cli("connections", "add", "n26", "bcf")[0] != 0
    assert _cli("connections", "add", "x2", "bcf", "--settings", "[1]")[0] == 2
    code, out = _cli("connections", "set", "n26", "--label", "N26", "--schedule", "0 7 * * *")
    assert json.loads(out)["label"] == "N26"
    assert _cli("connections", "set", "n26", "--schedule", "jamais")[0] != 0

    values = tmp_path / "n26.yaml"
    values.write_text("application_id: app\nprivate_key: clé\n")
    code, out = _cli("connections", "secrets", "n26", "--file", str(values))
    assert code == 0, out
    assert json.loads(out)["ready"] is True
    assert "clé" not in out
    result = cli_runner.invoke(cli.app, ["connections", "secrets", "n26"], input="app\nclé2\n")
    assert result.exit_code == 0
    assert "clé2" not in result.stdout
    piped = cli_runner.invoke(
        cli.app,
        ["connections", "secrets", "n26", "--file", "-"],
        input="application_id: app\nprivate_key: clé3\n",
    )
    assert piped.exit_code == 0, piped.output
    assert _cli("connections", "secrets", "absente")[0] != 0
    assert _cli("connections", "remove", "n26")[0] == 0
    assert _cli("connections", "remove", "n26")[0] != 0
    assert _cli("connections", "list")[1] == ""


# --- G5 : consentement depuis l'app, portefeuilles ----------------------------------------------


def test_app_requests_a_link_and_sees_the_url(khub: HubContext, kclient: TestClient) -> None:
    recipient = secrets.recipient(khub.settings.secrets.age_key_file)
    with khub.core.engine.begin() as conn:
        connections.create(
            conn,
            "n26",
            "enable_banking",
            "system:test",
            settings={"aspsp_name": "N26", "aspsp_country": "DE"},
        )
        connections.create(conn, "bcf", "bcf", "system:test")
    collector = bearer(_token(khub, "collector"))
    app_session(khub, kclient)
    assert kclient.post("/api/collectors/n26/link", json={}).status_code == 422  # sans secrets
    assert kclient.post("/api/collectors/bcf/link", json={}).status_code == 422
    with khub.core.engine.begin() as conn:
        connections.set_secrets(
            conn, "n26", {"application_id": "a", "private_key": "k"}, recipient, "x"
        )
    r = kclient.post("/api/collectors/n26/link", json={})
    assert (r.json()["link_requested"], r.json()["link_url"]) == (True, None)
    assert kclient.get("/api/collectors/n26", headers=collector).json()["link_requested"]
    # l'app ne peut pas poser l'adresse ; le collecteur, si
    put = {"url": "https://bank.example/auth?state=x"}
    assert kclient.put("/api/collectors/n26/link-url", json=put).status_code in {401, 403}
    bad = {"url": "http://bank.example/auth"}
    assert (
        kclient.put("/api/collectors/n26/link-url", json=bad, headers=collector).status_code == 422
    )
    r = kclient.put("/api/collectors/n26/link-url", json=put, headers=collector)
    assert (r.json()["link_requested"], r.json()["link_url"]) == (False, put["url"])
    state = next(s for s in kclient.get("/api/collectors").json()["items"] if s["name"] == "n26")
    assert state["link_url"] == put["url"]
    r = kclient.put("/api/collectors/n26/link-url", json={"url": None}, headers=collector)
    assert r.json()["link_url"] is None


def test_app_refreshes_a_connection_or_all_of_them(khub: HubContext, kclient: TestClient) -> None:
    """« Actualiser » : un run hors horaire, pour une connexion prête et active seulement ;
    le run déclaré par le service efface la demande."""
    recipient = secrets.recipient(khub.settings.secrets.age_key_file)
    with khub.core.engine.begin() as conn:
        connections.create(conn, "market", "market", "system:test")  # sans secret exigé
        connections.create(conn, "bcf", "bcf", "system:test")  # identifiants à donner
        connections.create(conn, "ibkr", "ibkr", "system:test")
        connections.set_secrets(conn, "ibkr", {"flex_token": "t", "query_id": "q"}, recipient, "x")
    collector = bearer(_token(khub, "collector"))
    assert kclient.post("/api/collectors/market/refresh", headers=collector).status_code == 403
    app_session(khub, kclient)
    assert kclient.post("/api/collectors/bcf/refresh", json={}).status_code == 422
    r = kclient.post("/api/collectors/market/refresh", json={})
    assert r.status_code == 200
    assert r.json()["run_requested"] is True
    assert kclient.post("/api/collectors/market/refresh", json={}).json()["run_requested"]
    assert kclient.get("/api/collectors/market", headers=collector).json()["run_requested"]
    # un contrôle déclaré ne vaut pas actualisation ; un run, si
    now = now_iso()
    run = {"started_at": now, "ended_at": now}
    check = {**run, "kind": "check", "outcome": "ok"}
    r = kclient.post("/api/collectors/market/runs", json=check, headers=collector)
    assert r.json()["run_requested"] is True
    r = kclient.post(
        "/api/collectors/market/runs", json={**run, "outcome": "nothing_new"}, headers=collector
    )
    assert r.json()["run_requested"] is False
    # une connexion désactivée ne s'actualise pas ; « tout » saute aussi les non prêtes
    assert kclient.post("/api/collectors/ibkr/mode", json={"mode": "disabled"}).status_code == 200
    r = kclient.post("/api/collectors/ibkr/refresh", json={})
    assert r.status_code == 409
    assert r.json()["type"].endswith("collector.not_enabled")
    kclient.post("/api/collectors/ibkr/mode", json={"mode": "enabled"})
    items = kclient.post("/api/collectors/refresh", json={}).json()["items"]
    asked = {s["name"]: s["run_requested"] for s in items}
    assert asked == {"bcf": False, "ibkr": True, "market": True}
    assert "refresh" in connections.RESERVED  # `POST /collectors/refresh` reste à l'app


def test_wallet_settings_are_checked(khub: HubContext) -> None:
    btc = {"account": "crypto:ledger", "asset": "btc", "xpub": "zpub6r…", "script": "wpkh"}
    eth = {
        "account": "crypto:metamask",
        "asset": "ETH",
        "addresses": ["0x" + "a" * 40],
        "networks": ["ethereum", "base"],
    }
    with khub.core.engine.begin() as conn:
        c = connections.create(
            conn, "market", "market", "system:test", settings={"wallets": [btc, eth]}
        )
        assert c.settings["wallets"][0]["asset"] == "BTC"
        assert c.settings["wallets"][0]["script"] == "wpkh"  # les champs en plus restent
        for wrong in (
            "pas une liste",
            [{"account": "ledger", "asset": "BTC", "addresses": ["bc1q"]}],
            [{"account": "crypto:x", "asset": "DOGE", "addresses": ["D"]}],
            [{"account": "crypto:x", "asset": "BTC"}],
            [{"account": "crypto:x", "asset": "ETH", "xpub": "xpub6…"}],
            [{"account": "crypto:x", "asset": "BTC", "xpub": "xprv9…"}],
            [{"account": "crypto:x", "asset": "SOL", "addresses": [1]}],
            [{"account": "crypto:x", "asset": "ETH", "addresses": ["0x"], "networks": ["mars"]}],
            [{"account": "crypto:x", "asset": "SOL", "addresses": ["S"], "networks": ["base"]}],
        ):
            with pytest.raises(Problem):
                connections.update(conn, "market", "system:test", settings={"wallets": wrong})


def test_import_moves_wallets_out_of_secrets(tmp_path: Path, cli_env: Path) -> None:
    folder = tmp_path / "old"
    folder.mkdir()
    wallets = [{"account": "crypto:ledger", "asset": "BTC", "xpub": "zpub6r…"}]
    _write(
        folder / "market.enc.yaml",
        cli_env,
        {"collector-market": {"token": "hub_x", "coingecko_key": "cg", "wallets": wallets}},
    )
    assert _cli("db", "upgrade")[0] == 0
    assert _cli("connections", "import", str(folder), "--no-service-files")[0] == 0
    market = json.loads(_cli("connections", "list")[1])
    assert market["settings"]["wallets"] == wallets
    assert market["has_secrets"] is True  # la clé CoinGecko reste chiffrée
    settings = get_settings()
    hub = HubContext.build(settings)
    with hub.core.engine.connect() as conn:
        blob = connections.require(conn, "market").secrets
    hub.dispose()
    assert blob is not None
    assert json.loads(secrets.decrypt_with(cli_env, blob)) == {"coingecko_key": "cg"}

    # une installation de G4 déjà reprise : les portefeuilles sortent au déploiement suivant
    with HubContext.build(settings).core.engine.begin() as conn:
        connections.update(conn, "market", "x", settings={})
        connections.set_secrets(
            conn, "market", {"wallets": wallets}, secrets.recipient(cli_env), "x"
        )
    out = json.loads(_cli("connections", "import", str(folder), "--no-service-files")[1])
    assert out["kept"] == ["market"]
    market = json.loads(_cli("connections", "list")[1])
    assert (market["settings"]["wallets"], market["has_secrets"]) == (wallets, False)
