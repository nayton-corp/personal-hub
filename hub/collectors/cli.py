"""Commande `hub-collector`, dans les conteneurs collecteurs.

hub-collector daemon bcf               boucle planifiée (service compose)
hub-collector run bcf [--check] [--diagnose]
hub-collector relogin viac             connexion avec le code 2FA tapé au terminal
hub-collector revolut link             consentement Enable Banking puis reprise complète
hub-collector revolut aspsps --country CH
hub-collector revolut status
"""

from __future__ import annotations

import json
import sys
from typing import Annotated

import typer

from hub.collectors import base
from hub.collectors.base import Failure
from hub.collectors.client import HubClient
from hub.collectors.runtime import Env, execute, run_forever
from hub.core import logging as hub_logging
from hub.core.clock import now_iso
from hub.core.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Collecteurs du Personal Hub")
revolut_app = typer.Typer(no_args_is_help=True, help="Revolut par Enable Banking")
app.add_typer(revolut_app, name="revolut")


def _check_name(name: str) -> str:
    if name not in base.NAMES:
        typer.echo(f"collecteur inconnu : {name} ({', '.join(base.NAMES)})", err=True)
        raise typer.Exit(2)
    return name


def make_env(name: str, *, diagnose: bool = False, headed: bool = False) -> Env:
    settings = get_settings()
    cfg = base.config(settings)
    if headed:
        cfg = cfg.model_copy(update={"headless": False})
    creds = base.credentials(settings, name)
    token = creds.get("token")
    hub = HubClient(cfg.api_url, token) if isinstance(token, str) and token else None
    return Env(name, cfg, creds, settings.paths.inbox, hub, diagnose)


def _out(result: base.Result) -> None:
    typer.echo(
        json.dumps({"outcome": result.outcome, "files": result.files, "detail": result.detail})
    )
    if result.outcome not in {"ok", "nothing_new"}:
        raise typer.Exit(1)


@app.command()
def daemon(
    names: Annotated[list[str], typer.Argument(help="bcf, viac, revolut, ibkr, market")],
) -> None:
    """Boucle du conteneur : runs planifiés si le collecteur est actif, contrôles demandés."""
    hub_logging.configure(get_settings().log_level)
    for n in names:
        _check_name(n)
    run_forever(make_env, names, base.config(get_settings()))


@app.command()
def run(
    name: str,
    check: Annotated[
        bool, typer.Option(help="contrôle : connexion et sélecteurs, rien de téléchargé")
    ] = False,
    diagnose: Annotated[
        bool, typer.Option(help="captures d'écran pour ce run (purgées à 7 jours)")
    ] = False,
) -> None:
    """Un run tout de suite, quel que soit le mode, déclaré au hub comme un run planifié."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    env = make_env(_check_name(name), diagnose=diagnose)
    _out(execute(env, "check" if check else "run"))


@app.command()
def relogin(
    name: str,
    headed: Annotated[bool, typer.Option(help="fenêtre visible (machine avec écran)")] = False,
    diagnose: Annotated[bool, typer.Option()] = False,
) -> None:
    """Reconnexion VIAC : identifiants des secrets, code 2FA tapé ici. Suivi d'un contrôle."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    if _check_name(name) != "viac":
        typer.echo("seul VIAC demande une reconnexion assistée", err=True)
        raise typer.Exit(2)
    from hub.collectors.viac import flow as viac

    env = make_env(name, diagnose=diagnose, headed=headed)
    try:
        viac.relogin(env, lambda: typer.prompt("Code 2FA reçu de VIAC", hide_input=False))
    except Failure as f:
        typer.echo(json.dumps({"outcome": f.outcome, "detail": f.detail}), err=True)
        raise typer.Exit(1) from None
    typer.echo("Connecté. Contrôle en cours…", err=True)
    _out(execute(make_env(name), "check"))


@revolut_app.command("link")
def revolut_link() -> None:
    """Nouveau consentement : ouvre l'URL affichée, valide dans l'app Revolut. La reprise de tout
    l'historique démarre dès le retour, dans la fenêtre de 5 minutes de Revolut."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    from hub.collectors.revolut import flow as revolut

    settings = get_settings()
    env = make_env("revolut")
    redirect = f"{settings.server.public_origin}/api/collectors/revolut/callback"

    def show(url: str) -> None:
        typer.echo("\nOuvre ce lien (de préférence sur le téléphone où est l'app Revolut) :\n")
        typer.echo(url)
        typer.echo(f"\nRetour attendu sur {redirect} (15 min au plus)…", err=True)

    started = now_iso()
    try:
        result = revolut.link(env, redirect, show)
    except Failure as f:
        result = base.Result(f.outcome, 0, f.detail)
    env.memory.save()
    if env.client is not None and result.outcome == "ok":
        env.client.report("revolut", "check", result, started, now_iso())
    typer.echo(
        json.dumps({"accounts": revolut.accounts_summary(env)}, ensure_ascii=False), err=True
    )
    _out(result)


@revolut_app.command("aspsps")
def revolut_aspsps(country: Annotated[str, typer.Option()] = "LT") -> None:
    """Banques Revolut proposées par Enable Banking pour un pays (test de liaison)."""
    from hub.collectors.revolut import flow as revolut

    eb = revolut.client(make_env("revolut"))
    for a in eb.aspsps(country):
        if "revolut" in str(a.get("name", "")).lower():
            days = int(a.get("maximum_consent_validity") or 0) // 86_400
            name, where, kinds = a.get("name"), a.get("country"), a.get("psu_types")
            typer.echo(f"{name} ({where}) · consentement {days} j · {kinds}")


@revolut_app.command("status")
def revolut_status() -> None:
    """Comptes reliés (devise, type) et jours de consentement restants ; aucun montant."""
    from hub.collectors.revolut import flow as revolut

    env = make_env("revolut")
    typer.echo(
        json.dumps(
            {"days_left": revolut.days_left(env), "accounts": revolut.accounts_summary(env)},
            ensure_ascii=False,
            indent=1,
        )
    )


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
