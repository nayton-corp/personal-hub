"""Commande `hub watch-inbox` (chantier S4) : range la racine de `inbox/` par domaine, puis
laisse chaque domaine traiter son dossier. Remplace `hub finance watch-inbox` dans compose."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Annotated

import typer

from hub.core import inbox
from hub.core.context import HubContext


def watch(ready: Callable[[], HubContext]) -> Callable[..., None]:
    def watch_inbox(
        poll: Annotated[int, typer.Option(min=1, help="secondes entre deux passages")] = 30,
        once: Annotated[bool, typer.Option(help="un seul passage")] = False,
    ) -> None:
        """Confie chaque fichier de `inbox/` au domaine qui le réclame, puis fait traiter
        `inbox/<domaine>/` par chacun. Compteurs seuls."""
        hub = ready()
        while True:
            routed = inbox.route(hub.registry, hub.settings.paths.inbox)
            done = {d.name: d.process_inbox() for d in hub.registry}
            if once or routed.moved or any(c.get("files") for c in done.values()):
                typer.echo(json.dumps({**routed.public(), "domains": done}, ensure_ascii=False))
            if once:
                return
            time.sleep(poll)

    return watch_inbox
