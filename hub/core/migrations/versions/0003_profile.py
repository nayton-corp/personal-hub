"""core.db : profil de l'instance (chantier « hub générique », G1).

Une seule ligne : le prénom que l'assistant emploie et le pays, qui ouvre les modules propres
à un pays (le pilier 3a en Suisse). Une base existante reçoit la Suisse, sans prénom.

Revision ID: 0003_profile
Revises: 0002_collectors
Create Date: 2026-10-28
"""

from alembic import op

revision = "0003_profile"
down_revision = "0002_collectors"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE profile (
      id           INTEGER PRIMARY KEY CHECK (id = 1),
      display_name TEXT CHECK (display_name IS NULL OR length(display_name) BETWEEN 1 AND 60),
      country      TEXT NOT NULL DEFAULT 'CH' CHECK (length(country) = 2),  -- ISO 3166-1
      updated_at   TEXT NOT NULL
    )
    """,
    "INSERT INTO profile (id, country, updated_at) VALUES (1, 'CH', '2026-10-28T00:00:00.000Z')",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
