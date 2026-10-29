"""finance.db : opérations des plateformes crypto au registre.

L'historique d'une plateforme lue par son API (Binance : dépôts, retraits, échanges,
récompenses) devient des écritures de son compte `crypto:<plateforme>`, codes `EXCHANGE/…`,
déclarés dans `institutions` ; règles système comme celles de SwissBorg.

Revision ID: 0015_exchange_journal
Revises: 0014_pockets
Create Date: 2026-10-29
"""

from alembic import op

revision = "0015_exchange_journal"
down_revision = "0014_pockets"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    INSERT INTO rules (id, field, pattern, category_id, priority, created_at) VALUES
      ('system-exchange-deposit', 'bank_tx_code', 'EXCHANGE/DEPOSIT', 'transfer-own', 0,
       '2026-10-29T00:00:00.000Z'),
      ('system-exchange-withdrawal', 'bank_tx_code', 'EXCHANGE/WITHDRAWAL', 'transfer-own', 0,
       '2026-10-29T00:00:00.000Z'),
      ('system-exchange-trade', 'bank_tx_code', 'EXCHANGE/TRADE', 'transfer-titres', 0,
       '2026-10-29T00:00:00.000Z'),
      ('system-exchange-income', 'bank_tx_code', 'EXCHANGE/INCOME', 'rendement', 0,
       '2026-10-29T00:00:00.000Z'),
      ('system-exchange-fee', 'bank_tx_code', 'EXCHANGE/FEE', 'frais-placement', 0,
       '2026-10-29T00:00:00.000Z')
    """,
    "UPDATE rules_meta SET version = version + 1",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
