"""Expiration et réconciliation des propositions : `applied_proposals` du domaine fait foi,
le statut de `core.db` n'en est qu'un reflet ; un effet externe au résultat inconnu est redemandé
au tiers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from hub.core.context import HubContext
from hub.core.coredb import audit
from hub.core.domain import ExternalHandler
from hub.core.links import owner, owners
from hub.core.proposals import APPLYING_GRACE, from_row, mark
from hub.kernel import canonical
from hub.kernel.clock import now_iso, parse_iso, utcnow
from hub.kernel.ids import urn
from hub.platform.logging import get_logger

log = get_logger("hub.proposals")


@dataclass(frozen=True)
class ReconcileReport:
    marked_applied: int
    released: int


def reconcile(hub: HubContext) -> ReconcileReport:
    """`applied_proposals` du domaine fait foi ; le statut de `core.db` n'en est qu'un reflet.

    - pending ou applying présente dans `applied_proposals` → applied ;
    - applying absente depuis plus de 5 minutes → pending.
    """
    marked = released = 0
    cutoff = utcnow() - APPLYING_GRACE
    for domain in owners(hub):
        with hub.core.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, status, claimed_at FROM proposals "
                    "WHERE domain = :d AND status IN ('pending', 'applying')"
                ),
                {"d": domain.name},
            ).fetchall()
        if not rows:
            continue
        applied = domain.applied([r.id for r in rows])
        with hub.core.engine.begin() as conn:
            for r in rows:
                if r.id in applied:
                    conn.execute(
                        text(
                            "UPDATE proposals SET status = 'applied', result_json = :res, "
                            "decided_at = coalesce(decided_at, :at) WHERE id = :id"
                        ),
                        {"id": r.id, "res": canonical.dumps(applied[r.id]), "at": now_iso()},
                    )
                    audit(
                        conn,
                        "system:reconcile",
                        "proposal.reconciled",
                        urn("core", "proposal", r.id),
                        "applied",
                    )
                    marked += 1
                elif r.status == "applying" and (
                    r.claimed_at is None or parse_iso(r.claimed_at) < cutoff
                ):
                    conn.execute(
                        text(
                            "UPDATE proposals SET status = 'pending', claimed_at = NULL "
                            "WHERE id = :id AND status = 'applying'"
                        ),
                        {"id": r.id},
                    )
                    audit(
                        conn,
                        "system:reconcile",
                        "proposal.reconciled",
                        urn("core", "proposal", r.id),
                        "released",
                    )
                    released += 1
    marked += _reconcile_external(hub)
    return ReconcileReport(marked, released)


def _reconcile_external(hub: HubContext) -> int:
    """Effet externe au résultat inconnu : on redemande au tiers où il en est."""
    with hub.core.engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM proposals WHERE status = 'unknown'")).fetchall()
    done = 0
    for r in rows:
        p = from_row(r)
        kind = owner(hub, p.domain).proposal_kinds.get(p.kind)
        if kind is None or not kind.external:
            continue
        external: ExternalHandler = kind.handler  # type: ignore[assignment]
        try:
            res = external.reconcile(p.id)
        except Exception as exc:
            log.warning("proposal.reconcile_failed", proposal=p.id, error=type(exc).__name__)
            continue
        if res.status != "unknown":
            status = "applied" if res.status == "ok" else "failed"
            mark(hub, p, status, res.detail, None, "system:reconcile")
            done += 1
    return done
