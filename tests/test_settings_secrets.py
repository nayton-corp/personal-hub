from pathlib import Path

import pyrage
import pytest

from hub.platform import secrets
from hub.platform.settings import Server, Settings


def test_toml_then_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    toml = tmp_path / "settings.toml"
    toml.write_text(
        '[paths]\ndata = "/x/data"\n[server]\nbind = "0.0.0.0:9000"\n'
        'public_origin = "https://hub.t.ts.net"\n[finance]\nimport_auto_apply = false\n'
    )
    monkeypatch.setenv("HUB_SETTINGS", str(toml))
    monkeypatch.setenv("HUB_SERVER__BIND", "0.0.0.0:8710")
    s = Settings()
    assert s.paths.data == Path("/x/data")
    assert s.server.port == 8710
    assert s.server.host == "0.0.0.0"
    assert s.server.rp_id == "hub.t.ts.net"
    assert s.server.secure
    assert s.domain("finance") == {"import_auto_apply": False}
    assert s.domain("absent") == {}
    assert s.db_path("core") == Path("/x/data/core.db")


def test_origin_must_be_an_origin() -> None:
    with pytest.raises(ValueError, match="origine"):
        Server(public_origin="https://hub.t.ts.net/app")
    assert Server(public_origin="http://localhost:8710/").public_origin == "http://localhost:8710"
    assert not Server(public_origin="http://localhost:8710").secure


def test_secrets_roundtrip(tmp_path: Path) -> None:
    identity = pyrage.x25519.Identity.generate()
    key = tmp_path / "age.key"
    key.write_text(f"# created: test\n{identity}\n")
    enc = tmp_path / "secrets.enc.yaml"
    enc.write_bytes(
        secrets.encrypt_for(
            str(identity.to_public()), b"restic:\n  password: pw\nbcf:\n  contract: '1'\n"
        )
    )
    assert secrets.section(enc, key, "restic") == {"password": "pw"}
    assert secrets.load(tmp_path / "absent", key) == {}
    with pytest.raises(secrets.SecretsError):
        secrets.load(enc, tmp_path / "nokey")
    other = tmp_path / "other.key"
    other.write_text(str(pyrage.x25519.Identity.generate()))
    with pytest.raises(secrets.SecretsError):
        secrets.load(enc, other)
    bad = tmp_path / "bad.key"
    bad.write_text("nothing")
    with pytest.raises(secrets.SecretsError):
        secrets.load(enc, bad)
