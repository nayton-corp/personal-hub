"""Routes de l'orbe : l'app parle à l'assistant de la maison par le hub (session de l'app seule).

Le hub relaie ; l'assistant garde la conversation, le hub ne garde rien (ni phrase ni son).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel, Field

from hub.core.assistant_link import AssistantError
from hub.core.auth import AppSession, Ctx
from hub.core.errors import Problem

router = APIRouter(prefix="/assistant", tags=["assistant"])
MAX_AUDIO = 8 * 1024 * 1024  # une phrase dite, pas un enregistrement


class AssistantStatusOut(BaseModel):
    configured: bool
    ok: bool
    voice: bool


class TalkIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AnswerOut(BaseModel):
    answer: str = ""
    done: list[Any] = []
    proposals: list[Any] = []
    confirm: str | None = None
    heard: str | None = None  # la phrase entendue, pour une réponse à la voix
    speech: dict[str, str] | None = None  # {mime, data en base64}


class HistoryOut(BaseModel):
    items: list[dict[str, Any]]
    waiting: list[dict[str, Any]] = []


def _relay(error: AssistantError) -> Problem:
    return Problem(f"assistant.{error.kind}", str(error))


@router.get("/status", response_model=AssistantStatusOut)
def status(hub_ctx: Ctx, _principal: AppSession) -> AssistantStatusOut:
    link = hub_ctx.assistant
    if not link.configured:
        return AssistantStatusOut(configured=False, ok=False, voice=False)
    try:
        found = link.health()
    except AssistantError:
        return AssistantStatusOut(configured=True, ok=False, voice=False)
    return AssistantStatusOut(configured=True, ok=True, voice=found.get("voice") == "ok")


@router.get("/history", response_model=HistoryOut)
def history(
    hub_ctx: Ctx,
    _principal: AppSession,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> HistoryOut:
    try:
        found = hub_ctx.assistant.history(hub_ctx.settings.assistant.person, days, limit)
    except AssistantError as e:
        raise _relay(e) from None
    return HistoryOut(items=found.get("items") or [], waiting=found.get("waiting") or [])


@router.post("/talk", response_model=AnswerOut)
def talk(body: TalkIn, hub_ctx: Ctx, _principal: AppSession) -> AnswerOut:
    try:
        found = hub_ctx.assistant.talk(body.text.strip(), hub_ctx.settings.assistant.person)
    except AssistantError as e:
        raise _relay(e) from None
    return AnswerOut.model_validate(found)


@router.post("/voice", response_model=AnswerOut)
async def voice(
    request: Request,
    hub_ctx: Ctx,
    _principal: AppSession,
    content_type: Annotated[str, Header()] = "",
) -> AnswerOut:
    mime = content_type.split(";")[0].strip().lower()
    audio = await request.body()
    if not mime.startswith("audio/") or not audio or len(audio) > MAX_AUDIO:
        raise Problem("validation.params", "son absent, trop long ou d'un type inconnu")
    try:
        found = hub_ctx.assistant.voice(audio, content_type, hub_ctx.settings.assistant.person)
    except AssistantError as e:
        raise _relay(e) from None
    return AnswerOut.model_validate(found)
