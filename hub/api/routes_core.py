"""Routes du cœur : santé, propositions, recherche, résolution d'URN et liens."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import text

import hub
from hub.api.schemas import (
    AcceptIn,
    AcceptOut,
    ApprovalChallengeIn,
    ApprovalChallengeOut,
    CoreHealthOut,
    DigestOut,
    DomainHealthOut,
    HealthOut,
    HitOut,
    LinkOut,
    LinksOut,
    ProfileIn,
    ProfileOut,
    ProposalCreateIn,
    ProposalListOut,
    ProposalOut,
    RefOut,
    RevertIn,
    SearchOut,
)
from hub.core import passkeys, profile, proposals
from hub.core.auth import AppSession, Ctx, CurrentPrincipal, Principal, require
from hub.core.clock import utcnow
from hub.core.errors import Problem
from hub.core.ids import Urn

router = APIRouter()


@router.get("/health", response_model=HealthOut, tags=["cœur"])
def health(hub_ctx: Ctx) -> HealthOut:
    try:
        revision = hub_ctx.core.revision()
        core_ok = hub_ctx.core.is_current()
        core = CoreHealthOut(db="ok" if core_ok else "outdated", revision=revision, ok=core_ok)
    except Exception:
        core = CoreHealthOut(db="error", revision=None, ok=False)
    domains: dict[str, DomainHealthOut] = {}
    for d in hub_ctx.registry:
        try:
            h = d.health()
            domains[d.name] = DomainHealthOut(db=h.db, schema_version=h.schema_version, ok=h.ok)
        except Exception:
            domains[d.name] = DomainHealthOut(db="error", schema_version=d.schema_version, ok=False)
    ok = core.ok and all(d.ok for d in domains.values())
    return HealthOut(
        status="ok" if ok else "degraded", version=hub.__version__, core=core, domains=domains
    )


def _reader(principal: CurrentPrincipal, hub_ctx: Ctx) -> Principal:
    """app, ou portée lecture/proposition d'au moins un domaine (le « brain »)."""
    if principal.is_app:
        return principal
    for d in hub_ctx.registry:
        if principal.allows_any(f"{d.name}:read", f"{d.name}:propose"):
            return principal
    raise Problem("auth.scope")


Reader = Annotated[Principal, Depends(_reader)]


def _searcher(principal: CurrentPrincipal, hub_ctx: Ctx) -> Principal:
    if principal.is_app or any(principal.allows(f"{d.name}:read") for d in hub_ctx.registry):
        return principal
    raise Problem("auth.scope")


Searcher = Annotated[Principal, Depends(_searcher)]


@router.get("/profile", response_model=ProfileOut, tags=["cœur"])
def get_profile(hub_ctx: Ctx, _principal: Reader) -> ProfileOut:
    with hub_ctx.core.engine.connect() as conn:
        return ProfileOut.model_validate(profile.get(conn).public())


@router.post("/profile", response_model=ProfileOut, tags=["cœur"])
def update_profile(body: ProfileIn, hub_ctx: Ctx, principal: AppSession) -> ProfileOut:
    fields = body.model_fields_set
    try:
        with hub_ctx.core.engine.begin() as conn:
            p = profile.update(
                conn,
                principal.actor,
                display_name=body.display_name if "display_name" in fields else None,
                country=body.country,
                clear_name="display_name" in fields and not (body.display_name or "").strip(),
            )
    except profile.ProfileError as exc:
        raise Problem("validation.params", str(exc)) from None
    return ProfileOut.model_validate(p.public())


