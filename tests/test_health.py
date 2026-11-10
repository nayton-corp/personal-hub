"""Audit du 10/11, O1 et D1 : le contrôle de santé alerte ce qui cloche (disque, réplique,
sauvegardes, contrôle de nuit, avertissements des domaines), rappelle, puis dit « réglé »."""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pyrage
import pytest

from hub.core import health
from hub.core.context import HubContext
from hub.core.domain import Health
from hub.core.notify import Message
from hub.platform import secrets
from hub.platform.settings import Backup, Monitoring, Secrets

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class Inbox:
    """Remplace ntfy : garde les titres envoyés."""

    def __init__(self) -> None:
        self.titles: list[str] = []
        self.up = True

    def send(self, msg: Message) -> bool:
        if self.up:
            self.titles.append(msg.title)
        return self.up


@pytest.fixture
def box(hub: HubContext, tmp_path: Path) -> Inbox:
    """Une instance saine : copies et passage restic du jour, contrôle de nuit récent."""
    box = Inbox()
    hub.notifier = box  # type: ignore[assignment]
    hub.settings = hub.settings.model_copy(
        update={"backup": Backup(restic_local=tmp_path / "restic", replica=tmp_path / "replica")}
    )
    backup = hub.settings.paths.backup
    backup.mkdir(parents=True, exist_ok=True)
    stamp = NOW.timestamp() - 3600
    for name, body in (
        ("core-2026-11-10.db", "x"),
        (health.RESTIC_MARK, json.dumps({"offsite": True})),
    ):
        (backup / name).write_text(body)
        os.utime(backup / name, (stamp, stamp))
    verify = hub.settings.paths.data / health.VERIFY_STATE
    verify.write_text(json.dumps({"at": "2026-11-10T11:00:00.000Z", "ok": True, "warnings": {}}))
    return box


def keys(hub: HubContext, now: datetime = NOW) -> list[str]:
    return health.run(hub, now)["findings"]


def test_a_healthy_instance_says_nothing(hub: HubContext, box: Inbox) -> None:
    result = health.run(hub, NOW)
    assert result == {"ok": True, "findings": [], "alerted": 0, "heartbeat": False}
    assert box.titles == []


def test_full_disk_alerts_once_reminds_daily_then_says_fixed(
    hub: HubContext, box: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "_percent", lambda _p: 91)
    assert keys(hub) == ["disk:données"]
    assert keys(hub, NOW + timedelta(hours=1)) == ["disk:données"]
    assert box.titles == ["Disque presque plein"]  # pas une alerte par heure
    keys(hub, NOW + timedelta(hours=25))
    assert box.titles == ["Disque presque plein"] * 2  # un rappel par jour
    monkeypatch.setattr(health, "_percent", lambda _p: 40)
    assert keys(hub, NOW + timedelta(hours=26)) == []
    assert box.titles[-1] == "Réglé : Disque presque plein"


