"""Commande `hub-brain`, en natif sur le Mac (S10 : plus de conteneur ; le classement du matin
passe par l'assistant, `python -m domia_assistant classify`).

hub-brain mcp [--token brain|aggregates]   serveur MCP sur stdio (docker exec -i …)
hub-brain suggest [--dry-run]              suggestions de catégorie (commerçants jamais vus)
hub-brain catchup [--limit N] [--dry-run]  rattrapage : une règle proposée par commerçant à classer
hub-brain check                            hub, modèle, outil, et un tour de conversation
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Annotated

import typer

from hub.brain.config import BrainConfig, TokenMissing, TokenName, config, token
from hub.brain.hubapi import HubApi, HubError
from hub.brain.llm import LlmError, OpenAICompatible
from hub.brain.mcp import McpServer
from hub.brain.suggest import (
    CATCHUP_MAX,
    DIRECT_MAX,
    Memory,
    Report,
    catchup,
    direct,
    suggest,
)
from hub.brain.toolbox import Toolbox
from hub.kernel.clock import local_tz
from hub.platform import logging as hub_logging
from hub.platform.logging import get_logger
from hub.platform.settings import get_settings

CHECK_QUESTION = "Combien ai-je dépensé en restaurants ce mois-ci ?"
CHECK_TOOL = "finance_month_summary"
CHECK_SYSTEM = (
    "Tu es l'assistant financier d'une personne. Nous sommes le {today}. Tout chiffre vient "
    "d'un outil ; « ce mois » est le mois en cours ({month})."
)
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
    _report("brain.suggest", report, dry_run)


@app.command("catchup")
def catchup_cmd(
    limit: Annotated[int, typer.Option(min=1, max=1000, help="commerçants")] = CATCHUP_MAX,
    dry_run: Annotated[bool, typer.Option(help="affiche sans créer de carte")] = False,
) -> None:
    """Rattrapage de « À classer » : une règle proposée par commerçant, toutes validées d'un
    coup dans l'app (« À valider »)."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
    report = catchup(
        _toolbox(cfg, "brain"), _model(cfg), Memory(cfg.state_dir), limit=limit, dry_run=dry_run
    )
    _report("brain.catchup", report, dry_run)


@app.command("direct")
def direct_cmd(
    limit: Annotated[int, typer.Option(min=1, max=1000, help="commerçants")] = DIRECT_MAX,
    max_count: Annotated[int, typer.Option(min=1, max=5, help="vu au plus N fois")] = 1,
    dry_run: Annotated[bool, typer.Option(help="affiche sans créer de carte")] = False,
) -> None:
    """Fin de « À classer » : les achats uniques, une carte par catégorie, sans règle."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
    report = direct(
        _toolbox(cfg, "brain"),
        _model(cfg),
        Memory(cfg.state_dir),
        limit=limit,
        max_count=max_count,
        dry_run=dry_run,
    )
    _report("brain.direct", report, dry_run)


def _report(event: str, report: Report, dry_run: bool) -> None:
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
    log.info(event, **summary)
    typer.echo(json.dumps(summary, ensure_ascii=False))


@app.command()
def check() -> None:
    """Contrôle de bout en bout : hub, modèle, l'outil du résumé du mois, puis un tour de
    conversation : à la question de sortie du lot 7, le modèle doit demander cet outil. La
    conversation entière est l'affaire de l'assistant (une seule boucle, audit M12)."""
    hub_logging.configure(get_settings().log_level, stream=sys.stderr)
    cfg = _cfg()
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
    summary = box.call(CHECK_TOOL, {})
    if summary.is_error:
        typer.echo(f"outil : {summary.text}")
        raise typer.Exit(1)
    typer.echo(f"outil : ok ({CHECK_TOOL}, données au {summary.data.get('data_as_of')})")
    today = _today()
    system = CHECK_SYSTEM.format(today=today.date().isoformat(), month=today.strftime("%Y-%m"))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": CHECK_QUESTION}]
    try:
        reply = model.chat(messages, box.definitions())
    except LlmError as exc:
        typer.echo(f"modèle : {exc}")
        raise typer.Exit(1) from None
    asked = [c.name for c in reply.tool_calls]
    typer.echo(f"question : {CHECK_QUESTION}\noutils demandés : {', '.join(asked) or 'aucun'}")
    if CHECK_TOOL not in asked:
        typer.echo(f"contrôle : écart, le modèle ne demande pas {CHECK_TOOL}")
        raise typer.Exit(1)
    typer.echo(f"contrôle : ok, le modèle demande {CHECK_TOOL}")


def main() -> None:  # pragma: no cover - point d'entrée
    app()
