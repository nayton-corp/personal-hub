"""Propositions (Double Sas), côté cœur : création idempotente, politique d'approbation,
validation (`accept`, section 5), refus, inverses, expiration et réconciliation.

Le statut de `core.db` n'est qu'un reflet : ce qui fait foi est `applied_proposals`, écrite
par le domaine dans la transaction de l'effet.
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
from hub.core.db import DatabaseBusy, begin_immediate
from hub.core.domain import Domain, ExternalHandler, LocalHandler, Preview, ProposalKind
from hub.core.errors import Problem
from hub.core.ids import new_id, urn
from hub.core.logging import get_logger
from hub.core.notify import Message

FINAL = frozenset({"applied", "rejected", "expired", "superseded", "obsolete", "failed"})
APPLYING_GRACE = timedelta(minutes=5)
MAX_BATCH = 50
BUSY_RETRY_SECONDS = 2
# acteur des effets appliqués sans carte (palier auto ou auto_digest)
POLICY_ACTOR = "system:policy"
SYSTEM = Principal("system:hub", frozenset(), is_app=True)
log = get_logger("hub.proposals")


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


def find(hub: HubContext, domain: str, kind: str, params: dict[str, Any]) -> Proposal | None:
    """Dernière proposition pour ces paramètres exacts (une carte liée à un import…)."""
    pk = hub.registry.get(domain).proposal_kinds.get(kind)
    if pk is None:
        return None
    clean = pk.params_model.model_validate(params).model_dump(mode="json")
    params_hash = canonical.sha256_hex({"domain": domain, "kind": kind, "params": clean})
    with hub.core.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT * FROM proposals WHERE domain = :d AND kind = :k AND params_hash = :h "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"d": domain, "k": kind, "h": params_hash},
        ).first()
    return _from_row(row) if row is not None else None


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


def _enforce_hourly(hub: HubContext, principal: Principal) -> None:
    """Un jeton crée au plus `auth.token_proposals_per_hour` propositions par heure glissante
    (un modèle emballé, ou manipulé par un libellé, ne noie pas l'app sous les cartes)."""
    since = iso(utcnow() - timedelta(hours=1))
    with hub.core.engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM proposals WHERE created_by = :a AND created_at >= :s"),
            {"a": principal.actor, "s": since},
        ).scalar_one()
    if count >= hub.settings.auth.token_proposals_per_hour:
        raise Problem(
            "rate_limited", "trop de propositions cette heure", headers={"Retry-After": "600"}
        )


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


def tier_for(
    conn: Connection, principal: Principal, domain: str, kind: str, external_text: bool | None
) -> str:
    if not principal.is_app and external_text is not False:
        return "human"
    return _tier(conn, domain, kind)


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
    external_text: bool | None = None,
) -> tuple[Proposal, bool]:
    """Renvoie (proposition, créée ?). Une même clé, ou une proposition identique encore en
    attente, renvoie la proposition existante au lieu d'en créer une seconde.

    Le palier vient de `approval_policies`. Un jeton (un modèle) reste au palier `human` tant
    qu'il ne déclare pas `external_text = False` : une proposition tirée d'un texte externe
    passe toujours par une carte. Aux paliers `auto` et `auto_digest`, l'effet est appliqué
    tout de suite."""
    d = hub.registry.get(domain)
    kind = d.proposal_kinds.get(kind_name)
    if kind is None:
        raise Problem("proposal.kind_unknown")
    _check_allowed(principal, domain, kind)
    model = _validate(kind, params)
    if not principal.is_app:
        _enforce_hourly(hub, principal)
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
                    "tier": tier_for(conn, principal, domain, kind_name, external_text),
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
        p = get(conn, proposal_id)
    if p.tier != "human":
        try:
            accept_one(hub, Principal(POLICY_ACTOR, frozenset(), is_app=True), p, None)
        except Problem as exc:  # reste en attente, comme une carte
            log.warning("proposal.auto_failed", proposal=p.id, type=exc.type)
        with hub.core.engine.connect() as conn:
            p = get(conn, proposal_id)
    return p, True


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


# --- validation (section 5, application côté cœur) ------------------------------------------


