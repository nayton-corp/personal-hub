"""Routes des collecteurs (lot 5) : état et modes pour l'app, déclaration des runs pour les
conteneurs collecteurs (jeton à portée `core:collector`), liaison d'un consentement Revolut."""

from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse

from hub.api.schemas import (
    CollectorLinkIn,
    CollectorLinkOut,
    CollectorListOut,
    CollectorModeIn,
    CollectorNotifyIn,
    CollectorNotifyOut,
    CollectorOut,
    CollectorRunIn,
    CollectorRunsOut,
    ConnectorListOut,
    ConnectorOut,
)
from hub.core import collectors, connectors
from hub.core.auth import AppSession, Ctx, CurrentPrincipal, Principal
from hub.core.errors import Problem
from hub.core.logging import get_logger
from hub.core.notify import Message

router = APIRouter(prefix="/collectors", tags=["collecteurs"])
log = get_logger("hub.api.collectors")
COLLECTOR_SCOPE = "core:collector"


def _collector(principal: CurrentPrincipal) -> Principal:
    if principal.is_app or not principal.allows(COLLECTOR_SCOPE):
        raise Problem("auth.scope", "réservé aux conteneurs collecteurs")
    return principal


def _app_or_collector(principal: CurrentPrincipal) -> Principal:
    if principal.is_app or principal.allows(COLLECTOR_SCOPE):
        return principal
    raise Problem("auth.scope")


Collector = Annotated[Principal, Depends(_collector)]
Viewer = Annotated[Principal, Depends(_app_or_collector)]


def _out(state: collectors.State) -> CollectorOut:
    return CollectorOut.model_validate(state.public())


@router.get("", response_model=CollectorListOut)
def list_collectors(hub_ctx: Ctx, _principal: Viewer) -> CollectorListOut:
    with hub_ctx.core.engine.begin() as conn:
        return CollectorListOut(items=[_out(s) for s in collectors.list_all(conn)])


@router.get("/catalog", response_model=ConnectorListOut)
def catalog(_principal: AppSession) -> ConnectorListOut:
    """Les connecteurs que ce hub sait collecter (méthode, pays, secrets attendus)."""
    return ConnectorListOut(
        items=[ConnectorOut.model_validate(c.public()) for c in connectors.CATALOG]
    )


@router.get("/{name}", response_model=CollectorOut)
def get_collector(name: str, hub_ctx: Ctx, _principal: Viewer) -> CollectorOut:
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.get(conn, name))


@router.get("/{name}/runs", response_model=CollectorRunsOut)
def list_runs(
    name: str,
    hub_ctx: Ctx,
    _principal: Viewer,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> CollectorRunsOut:
    collectors.label(name)
    with hub_ctx.core.engine.connect() as conn:
        return CollectorRunsOut.model_validate({"items": collectors.runs(conn, name, limit)})


@router.post("/{name}/runs", response_model=CollectorOut, status_code=201)
def record_run(name: str, body: CollectorRunIn, hub_ctx: Ctx, principal: Collector) -> CollectorOut:
    """Déclare un run ; applique la table des échecs et envoie les alertes ntfy."""
    run = collectors.Run(
        body.kind, body.outcome, body.started_at, body.ended_at, body.files, body.detail
    )
    with hub_ctx.core.engine.begin() as conn:
        recorded = collectors.record(conn, name, run, principal.actor)
    for alert in recorded.alerts:
        hub_ctx.notifier.send(alert)
    return _out(recorded.state)


@router.post("/{name}/notify", response_model=CollectorNotifyOut)
def notify(
    name: str, body: CollectorNotifyIn, hub_ctx: Ctx, _principal: Collector
) -> CollectorNotifyOut:
    """Le bot attend une validation sur le téléphone, ou un consentement arrive à échéance."""
    if body.event == "auth_pending":
        msg = collectors.auth_pending(name)
    else:
        msg = Message(
            f"Collecte {collectors.label(name)} : consentement à renouveler",
            "Le consentement expire bientôt : relance la liaison depuis le terminal.",
            "high",
        )
    return CollectorNotifyOut(sent=hub_ctx.notifier.send(msg))


@router.post("/{name}/mode", response_model=CollectorOut)
def set_mode(name: str, body: CollectorModeIn, hub_ctx: Ctx, principal: AppSession) -> CollectorOut:
    """Couper un collecteur, ou le remettre en marche après un contrôle réussi."""
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.set_mode(conn, name, body.mode, principal.actor))


@router.post("/{name}/check", response_model=CollectorOut)
def request_check(name: str, hub_ctx: Ctx, principal: AppSession) -> CollectorOut:
    """Demande un run de contrôle (connexion et sélecteurs, sans téléchargement)."""
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.request_check(conn, name, principal.actor))


@router.post("/{name}/links", response_model=CollectorLinkOut, status_code=201)
def register_link(
    name: str, body: CollectorLinkIn, hub_ctx: Ctx, _principal: Collector
) -> CollectorLinkOut:
    with hub_ctx.core.engine.begin() as conn:
        expires = collectors.register_link(conn, name, body.state)
    return CollectorLinkOut(state=body.state, expires_at=expires)


@router.get("/{name}/links/{state}", response_model=CollectorLinkOut)
def take_link(name: str, state: str, hub_ctx: Ctx, _principal: Collector) -> CollectorLinkOut:
    """Le code de retour, rendu une seule fois ; `code` nul tant qu'il n'est pas arrivé."""
    with hub_ctx.core.engine.begin() as conn:
        code = collectors.take_code(conn, name, state)
    return CollectorLinkOut(state=state, code=code)


@router.get("/{name}/callback", response_class=HTMLResponse, include_in_schema=False)
def callback(
    name: str,
    hub_ctx: Ctx,
    state: Annotated[str, Query(max_length=100)] = "",
    code: Annotated[str, Query(max_length=2000)] = "",
    error: Annotated[str, Query(max_length=200)] = "",
    error_description: Annotated[str, Query(max_length=500)] = "",
) -> HTMLResponse:
    """Retour du navigateur après le consentement chez la banque. Sans authentification : le
    `state` est aléatoire et n'est accepté que quelques minutes, et le code ne sert à rien sans
    la clé privée du collecteur."""
    label = collectors.label(name)
    accepted = False
    if code and not error:
        with hub_ctx.core.engine.begin() as conn:
            accepted = collectors.receive_code(conn, name, state, code)
    if accepted:
        text = f"Liaison {label} reçue. La reprise de l'historique démarre : tu peux fermer."
    elif error:
        # le détail de la banque sert au diagnostic ; il ne contient ni code ni montant
        log.warning("collector.link_refused", collector=name, error=error, detail=error_description)
        detail = f" : {error_description}" if error_description else ""
        text = f"Liaison {label} refusée ({error}){detail}."
    else:
        text = f"Liaison {label} inconnue ou expirée : relance-la depuis le terminal."
    page = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>Personal Hub</title><p>{escape(text)}</p>"
    )
    return HTMLResponse(page, status_code=200 if accepted else 400)
