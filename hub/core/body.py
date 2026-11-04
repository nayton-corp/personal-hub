"""Lire le corps d'une requête en flux, borné : rien n'est gardé au-delà de la limite (audit m18),
et la boucle d'évènements n'attend jamais un port synchrone (audit M13) : le travail bloquant part
dans le threadpool de Starlette (`run_in_threadpool`) depuis la route.

Le cœur ne connaît pas FastAPI : la requête est vue par sa forme (en-têtes, flux de morceaux)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Protocol


class Incoming(Protocol):
    """Ce qu'une requête HTTP montre ici : ses en-têtes et son corps en morceaux."""

    @property
    def headers(self) -> Mapping[str, str]: ...

    def stream(self) -> AsyncIterator[bytes]: ...


async def read_body(request: Incoming, limit: int) -> bytes | None:
    """Le corps, ou None dès qu'il dépasse `limit` (annoncé par Content-Length, ou lu)."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)
