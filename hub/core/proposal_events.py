"""Boîtes de sortie des domaines, côté cœur : `proposal.request` crée une carte, `proposal.obsolete`
rend sans objet celle qui attend, `notify.request` envoie une notification. Une lecture à la fois.
Une demande peut porter une `create_key` : une seule carte pour cette clé, quel que soit son sort.

Rien ne se perd et rien ne bloque (audit du 10/11, N1 et N3) : une notification que ntfy n'a pas
prise, ou un événement dont le traitement lève une erreur, passe dans la file de renvoi
(`event_retries`) et le curseur avance. Chaque passage commence par la file. Une notification y
reste un jour ; un autre événement, quelques essais, puis il est mis de côté avec une alerte.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text

from hub.core import notify
from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Domain
from hub.core.errors import Problem
from hub.core.links import owner
from hub.core.notify import Message
from hub.core.proposals import create
from hub.kernel import canonical
from hub.kernel.clock import now_iso, parse_iso, utcnow
from hub.platform.logging import get_logger

log = get_logger("hub.proposals")

EVENTS_CONSUMER = "proposals"
MAX_ATTEMPTS = 5  # essais d'un événement fautif avant de le mettre de côté
NOTIFY_KEPT = timedelta(hours=24)  # une notification attend ntfy un jour, pas plus
COUNTED = {
    "proposal.request": "requested",
    "proposal.obsolete": "obsoleted",
    "notify.request": "notified",
}

_SYNC = threading.Lock()  # deux lectures en même temps enverraient deux fois la même alerte


class NotSent(Exception):
    """ntfy est réglé et n'a pas pris le message : à renvoyer."""


@dataclass
class _Pass:
    counts: dict[str, int] = field(
        default_factory=lambda: {"requested": 0, "obsoleted": 0, "notified": 0}
    )
    ntfy_down: bool = False  # un envoi a échoué : les suivants attendent le prochain passage


def sync_events(hub: HubContext, limit: int = 500) -> dict[str, int]:
    """Lit la boîte de sortie de chaque domaine : `proposal.request` crée une carte (création
    idempotente), `proposal.obsolete` rend sans objet celle qui attend encore,
    `notify.request` envoie une notification (texte générique, posé par une sentinelle).
    Une lecture à la fois (audit m18) : un passage qui en trouve une en cours ne fait rien, le
    suivant reprend où le curseur en est."""
    state = _Pass()
    if not _SYNC.acquire(blocking=False):
        return state.counts
    try:
        _retry(hub, state)
        return _sync_events(hub, limit, state)
    finally:
        _SYNC.release()


def _handle(hub: HubContext, d: Domain, kind: str, payload: dict[str, Any], state: _Pass) -> None:
    """Traite un événement ; lève si c'est à refaire."""
    if kind == "proposal.request":
        state.counts["requested"] += _requested(hub, d, payload)
    elif kind == "proposal.obsolete":
        state.counts["obsoleted"] += _obsolete(hub, d.name, payload)
    elif kind == "notify.request":
        if state.ntfy_down:
            raise NotSent
        try:
            state.counts["notified"] += _notify(hub, payload)
        except NotSent:
            state.ntfy_down = True
            raise


def _sync_events(hub: HubContext, limit: int, state: _Pass) -> dict[str, int]:
    for d in hub.registry:
        with hub.core.engine.connect() as conn:
            row = conn.execute(
                text("SELECT cursor FROM event_cursors WHERE consumer = :c AND domain = :d"),
                {"c": EVENTS_CONSUMER, "d": d.name},
            ).first()
        cursor = int(row[0]) if row else 0
        while events := d.events_since(cursor, limit):
            held: list[dict[str, Any]] = []
            for e in events:
                if e.type not in COUNTED:
                    continue
                try:
                    _handle(hub, d, e.type, e.payload, state)
                except Exception as exc:  # à refaire au passage suivant, sans bloquer la file
                    held.append(_held(d.name, e.seq, e.type, e.payload, exc))
            cursor = events[-1].seq
            with hub.core.engine.begin() as conn:
                for h in held:
                    conn.execute(
                        text(
                            "INSERT OR IGNORE INTO event_retries (domain, seq, type, payload, "
                            "status, attempts, last_error, created_at, updated_at) VALUES "
                            "(:domain, :seq, :type, :payload, 'waiting', 1, :error, :at, :at)"
                        ),
                        h,
                    )
                values = {"c": EVENTS_CONSUMER, "d": d.name, "n": cursor, "at": now_iso()}
                moved = conn.execute(
                    text(
                        "UPDATE event_cursors SET cursor = :n, updated_at = :at "
                        "WHERE consumer = :c AND domain = :d"
                    ),
                    values,
                ).rowcount
                if not moved:
                    conn.execute(
                        text(
                            "INSERT INTO event_cursors (consumer, domain, cursor, updated_at) "
                            "VALUES (:c, :d, :n, :at)"
                        ),
                        values,
                    )
            if len(events) < limit:
                break
    return state.counts


