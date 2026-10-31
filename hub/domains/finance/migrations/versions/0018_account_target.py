"""finance.db : montant visé d'un compte.

`accounts.target_minor` : le montant que le compte doit atteindre (une poche Voiture, une
réserve de sécurité), en centimes de la devise du compte ; NULL, pas de montant visé. L'app en
tire la progression et une date estimée sur la page du compte.

Revision ID: 0018_account_target
Revises: 0017_snapshot_categories
Create Date: 2026-10-31
"""

from alembic import op

revision = "0018_account_target"
down_revision = "0017_snapshot_categories"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE accounts ADD COLUMN target_minor INTEGER CHECK (target_minor > 0)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