@router.get("/proposals", response_model=ProposalListOut, tags=["propositions"])
def list_proposals(
    hub_ctx: Ctx,
    principal: Reader,
    status: Annotated[str | None, Query(pattern="^[a-z_]+$")] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ProposalListOut:
    proposals.sync_events(hub_ctx)  # cartes demandées par les domaines (imports en attente…)
    with hub_ctx.core.engine.connect() as conn:
        items = proposals.list_by_status(conn, status, limit)
    visible = [
        p
        for p in items
        if principal.is_app or principal.allows_any(f"{p.domain}:read", f"{p.domain}:propose")
    ]
    return ProposalListOut(items=[ProposalOut.model_validate(p.public()) for p in visible])


@router.post(
    "/proposals",
    response_model=ProposalOut,
    status_code=201,
    tags=["propositions"],
    responses={200: {"description": "proposition existante (même clé ou identique en attente)"}},
)
def create_proposal(
    body: ProposalCreateIn,
    hub_ctx: Ctx,
    principal: CurrentPrincipal,
    response: Response,
    idempotency_key: Annotated[str | None, Header(max_length=100)] = None,
) -> ProposalOut:
    p, created = proposals.create(
        hub_ctx,
        principal,
        body.domain,
        body.kind,
        body.params,
        reason=body.reason,
        bundle_id=body.bundle_id,
        create_key=idempotency_key,
        external_text=body.external_text,
    )
    if not created:
        response.status_code = 200
    return ProposalOut.model_validate(p.public())


@router.get("/proposals/{proposal_id}", response_model=ProposalOut, tags=["propositions"])
def get_proposal(proposal_id: str, hub_ctx: Ctx, principal: Reader) -> ProposalOut:
    with hub_ctx.core.engine.connect() as conn:
        p = proposals.get(conn, proposal_id)
    if not (principal.is_app or principal.allows_any(f"{p.domain}:read", f"{p.domain}:propose")):
        raise Problem("proposal.not_found")
    return ProposalOut.model_validate(p.public())


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut, tags=["propositions"])
def reject_proposal(proposal_id: str, hub_ctx: Ctx, principal: AppSession) -> ProposalOut:
    return ProposalOut.model_validate(proposals.reject(hub_ctx, principal, proposal_id).public())


@router.post("/approvals/challenge", response_model=ApprovalChallengeOut, tags=["propositions"])
def approval_challenge(
    body: ApprovalChallengeIn, hub_ctx: Ctx, _principal: AppSession
) -> ApprovalChallengeOut:
    """Défi WebAuthn qui contient `approval_digest` : un seul Face ID pour tout le lot."""
    items = proposals.load_many(hub_ctx, body.proposal_ids)
    digest = proposals.approval_digest(items, body.action)
    with hub_ctx.core.engine.begin() as conn:
        out = passkeys.approval_options(conn, hub_ctx.settings, digest)
    return ApprovalChallengeOut(**out, approval_digest=digest)


@router.post("/proposals/accept", response_model=AcceptOut, tags=["propositions"])
def accept_proposals(body: AcceptIn, hub_ctx: Ctx, principal: AppSession) -> AcceptOut:
    """Valide un lot signé ; chaque proposition s'applique seule, avec son propre statut. Une
    signature qui porte sur une autre révision ou une autre empreinte est refusée."""
    items = proposals.load_many(hub_ctx, body.proposal_ids)
    with hub_ctx.core.engine.begin() as conn:
        signature = passkeys.verify_approval(
            conn,
            hub_ctx.settings,
            body.challenge_id,
            body.assertion,
            proposals.approval_digest(items),
        )
    results = proposals.accept(hub_ctx, principal, items, signature)
    return AcceptOut.model_validate({"results": [r.public() for r in results]})


@router.post("/proposals/{proposal_id}/revert", response_model=AcceptOut, tags=["propositions"])
def revert_proposal(
    proposal_id: str, body: RevertIn, hub_ctx: Ctx, principal: AppSession
) -> AcceptOut:
    """Crée et applique l'inverse d'une proposition réversible (un Face ID)."""
    (p,) = proposals.load_many(hub_ctx, [proposal_id])
    proposals.inverse_of(hub_ctx, p)  # refuse avant de consommer le défi
    with hub_ctx.core.engine.begin() as conn:
        signature = passkeys.verify_approval(
            conn,
            hub_ctx.settings,
            body.challenge_id,
            body.assertion,
            proposals.approval_digest([p], "revert"),
        )
    outcome = proposals.revert(hub_ctx, principal, p, signature)
    return AcceptOut.model_validate({"results": [outcome.public()]})


