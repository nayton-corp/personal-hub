"""Commande `hub` : serveur, migrations, jetons, amorçage des passkeys, tâches de fond."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from hub.core import logging as hub_logging
from hub.core import proposals, sessions, tokens
from hub.core.context import HubContext
from hub.core.registry import Registry
from hub.core.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Personal Hub")
db_app = typer.Typer(no_args_is_help=True, help="Bases et migrations")
token_app = typer.Typer(no_args_is_help=True, help="Jetons à portée")
auth_app = typer.Typer(no_args_is_help=True, help="Passkeys")
app.add_typer(db_app, name="db")
app.add_typer(token_app, name="token")
app.add_typer(auth_app, name="auth")

CLI_ACTOR = "system:cli"


def _ctx() -> HubContext:
    settings = get_settings()
    hub_logging.configure(settings.log_level, stream=sys.stderr)
    return HubContext.build(settings)


def _ready() -> HubContext:
    hub = _ctx()
    if not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    return hub


@app.command()
def serve(
    workers: Annotated[
        int, typer.Option(min=1, max=1, help="Un seul worker (aucun état partagé en mémoire).")
    ] = 1,
    migrate: Annotated[bool, typer.Option(help="Migrer au démarrage (développement).")] = False,
) -> None:
    """Lance l'API (uvicorn)."""
    import uvicorn

    from hub.api.app import create_app

    hub = _ctx()
    if not migrate and not hub.core.is_current():
        typer.echo("core.db n'est pas à jour : lancer `hub db upgrade`.", err=True)
        raise typer.Exit(2)
    settings = hub.settings
    uvicorn.run(
        create_app(hub, migrate=migrate),
        host=settings.server.host,
        port=settings.server.port,
        workers=workers,
        log_config=None,
        access_log=False,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


@db_app.command("upgrade")
def db_upgrade() -> None:
    """Monte `core.db` puis chaque base de domaine à la dernière version."""
    hub = _ctx()
    hub.migrate_all()
    typer.echo(json.dumps({"core": hub.core.revision(), "domains": hub.registry.names()}))


@db_app.command("status")
def db_status() -> None:
    hub = _ctx()
    typer.echo(
        json.dumps(
            {
                "core": {"revision": hub.core.revision(), "current": hub.core.is_current()},
                "domains": {d.name: d.health().db for d in hub.registry},
            }
        )
    )


@token_app.command("create")
def token_create(
    name: Annotated[str, typer.Argument(help="ex. brain-mac, collector-bcf")],
    scope: Annotated[
        list[str],
        typer.Option(
            "--scope", "-s", help="brain, aggregates, collector ou portée qualifiée finance:read"
        ),
    ],
) -> None:
    """Crée un jeton. Il n'est affiché qu'une fois : seule son empreinte est gardée."""
    hub = _ready()
    try:
        with hub.core.engine.begin() as conn:
            info, secret = tokens.create(conn, name, scope, CLI_ACTOR)
    except tokens.ScopeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"id      : {info.id}\nportées : {' '.join(info.scopes)}", err=True)
    typer.echo("jeton (affiché une seule fois) :", err=True)
    typer.echo(secret)


@token_app.command("list")
def token_list() -> None:
    hub = _ready()
    with hub.core.engine.connect() as conn:
        for t in tokens.list_all(conn):
            state = "révoqué" if t.revoked_at else "actif"
            typer.echo(
                f"{t.id}  {t.name:<20} {state:<8} {' '.join(t.scopes)}  "
                f"dernier usage : {t.last_used_at or 'jamais'}"
            )


@token_app.command("revoke")
def token_revoke(token_id: str) -> None:
    hub = _ready()
    with hub.core.engine.begin() as conn:
        done = tokens.revoke(conn, token_id, CLI_ACTOR)
    typer.echo("révoqué" if done else "inconnu ou déjà révoqué")
    if not done:
        raise typer.Exit(1)


@auth_app.command("bootstrap-code")
def bootstrap_code() -> None:
    """Code à usage unique pour inscrire une passkey depuis l'app (valable quelques minutes)."""
    hub = _ready()
    with hub.core.engine.begin() as conn:
        code = sessions.create_bootstrap_code(conn, hub.settings.auth.bootstrap_minutes, CLI_ACTOR)
    typer.echo(f"valable {hub.settings.auth.bootstrap_minutes} minutes :", err=True)
    typer.echo(code)


@app.command()
def nightly() -> None:
    """Expiration des propositions, purges, réconciliation, tâches de nuit des domaines."""
    from hub.core.maintenance import nightly as run

    typer.echo(json.dumps(run(_ready())))


@app.command()
def reconcile() -> None:
    """Recale les statuts des propositions sur `applied_proposals` (après une restauration)."""
    hub = _ready()
    report = proposals.reconcile(hub)
    typer.echo(json.dumps({"applied": report.marked_applied, "released": report.released}))


@app.command()
def verify() -> None:
    """Intégrité de chaque base et santé des domaines ; code de sortie 1 au moindre écart."""
    from hub.core.maintenance import verify as run

    report = run(_ctx())
    typer.echo(json.dumps({"ok": report.ok, "checks": report.checks}))
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def backup(
    dest: Annotated[Path | None, typer.Option(help="Dossier cible (défaut : paths.backup)")] = None,
    stamp: Annotated[str | None, typer.Option(help="Suffixe des fichiers (défaut : date)")] = None,
) -> None:
    """Copie `.backup` cohérente de chaque base, vérifiée par `integrity_check`."""
    from hub.core.maintenance import backup_all

    hub = _ctx()
    files = backup_all(hub, dest or hub.settings.paths.backup, stamp)
    typer.echo(json.dumps({"files": [f.name for f in files]}))


@app.command()
def scheduler(crontab: Path) -> None:
    """Exécute la crontab du dépôt (conteneur `scheduler`)."""
    from hub.core.cron import run_forever

    hub_logging.configure(get_settings().log_level)
    run_forever(crontab)


def main() -> None:
    # sous-commandes fournies par les domaines (`hub finance …`), sans que le cœur les importe
    try:
        for domain in Registry.discover(get_settings()):
            sub = domain.cli()
            if sub is not None:
                app.add_typer(sub, name=domain.name)
    except Exception as exc:  # un domaine cassé ne doit pas empêcher `hub db …`
        typer.echo(f"domaines non chargés : {type(exc).__name__}", err=True)
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
