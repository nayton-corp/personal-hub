"""Exécution d'un run : contexte d'un collecteur, conversion des erreurs en types d'échec,
déclaration au hub, et boucle planifiée du conteneur."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from hub.collectors.base import (
    CollectorConfig,
    Failure,
    Kind,
    Memory,
    Result,
)
from hub.collectors.browser import Browser, Selectors, open_browser, purge_diag
from hub.collectors.client import HubClient, HubUnavailable
from hub.collectors.dropbox import Inbox
from hub.core import cron
from hub.core.clock import local_today, local_tz, now_iso
from hub.core.logging import get_logger

log = get_logger("hub.collector")


@dataclass
class Env:
    """Ce qu'un flux de collecte reçoit : ses réglages, ses identifiants, sa mémoire, la boîte
    d'entrée et, pour les notifications, le client du hub."""

    name: str
    cfg: CollectorConfig
    creds: dict[str, Any]
    inbox_root: Path
    client: HubClient | None = None
    diagnose: bool = False
    today: date = field(default_factory=local_today)
    memory: Memory = field(init=False)
    inbox: Inbox = field(init=False)

    def __post_init__(self) -> None:
        self.memory = Memory(self.cfg.state_dir / f"{self.name}.json")
        self.inbox = Inbox(self.inbox_root, self.memory)

    def selectors(self, path: Path) -> Selectors:
        prefix = f"{self.name}."
        site = {k[len(prefix) :]: v for k, v in self.cfg.urls.items() if k.startswith(prefix)}
        return Selectors.load(path, site)

    def browser(self, selectors: Selectors) -> AbstractContextManager[Browser]:
        diag = self.cfg.diag / self.name if self.diagnose else None
        return open_browser(
            self.cfg.profiles / self.name, selectors, headless=self.cfg.headless, diag=diag
        )

    def notify(self, event: str) -> bool:
        return self.client.notify(self.name, event) if self.client else False

    def secret(self, key: str) -> str:
        value = self.creds.get(key)
        if not isinstance(value, str) or not value:
            raise Failure("auth_error", f"secret:{key}")
        return value


Flow = Callable[[Env, Kind], Result]


def flows() -> dict[str, Flow]:
    from hub.collectors.bcf import flow as bcf
    from hub.collectors.exchanges import binance, coinbase, kucoin
    from hub.collectors.ibkr import flow as ibkr
    from hub.collectors.market import flow as market
    from hub.collectors.revolut import flow as revolut
    from hub.collectors.viac import flow as viac

    return {
        "bcf": bcf.run,
        "viac": viac.run,
        "revolut": revolut.run,
        "ibkr": ibkr.run,
        "market": market.run,
        "binance": binance.run,
        "kucoin": kucoin.run,
        "coinbase": coinbase.run,
    }


def execute(env: Env, kind: Kind, flow: Flow | None = None) -> Result:
    """Un run complet ; ne lève jamais. Le résultat est déclaré au hub quand il est joignable."""
    started = now_iso()
    flow = flow or flows()[env.name]
    try:
        result = flow(env, kind)
    except Failure as f:
        result = Result(f.outcome, 0, f.detail)
    except Exception as exc:  # erreur inattendue : traitée comme un sélecteur manquant
        result = Result("unknown", 0, f"exception:{type(exc).__name__.lower()}")
    finally:
        env.memory.save()
    log.info(
        "collector.run",
        collector=env.name,
        kind=kind,
        outcome=result.outcome,
        files=result.files,
        detail=result.detail,
    )
    if env.client is not None:
        try:
            env.client.report(env.name, kind, result, started, now_iso())
        except HubUnavailable as exc:
            log.warning("collector.report_failed", collector=env.name, error=str(exc))
    return result


# --- boucle du conteneur ---------------------------------------------------------------------


def _minutes(start: datetime) -> Iterator[datetime]:
    nxt = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while True:
        yield nxt
        nxt += timedelta(minutes=1)


def due(schedule: str, at: datetime) -> bool:
    return any(job.due(at) for job in cron.parse(f"{schedule} run"))


def tick(
    make_env: Callable[[str], Env],
    names: list[str],
    cfg: CollectorConfig,
    at: datetime,
    *,
    poll_checks: bool,
    runner: Callable[[Env, Kind], Result] = execute,
) -> list[tuple[str, Kind, str]]:
    """Une minute de la boucle : runs planifiés si le collecteur est `enabled`, contrôles
    demandés depuis l'app. Sans réponse du hub, rien ne part : un run doit pouvoir être déclaré."""
    done: list[tuple[str, Kind, str]] = []
    for name in names:
        scheduled = due(cfg.schedules.get(name, ""), at) if cfg.schedules.get(name) else False
        if not scheduled and not poll_checks:
            continue
        env = make_env(name)
        try:
            state = env.client.state(name) if env.client else {"mode": "enabled"}
        except HubUnavailable as exc:
            log.warning("collector.hub_unavailable", collector=name, error=str(exc))
            continue
        if state.get("check_requested"):
            done.append((name, "check", runner(env, "check").outcome))
        elif scheduled and state.get("mode") == "enabled":
            done.append((name, "run", runner(env, "run").outcome))
        elif scheduled:
            log.info("collector.skipped", collector=name, mode=state.get("mode"))
    return done


def run_forever(
    make_env: Callable[[str], Env], names: list[str], cfg: CollectorConfig
) -> None:  # pragma: no cover - boucle
    log.info("collector.daemon_start", collectors=names)
    last_poll = 0
    last_purge = ""
    tz = local_tz()
    for at in _minutes(datetime.now(tz)):
        time.sleep(max(0, (at - datetime.now(tz)).total_seconds()))
        if at.date().isoformat() != last_purge:
            last_purge = at.date().isoformat()
            purge_diag(cfg.diag, cfg.diag_keep_days)
        poll = time.monotonic_ns() - last_poll >= cfg.check_poll_seconds * 1_000_000_000
        if poll:
            last_poll = time.monotonic_ns()
        tick(make_env, names, cfg, at, poll_checks=poll)
