"""Identifiants : ULID, URN `hub:<domaine>:<type>:<id>` et acteurs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ulid import ULID

_PART = r"[a-z][a-z0-9_-]*"
_URN = re.compile(rf"^hub:(?P<domain>{_PART}):(?P<type>{_PART}):(?P<id>[A-Za-z0-9_.-]+)$")
_ACTOR = re.compile(r"^(?P<kind>token|passkey|system):(?P<id>[A-Za-z0-9_.-]+)$")


def new_id(prefix: str = "") -> str:
    return f"{prefix}{ULID()}"


@dataclass(frozen=True, slots=True)
class Urn:
    domain: str
    type: str
    id: str

    def __str__(self) -> str:
        return f"hub:{self.domain}:{self.type}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> Urn:
        m = _URN.match(value)
        if m is None:
            raise ValueError(f"URN invalide : {value!r}")
        return cls(m["domain"], m["type"], m["id"])


def urn(domain: str, type_: str, id_: str) -> str:
    value = f"hub:{domain}:{type_}:{id_}"
    Urn.parse(value)
    return value


def actor(kind: str, id_: str) -> str:
    """`token:<id>`, `passkey:<credential_id>` ou `system:<service>`."""
    value = f"{kind}:{id_}"
    if _ACTOR.match(value) is None:
        raise ValueError(f"acteur invalide : {value!r}")
    return value


def is_actor(value: str) -> bool:
    return _ACTOR.match(value) is not None