def approval_digest(items: list[Proposal], action: str = "accept") -> str:
    """sha256 de la liste triée des triplets (id, révision, empreinte) : c'est ce que le défi
    WebAuthn contient, donc ce que Face ID signe."""
    triples = sorted([p.id, p.revision, p.fingerprint] for p in items)
    return canonical.sha256_hex({"action": action, "proposals": triples})


def load_many(hub: HubContext, ids: list[str]) -> list[Proposal]:
    unique = list(dict.fromkeys(ids))
    if not unique or len(unique) > MAX_BATCH:
        raise Problem("validation.params", f"de 1 à {MAX_BATCH} propositions")
    with hub.core.engine.connect() as conn:
        return [get(conn, i) for i in unique]


@dataclass(frozen=True)
class Outcome:
    id: str
    status: str
    result: dict[str, Any] | None = None
    problem: dict[str, Any] | None = None

    def public(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "status": self.status}
        if self.problem is not None:
            out["problem"] = self.problem
        else:
            out["result"] = self.result
        return out


def accept(
    hub: HubContext,
    principal: Principal,
    items: list[Proposal],
    signature: dict[str, Any] | None,
) -> list[Outcome]:
    """Un lot validé d'un seul geste ; chaque proposition s'applique ensuite seule, avec son
    propre statut. La signature a déjà été vérifiée contre `approval_digest(items)`."""
    out = []
    for p in items:
        try:
            out.append(accept_one(hub, principal, p, signature))
        except Problem as exc:
            with hub.core.engine.connect() as conn:
                now = get(conn, p.id)
            out.append(Outcome(p.id, now.status, problem=exc.body()))
    return out


def _claim(hub: HubContext, p: Proposal) -> bool:
    with hub.core.engine.begin() as conn:
        res = conn.execute(
            text(
                "UPDATE proposals SET status = 'applying', claimed_at = :at "
                "WHERE id = :id AND revision = :rev AND status = 'pending'"
            ),
            {"id": p.id, "rev": p.revision, "at": now_iso()},
        )
    return res.rowcount == 1


def release(hub: HubContext, proposal_id: str) -> None:
    """applying -> pending : seulement quand l'effet n'a pas eu lieu."""
    with hub.core.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE proposals SET status = 'pending', claimed_at = NULL "
                "WHERE id = :id AND status = 'applying'"
            ),
            {"id": proposal_id},
        )


def release_or_reconcile(hub: HubContext, p: Proposal) -> None:
    """Après une erreur ambiguë (au COMMIT par exemple) : `applied_proposals` décide."""
    done = hub.registry.get(p.domain).applied([p.id]).get(p.id)
    if done is not None:
        _mark(hub, p, "applied", done, None, "system:reconcile")
    else:
        release(hub, p.id)


def supersede(hub: HubContext, p: Proposal, fresh: Preview) -> Proposal:
    """Même id, révision + 1, nouvel aperçu : la carte se redessine et se revalide."""
    with hub.core.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE proposals SET revision = revision + 1, status = 'pending', "
                "claimed_at = NULL, preview_json = :pv, fingerprint = :fp "
                "WHERE id = :id AND status = 'applying'"
            ),
            {
                "id": p.id,
                "pv": canonical.dumps({"summary": fresh.summary, "details": fresh.details}),
                "fp": fresh.fingerprint,
            },
        )
        audit(conn, "system:hub", "proposal.superseded", p.urn, "conflict")
        return get(conn, p.id)


def _mark(
    hub: HubContext,
    p: Proposal,
    status: str,
    result: dict[str, Any] | None,
    signature: dict[str, Any] | None,
    actor: str,
) -> None:
    with hub.core.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE proposals SET status = :s, result_json = :res, "
                "signature_json = coalesce(:sig, signature_json), claimed_at = NULL, "
                "decided_at = coalesce(decided_at, :at) WHERE id = :id"
            ),
            {
                "id": p.id,
                "s": status,
                "res": canonical.dumps(result) if result is not None else None,
                "sig": canonical.dumps(signature) if signature is not None else None,
                "at": now_iso(),
            },
        )
        audit(conn, actor, "proposal.accept", p.urn, "ok" if status == "applied" else status)


