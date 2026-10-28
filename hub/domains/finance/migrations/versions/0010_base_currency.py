"""finance.db : devise de base de l'instance (chantier « hub générique », G1b).

Le patrimoine, les instantanés, les budgets et les cours de change sont tenus dans une devise
de base. Elle vient de `HUB_CURRENCY` à la création de la base et n'en change plus : les
instantanés et les cours déjà enregistrés ne se convertissent pas. Une base qui a déjà des
écritures a été tenue en CHF, la seule devise de base avant cette révision.

Revision ID: 0010_base_currency
Revises: 0009_rule_packs
Create Date: 2026-10-28
"""

import sqlalchemy as sa
from alembic import op

from hub.core.money import DEFAULT_BASE, base_currency

revision = "0010_base_currency"
down_revision = "0009_rule_packs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE base_currency (                 -- une ligne, fixée à la création
          id   INTEGER PRIMARY KEY CHECK (id = 1),
          code TEXT NOT NULL REFERENCES currencies(code)
        )
        """
    )
    conn = op.get_bind()
    used = conn.execute(sa.text("SELECT 1 FROM entries LIMIT 1")).first() is not None
    conn.execute(
        sa.text("INSERT INTO base_currency (id, code) VALUES (1, :c)"),
        {"c": DEFAULT_BASE if used else base_currency()},
    )


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
