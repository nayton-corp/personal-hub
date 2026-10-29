"""Première installation (chantier « hub générique », G6) : `hub init` prépare clé age, secrets
chiffrés, dossiers et `deploy/.env`, sans jamais remplacer ce qui existe."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hub import cli
from hub.core import install, profile
from hub.platform import secrets

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deploy" / ".env.example"
runner = CliRunner()


def choices(tmp_path: Path, **kw: str) -> install.Choices:
    return install.Choices(tmp_path / "config", tmp_path / "home", **kw)


def parse_env(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key] = value
    return out


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_init_prepares_a_machine(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    c = choices(tmp_path, timezone="Europe/Paris", currency="eur", country="fr")
    report = install.run(c, env_file, TEMPLATE)
    key = tmp_path / "config" / "age.key"
    assert mode(key) == 0o400
    assert mode(tmp_path / "config") == 0o700
    assert report.public_key == secrets.recipient(key)
    conf = secrets.section(tmp_path / "config" / "secrets.enc.yaml", key, "restic")
    assert len(conf["password"]) >= 40
    assert conf["password"] not in env_file.read_text()
    for sub in ("inbox", "backup/litestream", "backup/restic"):
        assert (tmp_path / "home" / sub).is_dir()
    assert (tmp_path / "config" / "collectors").is_dir()
    env = parse_env(env_file)
    assert mode(env_file) == 0o600
    assert env["HUB_TZ"] == "Europe/Paris"
    assert env["HUB_CURRENCY"] == "EUR"
    assert env["HUB_COUNTRY"] == "FR"
    assert env["HUB_AGE_KEY"] == str(key)
    assert env["HUB_INBOX"] == str(tmp_path / "home" / "inbox")
    assert env["COMPOSE_PROFILES"] == "collectors"
    assert env["TS_AUTHKEY"] == ""
    # tous les chemins du modèle sont remplis, aucun ne reste en exemple
    assert not [k for k, v in env.items() if "/chemin/" in v]
    assert set(env) == set(parse_env(TEMPLATE))


def test_init_never_replaces_anything(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    first = install.run(choices(tmp_path), env_file, TEMPLATE)
    before = {p: Path(p).read_bytes() for p in first.created if Path(p).is_file()}
    env_file.write_text("HUB_TAG=v1\n")
    again = install.run(choices(tmp_path, currency="EUR"), env_file, TEMPLATE)
    assert again.created == []
    assert again.public_key == first.public_key
    assert env_file.read_text() == "HUB_TAG=v1\n"
    for p, data in before.items():
        if p != str(env_file):
            assert Path(p).read_bytes() == data


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("timezone", "Mars/Olympus", "fuseau"),
        ("currency", "XXX", "devise"),
        ("country", "Suisse", "pays"),
        ("origin", "http://hub.local", "origine"),
    ],
)
def test_init_refuses_bad_choices(tmp_path: Path, field: str, value: str, message: str) -> None:
    with pytest.raises(install.InitError, match=message):
        install.run(choices(tmp_path, **{field: value}), tmp_path / ".env", TEMPLATE)
    assert not (tmp_path / "config").exists()


def test_init_refuses_relative_folders(tmp_path: Path) -> None:
    c = install.Choices(Path("config"), tmp_path / "home")
    with pytest.raises(install.InitError, match="absolus"):
        install.run(c, tmp_path / ".env", TEMPLATE)


def test_render_env_keeps_comments_and_unknown_keys() -> None:
    out = install.render_env("# note\nA=1\nB=2\n\nC=\n", {"A": "x", "C": "z"})
    assert out == "# note\nA=x\nB=2\n\nC=z\n"


def test_cli_init(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    args = ["init", "--config", str(tmp_path / "c"), "--home", str(tmp_path / "h")]
    args += ["--env", str(env_file), "--template", str(TEMPLATE), "--country", "BE"]
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert "clé publique age : age1" in result.stdout
    assert "AGE-SECRET-KEY" not in result.stdout
    assert parse_env(env_file)["HUB_COUNTRY"] == "BE"
    result = runner.invoke(cli.app, [*args[:4], "--tz", "Nowhere/Here"])
    assert result.exit_code == 2


def test_country_of_an_instance_without_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    assert profile.default().country == "CH"
    monkeypatch.setenv("HUB_COUNTRY", "fr")
    assert profile.default().country == "FR"
