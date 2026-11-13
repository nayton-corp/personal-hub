"""finance.db : frais courants des fonds (TER), en ajout seul.

Le TER d'un fonds est publié par son émetteur, en % par an. Il se saisit par une proposition
(`set_fund_fee`) ; la dernière ligne posée pour un ISIN fait foi. Sans ligne, le fonds est dit
« frais inconnus » : rien n'est deviné.

Revision ID: 0029_fund_fees
Revises: 0028_goods
Create Date: 2026-11-13
"""

from __future__ import annotations

from alembic import op

revision = "0029_fund_fees"
down_revision = "0028_goods"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE fund_fees (                           -- frais courants, en ajout seul
      id          TEXT PRIMARY KEY,
      isin        TEXT NOT NULL,
      ter         TEXT NOT NULL,                       -- décimal par an : '0.002' pour 0,20 %
      source      TEXT NOT NULL CHECK (source IN ('user','issuer')),
      proposal_id TEXT,
      created_at  TEXT NOT NULL
    )
    """,
    "CREATE INDEX fund_fees_isin ON fund_fees(isin, created_at)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
