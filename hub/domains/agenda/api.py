"""Routes de l'agenda (`/api/agenda/…`) et commandes `hub agenda …`."""

from __future__ import annotations

import json
from typing import Annotated, Any, Protocol

import typer
from fastapi import APIRouter, Depends, Query

from hub.core.auth import require
from hub.domains.agenda.bridge import BridgeError


class Host(Protocol):
    def overview(self) -> dict[str, Any]: ...

    def upcoming(self, days: int = 7) -> dict[str, Any]: ...

    def counts(self) -> dict[str, Any]: ...

    def bridge_status(self) -> dict[str, Any]: ...


def unavailable(exc: BridgeError) -> dict[str, Any]:
    """Le pont absent (Mac en veille, accès retiré) n'est pas une erreur du hub : il se dit."""
    return {"available": False, "reason": str(exc)}


def build_router(host: Host) -> APIRouter:
    r = APIRouter(tags=["agenda"])
    read = [Depends(require("app", "agenda:read"))]

    @r.get("/overview", dependencies=read)
    def overview() -> dict[str, Any]:
        """Le bloc de l'accueil : la semaine, les rappels ouverts, la liste de courses ; le pont
        absent se dit (`available: false`)."""
        return host.overview()

    @r.get("/upcoming", dependencies=read)
    def upcoming(days: Annotated[int, Query(ge=1, le=31)] = 7) -> dict[str, Any]:
        """Les événements des prochains jours, les rappels ouverts et la liste de courses."""
        try:
            return {"available": True, **host.upcoming(days)}
        except BridgeError as exc:
            return unavailable(exc)

    @r.get("/counts", dependencies=[Depends(require("app", "agenda:read", "agenda:aggregates"))])
    def counts() -> dict[str, Any]:
        """Des nombres seulement : événements de la semaine, rappels ouverts et en retard."""
        try:
            return {"available": True, **host.counts()}
        except BridgeError as exc:
            return unavailable(exc)

    return r


def build_cli(host: Host) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Agenda : Rappels et Calendrier du Mac")

    @app.callback()
    def agenda() -> None:
        """Agenda : Rappels et Calendrier du Mac, par le pont EventKit."""

    @app.command("status")
    def status() -> None:
        """Le pont répond-il, et macOS lui donne-t-il l'accès ?"""
        found = host.bridge_status()
        typer.echo(json.dumps(found, ensure_ascii=False))
        if found.get("bridge") != "ok":
            raise typer.Exit(1)

    return app
