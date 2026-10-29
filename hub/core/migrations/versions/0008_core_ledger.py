"""core.db : le cœur applique ses propres propositions (chantier S9, liens).

Comme une base de domaine, `core.db` gagne le journal chaîné, `applied_proposals` et
`events`, en ajout seul : un lien validé s'y inscrit avec son effet.

Revision ID: 0008_core_ledger
Revises: 0007_token_expiry
Create Date: 2026-10-30
"""

from alembic import op

from hub.core import integrity

revision = "0008_core_ledger"
down_revision = "0007_token_expiry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in integrity.schema():
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
