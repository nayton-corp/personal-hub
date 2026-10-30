"""Domaine Agenda (chantier S11) : Rappels et Calendrier du Mac, par le pont EventKit.

Aucune copie : les lectures passent au pont, chaque écriture est une proposition à effet
externe (ajouter un rappel, un événement, cocher ; la liste de courses au palier automatique).
Jamais de suppression.
"""

from hub.domains.agenda.domain import AgendaDomain, create

__all__ = ["AgendaDomain", "create"]
