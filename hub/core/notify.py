"""Notifications ntfy : textes génériques (« Collecte BCF : action requise »), jamais un montant.

Le sujet ntfy vaut un mot de passe (qui le connaît lit les messages) : il vit dans
`secrets.enc.yaml` (section `ntfy`, clé `topic`), ou dans le fichier `notify.ntfy_topic_file`.
Sans sujet, rien n'est envoyé et seul le journal en garde la trace.
"""

from __future__ import annotations

import base64
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from hub.core import secrets
from hub.core.logging import get_logger
from hub.core.settings import Settings

log = get_logger("hub.notify")

Priority = Literal["default", "high", "urgent"]


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    priority: Priority = "default"
    tags: str = ""


Sender = Callable[[str, Message], None]


def topic(settings: Settings) -> str | None:
    try:
        value = secrets.section(settings.secrets.file, settings.secrets.age_key_file, "ntfy").get(
            "topic"
        )
    except secrets.SecretsError:
        value = None
    if isinstance(value, str) and value.strip():
        return value.strip()
    path = settings.notify.ntfy_topic_file
    if path is not None and path.is_file():
        return path.read_text().strip() or None
    return None


def _post(url: str, msg: Message) -> None:  # pragma: no cover - réseau
    request = urllib.request.Request(  # noqa: S310 - URL des réglages, https
        url,
        data=msg.body.encode(),
        method="POST",
        headers={
            # en-têtes HTTP en latin-1 : le titre passe par l'encodage RFC 2047 de ntfy
            "Title": "=?UTF-8?B?" + _b64(msg.title) + "?=",
            "Priority": msg.priority,
            "Tags": msg.tags,
        },
    )
    with urllib.request.urlopen(request, timeout=10):  # noqa: S310
        pass


def _b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class Notifier:
    def __init__(self, settings: Settings, sender: Sender | None = None) -> None:
        self.settings = settings
        self.sender = sender or _post
        self.sent: list[Message] = []

    def send(self, msg: Message) -> bool:
        target = topic(self.settings)
        if target is None:
            log.info("notify.skipped", reason="no_topic", title=msg.title)
            return False
        url = f"{self.settings.notify.ntfy_url.rstrip('/')}/{target}"
        try:
            self.sender(url, msg)
        except Exception as exc:  # une notification perdue ne doit rien casser
            log.warning("notify.failed", error=type(exc).__name__)
            return False
        self.sent.append(msg)
        log.info("notify.sent", title=msg.title, priority=msg.priority)
        return True
