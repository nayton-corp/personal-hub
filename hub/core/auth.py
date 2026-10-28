"""Qui parle et ce qu'il peut faire : jeton Bearer à portées, ou session passkey (portée app)."""

from __future__ import annotations

import fnmatch
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from hub.core import sessions, tokens
from hub.core.context import HubContext
from hub.core.db import begin_immediate
from hub.core.errors import Problem

SESSION_COOKIE = "hub_session"


@dataclass(frozen=True)
class Principal:
    actor: str  # URN d'acteur : token:<id> ou passkey:<credential_id>
    scopes: frozenset[str]
    is_app: bool = False  # session passkey : portée app

    def allows(self, scope: str) -> bool:
        if self.is_app:
            return True
        return any(fnmatch.fnmatchcase(scope, granted) for granted in self.scopes)

    def allows_any(self, *scopes: str) -> bool:
        return any(self.allows(s) for s in scopes)


def ctx(request: Request) -> HubContext:
    value: HubContext = request.app.state.hub
    return value


Ctx = Annotated[HubContext, Depends(ctx)]


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise Problem("auth.invalid")
    return value.strip()


def current_principal(request: Request, hub: Ctx) -> Principal:
    secret = _bearer(request)
    if secret is not None:
        # verify lit puis écrit last_used_at : en BEGIN simple, deux requêtes à la même
        # milliseconde (les collecteurs, chaque minute pile) font échouer la seconde aussitôt
        # (« database is locked », sans attendre busy_timeout) ; IMMEDIATE les met en file
        with begin_immediate(hub.core.engine) as conn:
            info = tokens.verify(conn, secret)
        if info is None:
            raise Problem("auth.invalid")
        return Principal(actor=info.actor, scopes=frozenset(info.scopes))
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        with hub.core.engine.connect() as conn:
            session = sessions.get_valid(conn, cookie)
        if session is None:
            raise Problem("auth.invalid", "session expirée")
        return Principal(actor=session.actor, scopes=frozenset({"app"}), is_app=True)
    raise Problem("auth.missing")


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require(*scopes: str) -> Callable[[Principal], Principal]:
    """Dépendance FastAPI : l'une des portées suffit. `app` désigne la session passkey."""
    wanted = tuple(s for s in scopes if s != "app")

    def dependency(principal: CurrentPrincipal) -> Principal:
        if principal.is_app or (wanted and principal.allows_any(*wanted)):
            return principal
        raise Problem("auth.scope")

    return dependency


def require_app_session(principal: CurrentPrincipal) -> Principal:
    if not principal.is_app:
        raise Problem("auth.scope", "réservé à l'app après passkey")
    return principal


AppSession = Annotated[Principal, Depends(require_app_session)]
