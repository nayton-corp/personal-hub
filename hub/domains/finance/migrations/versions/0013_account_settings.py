"""finance.db : réglages des comptes et du mois budgétaire dans l'app.

`accounts.availability` et `accounts.category` remplacent ce que l'app déduit du type de compte
(filtres « Disponibilité » et « Catégorie » du patrimoine) ; NULL garde la déduction.
`accounts.hidden` écarte un compte des écrans Patrimoine et Accueil sans rien effacer : ses
relevés continuent d'arriver et il reste au registre. `budget_period` (une ligne au plus) donne
le jour où commence le mois budgétaire, le 1er sans ligne (voir period.py).

Revision ID: 0013_account_settings
Revises: 0012_account_goal
Create Date: 2026-10-29
"""

from alembic import op

revision = "0013_account_settings"
down_revision = "0012_account_goal"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE accounts ADD COLUMN availability TEXT CHECK (availability IN "
    "('immediate','days','locked'))",
    "ALTER TABLE accounts ADD COLUMN category TEXT CHECK (category IN ('cash','funds','crypto'))",
    "ALTER TABLE accounts ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1))",
    """
    CREATE TABLE budget_period (
      id         INTEGER PRIMARY KEY CHECK (id = 1),
      start_day  INTEGER NOT NULL CHECK (start_day BETWEEN 1 AND 28),
      updated_at TEXT NOT NULL,
      actor      TEXT NOT NULL
    )
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
