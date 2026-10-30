"""Routes des documents (`/api/documents/…`) et commandes `hub documents …`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Protocol

import typer
from fastapi import APIRouter, Depends, Query

from hub.core.auth import require
from hub.core.errors import Problem


class Host(Protocol):
    def overview(self) -> dict[str, Any]: ...

    def counts(self) -> dict[str, int]: ...

    def find(self, q: str, limit: int, household_only: bool) -> dict[str, Any]: ...

    def card_list(self) -> list[dict[str, Any]]: ...

    def card_view(self, card_id: str, household_only: bool) -> dict[str, Any] | None: ...

    def import_library(self, folder: Path) -> dict[str, int]: ...

    def reindex(self) -> int: ...

    def rebuild(self) -> dict[str, int]: ...

    def compare(self) -> dict[str, Any]: ...


def build_router(host: Host) -> APIRouter:
    r = APIRouter(tags=["documents"])
    read = [Depends(require("app", "documents:read"))]

    @r.get("/overview", dependencies=read)
    def overview() -> dict[str, Any]:
        """Le bloc de l'accueil : les nombres, les entretiens dus, les derniers documents."""
        return host.overview()

    @r.get(
        "/counts",
        dependencies=[Depends(require("app", "documents:read", "documents:aggregates"))],
    )
    def counts() -> dict[str, int]:
        """Des nombres seulement : fiches, documents, documents du foyer, entretiens dus."""
        return host.counts()

    @r.get("/search", dependencies=read)
    def search(
        q: Annotated[str, Query(min_length=3, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """Les passages et les fiches qui répondent, avec leur source et leur page."""
        return host.find(q, limit, household_only=False)

    @r.get("/cards", dependencies=read)
    def cards() -> list[dict[str, Any]]:
        return host.card_list()

    @r.get("/cards/{card_id}", dependencies=read)
    def card(card_id: str) -> dict[str, Any]:
        found = host.card_view(card_id, household_only=False)
        if found is None:
            raise Problem("not_found", "fiche inconnue")
        return found

    return r


def build_cli(host: Host) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Documents : fiches d'objets et documents")

    def show(value: Any) -> None:
        typer.echo(json.dumps(value, ensure_ascii=False))

    @app.callback()
    def documents() -> None:
        """Documents : fiches d'objets, notices, contrats ; archive chiffrée et index local."""

    @app.command("status")
    def status() -> None:
        """Les nombres du domaine."""
        show(host.counts())

    @app.command("import-library")
    def import_library(folder: Path) -> None:
        """Reprise unique de la bibliothèque de Domia (fiches YAML et documents à côté)."""
        if not folder.is_dir():
            typer.echo(f"dossier introuvable : {folder}", err=True)
            raise typer.Exit(1)
        show(host.import_library(folder))

    @app.command("index")
    def index() -> None:
        """Recalcule les passages de tous les documents, depuis l'archive."""
        show({"passages": host.reindex()})

    @app.command("rebuild")
    def rebuild(
        check: Annotated[bool, typer.Option(help="reconstruire à côté et comparer")] = False,
    ) -> None:
        """Reconstruit la base depuis l'archive (base absente) ou, avec --check, compare."""
        if check:
            found = host.compare()
            show(found)
            if not found["ok"]:
                raise typer.Exit(1)
            return
        try:
            show(host.rebuild())
        except FileExistsError as exc:
            typer.echo(f"{exc} : la déplacer d'abord, ou --check pour comparer", err=True)
            raise typer.Exit(1) from None

    return app
