import json
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pyrage
import pytest

from hub.core.context import HubContext
from hub.core.maintenance import (
    backup_all,
    backup_paths,
    prune_local_copies,
    restic_backup,
    restic_check,
    verify,
)
from hub.core.registry import Registry
from hub.platform import secrets
from hub.platform.settings import Backup, Secrets, Settings
from tests.conftest import make_settings


def test_verify_and_backup_include_domains(hub: HubContext, tmp_path: Path) -> None:
    report = verify(hub)
    assert report.ok
    assert report.checks == {
        "core": "ok",
        "core.ledger": "ok",
        "demo": "ok",
        "demo.verify": "ok",
        "demo.protected": "ok",
    }
    files = backup_all(hub, tmp_path / "b", "s")
    assert sorted(f.name for f in files) == ["core-s.db", "demo-s.db"]


def test_verify_fails_on_missing_base(settings: Settings) -> None:
    hub = HubContext.build(settings, Registry())
    assert not verify(hub).ok
    hub.dispose()


def test_prune_local_copies(tmp_path: Path) -> None:
    old = tmp_path / "core-2020-01-01.db"
    new = tmp_path / "core-2099-01-01.db"
    keep = tmp_path / "core-predeploy-v1.db"
    for f in (old, new, keep):
        f.write_text("x")
    os.utime(old, (0, 0))
    assert prune_local_copies(tmp_path, 7) == 1
    assert not old.exists()
    assert new.exists()
    assert keep.exists()


def _hub_with_secrets(tmp_path: Path, plain: bytes) -> HubContext:
    identity = pyrage.x25519.Identity.generate()
    key = tmp_path / "age.key"
    key.write_text(str(identity))
    enc = tmp_path / "secrets.enc.yaml"
    enc.write_bytes(secrets.encrypt_for(str(identity.to_public()), plain))
    base = make_settings(tmp_path)
    settings = base.model_copy(
        update={
            "secrets": Secrets(file=enc, age_key_file=key),
            "backup": Backup(restic_local=tmp_path / "restic", replica=None),
        }
    )
    return HubContext.build(settings, Registry())


def test_restic_runs_each_repository(tmp_path: Path) -> None:
    hub = _hub_with_secrets(tmp_path, b"restic:\n  password: pw\n  repository_offsite: sftp:x\n")
    hub.settings.paths.backup.mkdir(parents=True)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 1 if cmd[3] == "cat" else 0)

    done = restic_backup(hub, run=fake)
    assert done == [str(tmp_path / "restic"), "sftp:x"]
    verbs = [c[0][3] for c in calls]
    assert verbs == ["cat", "init", "backup", "forget"] * 2
    assert all(kw["env"]["RESTIC_PASSWORD"] == "pw" for _, kw in calls)
    assert "--prune" in calls[3][0]
    hub.dispose()


def test_restic_skipped_without_password(tmp_path: Path) -> None:
    hub = _hub_with_secrets(tmp_path, b"other: {}\n")
    assert restic_backup(hub, run=lambda *a, **k: None) == []  # type: ignore[arg-type,return-value]
    hub.dispose()


def test_predeploy_copies_keep_the_last_three_versions(tmp_path: Path) -> None:
    # audit du 10/11, D1 : une copie complète des bases par version, jamais purgée
    for age, tag in enumerate(("v5", "v4", "v3", "v2", "v1")):
        for base in ("core", "finance"):
            f = tmp_path / f"{base}-predeploy-{tag}.db"
            f.write_text("x")
            os.utime(f, (1_000_000 - age, 1_000_000 - age))
    assert prune_local_copies(tmp_path, 7) == 4
    assert sorted(f.name for f in tmp_path.iterdir()) == [
        f"{base}-predeploy-{tag}.db" for base in ("core", "finance") for tag in ("v3", "v4", "v5")
    ]


def test_verify_writes_its_state_for_the_health_check(hub: HubContext) -> None:
    report = verify(hub)
    state = json.loads((hub.settings.paths.data / "verify.json").read_text())
    assert state["ok"] is True
    assert state["checks"] == report.checks
    assert state["warnings"] == {}
    assert report.failed == []


