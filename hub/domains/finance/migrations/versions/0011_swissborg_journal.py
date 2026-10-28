"""finance.db : opérations SwissBorg au registre.

Les lignes du relevé SwissBorg deviennent des écritures du compte `crypto:swissborg` (codes
`SWISSBORG/…`, déclarés dans `institutions`) : leurs règles système, comme celles d'IBKR.

Revision ID: 0011_swissborg_journal
Revises: 0010_base_currency
Create Date: 2026-10-28
"""

from alembic import op

revision = "0011_swissborg_journal"
down_revision = "0010_base_currency"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    INSERT INTO rules (id, field, pattern, category_id, priority, created_at) VALUES
      ('system-swissborg-deposit', 'bank_tx_code', 'SWISSBORG/DEPOSIT', 'transfer-own', 0,
       '2026-10-28T00:00:00.000Z'),
      ('system-swissborg-withdrawal', 'bank_tx_code', 'SWISSBORG/WITHDRAWAL', 'transfer-own', 0,
       '2026-10-28T00:00:00.000Z'),
      ('system-swissborg-trade', 'bank_tx_code', 'SWISSBORG/TRADE', 'transfer-titres', 0,
       '2026-10-28T00:00:00.000Z'),
      ('system-swissborg-income', 'bank_tx_code', 'SWISSBORG/INCOME', 'rendement', 0,
       '2026-10-28T00:00:00.000Z'),
      ('system-swissborg-fee', 'bank_tx_code', 'SWISSBORG/FEE', 'frais-placement', 0,
       '2026-10-28T00:00:00.000Z')
    """,
    "UPDATE rules_meta SET version = version + 1",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
