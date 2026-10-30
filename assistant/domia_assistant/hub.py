"""Les outils du hub (chantier S10 du hub) : un module en plus, absent quand l'assistant sert Domia seul.

L'assistant lit les domaines que son jeton ouvre (`hub_capabilities`) et en reprend les outils, rangés par domaine
(un type de demande par domaine pour le modèle en deux temps). Trois règles, tenues ici et non par le modèle :

- les outils du hub ne sont montrés et ne répondent qu'aux personnes nommées dans `hub.owners` : Kim et les invités
  gardent la maison, sans jamais voir un outil du hub ;
- d'un domaine que le jeton lit en entier, rien n'est repris, sauf s'il est nommé dans `hub.full_domains` : une
  question d'argent n'obtient que des agrégats ;
- le jeton vient du fichier de secrets chiffré du hub (section `brain`, clé `aggregates`), jamais du dépôt.

La bibliothèque du foyer (fiches d'objets, notices) fait exception : elle vit dans le hub (domaine Documents) et
répond à tout le foyer, avec un jeton à elle (clé `library`) qui n'ouvre que la part marquée « foyer ».

Il fait aussi le travail de l'ancien conteneur `brain` du hub : chaque matin (`hub.classify_at`), il propose une
catégorie pour les commerçants jamais vus, avec le jeton `brain` et le modèle résident ; ce sont des cartes, que le
propriétaire valide dans l'app.

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

from .library import Library
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
    classify_at: str | None = "08:30"  # suggestions de catégorie du matin ; None : jamais
    state: Path = Path.home() / "PersonalHub" / "brain"  # commerçants déjà proposés


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
        classify_at=raw.get("classify_at", HubSettings.classify_at),
        state=path("state") or HubSettings.state,
    )


def token(cfg: HubSettings, name: str = "aggregates") -> str:
    """Le jeton `aggregates` (la conversation), `brain` (le classement) ou `library` (la bibliothèque du foyer) :
    celui de l'essai pour la conversation, sinon la section `brain` du fichier de secrets chiffré."""
    if cfg.token and name == "aggregates":
        return cfg.token
    if cfg.secrets is None or cfg.age_key is None:
        raise RuntimeError("hub : ni HUB_ASSISTANT_TOKEN, ni hub.secrets et hub.age_key")
    from hub.platform import secrets  # le paquet du hub, installé à côté

    value = secrets.section(cfg.secrets, cfg.age_key, "brain").get(name)
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"hub : jeton « {name} » absent de la section brain des secrets")
    return value


MODES = ("suggest", "catchup", "direct")


def classify(cfg: HubSettings, model_url: str, model: str, mode: str = "suggest", dry_run: bool = False) -> dict:
    """Le classement du brain du hub, avec le modèle résident de l'assistant (un seul modèle chargé) : `suggest` les
    commerçants jamais vus (le matin), `catchup` une règle par commerçant, `direct` les achats uniques. Rend des
    compteurs, jamais un montant ni un libellé."""
    from hub.brain import suggest as brain
    from hub.brain.hubapi import HubApi
    from hub.brain.llm import OpenAICompatible
    from hub.brain.toolbox import Toolbox as HubToolbox

    box = HubToolbox(HubApi(cfg.url, token(cfg, "brain")))
    box.start()
    run = {"suggest": brain.suggest, "catchup": brain.catchup, "direct": brain.direct}[mode]
    report = run(box, OpenAICompatible(model_url, model), brain.Memory(cfg.state), dry_run=dry_run)
    return {
        "merchants": report.merchants,
        "suggested": report.suggested,
        "proposals": report.proposals,
        "skipped": report.skipped,
        "stopped": report.stopped,
    }


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


def library(cfg: HubSettings, inbox_dir: Path) -> Library | None:
    """La bibliothèque du foyer, lue au hub avec le jeton `library` (`documents:household,documents:propose`) ; None
    sans le paquet du hub ou sans ce jeton."""
    try:
        from hub.brain.hubapi import HubApi
    except ImportError:
        LOG.warning("library skipped=not_installed (pip install -e .. dans le venv de l'assistant)")
        return None
    try:
        return Library(HubApi(cfg.url, token(cfg, "library")), inbox_dir)
    except Exception as e:
        LOG.warning("library skipped=%s", type(e).__name__)
        return None


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
