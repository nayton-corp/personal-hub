"""finance.db : plusieurs relevés de positions le même jour.

`holdings` perd sa contrainte UNIQUE (compte, date, instrument) : un solde crypto relevé une
deuxième fois dans la journée (« Actualiser », les passages de 4 h) ajoute une ligne quand il a
bougé, au lieu d'attendre le lendemain. À date égale, la ligne la plus récente (`seq`) fait foi.

La table est recréée à l'identique, lignes et `seq` compris (le journal pointe sur `seq` et les
empreintes ne changent pas), avec ses deux déclencheurs d'ajout seul et un index de lecture.

Revision ID: 0019_intraday_holdings
Revises: 0018_account_target
Create Date: 2026-10-31
"""

# ledger-migration: reviewed (DROP TABLE de `holdings_old` après copie ligne à ligne, seq gardés)

from alembic import op

from hub.core.integrity import append_only

revision = "0019_intraday_holdings"
down_revision = "0018_account_target"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE holdings RENAME TO holdings_old",
    """
    CREATE TABLE holdings (                          -- positions relevées par un rapport
      seq            INTEGER PRIMARY KEY,
      account_id     TEXT NOT NULL REFERENCES accounts(id),
      on_date        TEXT NOT NULL,
      isin           TEXT NOT NULL,
      quantity       TEXT NOT NULL,                -- Decimal, en texte
      value_minor    INTEGER NOT NULL,             -- valeur annoncée, dans `currency`
      currency       TEXT NOT NULL REFERENCES currencies(code),
      cost_price     TEXT,                         -- prix initial unitaire (devise de cotation)
      import_id      TEXT NOT NULL REFERENCES imports(id),
      created_at     TEXT NOT NULL,
      hash_v         INTEGER NOT NULL
    )
    """,
    """
    INSERT INTO holdings (seq, account_id, on_date, isin, quantity, value_minor, currency,
                          cost_price, import_id, created_at, hash_v)
    SELECT seq, account_id, on_date, isin, quantity, value_minor, currency,
           cost_price, import_id, created_at, hash_v
    FROM holdings_old ORDER BY seq
    """,
    "DROP TABLE holdings_old",
    "CREATE INDEX holdings_account_day ON holdings(account_id, on_date, isin, seq)",
    *append_only("holdings"),
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
