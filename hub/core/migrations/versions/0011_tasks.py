"""core.db : tâches planifiées relancées à la main depuis l'app.

`task_runs` garde, par tâche (`hub.backup`, `finance.strategies`…), la dernière demande faite
depuis l'app et le dernier passage : début, fin, issue et un résumé sans montant. L'app demande
(`requested_at`) ; le planificateur prend la demande dans la minute et lance la tâche comme la
nuit. `after_sources` : la demande attend que les actualisations des connexions soient finies
(« Tout actualiser » : les sources d'abord, puis les calculs).

`collector_state.force_requested_at` : une actualisation qui relit aussi ce que la connexion
garde d'habitude pour plus tard (les compositions des fonds, lues une fois par semaine).

# ledger-migration: reviewed

Revision ID: 0011_tasks
Revises: 0010_event_retries
Create Date: 2026-11-14
"""

from alembic import op

revision = "0011_tasks"
down_revision = "0010_event_retries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE task_runs (
          task          TEXT PRIMARY KEY,
          requested_at  TEXT,                   -- demandée depuis l'app, pas encore prise
          requested_by  TEXT,
          after_sources INTEGER NOT NULL DEFAULT 0,
          started_at    TEXT,
          ended_at      TEXT,
          outcome       TEXT CHECK (outcome IN ('ok','failed')),
          summary       TEXT                    -- quelques mots, jamais un montant
        )
        """
    )
    op.execute("ALTER TABLE collector_state ADD COLUMN force_requested_at TEXT")


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
