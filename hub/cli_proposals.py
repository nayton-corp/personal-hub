"""Commandes `hub proposals …` : lister, voir, valider, refuser, créer ; et les paliers
d'approbation (`policy`, chantier S11)."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated

import typer

from hub.core import policies, proposals
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.errors import Problem


def build(
    ready: Callable[[], HubContext],
    principal: Callable[[], Principal],
    problem_exit: Callable[[Problem], typer.Exit],
) -> typer.Typer:
    app = typer.Typer(no_args_is_help=True, help="Propositions (Double Sas)")

    @app.command("list")
    def proposals_list(
        status: Annotated[str, typer.Option(help="pending, applied, rejected… ou all")] = "pending",
        limit: Annotated[int, typer.Option(min=1, max=200)] = 50,
    ) -> None:
        hub = ready()
        proposals.sync_events(hub)
        with hub.core.engine.connect() as conn:
            items = proposals.list_by_status(conn, None if status == "all" else status, limit)
        for p in items:
            typer.echo(
                f"{p.id}  {p.domain}/{p.kind:<16} {p.status:<10} r{p.revision}  "
                f"{p.preview.get('summary', '')}"
            )

    @app.command("show")
    def proposals_show(proposal_id: str) -> None:
        hub = ready()
        try:
            with hub.core.engine.connect() as conn:
                p = proposals.get(conn, proposal_id)
        except Problem as exc:
            raise problem_exit(exc) from exc
        typer.echo(json.dumps(p.public(), ensure_ascii=False, indent=1))

    @app.command("accept")
    def proposals_accept(ids: Annotated[list[str], typer.Argument()]) -> None:
        """Valide depuis le terminal, une à une. Code 1 si l'une échoue."""
        hub = ready()
        try:
            items = proposals.load_many(hub, ids)
        except Problem as exc:
            raise problem_exit(exc) from exc
        results = proposals.accept(hub, principal(), items, None)
        for r in results:
            typer.echo(json.dumps(r.public(), ensure_ascii=False))
        if any(r.status != "applied" for r in results):
            raise typer.Exit(1)

    @app.command("reject")
    def proposals_reject(proposal_id: str) -> None:
        hub = ready()
        try:
            p = proposals.reject(hub, principal(), proposal_id)
        except Problem as exc:
            raise problem_exit(exc) from exc
        typer.echo(json.dumps({"id": p.id, "status": p.status}))

    @app.command("create")
    def proposals_create(
        domain: str,
        kind: str,
        params: Annotated[str, typer.Option(help="paramètres en JSON")] = "{}",
        reason: Annotated[str | None, typer.Option()] = None,
        accept: Annotated[bool, typer.Option(help="valider aussitôt")] = False,
    ) -> None:
        """Crée une proposition (aperçu affiché) ; `--accept` la valide dans la foulée."""
        hub = ready()
        try:
            values = json.loads(params)
        except json.JSONDecodeError as exc:
            typer.echo("paramètres : JSON invalide", err=True)
            raise typer.Exit(1) from exc
        try:
            p, _created = proposals.create(hub, principal(), domain, kind, values, reason=reason)
            typer.echo(json.dumps(p.public(), ensure_ascii=False, indent=1))
            if accept and p.status == "pending":
                (outcome,) = proposals.accept(hub, principal(), [p], None)
                typer.echo(json.dumps(outcome.public(), ensure_ascii=False))
                if outcome.status != "applied":
                    raise typer.Exit(1)
        except Problem as exc:
            raise problem_exit(exc) from exc

    @app.command("policy")
    def policy(
        domain: Annotated[str | None, typer.Argument()] = None,
        kind: Annotated[str | None, typer.Argument()] = None,
        tier: Annotated[
            str | None,
            typer.Argument(help="human, auto_digest ou auto ; « default » : celui du type"),
        ] = None,
    ) -> None:
        """Les paliers des types de proposition ; avec un palier, le change."""
        hub = ready()
        if tier is not None:
            if domain is None or kind is None:
                raise typer.BadParameter("domaine et type")
            if kind not in hub.registry.get(domain).proposal_kinds:
                typer.echo(f"type inconnu : {domain}/{kind}", err=True)
                raise typer.Exit(1)
            try:
                with hub.core.engine.begin() as conn:
                    policies.set_tier(conn, domain, kind, None if tier == "default" else tier)
            except ValueError as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(1) from None
        with hub.core.engine.connect() as conn:
            chosen = policies.overrides(conn)
        for d in hub.registry:
            if domain is not None and d.name != domain:
                continue
            for name, k in sorted(d.proposal_kinds.items()):
                if kind is not None and name != kind:
                    continue
                now = chosen.get((d.name, name), k.tier)
                mark = "" if (d.name, name) not in chosen else f"  (défaut : {k.tier})"
                typer.echo(f"{d.name}/{name:<24} {now}{mark}")

    return app
