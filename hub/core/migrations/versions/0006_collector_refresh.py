"""core.db : actualisation demandée depuis l'app.

L'app demande un run complet d'une connexion (`run_requested_at`), hors de son horaire ; le
service collecteur qui l'exécute le prend dans la minute et l'efface en le déclarant.

Revision ID: 0006_collector_refresh
Revises: 0005_collector_link
Create Date: 2026-10-29
"""

from alembic import op

revision = "0006_collector_refresh"
down_revision = "0005_collector_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE collector_state ADD COLUMN run_requested_at TEXT")


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
