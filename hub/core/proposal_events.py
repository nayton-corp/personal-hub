"""Boîtes de sortie des domaines, côté cœur : `proposal.request` crée une carte, `proposal.obsolete`
rend sans objet celle qui attend, `notify.request` envoie une notification. Une lecture à la fois.
"""

from __future__ import annotations

import threading
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text

from hub.core.auth import Principal
from hub.core.context import HubContext
from hub.core.domain import Domain
from hub.core.errors import Problem
from hub.core.links import owner
from hub.core.notify import Message
from hub.core.proposals import create
from hub.kernel import canonical
from hub.kernel.clock import now_iso
from hub.platform.logging import get_logger

log = get_logger("hub.proposals")

EVENTS_CONSUMER = "proposals"


_SYNC = threading.Lock()  # deux lectures en même temps enverraient deux fois la même alerte


def sync_events(hub: HubContext, limit: int = 500) -> dict[str, int]:
    """Lit la boîte de sortie de chaque domaine : `proposal.request` crée une carte (création
    idempotente), `proposal.obsolete` rend sans objet celle qui attend encore,
    `notify.request` envoie une notification (texte générique, posé par une sentinelle).
    Une lecture à la fois (audit m18) : un passage qui en trouve une en cours ne fait rien, le
    suivant reprend où le curseur en est."""
    counts = {"requested": 0, "obsoleted": 0, "notified": 0}
    if not _SYNC.acquire(blocking=False):
        return counts
    try:
        return _sync_events(hub, limit, counts)
    finally:
        _SYNC.release()


def _sync_events(hub: HubContext, limit: int, counts: dict[str, int]) -> dict[str, int]:
    for d in hub.registry:
        with hub.core.engine.connect() as conn:
            row = conn.execute(
                text("SELECT cursor FROM event_cursors WHERE consumer = :c AND domain = :d"),
                {"c": EVENTS_CONSUMER, "d": d.name},
            ).first()
        cursor = int(row[0]) if row else 0
        while events := d.events_since(cursor, limit):
            for e in events:
                if e.type == "proposal.request":
                    counts["requested"] += _requested(hub, d, e.payload)
                elif e.type == "proposal.obsolete":
                    counts["obsoleted"] += _obsolete(hub, d.name, e.payload)
                elif e.type == "notify.request":
                    counts["notified"] += _notify(hub, e.payload)
            cursor = events[-1].seq
            with hub.core.engine.begin() as conn:
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
    return counts


def _notify(hub: HubContext, payload: dict[str, Any]) -> int:
    title = str(payload.get("title") or "Personal Hub")[:120]
    body = str(payload.get("body") or "")[:300]
    click = str(payload.get("click") or "")
    msg = Message(title, body, tags=str(payload.get("tags") or ""), click=click[:200])
    return int(hub.notifier.send(msg))


def _requested(hub: HubContext, d: Domain, payload: dict[str, Any]) -> int:
    try:
        _p, created = create(
            hub,
            Principal(f"system:{d.name}", frozenset(), is_app=True),
            d.name,
            str(payload.get("kind")),
            dict(payload.get("params") or {}),
            reason=payload.get("reason"),
        )
    except Problem as exc:  # sans objet entre-temps (import déjà appliqué…)
        log.info("proposal.request_skipped", domain=d.name, type=exc.type)
        return 0
    return int(created)


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
