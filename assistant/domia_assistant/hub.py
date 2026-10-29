"""Les outils du hub (chantier S10 du hub) : un module en plus, absent quand l'assistant sert Domia seul.

L'assistant lit les domaines que son jeton ouvre (`hub_capabilities`) et en reprend les outils, rangés par domaine
(un type de demande par domaine pour le modèle en deux temps). Trois règles, tenues ici et non par le modèle :

- les outils du hub ne sont montrés et ne répondent qu'aux personnes nommées dans `hub.owners` : Kim et les invités
  gardent la maison, sans jamais voir un outil du hub ;
- d'un domaine que le jeton lit en entier, rien n'est repris, sauf s'il est nommé dans `hub.full_domains` : une
  question d'argent n'obtient que des agrégats ;
- le jeton vient du fichier de secrets chiffré du hub (section `brain`, clé `aggregates`), jamais du dépôt.

Le client et la boîte à outils sont ceux du hub (`hub.brain`) : ce module n'existe que si le paquet du hub est
installé à côté de l'assistant (`pip install -e ..`).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .tools import Speaker, Tool

LOG = logging.getLogger("assistant.hub")
NOT_YOURS = "Ces outils ne sont ouverts qu'à la personne à qui appartient le hub."


@dataclass(frozen=True)
class HubSettings:
    url: str
    owners: tuple[str, ...]  # les personnes de Domia (leur id) qui atteignent les outils du hub
    full_domains: tuple[str, ...] = ()  # domaines repris même lus en entier (jamais la finance par défaut)
    secrets: Path | None = None  # brain.enc.yaml, chiffré par age
    age_key: Path | None = None
    token: str | None = field(default=None, repr=False)  # HUB_ASSISTANT_TOKEN, pour un essai


def settings(raw: dict | None, env: dict[str, str]) -> HubSettings | None:
    """La section `hub:` de config.yaml ; absente ou sans propriétaire : pas d'outils du hub."""
    raw = raw or {}
    owners = tuple(str(p) for p in raw.get("owners") or ())
    if not raw.get("url") or not owners:
        return None

    def path(key: str) -> Path | None:
        value = raw.get(key)
        return Path(os.path.expanduser(str(value))) if value else None

    return HubSettings(
        url=str(raw["url"]).rstrip("/"),
        owners=owners,
        full_domains=tuple(str(d) for d in raw.get("full_domains") or ()),
        secrets=path("secrets"),
        age_key=path("age_key"),
        token=env.get("HUB_ASSISTANT_TOKEN", "").strip() or None,
    )


def token(cfg: HubSettings) -> str:
    """Le jeton « agrégats » : celui de l'essai, sinon la section `brain` du fichier de secrets chiffré."""
    if cfg.token:
        return cfg.token
    if cfg.secrets is None or cfg.age_key is None:
        raise RuntimeError("hub : ni HUB_ASSISTANT_TOKEN, ni hub.secrets et hub.age_key")
    from hub.platform import secrets  # le paquet du hub, installé à côté

    value = secrets.section(cfg.secrets, cfg.age_key, "brain").get("aggregates")
    if not isinstance(value, str) or not value:
        raise RuntimeError("hub : jeton « aggregates » absent de la section brain des secrets")
    return value


@dataclass
class HubModule:
    """Les outils du hub vus par l'assistant, et ce que le modèle doit en savoir."""

    tools: list[Tool]
    families: dict[str, str]  # domaine → ce qu'on y demande (le routeur du modèle en deux temps)
    notes: str  # les consignes des domaines, ajoutées au système pour un propriétaire
    owner: Speaker | None = None


def build(cfg: HubSettings, api: Any) -> HubModule:
    """`api` : un `hub.brain.hubapi.HubApi` (ou un faux, pour les tests)."""
    owners = frozenset(cfg.owners)

    def allowed(who: Speaker | None) -> bool:
        return who is not None and who.person in owners

    tools: list[Tool] = []
    families: dict[str, str] = {}
    notes: list[str] = []
    for cap in api.hello()["domains"]:
        domain = str(cap["domain"])
        if not cap.get("aggregates_only") and domain not in cfg.full_domains:
            LOG.warning("hub domain=%s skipped=full_read (jeton trop large : agrégats seulement)", domain)
            continue
        families[domain] = str(cap.get("description") or domain)
        if cap.get("instructions"):
            notes.append(f"{domain} : {cap['instructions']}")
        for spec in api.tools(domain):
            tools.append(_tool(api, domain, spec, allowed))
    return HubModule(tools, families, "\n".join(notes), Speaker(person=cfg.owners[0]))


def _tool(api: Any, domain: str, spec: dict, allowed: Callable[[Speaker | None], bool]) -> Tool:
    name = str(spec["name"])

    def run(args: dict, who: Speaker) -> Any:
        if not allowed(who):
            return {"error": NOT_YOURS}
        try:
            return api.call(domain, name, args)
        except Exception as e:  # HubError du client : son type, jamais un contenu
            return {"error": f"hub : {getattr(e, 'type', type(e).__name__)}"}

    return Tool(
        name=name,
        description=str(spec.get("description") or ""),
        parameters=spec.get("input_schema") or {"type": "object", "properties": {}},
        run=run,
        family=domain,
        allowed=allowed,
    )


def connect(cfg: HubSettings) -> HubModule | None:
    """Le module, ou None quand le hub ne répond pas : l'assistant garde la maison."""
    try:
        from hub.brain.hubapi import HubApi
    except ImportError:
        LOG.warning("hub skipped=not_installed (pip install -e .. dans le venv de l'assistant)")
        return None
    try:
        return build(cfg, HubApi(cfg.url, token(cfg)))
    except Exception as e:
        LOG.warning("hub unreachable=%s", type(e).__name__)
        return None
