"""Commandes `hub ops …` (chantier S7) : ce que les scripts d'exploitation lisent au lieu d'une
liste de bases en dur."""

from __future__ import annotations

from collections.abc import Callable

import typer

from hub.core import ops
from hub.core.context import HubContext


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

    return app
