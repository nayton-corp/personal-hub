"""Propositions (Double Sas), côté cœur : création idempotente, lecture, refus, expiration et
réconciliation. La validation signée (`accept`) arrive au lot 3 (L3-02).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Row, text
from sqlalchemy.exc import IntegrityError

from hub.core import canonical
from hub.core.auth import Principal
from hub.core.clock import iso, now_iso, parse_iso, utcnow
from hub.core.context import HubContext
from hub.core.coredb import audit
from hub.core.domain import ExternalHandler, LocalHandler, Preview, ProposalKind
from hub.core.errors import Problem
from hub.core.ids import new_id, urn

FINAL = frozenset({"applied", "rejected", "expired", "superseded", "obsolete", "failed"})
APPLYING_GRACE = timedelta(minutes=5)


@dataclass(frozen=True)
class Proposal:
    id: str
    domain: str
    kind: str
    params: dict[str, Any]
    params_hash: str
    preview: dict[str, Any]
    fingerprint: str
    revision: int
    status: str
    tier: str
    created_by: str
    reason: str | None
    bundle_id: str | None
    create_key: str | None
    created_at: str
    expires_at: str
    decided_at: str | None
    result: dict[str, Any] | None

    @property
    def urn(self) -> str:
        return urn("core", "proposal", self.id)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "urn": self.urn,
            "domain": self.domain,
            "kind": self.kind,
            "params": self.params,
            "revision": self.revision,
            "status": self.status,
            "tier": self.tier,
            "preview": self.preview,
            "reason": self.reason,
            "bundle_id": self.bundle_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "decided_at": self.decided_at,
            "result": self.result,
        }


def _from_row(r: Row[Any]) -> Proposal:
    m = r._mapping
    return Proposal(
        id=m["id"],
        domain=m["domain"],
        kind=m["kind"],
        params=json.loads(m["params_json"]),
        params_hash=m["params_hash"],
        preview=json.loads(m["preview_json"]),
        fingerprint=m["fingerprint"],
        revision=m["revision"],
        status=m["status"],
        tier=m["tier"],
        created_by=m["created_by"],
        reason=m["reason"],
        bundle_id=m["bundle_id"],
        create_key=m["create_key"],
        created_at=m["created_at"],
        expires_at=m["expires_at"],
        decided_at=m["decided_at"],
        result=json.loads(m["result_json"]) if m["result_json"] else None,
    )


def get(conn: Connection, proposal_id: str) -> Proposal:
    row = conn.execute(text("SELECT * FROM proposals WHERE id = :id"), {"id": proposal_id}).first()
    if row is None:
        raise Problem("proposal.not_found")
    return _from_row(row)


def list_by_status(conn: Connection, status: str | None, limit: int = 100) -> list[Proposal]:
    if status is None:
        rows = conn.execute(
            text("SELECT * FROM proposals ORDER BY created_at DESC LIMIT :n"), {"n": limit}
        ).fetchall()
    else:
        rows = conn.execute(
            text("SELECT * FROM proposals WHERE status = :s ORDER BY created_at DESC LIMIT :n"),
            {"s": status, "n": limit},
        ).fetchall()
    return [_from_row(r) for r in rows]


def _check_allowed(principal: Principal, domain: str, kind: ProposalKind) -> None:
    if principal.is_app:
        return
    if not principal.allows(f"{domain}:propose"):
        raise Problem("auth.scope")
    if not kind.ai_allowed:
        raise Problem("proposal.kind_not_allowed")


def _validate(kind: ProposalKind, params: dict[str, Any]) -> BaseModel:
    try:
        return kind.params_model.model_validate(params)
    except ValidationError as exc:
        errors = [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        raise Problem("validation.params", errors=errors) from None


def _preview(hub: HubContext, domain: str, kind: ProposalKind, params: BaseModel) -> Preview:
    if kind.external:
        external: ExternalHandler = kind.handler  # type: ignore[assignment]
        return external.preview(params)
    local: LocalHandler = kind.handler  # type: ignore[assignment]
    with hub.registry.get(domain).engine().connect() as conn:
        return local.preview(conn, params)


def _tier(conn: Connection, domain: str, kind: str) -> str:
    row = conn.execute(
        text("SELECT tier FROM approval_policies WHERE domain = :d AND kind = :k"),
        {"d": domain, "k": kind},
    ).first()
    return str(row[0]) if row is not None else "human"


def _existing(
    conn: Connection, domain: str, kind: str, params_hash: str, create_key: str | None
) -> Proposal | None:
    if create_key is not None:
        row = conn.execute(
            text("SELECT * FROM proposals WHERE create_key = :k"), {"k": create_key}
        ).first()
        if row is not None:
            found = _from_row(row)
            if (found.domain, found.kind, found.params_hash) != (domain, kind, params_hash):
                raise Problem("idempotency.key_mismatch")
            return found
    row = conn.execute(
        text(
            "SELECT * FROM proposals WHERE domain = :d AND kind = :k AND params_hash = :h "
            "AND status = 'pending'"
        ),
        {"d": domain, "k": kind, "h": params_hash},
    ).first()
    return _from_row(row) if row is not None else None


def create(
    hub: HubContext,
    principal: Principal,
    domain: str,
    kind_name: str,
    params: dict[str, Any],
    *,
    reason: str | None = None,
    bundle_id: str | None = None,
    create_key: str | None = None,
) -> tuple[Proposal, bool]:
    """Renvoie (proposition, créée ?). Une même clé, ou une proposition identique encore en
    attente, renvoie la proposition existante au lieu d'en créer une seconde."""
    d = hub.registry.get(domain)
    kind = d.proposal_kinds.get(kind_name)
    if kind is None:
        raise Problem("proposal.kind_unknown")
    _check_allowed(principal, domain, kind)
    model = _validate(kind, params)
    clean = model.model_dump(mode="json")
    params_hash = canonical.sha256_hex({"domain": domain, "kind": kind_name, "params": clean})

    with hub.core.engine.connect() as conn:
        found = _existing(conn, domain, kind_name, params_hash, create_key)
    if found is not None:
        return found, False

    preview = _preview(hub, domain, kind, model)
    now = utcnow()
    proposal_id = new_id()
    try:
        with hub.core.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO proposals (id, domain, kind, params_json, params_hash, "
                    "preview_json, fingerprint, revision, status, tier, created_by, reason, "
                    "bundle_id, create_key, created_at, expires_at) VALUES (:id, :d, :k, :p, :h, "
                    ":pv, :fp, 1, 'pending', :tier, :by, :reason, :bundle, :ck, :at, :exp)"
                ),
                {
                    "id": proposal_id,
                    "d": domain,
                    "k": kind_name,
                    "p": canonical.dumps(clean),
                    "h": params_hash,
                    "pv": canonical.dumps({"summary": preview.summary, "details": preview.details}),
                    "fp": preview.fingerprint,
                    "tier": _tier(conn, domain, kind_name),
                    "by": principal.actor,
                    "reason": reason,
                    "bundle": bundle_id,
                    "ck": create_key,
                    "at": iso(now),
                    "exp": iso(now + kind.ttl),
                },
            )
            audit(
                conn, principal.actor, "proposal.create", urn("core", "proposal", proposal_id), "ok"
            )
    except IntegrityError:
        # course perdue contre une création identique : on renvoie la gagnante
        with hub.core.engine.connect() as conn:
            found = _existing(conn, domain, kind_name, params_hash, create_key)
        if found is None:
            raise
        return found, False
    with hub.core.engine.connect() as conn:
        return get(conn, proposal_id), True


def reject(hub: HubContext, principal: Principal, proposal_id: str) -> Proposal:
    with hub.core.engine.begin() as conn:
        p = get(conn, proposal_id)
        res = conn.execute(
            text(
                "UPDATE proposals SET status = 'rejected', decided_at = :at "
                "WHERE id = :id AND status = 'pending'"
            ),
            {"id": proposal_id, "at": now_iso()},
        )
        if res.rowcount != 1:
            raise Problem("proposal.not_pending", status_now=p.status)
        audit(conn, principal.actor, "proposal.reject", p.urn, "ok")
        return get(conn, proposal_id)


def expire(conn: Connection) -> int:
    return conn.execute(
        text(
            "UPDATE proposals SET status = 'expired', decided_at = :now "
            "WHERE status = 'pending' AND expires_at <= :now"
        ),
        {"now": now_iso()},
    ).rowcount


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
    for domain in hub.registry:
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
    return ReconcileReport(marked, released)
