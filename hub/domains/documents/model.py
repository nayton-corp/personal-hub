"""Fiches d'objets et documents, sans base ni fichier : champs permis, échéances d'entretien,
découpage du texte en passages. Repris de la bibliothèque de l'assistant de Domia."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

CARD_FIELDS = frozenset(
    {
        "name",
        "room",
        "brand",
        "model",
        "serial",
        "bought_at",
        "shop",
        "price_chf",
        "warranty_until",
        "domia",
        "maintenance",
        "parts",
        "documents",
        "notes",
    }
)
CARD_ID = re.compile(r"[\w\- ]{1,80}")
CHUNK_CHARS = 1200
EVERY = re.compile(r"^\s*(\d+)\s*(jour|jours|semaine|semaines|mois|an|ans|annee|annees)\s*$")
DAYS = {"jour": 1, "semaine": 7, "mois": 30, "an": 365, "annee": 365}


class CardError(ValueError):
    pass


def check_card(card_id: str, fields: dict[str, Any]) -> None:
    if not CARD_ID.fullmatch(card_id):
        raise CardError("un id de fiche : lettres, chiffres, espaces, - et _")
    unknown = set(fields) - CARD_FIELDS
    if unknown:
        raise CardError(f"champs inconnus : {', '.join(sorted(unknown))}")


def merged(current: dict[str, Any] | None, fields: dict[str, Any]) -> dict[str, Any]:
    """Une fiche complétée : un champ à `None` ne retire rien."""
    out = dict(current or {})
    out.update({k: v for k, v in fields.items() if v is not None})
    return out


def every(text: str) -> timedelta | None:
    """« 1 mois », « 2 semaines », « 1 an » en durée ; None si illisible."""
    m = EVERY.match(str(text).lower().replace("é", "e"))
    if not m:
        return None
    unit = m.group(2).rstrip("s") if m.group(2) not in ("mois",) else "mois"
    return timedelta(days=int(m.group(1)) * DAYS[unit])


def maintenance_due(cards: dict[str, dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """Les tâches d'entretien dont l'échéance est passée."""
    due = []
    for card_id, card in cards.items():
        for task in card.get("maintenance") or []:
            period = every(task.get("every", ""))
            last = task.get("last")
            if period is None or last is None:
                continue
            since = date.fromisoformat(str(last)) + period
            if since <= today:
                due.append(
                    {
                        "card": card_id,
                        "name": card.get("name", card_id),
                        "what": task.get("what"),
                        "since": since.isoformat(),
                    }
                )
    return due


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Des passages d'environ `size` caractères, coupés entre paragraphes quand c'est possible."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    current = ""
    for p in paragraphs:
        while len(p) > size:
            if current:
                out.append(current)
                current = ""
            out.append(p[:size])
            p = p[size:]
        if len(current) + len(p) + 2 > size and current:
            out.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        out.append(current)
    return out


def plain(value: Any) -> Any:
    """Une valeur lue dans un YAML, en JSON : une date devient son texte ISO."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [plain(v) for v in value]
    return value
