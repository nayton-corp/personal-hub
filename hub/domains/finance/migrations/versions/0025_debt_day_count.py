"""finance.db : la convention de décompte des intérêts d'une dette (audit m3). `debts.day_count`
vaut `act/365` (jours réels sur 365, ce que le hub faisait pour toutes), `act/360` ou `30/360`
(mois de trente jours sur une année de 360, l'usage des hypothèques suisses). Les dettes en
place gardent `act/365` : leur solde ne bouge pas.

Revision ID: 0025_debt_day_count
Revises: 0024_source_gaps
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "0025_debt_day_count"
down_revision = "0024_source_gaps"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE debts ADD COLUMN day_count TEXT NOT NULL DEFAULT 'act/365' "
    "CHECK (day_count IN ('act/365', 'act/360', '30/360'))",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
