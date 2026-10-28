"""core.db : consentement Enable Banking demandé depuis l'app (chantier « hub générique », G5).

L'app demande une liaison (`link_requested_at`) ; le service `collector-api` la prend dans la
minute, ouvre l'autorisation chez Enable Banking et remonte l'adresse à ouvrir (`link_url`),
que l'app affiche pendant quelques minutes. Le retour passe ensuite par `collector_links`.

Revision ID: 0005_collector_link
Revises: 0004_connections
Create Date: 2026-10-28
"""

from alembic import op

revision = "0005_collector_link"
down_revision = "0004_connections"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE collector_state ADD COLUMN link_requested_at TEXT",
    "ALTER TABLE collector_state ADD COLUMN link_url TEXT",
    "ALTER TABLE collector_state ADD COLUMN link_url_at TEXT",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
