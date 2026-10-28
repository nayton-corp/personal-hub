"""Commande `hub-brain`, dans le conteneur `brain` (profil compose « brain »).

hub-brain mcp [--token brain|aggregates]   serveur MCP sur stdio (docker exec -i …)
hub-brain ask "combien en restaurants ce mois ?"
hub-brain suggest [--dry-run]              suggestions de catégorie (commerçants jamais vus)
hub-brain check                            hub, modèle, et une question de contrôle
hub-brain daemon                           tâches planifiées (deploy/brain-crontab)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from hub.brain import agent
from hub.brain.config import BrainConfig, TokenMissing, TokenName, config, token
from hub.brain.hubapi import HubApi, HubError
from hub.brain.llm import LlmError, OpenAICompatible
from hub.brain.mcp import McpServer
from hub.brain.suggest import Memory, suggest
from hub.brain.toolbox import Toolbox
from hub.core import cron
from hub.core import logging as hub_logging
from hub.core.clock import local_tz
from hub.core.logging import get_logger
from hub.core.settings import get_settings

CRONTAB = Path("/srv/hub/app/deploy/brain-crontab")
CHECK_QUESTION = "Combien ai-je dépensé en restaurants ce mois-ci ?"
CHECK_CATEGORY = "restaurants"
log = get_logger("hub.brain")

app = typer.Typer(no_args_is_help=True, add_completion=False, help="IA locale du Personal Hub")


def _cfg() -> BrainConfig:
    return config(get_settings())


def _toolbox(cfg: BrainConfig, which: TokenName) -> Toolbox:
    try:
        secret = token(get_settings(), which)
    except TokenMissing as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from None
    box = Toolbox(HubApi(cfg.api_url, secret))
    try:
        box.start()
    except HubError as exc:
        typer.echo(f"hub : {exc}", err=True)
        raise typer.Exit(1) from None
    return box


def _model(cfg: BrainConfig) -> OpenAICompatible:
    return OpenAICompatible(cfg.llm_url, cfg.model, cfg.timeout)


def _today() -> datetime:
    return datetime.now(local_tz())


@app.command()
def mcp(
    which: Annotated[
        str, typer.Option("--token", help="brain (modèle local) ou aggregates (client externe)")
    ] = "brain",
) -> None:
    """Serveur MCP sur stdio ; les journaux vont sur stderr."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    if which not in ("brain", "aggregates"):
        typer.echo("--token : brain ou aggregates", err=True)
        raise typer.Exit(2)
    box = _toolbox(_cfg(), which)  # type: ignore[arg-type]
    McpServer(box).serve(sys.stdin, sys.stdout)


@app.command()
def ask(question: str) -> None:
    """Pose une question au modèle local, outils du jeton « brain »."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
    box = _toolbox(cfg, "brain")
    try:
        answer = agent.ask(question, box, _model(cfg), _today().date(), cfg.max_steps)
    except LlmError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from None
    typer.echo(answer.text)
    if answer.proposals:
        typer.echo(f"\n{len(answer.proposals)} carte(s) à valider dans l'app.")
    log.info("brain.ask", tools=len(answer.tools), proposals=len(answer.proposals))


@app.command("suggest")
def suggest_cmd(
    dry_run: Annotated[bool, typer.Option(help="affiche sans créer de carte")] = False,
) -> None:
    """Suggestions de catégorie pour les commerçants jamais vus (cartes à valider)."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
    box = _toolbox(cfg, "brain")
    report = suggest(
        box,
        _model(cfg),
        Memory(cfg.state_dir),
        groups=cfg.suggest_groups,
        entries=cfg.suggest_entries,
        dry_run=dry_run,
    )
    if dry_run:
        for item in report.items:
            typer.echo(json.dumps(item, ensure_ascii=False))
    summary = {
        "merchants": report.merchants,
        "suggested": report.suggested,
        "proposals": report.proposals,
        "skipped": report.skipped,
        "stopped": report.stopped,
    }
    log.info("brain.suggest", **summary)
    typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command()
def check() -> None:
    """Contrôle de bout en bout : hub, modèle, puis la question de sortie du lot 7, comparée au
    chiffre de l'outil."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
    ok = True
    box = _toolbox(cfg, "brain")
    typer.echo(f"hub : ok ({', '.join(d['domain'] for d in box.domains)})")
    model = _model(cfg)
    try:
        names = model.models()
    except LlmError as exc:
        typer.echo(f"modèle : {exc}")
        raise typer.Exit(1) from None
    if cfg.model not in names and f"{cfg.model}:latest" not in names:
        typer.echo(f"modèle : {cfg.model} absent ({', '.join(names) or 'aucun'}) ; ollama pull")
        raise typer.Exit(1)
    typer.echo(f"modèle : ok ({cfg.model})")
    summary = box.call("finance_month_summary", {})
    expected = None
    currency = "CHF"
    if not summary.is_error:
        currency = str(summary.data.get("currency") or currency)
        for c in summary.data["by_category"]:
            if c["category"] == CHECK_CATEGORY:
                expected = c["amount"]
    answer = agent.ask(CHECK_QUESTION, box, model, _today().date(), cfg.max_steps)
    typer.echo(f"question : {CHECK_QUESTION}\nréponse : {answer.text}")
    typer.echo(f"outils appelés : {', '.join(answer.tools) or 'aucun'}")
    if expected is None:
        typer.echo("contrôle : aucune dépense « restaurants » ce mois, rien à comparer")
    elif expected in answer.text or expected.replace(".", ",") in answer.text:
        typer.echo(f"contrôle : ok, la réponse contient {expected} {currency}")
    else:
        typer.echo(f"contrôle : écart, l'outil donne {expected} {currency}")
        ok = False
    if not ok:
        raise typer.Exit(1)


@app.command()
def daemon(
    crontab: Annotated[Path, typer.Option(help="tâches du brain")] = CRONTAB,
) -> None:
    """Boucle du conteneur : suggestions de catégorie chaque matin."""
    hub_logging.configure(get_settings().log_level)
    cron.run_forever(crontab)


def main() -> None:  # pragma: no cover - point d'entrée
    app()
