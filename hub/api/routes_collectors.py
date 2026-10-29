"""Routes des collecteurs (lot 5) : état et modes pour l'app, déclaration des runs pour les
conteneurs collecteurs (jeton à portée `core:collector`), liaison d'un consentement Enable
Banking. G4 : les connexions (réglées par l'app, exécutées par les services collecteurs)."""

from __future__ import annotations

from html import escape
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import HTMLResponse

from hub.api.schemas import (
    CollectorLinkIn,
    CollectorLinkOut,
    CollectorLinkUrlIn,
    CollectorListOut,
    CollectorModeIn,
    CollectorNotifyIn,
    CollectorNotifyOut,
    CollectorOut,
    CollectorRunIn,
    CollectorRunsOut,
    ConnectionIn,
    ConnectionListOut,
    ConnectionOut,
    ConnectionPatch,
    ConnectionSecretsIn,
    ConnectorListOut,
    ConnectorOut,
    RunnerListOut,
)
from hub.core import collectors, connections, connectors
from hub.core.auth import AppSession, Ctx, CurrentPrincipal, Principal
from hub.core.errors import Problem
from hub.core.notify import Message
from hub.platform import secrets
from hub.platform.logging import get_logger

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


@router.post("/refresh", response_model=CollectorListOut)
def refresh_all(hub_ctx: Ctx, principal: AppSession) -> CollectorListOut:
    """« Tout actualiser » : un run de chaque connexion prête et active, dans la minute."""
    with hub_ctx.core.engine.begin() as conn:
        states = collectors.request_run_all(conn, principal.actor)
    return CollectorListOut(items=[_out(s) for s in states])


@router.get("/catalog", response_model=ConnectorListOut)
def catalog(_principal: AppSession) -> ConnectorListOut:
    """Les connecteurs que ce hub sait collecter (méthode, pays, secrets attendus)."""
    return ConnectorListOut(
        items=[ConnectorOut.model_validate(c.public()) for c in connectors.catalog()]
    )


def _connection(c: connections.Connection) -> ConnectionOut:
    return ConnectionOut.model_validate(c.public())


@router.get("/connections", response_model=ConnectionListOut)
def list_connections(hub_ctx: Ctx, _principal: AppSession) -> ConnectionListOut:
    """Les connexions de l'instance, sans leurs secrets (seulement s'ils sont donnés)."""
    with hub_ctx.core.engine.connect() as conn:
        return ConnectionListOut(items=[_connection(c) for c in connections.list_all(conn)])


@router.post("/connections", response_model=ConnectionOut, status_code=201)
def create_connection(body: ConnectionIn, hub_ctx: Ctx, principal: AppSession) -> ConnectionOut:
    with hub_ctx.core.engine.begin() as conn:
        created = connections.create(
            conn,
            body.id,
            body.connector,
            principal.actor,
            label=body.label,
            schedule=body.schedule,
            settings=body.settings,
        )
    return _connection(created)


@router.patch("/connections/{cid}", response_model=ConnectionOut)
def update_connection(
    cid: str, body: ConnectionPatch, hub_ctx: Ctx, principal: AppSession
) -> ConnectionOut:
    with hub_ctx.core.engine.begin() as conn:
        updated = connections.update(
            conn,
            cid,
            principal.actor,
            label=body.label,
            schedule=body.schedule,
            default_schedule=body.default_schedule,
            settings=body.settings,
        )
    return _connection(updated)


@router.put("/connections/{cid}/secrets", response_model=ConnectionOut)
def set_connection_secrets(
    cid: str, body: ConnectionSecretsIn, hub_ctx: Ctx, principal: AppSession
) -> ConnectionOut:
    """Remplace les secrets : chiffrés vers la clé de la machine, jamais relus par l'API."""
    try:
        recipient = secrets.recipient(hub_ctx.settings.secrets.age_key_file)
    except (OSError, secrets.SecretsError):
        raise Problem("internal", "clé age de la machine illisible") from None
    with hub_ctx.core.engine.begin() as conn:
        updated = connections.set_secrets(conn, cid, body.values, recipient, principal.actor)
    return _connection(updated)


@router.delete("/connections/{cid}", status_code=204)
def delete_connection(cid: str, hub_ctx: Ctx, principal: AppSession) -> Response:
    with hub_ctx.core.engine.begin() as conn:
        connections.delete(conn, cid, principal.actor)
    return Response(status_code=204)


@router.get("/runner/{runner}", response_model=RunnerListOut)
def runner_connections(runner: str, hub_ctx: Ctx, _principal: Collector) -> RunnerListOut:
    """Ce qu'un service collecteur exécute : connexions prêtes, secrets toujours chiffrés."""
    if runner not in connectors.RUNNERS:
        raise Problem("validation.params", "service : api ou browser")
    with hub_ctx.core.engine.connect() as conn:
        found = connections.for_runner(conn, runner)
    return RunnerListOut.model_validate({"items": [c.for_runner() for c in found]})


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
    with hub_ctx.core.engine.connect() as conn:
        collectors.label(conn, name)
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
    with hub_ctx.core.engine.connect() as conn:
        name_label = collectors.label(conn, name)
    if body.event == "auth_pending":
        msg = collectors.auth_pending(name_label)
    else:
        msg = Message(
            f"Collecte {name_label} : consentement à renouveler",
            "Le consentement expire bientôt : relance la liaison depuis l'app (Sources).",
            "high",
            click=collectors.SOURCES_CLICK,
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


@router.post("/{name}/refresh", response_model=CollectorOut)
def request_refresh(name: str, hub_ctx: Ctx, principal: AppSession) -> CollectorOut:
    """Actualiser maintenant : un run complet hors horaire, pris dans la minute par le service
    collecteur ; les limites de la source (synchros par jour) restent celles du flux."""
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.request_run(conn, name, principal.actor))


@router.post("/{name}/link", response_model=CollectorOut)
def request_link(name: str, hub_ctx: Ctx, principal: AppSession) -> CollectorOut:
    """Nouveau consentement Enable Banking : le service collecteur ouvre l'autorisation dans la
    minute ; l'adresse à ouvrir apparaît ensuite dans `link_url`."""
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.request_link(conn, name, principal.actor))


@router.put("/{name}/link-url", response_model=CollectorOut)
def set_link_url(
    name: str, body: CollectorLinkUrlIn, hub_ctx: Ctx, _principal: Collector
) -> CollectorOut:
    with hub_ctx.core.engine.begin() as conn:
        return _out(collectors.set_link_url(conn, name, body.url))


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
    with hub_ctx.core.engine.connect() as conn:
        label = collectors.label(conn, name)
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
        text = f"Liaison {label} inconnue ou expirée : relance-la depuis l'app."
    page = (
        "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
        f"<title>Personal Hub</title><p>{escape(text)}</p>"
    )
    return HTMLResponse(page, status_code=200 if accepted else 400)
