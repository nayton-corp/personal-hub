"""Routes des tâches planifiées : leur dernier passage, et les relancer depuis l'app (pris dans
la minute par le planificateur, comme la nuit). Session de l'app seulement."""

from __future__ import annotations

from fastapi import APIRouter

from hub.api.schemas_tasks import TaskListOut
from hub.core import tasks
from hub.core.auth import AppSession, Ctx
from hub.core.context import HubContext

router = APIRouter(prefix="/tasks", tags=["tâches"])


def _list(hub_ctx: HubContext) -> TaskListOut:
    with hub_ctx.core.engine.begin() as conn:
        return TaskListOut.model_validate({"items": tasks.status(conn, hub_ctx)})


@router.get("", response_model=TaskListOut)
def list_tasks(hub_ctx: Ctx, _principal: AppSession) -> TaskListOut:
    """Chaque tâche : son horaire, sa dernière demande, son dernier passage."""
    return _list(hub_ctx)


@router.post("/refresh", response_model=TaskListOut)
def refresh_all(hub_ctx: Ctx, principal: AppSession) -> TaskListOut:
    """« Tout actualiser » : chaque connexion active, puis les calculs des domaines quand elles
    ont fini."""
    with hub_ctx.core.engine.begin() as conn:
        tasks.refresh_all(conn, hub_ctx, principal.actor)
    return _list(hub_ctx)


@router.post("/{name}/run", response_model=TaskListOut)
def run_task(name: str, hub_ctx: Ctx, principal: AppSession) -> TaskListOut:
    """Relancer une tâche maintenant : le planificateur la prend dans la minute."""
    with hub_ctx.core.engine.begin() as conn:
        tasks.request(conn, hub_ctx, name, principal.actor)
    return _list(hub_ctx)
