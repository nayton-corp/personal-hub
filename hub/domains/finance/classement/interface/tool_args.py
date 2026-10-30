"""Arguments des outils du classement et du budget, validés avant tout appel : un modèle ne
passe que ce que le schéma annonce."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import AliasChoices, Field

from hub.domains.finance.classement.app.categorize_kinds import ENTRIES_MAX
from hub.domains.finance.registre.interface.tools import (
    EntryId,
    Reason,
    _Args,
)

REVIEW_GROUPS = 100  # un passage de rattrapage du brain voit toute la file
REVIEW_IDS = 10
REVIEW_OFFSET_MAX = 5000  # la file se parcourt par pages de REVIEW_GROUPS groupes
# règle proposée par un assistant : avant les packs (11+) et la règle « tout le reste », après
# « Toujours » (4) et la règle d'une poche (5)
RULE_PRIORITY = 10


class TrendArgs(_Args):
    category: str
    months: int = Field(default=6, ge=1, le=36)


class ReviewArgs(_Args):
    limit: int = Field(default=10, ge=1, le=REVIEW_GROUPS)
    offset: int = Field(default=0, ge=0, le=REVIEW_OFFSET_MAX)


class ProposeCategoryArgs(_Args):
    entry_id: EntryId
    category: str
    reason: Reason = None


class ProposeCategoriesArgs(_Args):
    entry_ids: list[EntryId] = Field(min_length=1, max_length=ENTRIES_MAX)
    category: str
    reason: Reason = None


class ProposeRuleArgs(_Args):
    keyword: str = Field(min_length=3, max_length=60)
    category: str
    direction: Literal["any", "debit", "credit"] = "any"
    reason: Reason = None


class ProposeBudgetArgs(_Args):
    category: str
    # `amount_chf` : ancien nom, accepté tant que des prompts l'emploient
    amount: Decimal = Field(
        ge=0,
        le=1_000_000,
        max_digits=9,
        decimal_places=2,
        validation_alias=AliasChoices("amount", "amount_chf"),
    )
    # « year » : `amount` est la cible annuelle, suivie en cumul depuis janvier
    cadence: Literal["month", "year"] = "month"
    reason: Reason = None
