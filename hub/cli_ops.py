"""Commandes `hub ops …` (chantier S7) : ce que les scripts d'exploitation lisent au lieu d'une
liste de bases en dur."""

from __future__ import annotations

from collections.abc import Callable

import typer

from hub.core import ops
from hub.core.context import HubContext
from hub.core.notify import Message, Notifier
from hub.platform.settings import get_settings


def build(ctx: Callable[[], HubContext]) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Exploitation : bases et réplication")

    @app.command("databases")
    def databases() -> None:
        """Une base par ligne : core, puis chaque domaine monté (HUB_DOMAINS)."""
        for name in ops.database_names(ctx()):
            typer.echo(name)

    @app.command("litestream")
    def litestream() -> None:
        """La configuration Litestream de ces bases, sur la sortie standard."""
        typer.echo(ops.litestream_config(ctx()), nl=False)

    @app.command("notify")
    def notify(
        title: str,
        body: str,
        urgent: bool = typer.Option(False, "--urgent", help="priorité haute (un échec)"),
    ) -> None:
        """Une notification ntfy depuis un script d'exploitation (mise à jour du Pi). Un texte
        générique : jamais un montant. Sans sujet ntfy, rien n'est envoyé (code 0)."""
        Notifier(get_settings()).send(
            Message(title, body, priority="high" if urgent else "default", tags="package")
        )

    return app