def _applied_result(conn: Connection, proposal_id: str) -> dict[str, Any] | None:
    """Contrat de domaine : chaque base de domaine a `applied_proposals`."""
    row = conn.execute(
        text("SELECT result_json FROM applied_proposals WHERE proposal_id = :p"),
        {"p": proposal_id},
    ).first()
    return json.loads(row[0]) if row is not None else None


def _not_pending(hub: HubContext, p: Proposal) -> Problem:
    with hub.core.engine.connect() as conn:
        now = get(conn, p.id)
    if now.status == "pending" and now.revision != p.revision:
        return Problem("conflict.state_changed", proposal=now.public())
    return Problem("proposal.not_pending", status_now=now.status)


def accept_one(
    hub: HubContext,
    principal: Principal,
    p: Proposal,
    signature: dict[str, Any] | None,
) -> Outcome:
    """`p` est la proposition telle qu'elle a été validée (révision et empreinte comprises)."""
    if p.status == "applied":
        return Outcome(p.id, "applied", p.result)  # même réponse, aucun effet
    if p.status == "pending" and parse_iso(p.expires_at) <= utcnow():
        with hub.core.engine.begin() as conn:
            expire(conn)
        raise Problem("proposal.expired")
    if not _claim(hub, p):  # pending -> applying, et seulement pour cette révision
        with hub.core.engine.connect() as conn:
            now = get(conn, p.id)
        if now.status == "applied":
            return Outcome(p.id, "applied", now.result)
        raise _not_pending(hub, p)
    domain = hub.registry.get(p.domain)
    kind = domain.proposal_kinds[p.kind]
    params = kind.params_model.model_validate(p.params)
    if kind.external:
        return _external_apply(hub, principal, p, kind, params, signature)
    handler: LocalHandler = kind.handler  # type: ignore[assignment]
    conflict: Preview | None = None
    result: dict[str, Any] | None = None
    try:
        # verrou d'écriture pris AVANT la vérification de l'empreinte
        with begin_immediate(domain.engine()) as conn:
            result = _applied_result(conn, p.id)  # appliquée, mais COMMIT ambigu la dernière fois
            if result is None:
                fresh = handler.preview(conn, params)
                if fresh.fingerprint != p.fingerprint:
                    conflict = fresh
                else:
                    result = handler.apply(conn, params, p.id)
                    domain.record_applied(conn, p.id, p.kind, result)
    except DatabaseBusy:
        release(hub, p.id)  # rien n'a été écrit
        raise Problem(
            "busy.retry",
            retry_after=BUSY_RETRY_SECONDS,
            headers={"Retry-After": str(BUSY_RETRY_SECONDS)},
        ) from None
    except Problem:
        release(hub, p.id)  # refus du handler : transaction annulée
        raise
    except Exception:
        release_or_reconcile(hub, p)
        raise
    if conflict is not None:
        new = supersede(hub, p, conflict)
        raise Problem("conflict.state_changed", proposal=new.public())
    assert result is not None  # noqa: S101 - fixé dans la transaction
    _mark(hub, p, "applied", result, signature, principal.actor)
    _after_commit(domain, kind, params, result)
    return Outcome(p.id, "applied", result)


def _after_commit(
    domain: Domain, kind: ProposalKind, params: BaseModel, result: dict[str, Any]
) -> None:
    hook = getattr(kind.handler, "after_commit", None)
    if hook is None:
        return
    try:
        hook(params, result)
    except Exception as exc:  # l'effet est fait ; la tâche de nuit rattrapera
        log.warning("proposal.after_commit_failed", domain=domain.name, error=type(exc).__name__)


def _external_apply(
    hub: HubContext,
    principal: Principal,
    p: Proposal,
    kind: ProposalKind,
    params: BaseModel,
    signature: dict[str, Any] | None,
) -> Outcome:
    """Appel idempotent au tiers avec la clé `<id>:<révision>` ; aucune atomicité promise."""
    external: ExternalHandler = kind.handler  # type: ignore[assignment]
    try:
        res = external.apply(params, f"{p.id}:{p.revision}")
    except Exception:
        _mark(hub, p, "unknown", None, signature, principal.actor)
        raise
    status = {"ok": "applied", "failed": "failed", "unknown": "unknown"}[res.status]
    _mark(hub, p, status, res.detail, signature, principal.actor)
    return Outcome(p.id, status, res.detail)