def _held(
    domain: str, seq: int, kind: str, payload: dict[str, Any], exc: Exception
) -> dict[str, Any]:
    if not isinstance(exc, NotSent):
        log.warning("events.held", domain=domain, seq=seq, type=kind, error=type(exc).__name__)
    return {
        "domain": domain,
        "seq": seq,
        "type": kind,
        "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
        "error": type(exc).__name__,
        "at": now_iso(),
    }


def _retry(hub: HubContext, state: _Pass) -> None:
    """La file de renvoi, la plus ancienne ligne d'abord."""
    with hub.core.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT domain, seq, type, payload, attempts, created_at FROM event_retries "
                "WHERE status = 'waiting' ORDER BY created_at, domain, seq"
            )
        ).all()
    for domain, seq, kind, payload, attempts, created_at in rows:
        key = {"d": domain, "s": seq, "at": now_iso()}
        try:
            _handle(hub, hub.registry.get(domain), kind, json.loads(payload), state)
        except Exception as exc:
            old = utcnow() - parse_iso(created_at) >= NOTIFY_KEPT
            give_up = old if isinstance(exc, NotSent) else attempts + 1 >= MAX_ATTEMPTS
            with hub.core.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE event_retries SET attempts = attempts + 1, last_error = :e, "
                        "status = :st, updated_at = :at WHERE domain = :d AND seq = :s"
                    ),
                    key | {"e": type(exc).__name__, "st": "set_aside" if give_up else "waiting"},
                )
            if give_up:
                _set_aside(hub, domain, seq, kind, exc)
            continue
        with hub.core.engine.begin() as conn:
            conn.execute(text("DELETE FROM event_retries WHERE domain = :d AND seq = :s"), key)


def _set_aside(hub: HubContext, domain: str, seq: int, kind: str, exc: Exception) -> None:
    log.error("events.set_aside", domain=domain, seq=seq, type=kind, error=type(exc).__name__)
    if isinstance(exc, NotSent):  # ntfy ne répond pas depuis un jour : rien à lui confier
        return
    hub.notifier.send(
        Message(
            "Hub : un événement mis de côté",
            f"Domaine {domain}, {kind} : {MAX_ATTEMPTS} essais sans succès. "
            "La file continue ; la ligne reste dans event_retries.",
            priority="high",
            tags="warning",
        )
    )


def _notify(hub: HubContext, payload: dict[str, Any]) -> int:
    title = str(payload.get("title") or "Personal Hub")[:120]
    body = str(payload.get("body") or "")[:300]
    click = str(payload.get("click") or "")
    msg = Message(title, body, tags=str(payload.get("tags") or ""), click=click[:200])
    if hub.notifier.send(msg):
        return 1
    if notify.topic(hub.notifier.settings) is None:
        return 0  # ntfy pas réglé : rien à renvoyer, le journal en garde la trace
    raise NotSent


def _requested(hub: HubContext, d: Domain, payload: dict[str, Any]) -> int:
    try:
        _p, created = create(
            hub,
            Principal(f"system:{d.name}", frozenset(), is_app=True),
            d.name,
            str(payload.get("kind")),
            dict(payload.get("params") or {}),
            reason=payload.get("reason"),
            create_key=_key(payload.get("create_key")),
        )
    except Problem as exc:  # sans objet entre-temps (import déjà appliqué…)
        log.info("proposal.request_skipped", domain=d.name, type=exc.type)
        return 0
    return int(created)


def _key(raw: object) -> str | None:
    """Une clé de création posée par le domaine : la carte n'est créée qu'une fois pour elle,
    même refusée ou expirée (une proposition devinée qu'on a refusée ne revient pas)."""
    return raw[:200] if isinstance(raw, str) and raw else None


def _obsolete(hub: HubContext, domain: str, payload: dict[str, Any]) -> int:
    kind = str(payload.get("kind"))
    d = owner(hub, domain)
    pk = d.proposal_kinds.get(kind)
    if pk is None:
        return 0
    try:
        clean = pk.params_model.model_validate(payload.get("params") or {}).model_dump(mode="json")
    except ValidationError:
        return 0
    params_hash = canonical.sha256_hex({"domain": domain, "kind": kind, "params": clean})
    with hub.core.engine.begin() as conn:
        n = conn.execute(
            text(
                "UPDATE proposals SET status = 'obsolete', decided_at = :at WHERE domain = :d "
                "AND kind = :k AND params_hash = :h AND status = 'pending'"
            ),
            {"d": domain, "k": kind, "h": params_hash, "at": now_iso()},
        ).rowcount
    return int(n)