def test_an_alert_that_could_not_be_sent_is_tried_again(
    hub: HubContext, box: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(health, "_percent", lambda _p: 91)
    box.up = False
    assert health.run(hub, NOW)["alerted"] == 0
    box.up = True
    assert health.run(hub, NOW + timedelta(hours=1))["alerted"] == 1


def test_stale_backup_restic_and_night_check(hub: HubContext, box: Inbox) -> None:
    later = NOW + timedelta(hours=40)
    assert keys(hub, later) == ["backup", "restic", "verify:late"]
    assert box.titles == [
        "Sauvegarde en retard",
        "Sauvegarde chiffrée en retard",
        "Contrôle de nuit en retard",
    ]


def test_a_new_instance_gets_a_day_before_being_told_it_has_no_backup(
    hub: HubContext, box: Inbox
) -> None:
    for f in hub.settings.paths.backup.iterdir():
        f.unlink()
    (hub.settings.paths.data / health.VERIFY_STATE).unlink()
    assert keys(hub) == []  # premier passage : le délai court d'ici
    assert keys(hub, NOW + timedelta(hours=37)) == ["backup", "restic", "verify:late"]


def test_no_offsite_copy_is_reminded_weekly(hub: HubContext, box: Inbox) -> None:
    mark = hub.settings.paths.backup / health.RESTIC_MARK
    mark.write_text(json.dumps({"offsite": False}))
    os.utime(mark, (NOW.timestamp(), NOW.timestamp()))
    assert keys(hub) == ["offsite"]
    keys(hub, NOW + timedelta(hours=20))  # la copie du jour est toujours là : rien d'autre
    assert box.titles == ["Pas de sauvegarde hors de la machine"]


def test_replica_behind_its_database(hub: HubContext, box: Inbox) -> None:
    replica = hub.settings.backup.replica
    assert replica is not None
    for name in ("core", "demo"):
        (replica / f"{name}.db" / "ltx").mkdir(parents=True)
        (replica / f"{name}.db" / "ltx" / "0001.ltx").write_text("x")
    assert keys(hub) == []
    old = NOW.timestamp() - 8 * 3600
    os.utime(replica / "demo.db" / "ltx" / "0001.ltx", (old, old))
    os.utime(hub.settings.db_path("demo"), (NOW.timestamp(), NOW.timestamp()))
    assert keys(hub) == ["replica:demo"]


def test_verify_warnings_and_domain_warnings_reach_the_phone(
    hub: HubContext, box: Inbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = hub.settings.paths.data / health.VERIFY_STATE
    state.write_text(
        json.dumps(
            {
                "at": "2026-11-10T11:00:00.000Z",
                "ok": True,
                "warnings": {"finance": ["figures.crypto_gap"]},
            }
        )
    )
    demo = next(iter(hub.registry))
    monkeypatch.setattr(
        demo, "health", lambda: Health(True, "ok", 1, warnings=("imports.stuck",)), raising=False
    )
    assert keys(hub) == ["demo:imports.stuck", "verify:finance:figures.crypto_gap"]
    assert "Contrôle des chiffres : écart à regarder" in box.titles


def test_heartbeat_only_when_all_is_well(
    hub: HubContext, box: Inbox, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = pyrage.x25519.Identity.generate()
    key = tmp_path / "age.key"
    key.write_text(str(identity))
    enc = tmp_path / "secrets.enc.yaml"
    plain = b"monitoring:\n  heartbeat_url: https://ping.example/abc\n"
    enc.write_bytes(secrets.encrypt_for(str(identity.to_public()), plain))
    hub.settings = hub.settings.model_copy(
        update={"secrets": Secrets(file=enc, age_key_file=key), "monitoring": Monitoring()}
    )
    pinged: list[str] = []
    assert health.run(hub, NOW, pinged.append)["heartbeat"] is True
    assert pinged == ["https://ping.example/abc"]
    monkeypatch.setattr(health, "_percent", lambda _p: 99)
    assert health.run(hub, NOW, pinged.append)["heartbeat"] is False
    assert len(pinged) == 1  # un hub qui a un souci ne dit pas « tout va bien »

    def down(_url: str) -> None:
        raise OSError

    monkeypatch.setattr(health, "_percent", lambda _p: 10)
    assert health.run(hub, NOW + timedelta(hours=2), down)["heartbeat"] is False


def test_heartbeat_needs_an_https_address(hub: HubContext) -> None:
    fake: Any = SimpleNamespace(settings=hub.settings)
    assert health.heartbeat(fake, lambda _u: None) is False  # pas de secrets : rien n'est envoyé


def test_a_declared_expiry_is_announced_two_weeks_ahead(hub: HubContext, box: Inbox) -> None:
    from datetime import date

    hub.settings = hub.settings.model_copy(
        update={
            "monitoring": Monitoring(
                expiries={"jeton GHCR": date(2026, 11, 20), "autre": date(2027, 6, 1)}
            )
        }
    )
    assert keys(hub) == ["expiry:jeton GHCR"]
    assert box.titles == ["Échéance proche"]
    keys(hub, NOW + timedelta(days=3))
    assert box.titles.count("Échéance proche") == 1  # un rappel par semaine, pas par jour
    keys(hub, NOW + timedelta(days=8))
    assert box.titles.count("Échéance proche") == 2


def test_expiries_short_form_never_stops_the_hub() -> None:
    from datetime import date

    parsed = Monitoring(expiries="jeton GHCR du Pi=2027-11-01; clé=bientôt;;").expiries  # type: ignore[arg-type]
    assert parsed == {"jeton GHCR du Pi": date(2027, 11, 1), "clé": date.min}
    assert Monitoring(expiries="").expiries == {}  # type: ignore[arg-type]
    assert Monitoring(expiries='{"a": "2027-01-01"}').expiries == {"a": date(2027, 1, 1)}  # type: ignore[arg-type]
