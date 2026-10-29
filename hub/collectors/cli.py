"""Commande `hub-collector`, dans les services collecteurs (G4 : `collector-api` et
`collector-browser`). Une connexion se désigne par son identifiant (`bcf`, `revolut`…).

hub-collector daemon browser             boucle planifiée du service (compose)
hub-collector run bcf [--check] [--diagnose]
hub-collector relogin viac               connexion avec le code 2FA tapé au terminal
hub-collector link revolut               consentement Enable Banking puis reprise complète
hub-collector aspsps revolut --country CH
hub-collector consent revolut            comptes reliés et jours de consentement restants

Le service se lit dans `HUB_COLLECTOR_RUNNER` (posé par compose) : son jeton est dans la
section `collector-<service>` de son fichier de secrets. Les anciennes commandes
`hub-collector revolut link|aspsps|status` restent, pour la connexion « revolut ».
"""

from __future__ import annotations

import json
import os
import sys
from typing import Annotated

import typer

from hub.collectors import base
from hub.collectors.base import Failure
from hub.collectors.client import HubClient
from hub.collectors.runtime import Assigned, Env, execute, run_forever, start_link
from hub.core import connectors
from hub.kernel.clock import now_iso
from hub.platform import logging as hub_logging
from hub.platform.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Collecteurs du Personal Hub")
revolut_app = typer.Typer(no_args_is_help=True, help="Connexion « revolut » (anciens noms)")
app.add_typer(revolut_app, name="revolut")


def _runner(runner: str | None = None) -> str:
    name = runner or os.environ.get("HUB_COLLECTOR_RUNNER", "")
    if name not in base.RUNNERS:
        typer.echo("service attendu : api ou browser (HUB_COLLECTOR_RUNNER)", err=True)
        raise typer.Exit(2)
    return name


def _client(runner: str) -> HubClient:
    settings = get_settings()
    token = base.service_token(settings, runner)
    if token is None:
        typer.echo(f"jeton absent : section collector-{runner} des secrets", err=True)
        raise typer.Exit(2)
    return HubClient(base.config(settings).api_url, token)


def env_for(
    item: Assigned, client: HubClient | None, *, diagnose: bool = False, headed: bool = False
) -> Env:
    """Contexte d'un run : réglages du service et de la connexion, secrets déchiffrés ici."""
    settings = get_settings()
    cfg = base.for_connection(base.config(settings), item.connector, item.settings)
    if headed:
        cfg = cfg.model_copy(update={"headless": False})
    creds = base.open_secrets(settings, item.secrets)
    spec = connectors.get(item.connector)
    inbox = settings.paths.inbox_of(spec.domain) if spec else settings.paths.inbox
    return Env(item.id, cfg, creds, inbox, client, diagnose, connector=item.connector)


def make_env(
    connection: str, *, diagnose: bool = False, headed: bool = False, runner: str | None = None
) -> Env:
    """Une connexion de ce service, demandée au hub."""
    client = _client(_runner(runner))
    for raw in client.connections(_runner(runner)):
        if raw.get("id") == connection:
            return env_for(Assigned.parse(raw), client, diagnose=diagnose, headed=headed)
    typer.echo(f"connexion inconnue, pas prête ou d'un autre service : {connection}", err=True)
    raise typer.Exit(2)


def _out(result: base.Result) -> None:
    typer.echo(
        json.dumps({"outcome": result.outcome, "files": result.files, "detail": result.detail})
    )
    if result.outcome not in {"ok", "nothing_new"}:
        raise typer.Exit(1)


@app.command()
def daemon(
    runner: Annotated[str | None, typer.Argument(help="api ou browser")] = None,
) -> None:
    """Boucle du service : il demande chaque minute ses connexions au hub, lance les runs
    planifiés des connexions actives, les contrôles et les consentements demandés depuis
    l'app."""
    settings = get_settings()
    hub_logging.configure(settings.log_level)
    name = _runner(runner)
    client = _client(name)
    origin = settings.server.public_origin

    def linker(env: Env) -> object:
        return start_link(env, f"{origin}/api/collectors/{env.name}/callback")

    run_forever(lambda item: env_for(item, client), name, base.config(settings), client, linker)


