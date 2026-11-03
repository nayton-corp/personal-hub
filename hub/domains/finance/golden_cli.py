"""Commandes `hub finance golden save | check` : l'étalon des agrégats (golden.py), à prendre
avant une mise à jour et à vérifier après. Sorties : un chemin, une date, des compteurs et les
écarts (clés et chiffres agrégés)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from hub.domains.finance import golden
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.interface.terminal import out as _out


def register(domain: Finance, ready: Callable[[], None], *, app: typer.Typer) -> None:
    golden_app = typer.Typer(
        no_args_is_help=True,
        help="Étalon des agrégats : à figer avant une mise à jour, à vérifier après",
    )
    app.add_typer(golden_app, name="golden")

    def folder() -> Path:
        return domain.settings.paths.backup / "golden"

    @golden_app.command("save")
    def save_cmd(
        out: Annotated[
            Path | None,
            typer.Option(help="fichier à écrire (défaut : <backup>/golden/finance-<date>.json)"),
        ] = None,
        as_of: Annotated[
            str | None,
            typer.Option("--as-of", help="date des agrégats, AAAA-MM-JJ (défaut : aujourd'hui)"),
        ] = None,
    ) -> None:
        """Fige les agrégats d'une date : patrimoine, positions, performance, ruptures, budget,
        dettes, compteurs. Aucune écriture ni libellé dans le fichier."""
        ready()
        try:
            day = date.fromisoformat(as_of) if as_of else domain.today()
        except ValueError:
            typer.echo("--as-of : une date AAAA-MM-JJ", err=True)
            raise typer.Exit(2) from None
        found = golden.build(domain.engine(), day)
        path = golden.save(found, out or folder() / f"finance-{day.isoformat()}.json")
        _out(
            {
                "path": str(path),
                "as_of": found.as_of,
                "hub_version": found.hub_version,
                "digest": found.digest,
                "sections": sorted(found.sections),
            }
        )

    @golden_app.command("check")
    def check_cmd(
        path: Annotated[
            Path | None,
            typer.Argument(help="étalon à vérifier (défaut : le plus récent de <backup>/golden)"),
        ] = None,
    ) -> None:
        """Recalcule les agrégats à la date de l'étalon et les compare ; 1 au moindre écart,
        2 sans étalon lisible."""
        ready()
        target = path or golden.latest(folder())
        if target is None:
            typer.echo("aucun étalon : lancer `hub finance golden save` d'abord", err=True)
            raise typer.Exit(2)
        try:
            found = golden.load(target)
        except golden.GoldenError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from None
        result = golden.check(domain.engine(), found)
        _out({"path": str(target), **result.public()})
        if not result.ok:
            raise typer.Exit(1)
