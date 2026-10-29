"""Journaux JSON sur stdout, filtrés : jamais de montant, libellé, IBAN, solde ni contrepartie,
ni le texte d'une question ou d'une réponse de l'assistant.

Un événement qui porte une clé interdite (ou une valeur qui ressemble à un IBAN, ou un `Money`)
n'est pas écrit : il est remplacé par `log.rejected`, qui ne garde que le nom de l'événement et
les clés fautives. Le contenu ne sort jamais.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterable, MutableMapping
from typing import Any, TextIO

import structlog

from hub.kernel.money import Money

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "amount",
        "amount_minor",
        "minor",
        "balance",
        "balance_minor",
        "label",
        "remittance",
        "iban",
        "counterparty",
        "counterparty_iban",
        "counterparty_name",
        "description",
        "merchant",
        "question",
        "answer",
        "prompt",
        "password",
        "secret",
        "token",
        "authorization",
        "cookie",
    }
)

_IBAN_IN_TEXT = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}(?: ?[A-Z0-9]{1,3})?\b")
_ALLOWED_META = frozenset({"event", "level", "timestamp", "logger"})


def _offending(event: MutableMapping[str, Any]) -> list[str]:
    bad: list[str] = []
    for key, value in event.items():
        if key in _ALLOWED_META and key != "event":
            continue
        if (
            key.lower() in FORBIDDEN_KEYS
            or isinstance(value, Money)
            or (isinstance(value, str) and _IBAN_IN_TEXT.search(value))
            or (isinstance(value, dict) and _offending(value))
        ):
            bad.append(key)
    return sorted(bad)


def reject_forbidden(
    _logger: Any, _method: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    bad = _offending(event)
    if not bad:
        return event
    name = event.get("event")
    safe_name = name if isinstance(name, str) and not _IBAN_IN_TEXT.search(name) else "?"
    if "event" in bad:
        bad.remove("event")
        bad.append("event(text)")
    return {
        "event": "log.rejected",
        "original_event": safe_name,
        "rejected_keys": bad,
        "level": "error",
        **({"timestamp": event["timestamp"]} if "timestamp" in event else {}),
    }


def processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        reject_forbidden,
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(sort_keys=True),
    ]


def configure(level: str = "INFO", stream: TextIO | None = None) -> None:
    structlog.configure(
        processors=processors(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.WriteLoggerFactory(file=stream or sys.stdout),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)


def forbidden_keys_in(keys: Iterable[str]) -> set[str]:
    return {k for k in keys if k.lower() in FORBIDDEN_KEYS}
