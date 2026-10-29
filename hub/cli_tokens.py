"""Commandes `hub token …` : créer, lister, renouveler, révoquer (chantier S8 : date de fin)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer

from hub.core import tokens
from hub.core.context import HubContext

# au niveau du module : typer relit les annotations (chaînes, `from __future__`) dans ses globales
DAYS = typer.Option(
    "--days", min=1, max=tokens.MAX_DAYS, help="durée de vie en jours (alerte 14 jours avant)"
)


def build(ready: Callable[[], HubContext], actor: str) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Jetons à portée, chacun avec sa date de fin")

    def show(info: tokens.TokenInfo, secret: str) -> None:
        typer.echo(f"id      : {info.id}\nportées : {' '.join(info.scopes)}", err=True)
        typer.echo(f"fin     : {info.expires_at[:10]}", err=True)
        typer.echo("jeton (affiché une seule fois) :", err=True)
        typer.echo(secret)

    @app.command("create")
    def create(
        name: Annotated[str, typer.Argument(help="ex. brain-mac, claude-aggregates")],
        scope: Annotated[
            list[str],
            typer.Option(
                "--scope", "-s", help="brain (agrégats), brain=finance, aggregates, finance:read…"
            ),
        ],
        days: Annotated[int, DAYS] = tokens.DEFAULT_DAYS,
    ) -> None:
        """Crée un jeton. Il n'est affiché qu'une fois : seule son empreinte est gardée."""
        hub = ready()
        try:
            with hub.core.engine.begin() as conn:
                info, secret = tokens.create(conn, name, scope, actor, days=days)
        except tokens.ScopeError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(1) from exc
        show(info, secret)

    @app.command("list")
    def list_() -> None:
        hub = ready()
        with hub.core.engine.connect() as conn:
            for t in tokens.list_all(conn):
                typer.echo(
                    f"{t.id}  {t.name:<20} {t.state:<8} fin {t.expires_at[:10]}  "
                    f"{' '.join(t.scopes)}  dernier usage : {t.last_used_at or 'jamais'}"
                )

    @app.command("rotate")
    def rotate(token_id: str, days: Annotated[int | None, DAYS] = None) -> None:
        """Nouveau secret, mêmes portées ; l'ancien est révoqué aussitôt. À remettre là où
        l'ancien servait (secrets de l'assistant, configuration MCP)."""
        hub = ready()
        with hub.core.engine.begin() as conn:
            done = tokens.rotate(conn, token_id, actor, days=days)
        if done is None:
            typer.echo("inconnu ou déjà révoqué", err=True)
            raise typer.Exit(1)
        show(*done)

    @app.command("revoke")
    def revoke(token_id: str) -> None:
        hub = ready()
        with hub.core.engine.begin() as conn:
            done = tokens.revoke(conn, token_id, actor)
        typer.echo("révoqué" if done else "inconnu ou déjà révoqué")
        if not done:
            raise typer.Exit(1)

    return app
