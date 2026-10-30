"""Routes Finance (section 6) : celles de chaque sous-contexte, sous /api/finance."""

from __future__ import annotations

from fastapi import APIRouter

from hub.domains.finance.classement.interface import api as classement
from hub.domains.finance.patrimoine.interface import api as patrimoine
from hub.domains.finance.port import Finance
from hub.domains.finance.registre.interface import api as registre
from hub.domains.finance.sources.interface import api as sources


def build_router(domain: Finance) -> APIRouter:
    r = APIRouter()
    for part in (patrimoine, registre, classement, sources):
        r.include_router(part.build_router(domain))
    return r
