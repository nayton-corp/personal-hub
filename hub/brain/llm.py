"""Modèle local par l'API compatible OpenAI (`/v1/chat/completions`, `/v1/models`).

Ollama l'expose (http://localhost:11434/v1), `mlx_lm.server` aussi : changer de moteur ne
change que `llm_url` et `model`. Rien ne sort du Mac : l'adresse est celle de l'hôte Docker.
"""

from __future__ import annotations

import json
import re
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Protocol

from hub.brain.hubapi import Transport, loads, urllib_transport

_THINK = re.compile(r"<think>.*?</think>", re.S)


class LlmError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)  # message assistant, renvoyé tel quel


class ChatModel(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
    ) -> Reply: ...


def clean(content: str | None) -> str:
    """Retire le raisonnement `<think>…</think>` que certains modèles laissent dans la réponse."""
    return _THINK.sub("", content or "").strip()


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value, parse_float=str)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


class OpenAICompatible:
    def __init__(
        self, base_url: str, model: str, timeout: int = 300, transport: Transport | None = None
    ) -> None:
        self.base = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport or urllib_transport

    def _post(self, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            status, raw = self.transport(
                "POST" if body is not None else "GET", self.base + path, headers, data
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise LlmError(f"modèle injoignable ({type(exc).__name__}) : {self.base}") from None
        if status != 200:
            raise LlmError(f"modèle : HTTP {status} sur {path}")
        try:
            return loads(raw)
        except ValueError:
            raise LlmError("modèle : réponse illisible") from None

    def models(self) -> list[str]:
        found = self._post("/models").get("data") or []
        return [str(m.get("id")) for m in found if isinstance(m, dict)]

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        json_mode: bool = False,
    ) -> Reply:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
            "stream": False,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["input_schema"],
                    },
                }
                for t in tools
            ]
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        out = self._post("/chat/completions", body)
        try:
            message = out["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LlmError("modèle : réponse sans message") from None
        calls = [
            ToolCall(
                str(c.get("id") or f"call_{i}"),
                str(c["function"]["name"]),
                _arguments(c["function"].get("arguments")),
            )
            for i, c in enumerate(message.get("tool_calls") or [])
            if isinstance(c, dict) and isinstance(c.get("function"), dict)
        ]
        return Reply(clean(message.get("content")), calls, message)
