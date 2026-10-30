"""Ce que les routes de la finance partagent : la forme des paramètres, les portées qui lisent,
et ce qu'une route attend du domaine (`Host`, que `FinanceDomain` remplit). Les routes de chaque
sous-contexte étendent `Host` de ce dont elles ont besoin en plus."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import Engine

from hub.core.auth import Principal, require
from hub.core.errors import Problem
from hub.domains.finance.registre.model import amounts, period
from hub.platform.settings import Settings

MONTH = r"^\d{4}-(0[1-9]|1[0-2])$"
PERIOD = r"^[mq]$"
DATE = r"^\d{4}-\d{2}-\d{2}$"

Reader = Annotated[Principal, Depends(require("app", "finance:read"))]
AnyReader = Annotated[Principal, Depends(require("app", "finance:read", "finance:aggregates"))]


class Host(Protocol):
    settings: Settings

    def engine(self) -> Engine: ...

    def today(self) -> date: ...


def aggregates_only(p: Principal) -> bool:
    return not (p.is_app or p.allows("finance:read"))


def this_month(host: Host) -> str:
    return period.month_of(host.today())


def checked_month(host: Host, month: str | None) -> str:
    """Mois demandé (mois en cours par défaut) ; un mois futur n'a pas encore de chiffres."""
    value = month or this_month(host)
    try:
        amounts.as_of(value, host.today())
    except amounts.FutureMonth:
        raise Problem("validation.params", "mois futur") from None
    return value
