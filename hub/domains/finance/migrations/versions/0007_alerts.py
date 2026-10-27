"""finance.db : sentinelles (lot 7).

`alerts` garde chaque alerte levée par une sentinelle de nuit (budget qui va dépasser,
abonnement qui augmente, marge 3a pas encore versée). La clé identifie l'occasion (catégorie et
mois, abonnement et date du paiement) : une alerte n'est levée, et notifiée, qu'une fois. Table
dérivée et non protégée : elle se recalcule depuis le registre.

Revision ID: 0007_alerts
Revises: 0006_wealth
Create Date: 2026-10-27
"""

from alembic import op

revision = "0007_alerts"
down_revision = "0006_wealth"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE alerts (
      key          TEXT PRIMARY KEY,                 -- 'budget-likely:restaurants:2026-10'
      kind         TEXT NOT NULL CHECK (kind IN
                     ('budget_over','budget_likely','recurring_up','pillar3a_margin')),
      title        TEXT NOT NULL,                    -- texte de la notification, sans montant
      detail_json  TEXT NOT NULL DEFAULT '{}',       -- montants en centimes, pour l'app
      on_date      TEXT NOT NULL,                    -- jour civil de la levée
      created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX alerts_by_date ON alerts(on_date)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
