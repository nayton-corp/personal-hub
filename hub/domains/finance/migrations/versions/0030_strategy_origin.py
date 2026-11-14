"""finance.db : d'où vient une stratégie, en ajout seul.

Une stratégie écrite par la personne n'a pas d'origine (`NULL`). Une stratégie repérée par le hub
dans le journal (achats réguliers du même actif, ou versements réguliers sur un compte qui
investit seul), proposée dans « À valider » puis validée, porte `origin = 'detected'`. Son jour
de départ (`created_on`) est alors celui du premier achat de la série : les échéances passées
sont posées tenues ou passées d'après le journal.

Revision ID: 0030_strategy_origin
Revises: 0029_fund_fees
Create Date: 2026-11-14
"""

from __future__ import annotations

from alembic import op

revision = "0030_strategy_origin"
down_revision = "0029_fund_fees"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE strategies ADD COLUMN origin TEXT CHECK (origin IN ('detected'))",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
