"""core.db : chaque jeton a une date de fin (chantier S8).

`expires_at` est obligatoire à la création ; les jetons d'avant reçoivent un an depuis leur
création. `warned_at` note l'alerte envoyée 14 jours avant la fin, pour ne l'envoyer qu'une fois.

Revision ID: 0007_token_expiry
Revises: 0006_collector_refresh
Create Date: 2026-10-29
"""

from alembic import op

revision = "0007_token_expiry"
down_revision = "0006_collector_refresh"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tokens ADD COLUMN expires_at TEXT")
    op.execute("ALTER TABLE tokens ADD COLUMN warned_at TEXT")
    op.execute(
        "UPDATE tokens SET expires_at = strftime('%Y-%m-%dT%H:%M:%fZ', created_at, '+365 days') "
        "WHERE expires_at IS NULL"
    )


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
