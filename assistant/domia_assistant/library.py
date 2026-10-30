"""La bibliothèque des objets du ménage (spec §8), lue au hub (domaine Documents, chantier S12 du hub).

Les fiches des objets et les documents du foyer (notices, bail, assurances, décomptes) vivent dans le hub depuis la
reprise unique de `~/Domia/Bibliothèque/` (`hub documents import-library`) : l'assistant ne lit plus ce dossier. Il
appelle les outils du domaine avec le jeton `library` (section `brain` des secrets chiffrés), dont la portée
`documents:household` n'ouvre que les fiches et les documents marqués « foyer » : ce que Kim et les invités lisaient
déjà. Une fiche se complète par une proposition, validée dans l'app. Une réponse cite toujours sa source et sa page.

Seul le dossier `à-trier/` reste local : les photos d'une plaque signalétique, que le modèle de vision lit avant de
proposer la fiche.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

LOG = logging.getLogger("assistant.library")
INBOX = "à-trier"
DOMAIN = "documents"


class Api(Protocol):
    """`hub.brain.hubapi.HubApi`, ou un faux pour les tests."""

    def call(self, domain: str, name: str, args: dict[str, Any]) -> Any: ...


@dataclass(frozen=True)
class Passage:
    source: str  # « notice, p. 3 » : ce que le hub rend à citer
    page: int | None
    text: str

    def cite(self) -> str:
        return self.source


class LibraryUnavailable(RuntimeError):
    pass


class Library:
    def __init__(self, api: Api, inbox_dir: Path):
        self.api = api
        self.inbox_dir = inbox_dir

    def _call(self, name: str, args: dict[str, Any] | None = None) -> Any:
        try:
            return self.api.call(DOMAIN, name, args or {})
        except Exception as e:  # HubError du client : son type, jamais un contenu
            kind = getattr(e, "type", type(e).__name__)
            if kind == "not_found":
                return None
            raise LibraryUnavailable(f"bibliothèque du hub : {kind}") from None

    def search(self, question: str, k: int = 5) -> list[Passage]:
        if len(question.strip()) < 3:
            return []
        found = self._call("documents_search", {"q": question[:200], "limit": max(1, min(k, 20))}) or {}
        return [Passage(p["cite"], p.get("page"), p["text"]) for p in found.get("passages", [])]

    def cards(self) -> dict[str, dict]:
        return {c["card_id"]: c for c in self._call("documents_cards") or []}

    def card(self, card_id: str) -> dict | None:
        return self._call("documents_card", {"card_id": card_id})

    def save_card(self, card_id: str, fields: dict) -> dict:
        """Propose de créer ou de compléter une fiche : une carte dans l'app, pas une écriture."""
        return self._call("documents_propose_card", {"card_id": card_id, "fields": fields}) or {}

    def maintenance_due(self, today: date | None = None) -> list[dict]:
        """Les entretiens dus, à la date du hub (`today` est gardé pour l'appel d'avant)."""
        return list(self._call("documents_maintenance_due") or [])

    def inbox(self) -> list[Path]:
        if not self.inbox_dir.is_dir():
            return []
        return sorted(p for p in self.inbox_dir.iterdir() if p.is_file() and not p.name.startswith("."))
