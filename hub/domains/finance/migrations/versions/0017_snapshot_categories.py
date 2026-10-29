"""finance.db : les instantanés suivent aussi les catégories.

Une écriture reclassée change les versements cumulés et les paiements d'une dette (debts.py) :
`snapshot_state.categorizations_seq` garde max(categorizations.seq) du dernier calcul, et un
reclassement relance le calcul à la lecture suivante, comme une nouvelle écriture.

Revision ID: 0017_snapshot_categories
Revises: 0016_debts
Create Date: 2026-10-29
"""

from alembic import op

revision = "0017_snapshot_categories"
down_revision = "0016_debts"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE snapshot_state ADD COLUMN categorizations_seq INTEGER NOT NULL DEFAULT 0",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
