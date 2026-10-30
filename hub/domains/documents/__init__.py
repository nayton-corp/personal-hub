"""Domaine Documents (chantier S12) : fiches d'objets et documents de la maison.

Archive chiffrée dont la base se reconstruit, index local des passages, marque « foyer » pour
ce que tout le foyer peut lire ; liens vers la finance par `core/link`.
"""

from hub.domains.documents.domain import DocumentsDomain, create

__all__ = ["DocumentsDomain", "create"]
