"""Exécution d'un run : contexte d'une connexion, conversion des erreurs en types d'échec,
déclaration au hub, et boucle planifiée d'un service collecteur (G4 : `collector-api` ou
`collector-browser`, qui demande chaque minute au hub les connexions qu'il exécute)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator, Sequence
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


@dataclass(frozen=True)
class Assigned:
    """Une connexion confiée au service par le hub ; `secrets` reste chiffré jusqu'au run."""

    id: str
    connector: str
    label: str
    schedule: str | None
    settings: dict[str, Any]
    secrets: str | None

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> Assigned:
        return cls(
            str(raw["id"]),
            str(raw["connector"]),
            str(raw.get("label") or raw["id"]),
            raw.get("schedule"),
            dict(raw.get("settings") or {}),
            raw.get("secrets"),
        )


@dataclass
class Env:
    """Ce qu'un flux de collecte reçoit : ses réglages, ses identifiants, sa mémoire, la boîte
    d'entrée et, pour les notifications, le client du hub. `name` est l'identifiant de la
    connexion (état, mémoire, profil du navigateur), `connector` le flux qui l'exécute."""

    name: str
    cfg: CollectorConfig
    creds: dict[str, Any]
    inbox_root: Path
    client: HubClient | None = None
    diagnose: bool = False
    today: date = field(default_factory=local_today)
    connector: str = ""
    memory: Memory = field(init=False)
    inbox: Inbox = field(init=False)

    def __post_init__(self) -> None:
        self.connector = self.connector or self.name
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
        "enable_banking": revolut.run,
        "ibkr": ibkr.run,
        "market": market.run,
        "binance": binance.run,
        "kucoin": kucoin.run,
        "coinbase": coinbase.run,
    }


def execute(env: Env, kind: Kind, flow: Flow | None = None) -> Result:
    """Un run complet ; ne lève jamais. Le résultat est déclaré au hub quand il est joignable."""
    started = now_iso()
    flow = flow or flows()[env.connector]
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


# --- consentement demandé depuis l'app (G5) ---------------------------------------------------

# connexions dont la liaison tourne dans un fil : leurs runs attendent qu'elle finisse
LINKING: set[str] = set()
_linking = threading.Lock()


def link_now(env: Env, redirect_url: str) -> Result:
    """Liaison Enable Banking lancée depuis l'app : l'adresse d'autorisation remonte au hub,
    qui l'affiche ; le retour du navigateur débloque la reprise complète. Déclarée comme un
    contrôle, réussi ou non ; ne lève jamais."""
    from hub.collectors.revolut import flow as open_banking

    def show(url: str) -> None:
        if env.client is not None:
            env.client.set_link_url(env.name, url)

    def linked(e: Env, _kind: Kind) -> Result:
        return open_banking.link(e, redirect_url, show)

    try:
        return execute(env, "check", linked)
    finally:
        if env.client is not None:
            try:
                env.client.set_link_url(env.name, None)
            except HubUnavailable as exc:
                log.warning("collector.link_clear_failed", collector=env.name, error=str(exc))


def start_link(env: Env, redirect_url: str) -> threading.Thread | None:
    """La liaison attend le retour jusqu'à 15 minutes : elle tourne à côté de la boucle, une
    seule à la fois par connexion."""
    with _linking:
        if env.name in LINKING:
            return None
        LINKING.add(env.name)

    def work() -> None:
        try:
            link_now(env, redirect_url)
        finally:
            with _linking:
                LINKING.discard(env.name)

    thread = threading.Thread(target=work, name=f"link-{env.name}", daemon=True)
    thread.start()
    return thread


# --- boucle du conteneur ---------------------------------------------------------------------


def _minutes(start: datetime) -> Iterator[datetime]:
    nxt = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while True:
        yield nxt
        nxt += timedelta(minutes=1)


def due(schedule: str, at: datetime) -> bool:
    return any(job.due(at) for job in cron.parse(f"{schedule} run"))


def tick(
    make_env: Callable[[Assigned], Env],
    items: Sequence[Assigned],
    client: HubClient | None,
    at: datetime,
    *,
    poll_checks: bool,
    runner: Callable[[Env, Kind], Result] = execute,
    linker: Callable[[Env], object] | None = None,
) -> list[tuple[str, str, str]]:
    """Une minute de la boucle : runs planifiés ou actualisations demandées depuis l'app si la
    connexion est `enabled`, contrôles et consentements demandés depuis l'app. Sans réponse du
    hub, rien ne part : un run doit pouvoir être déclaré. Les secrets d'une connexion ne sont
    déchiffrés que si elle tourne maintenant."""
    done: list[tuple[str, str, str]] = []
    for item in items:
        if item.id in LINKING:
            continue
        scheduled = bool(item.schedule) and due(str(item.schedule), at)
        if not scheduled and not poll_checks:
            continue
        try:
            state = client.state(item.id) if client else {"mode": "enabled"}
        except HubUnavailable as exc:
            log.warning("collector.hub_unavailable", collector=item.id, error=str(exc))
            continue
        if state.get("link_requested") and linker is not None:
            if item.connector != "enable_banking":
                continue
            try:
                env = make_env(item)
            except Exception as exc:
                done.append((item.id, "check", _refused(client, item.id, "check", exc).outcome))
                continue
            linker(env)
            done.append((item.id, "link", "started"))
            continue
        kind: Kind
        if state.get("check_requested"):
            kind = "check"
        elif (scheduled or state.get("run_requested")) and state.get("mode") == "enabled":
            kind = "run"
        else:
            if scheduled:
                log.info("collector.skipped", collector=item.id, mode=state.get("mode"))
            continue
        try:
            env = make_env(item)
        except Exception as exc:  # secrets illisibles, réglage invalide : déclaré, pas de run
            done.append((item.id, kind, _refused(client, item.id, kind, exc).outcome))
            continue
        done.append((item.id, kind, runner(env, kind).outcome))
    return done


def _refused(client: HubClient | None, name: str, kind: Kind, exc: Exception) -> Result:
    result = Result("unknown", 0, f"config:{type(exc).__name__.lower()}")
    log.warning("collector.config_refused", collector=name, error=type(exc).__name__)
    if client is not None:
        try:
            client.report(name, kind, result, now_iso(), now_iso())
        except HubUnavailable as e:
            log.warning("collector.report_failed", collector=name, error=str(e))
    return result


def assigned(client: HubClient, runner: str) -> list[Assigned] | None:
    """Les connexions du service, ou None si le hub ne répond pas (la minute est sautée)."""
    try:
        return [Assigned.parse(raw) for raw in client.connections(runner)]
    except HubUnavailable as exc:
        log.warning("collector.hub_unavailable", runner=runner, error=str(exc))
        return None


def run_forever(
    make_env: Callable[[Assigned], Env],
    runner: str,
    cfg: CollectorConfig,
    client: HubClient,
    linker: Callable[[Env], object] | None = None,
) -> None:  # pragma: no cover - boucle
    log.info("collector.daemon_start", runner=runner)
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
        items = assigned(client, runner)
        if items is not None:
            tick(make_env, items, client, at, poll_checks=poll, linker=linker)
