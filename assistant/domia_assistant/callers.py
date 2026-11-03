"""Qui parle à l'assistant (audit C4) : chaque appelant a son jeton, posé dans `.env`
(`ASSISTANT_CALLER_<NOM>=<jeton>`) et décrit dans `listen.callers` de `config.yaml`. La personne vient du jeton,
jamais du corps de la requête seul : le hub parle toujours pour son propriétaire ; Domia dit qui parle, parmi les
personnes qu'on l'autorise à nommer (ses appareils autorisés). L'adresse (`listen.allow_from`) reste une seconde
barrière. Le service ne garde que l'empreinte SHA-256 des jetons."""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass

from .tools import Speaker

NAME = re.compile(r"^[a-z][a-z0-9_]*$")
ENV_PREFIX = "ASSISTANT_CALLER_"


@dataclass(frozen=True)
class Caller:
    name: str
    person: str | None = None  # fixée : l'appelant parle toujours pour cette personne (le hub, un Raccourci)
    speaks_for: frozenset[str] = frozenset()  # sinon : les personnes qu'il peut nommer (Domia)


Callers = dict[str, Caller]  # empreinte du jeton → appelant


class Refused(Exception):
    """L'appelant nomme une personne pour qui il ne parle pas."""


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def from_config(raw: Mapping[str, object] | None, env: Mapping[str, str]) -> Callers:
    """La section `listen.callers` ; un appelant déclaré sans jeton dans l'environnement arrête le service."""
    out: Callers = {}
    for name, spec in (raw or {}).items():
        name = str(name)
        if not NAME.match(name):
            raise SystemExit(f"assistant : appelant « {name} » : un nom en minuscules, chiffres et _")
        var = ENV_PREFIX + name.upper()
        token = env.get(var, "").strip()
        if not token:
            raise SystemExit(f"assistant : {var} manque (le jeton de l'appelant « {name} », dans .env)")
        fields = dict(spec) if isinstance(spec, Mapping) else {}
        person = fields.get("person")
        speaks_for = frozenset(str(p) for p in (fields.get("speaks_for") or ()))
        out[digest(token)] = Caller(name, str(person) if person else None, speaks_for)
    return out


def identify(header: str | None, callers: Callers) -> Caller | None:
    """L'appelant derrière `Authorization: Bearer <jeton>`, comparé en temps constant ; None sinon."""
    if not header or not header.startswith("Bearer "):
        return None
    given = digest(header[7:].strip())
    for known, caller in callers.items():
        if hmac.compare_digest(known, given):
            return caller
    return None


def person(caller: Caller, claimed: str | None) -> str | None:
    """Pour qui l'appelant parle : sa personne, sinon celle qu'il nomme si on l'y autorise, sinon personne."""
    if caller.person is not None:
        return caller.person
    if claimed is None or claimed == "":
        return None
    if claimed in caller.speaks_for:
        return claimed
    raise Refused(f"l'appelant « {caller.name} » ne parle pas pour « {claimed} »")


def speaker(caller: Caller, claimed: str | None, room: str | None, client: str | None) -> Speaker:
    return Speaker(person=person(caller, claimed), room=room or None, client=client or caller.name)
