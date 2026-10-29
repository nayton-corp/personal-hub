"""Le modèle, derrière un serveur local compatible OpenAI (Ollama, LM Studio, mlx_lm.server ; spec §6) : l'assistant
ne connaît que son adresse et son nom. En test, un modèle scripté rejoue des réponses enregistrées (spec §17)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Protocol

LOG = logging.getLogger("assistant.model")
MAX_TOKENS = 600


class ModelError(Exception):
    pass


class Model(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Le message de l'assistant : {"role": "assistant", "content": ..., "tool_calls": [...]}."""


class OpenAICompatible:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float = 120.0,
        keep_alive: str | None = None,
        reasoning: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.keep_alive = keep_alive  # Ollama le lit aussi sur /v1 ; les autres serveurs l'ignorent
        self.reasoning = reasoning

    def _post(self, path: str, body: dict) -> dict:
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise ModelError(f"le modèle ne répond pas ({e})") from None

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        # une réponse de l'assistant tient en deux phrases ou quelques appels d'outils : au banc, un appel sur 15 à 20
        # tournait 120 s sans fin ; borné, il s'arrête et la boucle répond quand même
        body = {"model": self.model, "messages": messages, "temperature": 0.2, "max_tokens": MAX_TOKENS}
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        if self.reasoning:
            body["reasoning_effort"] = self.reasoning
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        started = time.monotonic()
        answer = self._post("/chat/completions", body)
        try:
            message = answer["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModelError("réponse du modèle illisible") from None
        # où partent les secondes : un modèle rechargé, un long préfixe recalculé, ou une longue réponse
        usage = answer.get("usage") or {}
        LOG.info(
            "chat ms=%d prompt=%s out=%s tools=%s",
            (time.monotonic() - started) * 1000,
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            ",".join(c["function"]["name"] for c in message.get("tool_calls") or []) or "-",
        )
        return message

    def look(self, image: bytes, mime: str, question: str, model: str) -> str:
        """Une photo et une question à un modèle de vision (lire une plaque signalétique, spec §8.2)."""
        import base64

        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        content = [{"type": "text", "text": question}, {"type": "image_url", "image_url": {"url": url}}]
        answer = self._post(
            "/chat/completions", {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0}
        )
        return answer["choices"][0]["message"].get("content") or ""

    def embed(self, texts: list[str], model: str) -> list[list[float]]:
        body = {"model": model, "input": texts}
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        answer = self._post("/embeddings", body)
        return [d["embedding"] for d in sorted(answer["data"], key=lambda d: d["index"])]


class ScriptedModel:
    """Rejoue des messages, un par appel ; garde ce qu'on lui a demandé (les outils proposés, les résultats rendus)."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.requests: list[tuple[list[dict], list[dict]]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        self.requests.append(([dict(m) for m in messages], tools))
        if not self.replies:
            raise ModelError("plus de réponse scriptée")
        return self.replies.pop(0)


def call(name: str, arguments: dict, call_id: str = "c1") -> dict:
    """Un appel d'outil, à la forme OpenAI (pour écrire les scripts)."""
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


def say(content: str) -> dict:
    return {"role": "assistant", "content": content}


def calls(*tool_calls: dict) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": list(tool_calls)}
