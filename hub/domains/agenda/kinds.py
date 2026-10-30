"""Les types de proposition de l'agenda : des effets externes, chez Rappels et Calendrier.

Ajouter un rappel, un événement, cocher un rappel, ajouter à la liste de courses ; jamais
supprimer. Chaque envoi est noté dans `sent` avant l'appel au pont, puis son issue : une même
validation rejouée renvoie le premier résultat, et la réconciliation sait ce qui est parti.
La liste de courses a son type à elle, au palier automatique : un article de plus n'attend pas
une carte (on le coche ou on l'ignore dans Rappels).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, text

from hub.core.domain import ExternalResult, Preview, ProposalKind
from hub.domains.agenda.bridge import SHOPPING, Bridge, BridgeError
from hub.kernel import canonical
from hub.kernel.clock import now_iso

ISO = r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}(:\d{2})?)?$"


class AddReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    list: str | None = Field(default=None, max_length=80)
    due: str | None = Field(default=None, pattern=ISO)
    notes: str | None = Field(default=None, max_length=1000)


class AddShopping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=100)


class AddEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    start: str = Field(pattern=ISO)
    end: str = Field(pattern=ISO)
    calendar: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _ordered(self) -> AddEvent:
        if datetime.fromisoformat(self.end) < datetime.fromisoformat(self.start):
            raise ValueError("la fin précède le début")
        return self


class CompleteReminder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reminder_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)  # pour la carte ; le pont coche par l'id


Send = Callable[[Bridge, Any], dict[str, Any]]
Found = Callable[[Bridge, Any], bool]


class Handler:
    """Un effet chez Rappels ou Calendrier : aperçu, envoi idempotent, réconciliation."""

    def __init__(
        self,
        engine: Callable[[], Engine],
        bridge: Bridge,
        kind: str,
        model: type[BaseModel],
        summary: Callable[[Any], str],
        send: Send,
        found: Found,
    ) -> None:
        self._engine = engine
        self._bridge = bridge
        self._kind = kind
        self._model = model
        self._summary = summary
        self._send = send
        self._found = found

    def preview(self, params: BaseModel) -> Preview:
        data = params.model_dump(mode="json")
        return Preview(
            self._summary(params),
            {k: v for k, v in data.items() if v is not None},
            canonical.sha256_hex({"kind": self._kind, "params": data}),
        )

    def apply(self, params: BaseModel, idempotency_key: str) -> ExternalResult:
        proposal_id = idempotency_key.split(":", 1)[0]
        with self._engine().begin() as conn:
            row = conn.execute(
                text("SELECT status, result_json FROM sent WHERE key = :k"), {"k": idempotency_key}
            ).first()
            if row is not None and row[0] == "ok":
                return ExternalResult("ok", json.loads(row[1]))
            if row is None:
                conn.execute(
                    text(
                        "INSERT INTO sent (key, proposal_id, kind, params_json, status, sent_at) "
                        "VALUES (:k, :p, :kind, :params, 'sending', :at)"
                    ),
                    {
                        "k": idempotency_key,
                        "p": proposal_id,
                        "kind": self._kind,
                        "params": canonical.dumps(params.model_dump(mode="json")),
                        "at": now_iso(),
                    },
                )
        try:
            result = self._send(self._bridge, params)
        except BridgeError as exc:
            if exc.unreachable:
                return ExternalResult("unknown", {"error": str(exc)})
            self._mark(idempotency_key, "failed", {"error": str(exc)})
            return ExternalResult("failed", {"error": str(exc)})
        detail = {"id": str(result.get("id", ""))}
        self._mark(idempotency_key, "ok", detail)
        return ExternalResult("ok", detail)

    def reconcile(self, proposal_id: str) -> ExternalResult:
        """Après un envoi au résultat inconnu : ce que `sent` en sait, sinon ce que le pont
        montre (un rappel ou un événement de même titre et de même date)."""
        with self._engine().connect() as conn:
            row = conn.execute(
                text(
                    "SELECT key, status, params_json, result_json FROM sent "
                    "WHERE proposal_id = :p ORDER BY sent_at DESC LIMIT 1"
                ),
                {"p": proposal_id},
            ).first()
        if row is None:
            return ExternalResult("failed", {"error": "jamais envoyé"})
        if row[1] != "sending":
            return ExternalResult("ok" if row[1] == "ok" else "failed", json.loads(row[3]))
        params = self._model.model_validate(json.loads(row[2]))
        try:
            there = self._found(self._bridge, params)
        except BridgeError:
            return ExternalResult("unknown")
        self._mark(row[0], "ok" if there else "failed", {})
        return ExternalResult("ok" if there else "failed")

    def _mark(self, key: str, status: str, result: dict[str, Any]) -> None:
        with self._engine().begin() as conn:
            conn.execute(
                text("UPDATE sent SET status = :s, result_json = :r WHERE key = :k"),
                {"s": status, "r": canonical.dumps(result), "k": key},
            )


def _reminder_body(p: Any) -> dict[str, Any]:
    if isinstance(p, AddShopping):
        return {"title": p.title, "list": SHOPPING}
    return {"title": p.title, "list": p.list, "due": p.due, "notes": p.notes}


def _reminder_there(b: Bridge, p: Any) -> bool:
    body = _reminder_body(p)
    return any(
        r.get("title") == body["title"] and (body.get("list") in (None, r.get("list")))
        for r in b.reminders(body.get("list"), done=True)
    )


def _event_there(b: Bridge, p: Any) -> bool:
    return any(
        e.get("title") == p.title and str(e.get("start", ""))[:16] == p.start[:16]
        for e in b.events(p.start[:10], p.end[:10] + "T23:59")
    )


def _completed(b: Bridge, p: Any) -> bool:
    return any(r.get("id") == p.reminder_id and r.get("done") for r in b.reminders(None, done=True))


def kinds(engine: Callable[[], Engine], bridge: Bridge) -> Mapping[str, ProposalKind]:
    def handler(
        kind: str, model: type[BaseModel], summary: Callable[[Any], str], send: Send, found: Found
    ) -> Handler:
        return Handler(engine, bridge, kind, model, summary, send, found)

    return {
        "add_reminder": ProposalKind(
            AddReminder,
            handler(
                "add_reminder",
                AddReminder,
                lambda p: f"Rappel « {p.title} »" + (f" pour le {p.due[:10]}" if p.due else ""),
                lambda b, p: b.add_reminder(_reminder_body(p)),
                _reminder_there,
            ),
            ai_allowed=True,
            external=True,
        ),
        "add_shopping": ProposalKind(
            AddShopping,
            handler(
                "add_shopping",
                AddShopping,
                lambda p: f"« {p.title} » sur la liste de courses",
                lambda b, p: b.add_reminder(_reminder_body(p)),
                _reminder_there,
            ),
            ai_allowed=True,
            external=True,
            tier="auto",  # un article de plus n'attend pas de carte (D-023)
        ),
        "add_event": ProposalKind(
            AddEvent,
            handler(
                "add_event",
                AddEvent,
                lambda p: f"Événement « {p.title} » le {p.start[:10]}",
                lambda b, p: b.add_event(p.model_dump()),
                _event_there,
            ),
            ai_allowed=True,
            external=True,
        ),
        "complete_reminder": ProposalKind(
            CompleteReminder,
            handler(
                "complete_reminder",
                CompleteReminder,
                lambda p: f"Cocher « {p.title} »",
                lambda b, p: b.complete(p.reminder_id),
                _completed,
            ),
            ai_allowed=True,
            external=True,
        ),
    }