@app.command()
def run(
    connection: str,
    check: Annotated[
        bool, typer.Option(help="contrôle : connexion et sélecteurs, rien de téléchargé")
    ] = False,
    diagnose: Annotated[
        bool, typer.Option(help="captures d'écran pour ce run (purgées à 7 jours)")
    ] = False,
) -> None:
    """Un run tout de suite, quel que soit le mode, déclaré au hub comme un run planifié."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    env = make_env(connection, diagnose=diagnose)
    _out(execute(env, "check" if check else "run"))


@app.command()
def relogin(
    connection: str,
    headed: Annotated[bool, typer.Option(help="fenêtre visible (machine avec écran)")] = False,
    diagnose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Reconnexion VIAC : identifiants de la connexion, code 2FA tapé ici. Suivi d'un contrôle."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    env = make_env(connection, diagnose=diagnose, headed=headed)
    if env.connector != "viac":
        typer.echo("seul VIAC demande une reconnexion assistée", err=True)
        raise typer.Exit(2)
    from hub.collectors.viac import flow as viac

    try:
        viac.relogin(env, lambda: typer.prompt("Code 2FA reçu de VIAC", hide_input=False))
    except Failure as f:
        typer.echo(json.dumps({"outcome": f.outcome, "detail": f.detail}), err=True)
        raise typer.Exit(1) from None
    typer.echo("Connecté. Contrôle en cours…", err=True)
    _out(execute(make_env(connection), "check"))


def _open_banking(connection: str) -> Env:
    env = make_env(connection)
    if env.connector != "enable_banking":
        typer.echo(f"{connection} n'est pas une connexion Enable Banking", err=True)
        raise typer.Exit(2)
    return env


@app.command()
def link(connection: str) -> None:
    """Nouveau consentement : ouvre l'URL affichée, valide chez la banque. La reprise de tout
    l'historique démarre dès le retour (Revolut ne la donne que dans les 5 minutes)."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    from hub.collectors.revolut import flow as open_banking

    settings = get_settings()
    env = _open_banking(connection)
    redirect = f"{settings.server.public_origin}/api/collectors/{connection}/callback"

    def show(url: str) -> None:
        typer.echo("\nOuvre ce lien (de préférence sur le téléphone où est l'app de la banque) :\n")
        typer.echo(url)
        typer.echo(f"\nRetour attendu sur {redirect} (15 min au plus)…", err=True)

    started = now_iso()
    try:
        result = open_banking.link(env, redirect, show)
    except Failure as f:
        result = base.Result(f.outcome, 0, f.detail)
    env.memory.save()
    if env.client is not None and result.outcome == "ok":
        env.client.report(connection, "check", result, started, now_iso())
    typer.echo(
        json.dumps({"accounts": open_banking.accounts_summary(env)}, ensure_ascii=False), err=True
    )
    _out(result)


@app.command()
def aspsps(
    connection: str,
    country: Annotated[str | None, typer.Option(help="pays ; celui de la connexion")] = None,
) -> None:
    """Banques proposées par Enable Banking pour un pays, avec la durée de consentement."""
    from hub.collectors.revolut import flow as open_banking

    env = _open_banking(connection)
    for a in open_banking.client(env).aspsps(country or env.cfg.revolut.aspsp_country):
        days = int(a.get("maximum_consent_validity") or 0) // 86_400
        name, where, kinds = a.get("name"), a.get("country"), a.get("psu_types")
        typer.echo(f"{name} ({where}) · consentement {days} j · {kinds}")


@app.command()
def consent(connection: str) -> None:
    """Comptes reliés (devise, type) et jours de consentement restants ; aucun montant."""
    from hub.collectors.revolut import flow as open_banking

    env = _open_banking(connection)
    typer.echo(
        json.dumps(
            {
                "days_left": open_banking.days_left(env),
                "accounts": open_banking.accounts_summary(env),
            },
            ensure_ascii=False,
            indent=1,
        )
    )


@revolut_app.command("link")
def revolut_link() -> None:
    """= `hub-collector link revolut`."""
    link("revolut")


@revolut_app.command("aspsps")
def revolut_aspsps(country: Annotated[str, typer.Option()] = "LT") -> None:
    """= `hub-collector aspsps revolut`."""
    aspsps("revolut", country)


@revolut_app.command("status")
def revolut_status() -> None:
    """= `hub-collector consent revolut`."""
    consent("revolut")


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
