import os
import subprocess
from pathlib import Path
from typing import Any

import pyrage

from hub.core import secrets
from hub.core.context import HubContext
from hub.core.maintenance import backup_all, prune_local_copies, restic_backup, verify
from hub.core.registry import Registry
from hub.core.settings import Backup, Secrets, Settings
from tests.conftest import make_settings


def test_verify_and_backup_include_domains(hub: HubContext, tmp_path: Path) -> None:
    report = verify(hub)
    assert report.ok
    assert report.checks == {"core": "ok", "demo": "ok", "demo.health": "ok"}
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