@router.get("/digest", response_model=DigestOut, tags=["propositions"])
def day_digest(
    hub_ctx: Ctx,
    _principal: AppSession,
    day: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> DigestOut:
    """Effets appliqués au palier auto_digest, avec leur inverse d'un geste."""
    value = day or utcnow().date().isoformat()
    return DigestOut.model_validate({"day": value, "items": proposals.digest(hub_ctx, value)})


@router.get("/search", response_model=SearchOut, tags=["cœur"])
def search(
    hub_ctx: Ctx,
    principal: Searcher,
    q: Annotated[str, Query(min_length=3, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SearchOut:
    scored: list[tuple[int, HitOut]] = []
    for d in hub_ctx.registry:
        if not (principal.is_app or principal.allows(f"{d.name}:read")):
            continue
        granted = frozenset({"app"}) if principal.is_app else principal.scopes
        for h in d.search(q, limit, granted):
            scored.append((h.score, HitOut(domain=d.name, urn=h.urn, title=h.title, date=h.date)))
    scored.sort(key=lambda item: (item[0], item[1].date or ""), reverse=True)
    return SearchOut(items=[h for _, h in scored[:limit]])


def _resolve(hub_ctx: Ctx, principal: Principal, value: str) -> RefOut | None:
    try:
        parsed = Urn.parse(value)
    except ValueError:
        raise Problem("validation.params", "URN invalide") from None
    if parsed.domain not in hub_ctx.registry.names():
        return None
    if not (principal.is_app or principal.allows(f"{parsed.domain}:read")):
        raise Problem("auth.scope")
    ref = hub_ctx.registry.get(parsed.domain).resolve(value)
    return RefOut(urn=ref.urn, title=ref.title, date=ref.date, href=ref.href) if ref else None


@router.get("/resolve", response_model=RefOut, tags=["cœur"])
def resolve(
    hub_ctx: Ctx, principal: CurrentPrincipal, urn: Annotated[str, Query(max_length=200)]
) -> RefOut:
    ref = _resolve(hub_ctx, principal, urn)
    if ref is None:
        raise Problem("not_found")
    return ref


@router.get("/links", response_model=LinksOut, tags=["cœur"])
def links(
    hub_ctx: Ctx, principal: CurrentPrincipal, urn: Annotated[str, Query(max_length=200)]
) -> LinksOut:
    _resolve(hub_ctx, principal, urn)  # valide l'URN et la portée
    sql = text(
        "SELECT l.from_urn, l.to_urn, l.rel FROM links l "
        "WHERE (l.from_urn = :u OR l.to_urn = :u) AND l.seq = ("
        "  SELECT max(seq) FROM links m WHERE m.from_urn = l.from_urn AND m.to_urn = l.to_urn "
        "  AND m.rel = l.rel) AND l.active = 1 ORDER BY l.seq"
    )
    with hub_ctx.core.engine.connect() as conn:
        rows = conn.execute(sql, {"u": urn}).fetchall()
    out: dict[str, list[LinkOut]] = {"outgoing": [], "incoming": []}
    for r in rows:
        other_urn = r.to_urn if r.from_urn == urn else r.from_urn
        try:
            other = _resolve(hub_ctx, principal, other_urn)
        except Problem:
            continue  # lien vers un domaine que ce jeton ne lit pas : invisible
        side = "outgoing" if r.from_urn == urn else "incoming"
        out[side].append(LinkOut(from_urn=r.from_urn, to_urn=r.to_urn, rel=r.rel, other=other))
    return LinksOut(**out)


def domain_router_dependencies(name: str) -> list[Any]:
    """Toute route d'un domaine exige au moins une portée de ce domaine (ou l'app)."""
    return [Depends(require("app", f"{name}:read", f"{name}:propose", f"{name}:aggregates"))]
