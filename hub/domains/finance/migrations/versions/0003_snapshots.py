"""finance.db : instantanés du patrimoine (ticket L2-01, section 2 de la spécification).

Les instantanés sont dérivés du registre : ils ne sont pas protégés, la tâche de nuit et
l'événement `import.applied` les recalculent en entier.

Revision ID: 0003_snapshots
Revises: 0002_fts
Create Date: 2026-10-27
"""

from alembic import op

revision = "0003_snapshots"
down_revision = "0002_fts"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE snapshots (
      on_date            TEXT PRIMARY KEY,
      net_worth_minor    INTEGER NOT NULL,        -- CHF, toutes enveloppes
      deposits_cum_minor INTEGER NOT NULL,        -- versements nets cumulés depuis l'origine
      by_envelope_json   TEXT NOT NULL,           -- {"cash": …, "pilier3a": …, "ibkr": …, …}
      computed_at        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE snapshot_state (                 -- consommateur de la boîte de sortie
      id           INTEGER PRIMARY KEY CHECK (id = 1),
      event_cursor INTEGER NOT NULL,              -- dernier events.seq lu
      entries_seq  INTEGER NOT NULL,              -- max(entries.seq) au dernier calcul
      as_of        TEXT NOT NULL,
      computed_at  TEXT NOT NULL
    )
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
