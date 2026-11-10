"""Commande `hub watch-inbox` (chantier S4) : range la racine de `inbox/` par domaine, puis
laisse chaque domaine traiter son dossier. Remplace `hub finance watch-inbox` dans compose.

Un passage qui échoue (base occupée, domaine en faute) ne tue pas la boucle : il est journalisé,
les autres domaines continuent, et le passage suivant réessaie. Au troisième échec de suite d'un
même domaine, une alerte part, une fois, jusqu'au retour à la normale (audit du 10/11, I1)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Annotated, Any

import typer

from hub.core import inbox
from hub.core.context import HubContext
from hub.core.notify import Message
from hub.platform.logging import get_logger

log = get_logger("hub.inbox")

ALERT_AFTER = 3  # échecs de suite avant d'alerter : une base occupée un instant n'alerte pas


class Guard:
    """Compte les échecs de suite par domaine et alerte au seuil, une fois par panne."""

    def __init__(self, hub: HubContext) -> None:
        self.hub = hub
        self.failures: dict[str, int] = {}

    def run(self, name: str, work: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        try:
            done = work()
        except Exception as exc:  # la boucle doit survivre à tout : c'est elle qui importe
            count = self.failures[name] = self.failures.get(name, 0) + 1
            log.error("inbox.failed", domain=name, error=type(exc).__name__, failures=count)
            if count == ALERT_AFTER:
                self.hub.notifier.send(
                    Message(
                        "Boîte d'entrée : traitement en échec",
                        f"Domaine {name} : {count} passages de suite ont échoué "
                        f"({type(exc).__name__}). Les fichiers attendent.",
                        priority="high",
                        tags="warning",
                    )
                )
            return {"failed": 1}
        if self.failures.pop(name, 0) >= ALERT_AFTER:
            self.hub.notifier.send(
                Message("Boîte d'entrée : rétablie", f"Domaine {name} : le traitement a repris.")
            )
        return done


def watch(ready: Callable[[], HubContext]) -> Callable[..., None]:
    def watch_inbox(
        poll: Annotated[int, typer.Option(min=1, help="secondes entre deux passages")] = 30,
        once: Annotated[bool, typer.Option(help="un seul passage")] = False,
    ) -> None:
        """Confie chaque fichier de `inbox/` au domaine qui le réclame, puis fait traiter
        `inbox/<domaine>/` par chacun. Compteurs seuls."""
        hub = ready()
        guard = Guard(hub)
        while True:
            routed = guard.run(
                "inbox", lambda: inbox.route(hub.registry, hub.settings.paths.inbox).public()
            )
            done = {d.name: guard.run(d.name, d.process_inbox) for d in hub.registry}
            if once or routed.get("moved") or any(c.get("files") for c in done.values()):
                typer.echo(json.dumps({**routed, "domains": done}, ensure_ascii=False))
            if once:
                return
            time.sleep(poll)

    return watch_inbox
