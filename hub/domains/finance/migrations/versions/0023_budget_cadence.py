"""finance.db : la cible d'un budget est gardée telle que saisie, avec sa cadence (audit M4) :
`amount_minor` (le montant saisi : 1 000 francs par an restent 1 000 francs) et `cadence`
(`month` ou `year`) sur `budgets`. Les anciennes lignes n'ont que `monthly_minor` (une cible
annuelle y était un douzième arrondi) : elles se lisent avec la cadence de `budget_cadence`.

Revision ID: 0023_budget_cadence
Revises: 0022_crypto_moves
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "0023_budget_cadence"
down_revision = "0022_crypto_moves"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE budgets ADD COLUMN amount_minor INTEGER CHECK (amount_minor >= 0)",
    "ALTER TABLE budgets ADD COLUMN cadence TEXT CHECK (cadence IN ('month', 'year'))",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
