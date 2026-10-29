"""Horodatages UTC ISO 8601 en `...Z`. Le fuseau de l'instance (`HUB_TZ`, Europe/Zurich par
défaut) ne sert qu'au jour civil des chiffres et aux horaires."""

import os
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Zurich"


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        raise ValueError("horodatage sans fuseau")
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_iso() -> str:
    return iso(utcnow())


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def local_tz() -> ZoneInfo:
    """Fuseau de l'instance, posé par compose depuis `deploy/.env` ; un nom inconnu échoue."""
    return ZoneInfo(os.environ.get("HUB_TZ") or DEFAULT_TZ)


def local_today() -> date:
    return utcnow().astimezone(local_tz()).date()
