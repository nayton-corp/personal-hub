"""Ce que les commandes `hub finance …` partagent : la sortie (une ligne JSON), la validation
d'une proposition depuis le terminal (Double Sas, ticket L1-12), et ce qu'une commande attend
du domaine (`Host`, que `FinanceDomain` remplit). Les sorties sont des identifiants et des
compteurs, jamais le contenu d'une écriture."""

from __future__ import annotations

import json
from typing import Protocol

import typer
from sqlalchemy import Engine

from hub.core import proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Domain
from hub.core.errors import Problem
from hub.core.registry import Registry
from hub.platform.settings import Settings

CLI = Principal("system:cli", frozenset(), is_app=True)


class Host(Domain, Protocol):
    settings: Settings

    def engine(self) -> Engine: ...

    def is_current(self) -> bool: ...


def out(value: object) -> None:
    typer.echo(json.dumps(value, ensure_ascii=False))


def propose_and_accept(host: Host, kind: str, params: dict[str, object]) -> dict[str, object]:
    """Crée la proposition et la valide depuis le terminal ; renvoie son résultat."""
    hub = HubContext.build(host.settings, Registry([host]))
    if not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    try:
        p, _ = proposals.create(hub, CLI, "finance", kind, params)
        if p.status == "applied":
            return {"proposal_id": p.id, **(p.result or {})}
        (outcome,) = proposals.accept(hub, CLI, [p], None)
    except Problem as exc:
        typer.echo(exc.detail or exc.title, err=True)
        raise typer.Exit(1) from exc
    finally:
        hub.core.dispose()
    if outcome.status != "applied":
        problem = outcome.problem or {}
        typer.echo(str(problem.get("detail") or problem.get("title") or outcome.status), err=True)
        raise typer.Exit(1)
    return {"proposal_id": p.id, **(outcome.result or {})}
