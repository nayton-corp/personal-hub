"""core.db : collecteurs (lot 5, spécification section 8).

Les runs se distinguent en collecte et contrôle ; l'app peut demander un contrôle ; la liaison
Revolut (Enable Banking) attend le code de retour dans `collector_links`, quelques minutes.

Revision ID: 0002_collectors
Revises: 0001_core_init
Create Date: 2026-10-27
"""

from alembic import op

revision = "0002_collectors"
down_revision = "0001_core_init"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE collector_runs ADD COLUMN kind TEXT NOT NULL DEFAULT 'run' "
    "CHECK (kind IN ('run','check'))",
    "CREATE INDEX collector_runs_by_collector ON collector_runs(collector, started_at)",
    "ALTER TABLE collector_state ADD COLUMN check_requested_at TEXT",
    """
    CREATE TABLE collector_links (                   -- consentement en cours (Revolut)
      state       TEXT PRIMARY KEY,                  -- aléatoire, posé par le collecteur
      collector   TEXT NOT NULL,
      created_at  TEXT NOT NULL,
      expires_at  TEXT NOT NULL,
      code        TEXT,                              -- rendu une seule fois au collecteur
      received_at TEXT
    )
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