# --- inverses et résumé du jour --------------------------------------------------------------


def inverse_of(hub: HubContext, p: Proposal) -> tuple[str, dict[str, Any]]:
    kind = hub.registry.get(p.domain).proposal_kinds.get(p.kind)
    if p.status != "applied" or kind is None or not kind.reversible or kind.inverse is None:
        raise Problem("proposal.not_reversible")
    if reverted_by(hub, p) is not None:
        raise Problem("proposal.not_reversible", "déjà annulée")
    try:
        return kind.inverse(p.params, p.result or {})
    except ValueError as exc:
        raise Problem("proposal.not_reversible", str(exc)) from None


def reverted_by(hub: HubContext, p: Proposal) -> str | None:
    with hub.core.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT from_urn FROM links WHERE to_urn = :u AND rel = 'reverts' AND active = 1 "
                "ORDER BY seq DESC LIMIT 1"
            ),
            {"u": p.urn},
        ).first()
    return str(row[0]) if row else None


def revert(
    hub: HubContext, principal: Principal, p: Proposal, signature: dict[str, Any] | None
) -> Outcome:
    """Crée et applique l'inverse d'une proposition réversible, d'un seul geste."""
    inv_kind, inv_params = inverse_of(hub, p)
    inv, _ = create(
        hub, SYSTEM, p.domain, inv_kind, inv_params, reason=f"annule {p.id}", bundle_id=p.bundle_id
    )
    outcome = accept_one(hub, principal, inv, signature)
    if outcome.status == "applied":
        with hub.core.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO links (from_urn, to_urn, rel, proposal_id, created_by, "
                    "created_at) VALUES (:f, :t, 'reverts', :p, :by, :at)"
                ),
                {"f": inv.urn, "t": p.urn, "p": inv.id, "by": principal.actor, "at": now_iso()},
            )
            audit(conn, principal.actor, "proposal.revert", p.urn, "ok")
    return outcome


def digest(hub: HubContext, day: str) -> list[dict[str, Any]]:
    """Effets appliqués au palier `auto_digest` ce jour (UTC), avec leur inverse éventuel."""
    with hub.core.engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT * FROM proposals WHERE tier = 'auto_digest' AND status = 'applied' "
                "AND substr(decided_at, 1, 10) = :d ORDER BY decided_at"
            ),
            {"d": day},
        ).fetchall()
    out = []
    for r in rows:
        p = _from_row(r)
        kind = hub.registry.get(p.domain).proposal_kinds.get(p.kind)
        out.append(
            {
                **p.public(),
                "reversible": bool(kind and kind.reversible),
                "reverted_by": reverted_by(hub, p),
            }
        )
    return out


# --- événements des domaines ----------------------------------------------------------------

EVENTS_CONSUMER = "proposals"


def sync_events(hub: HubContext, limit: int = 500) -> dict[str, int]:
    """Lit la boîte de sortie de chaque domaine : `proposal.request` crée une carte (création
    idempotente), `proposal.obsolete` rend sans objet celle qui attend encore,
    `notify.request` envoie une notification (texte générique, posé par une sentinelle)."""
    counts = {"requested": 0, "obsoleted": 0, "notified": 0}
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
    return int(hub.notifier.send(Message(title, body, tags=str(payload.get("tags") or ""))))


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
    d = hub.registry.get(domain)
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
    marked += _reconcile_external(hub)
    return ReconcileReport(marked, released)


def _reconcile_external(hub: HubContext) -> int:
    """Effet externe au résultat inconnu : on redemande au tiers où il en est."""
    with hub.core.engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM proposals WHERE status = 'unknown'")).fetchall()
    done = 0
    for r in rows:
        p = _from_row(r)
        kind = hub.registry.get(p.domain).proposal_kinds.get(p.kind)
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
            _mark(hub, p, status, res.detail, None, "system:reconcile")
            done += 1
    return done