def test_restic_takes_the_configuration_and_marks_its_run(tmp_path: Path) -> None:
    # audit du 10/11, K1 : les secrets chiffrés partent avec les bases ; identifiants du dépôt
    # distant dans l'environnement de restic seulement
    plain = (
        b"restic:\n  password: pw\n  repository_offsite: s3:x\n  env:\n    AWS_ACCESS_KEY_ID: k\n"
    )
    hub = _hub_with_secrets(tmp_path, plain)
    hub.settings.paths.backup.mkdir(parents=True)
    assert str(hub.settings.secrets.file) in backup_paths(hub)
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0)

    assert len(restic_backup(hub, run=fake)) == 2
    backup = next(cmd for cmd, _ in calls if cmd[3] == "backup")
    assert str(hub.settings.secrets.file) in backup
    assert all(kw["env"]["AWS_ACCESS_KEY_ID"] == "k" for _, kw in calls)
    mark = json.loads((hub.settings.paths.backup / "restic.last.json").read_text())
    assert mark["repositories"] == 2
    assert mark["offsite"] is True
    hub.dispose()


def test_a_failing_repository_does_not_stop_the_other_but_fails_the_run(tmp_path: Path) -> None:
    hub = _hub_with_secrets(tmp_path, b"restic:\n  password: pw\n  repository_offsite: s3:x\n")
    hub.settings.paths.backup.mkdir(parents=True)
    backed: list[str] = []

    def fake(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        if cmd[3] == "backup":
            if cmd[2] != "s3:x":
                raise subprocess.CalledProcessError(1, cmd)
            backed.append(cmd[2])
        return subprocess.CompletedProcess(cmd, 0)

    with pytest.raises(RuntimeError, match="1 dépôt"):
        restic_backup(hub, run=fake)
    assert backed == ["s3:x"]  # le second dépôt a bien reçu sa sauvegarde
    assert not (hub.settings.paths.backup / "restic.last.json").exists()
    hub.dispose()


def _copy(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE t (x)")


def test_restic_check_restores_the_latest_copies_and_compares(tmp_path: Path) -> None:
    hub = _hub_with_secrets(tmp_path, b"restic:\n  password: pw\n")
    backup = hub.settings.paths.backup
    backup.mkdir(parents=True)
    for name in ("core-2026-11-09.db", "core-2026-11-10.db", "finance-2026-11-10.db"):
        _copy(backup / name)
    verbs: list[str] = []
    tamper = False

    def fake(cmd: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        verbs.append(cmd[3])
        if cmd[3] == "restore":
            target = Path(cmd[cmd.index("--target") + 1])
            wanted = [Path(cmd[i + 1]) for i, a in enumerate(cmd) if a == "--include"]
            assert sorted(p.name for p in wanted) == ["core-2026-11-10.db", "finance-2026-11-10.db"]
            for src in wanted:
                out = target / str(src).lstrip("/")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"autre chose" if tamper else src.read_bytes())
        return subprocess.CompletedProcess(cmd, 0)

    assert restic_check(hub, run=fake) == {"repositories": 1, "databases": 2}
    assert verbs == ["check", "restore"]
    assert (backup / "restic.check.json").exists()
    assert not list(backup.glob(".restore-test-*"))  # rien ne reste derrière l'essai
    tamper = True
    with pytest.raises(RuntimeError, match="différente"):
        restic_check(hub, run=fake)
    assert not list(backup.glob(".restore-test-*"))
    hub.dispose()


def test_restic_check_needs_something_to_check(tmp_path: Path) -> None:
    hub = _hub_with_secrets(tmp_path, b"restic:\n  password: pw\n")
    hub.settings.paths.backup.mkdir(parents=True)
    with pytest.raises(RuntimeError, match="aucune copie"):
        restic_check(hub, run=lambda *a, **k: None)  # type: ignore[arg-type,return-value]
    bare = _hub_with_secrets(tmp_path, b"other: {}\n")
    with pytest.raises(RuntimeError, match="mot de passe"):
        restic_check(bare, run=lambda *a, **k: None)  # type: ignore[arg-type,return-value]
    hub.dispose()
    bare.dispose()
