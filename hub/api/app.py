"""Application FastAPI : un seul worker, aucun état partagé en mémoire."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

import hub
from hub.api import routes_auth, routes_core
from hub.core import errors
from hub.core.context import HubContext


def create_app(hub_ctx: HubContext, *, migrate: bool = False) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if migrate:
            hub_ctx.migrate_all()
        yield
        hub_ctx.dispose()

    app = FastAPI(
        title="Personal Hub",
        version=hub.__version__,
        openapi_url="/api/openapi.json",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.hub = hub_ctx
    errors.install(app)

    @app.middleware("http")
    async def no_store(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.include_router(routes_core.router, prefix="/api")
    app.include_router(routes_auth.router, prefix="/api")
    for domain in hub_ctx.registry:
        app.include_router(
            domain.router(),
            prefix=f"/api/{domain.name}",
            tags=[domain.name],
            dependencies=routes_core.domain_router_dependencies(domain.name),
        )

    web_root = hub_ctx.settings.server.web_root
    if web_root is not None:
        # développement seulement : en production, Caddy sert l'app et pose la CSP
        app.mount("/", StaticFiles(directory=web_root, html=True), name="web")
    return app
