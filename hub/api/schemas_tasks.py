"""Schémas des tâches planifiées relancées à la main (core.tasks)."""

from __future__ import annotations

from pydantic import BaseModel


class TaskOut(BaseModel):
    name: str  # `hub.backup`, `finance.strategies`
    domain: str  # `hub` : l'entretien du hub
    label: str
    when: str  # son horaire, en mots
    requested: bool  # demandée depuis l'app, pas encore prise
    after_sources: bool  # elle attend que les connexions aient fini
    running: bool
    available: bool  # faux : aucune connexion active ne peut la faire
    started_at: str | None
    ended_at: str | None
    outcome: str | None  # `ok`, `failed`, ou rien tant qu'elle n'a jamais tourné
    summary: str | None  # quelques mots, jamais un montant


class TaskListOut(BaseModel):
    items: list[TaskOut]
