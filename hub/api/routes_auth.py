"""Passkeys : inscription par code d'amorçage ou depuis une session, connexion, déconnexion."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from hub.api.schemas import (
    ChallengeOut,
    LoginFinishIn,
    PasskeyOut,
    PasskeysOut,
    RegisterBeginIn,
    RegisterFinishIn,
    SessionOut,
)
from hub.core import passkeys, ratelimit, sessions
from hub.core.auth import SESSION_COOKIE, AppSession, Ctx
from hub.core.context import HubContext
from hub.core.errors import Problem

router = APIRouter(prefix="/auth", tags=["authentification"])


def _session_from_cookie(hub_ctx: HubContext, request: Request) -> sessions.Session | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    with hub_ctx.core.engine.connect() as conn:
        return sessions.get_valid(conn, cookie)


def _set_cookie(hub_ctx: HubContext, response: Response, cookie: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        cookie,
        max_age=hub_ctx.settings.auth.session_hours * 3600,
        httponly=True,
        secure=hub_ctx.settings.server.secure,
        samesite="strict",
        path="/api",
    )


def _client_key(request: Request, what: str) -> str:
    host = request.client.host if request.client else "unknown"
    return f"{what}:{host}"


@router.get("/session", response_model=SessionOut)
def session(hub_ctx: Ctx, request: Request) -> SessionOut:
    current = _session_from_cookie(hub_ctx, request)
    with hub_ctx.core.engine.connect() as conn:
        n = passkeys.count(conn)
    return SessionOut(
        authenticated=current is not None,
        actor=current.actor if current else None,
        expires_at=current.expires_at if current else None,
        passkeys=n,
        needs_bootstrap=n == 0,
    )


@router.post("/passkey/register/begin", response_model=ChallengeOut)
def register_begin(body: RegisterBeginIn, hub_ctx: Ctx, request: Request) -> ChallengeOut:
    ratelimit.enforce(
        hub_ctx.core.engine,
        _client_key(request, "register"),
        hub_ctx.settings.auth.login_attempts_per_minute,
    )
    current = _session_from_cookie(hub_ctx, request)
    with hub_ctx.core.engine.begin() as conn:
        if current is None and not (
            body.bootstrap_code and sessions.check_bootstrap_code(conn, body.bootstrap_code)
        ):
            raise Problem("auth.bootstrap_invalid")
        return ChallengeOut(**passkeys.registration_options(conn, hub_ctx.settings))


@router.post("/passkey/register/finish", response_model=SessionOut)
def register_finish(
    body: RegisterFinishIn, hub_ctx: Ctx, request: Request, response: Response
) -> SessionOut:
    current = _session_from_cookie(hub_ctx, request)
    with hub_ctx.core.engine.begin() as conn:
        if current is not None:
            by = current.actor
        elif body.bootstrap_code and sessions.consume_bootstrap_code(conn, body.bootstrap_code):
            by = "system:bootstrap"
        else:
            raise Problem("auth.bootstrap_invalid")
        credential_id = passkeys.register(
            conn, hub_ctx.settings, body.challenge_id, body.credential, body.device_name, by
        )
        if current is None:
            new, cookie = sessions.create(conn, credential_id, hub_ctx.settings.auth.session_hours)
            _set_cookie(hub_ctx, response, cookie)
            current = new
        n = passkeys.count(conn)
    return SessionOut(
        authenticated=True,
        actor=current.actor,
        expires_at=current.expires_at,
        passkeys=n,
        needs_bootstrap=False,
    )


@router.post("/passkey/login/begin", response_model=ChallengeOut)
def login_begin(hub_ctx: Ctx, request: Request) -> ChallengeOut:
    ratelimit.enforce(
        hub_ctx.core.engine,
        _client_key(request, "login"),
        hub_ctx.settings.auth.login_attempts_per_minute,
    )
    with hub_ctx.core.engine.begin() as conn:
        return ChallengeOut(**passkeys.login_options(conn, hub_ctx.settings))


@router.post("/passkey/login/finish", response_model=SessionOut)
def login_finish(body: LoginFinishIn, hub_ctx: Ctx, response: Response) -> SessionOut:
    with hub_ctx.core.engine.begin() as conn:
        credential_id = passkeys.authenticate(
            conn, hub_ctx.settings, body.challenge_id, body.credential
        )
        new, cookie = sessions.create(conn, credential_id, hub_ctx.settings.auth.session_hours)
        n = passkeys.count(conn)
    _set_cookie(hub_ctx, response, cookie)
    return SessionOut(
        authenticated=True,
        actor=new.actor,
        expires_at=new.expires_at,
        passkeys=n,
        needs_bootstrap=False,
    )


@router.post("/logout", status_code=204)
def logout(hub_ctx: Ctx, request: Request, response: Response) -> None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        with hub_ctx.core.engine.begin() as conn:
            sessions.revoke(conn, cookie)
    response.delete_cookie(SESSION_COOKIE, path="/api")


@router.get("/passkeys", response_model=PasskeysOut)
def list_passkeys(hub_ctx: Ctx, _principal: AppSession) -> PasskeysOut:
    with hub_ctx.core.engine.connect() as conn:
        return PasskeysOut(items=[PasskeyOut(**p) for p in passkeys.list_all(conn)])
