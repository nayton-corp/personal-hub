"""finance.db : VIAC et patrimoine minimal (lot 4).

Deux comptes par portefeuille VIAC (liquidités 3a et titres, référence externe
`viac:<portefeuille>:cash|titres`). Les avis d'opération deviennent des écritures, et les
achats et ventes des lignes de `trades` ; le rapport VIAC donne les positions relevées
(`holdings`) et les cours (`prices`). Ces trois tables sont en ajout seul et chaînées au
journal, comme le registre. `instruments` (noms des fonds) et `rebuild_meta` sont des
métadonnées.

Revision ID: 0005_viac
Revises: 0004_rules
Create Date: 2026-10-27
"""

from alembic import op

revision = "0005_viac"
down_revision = "0004_rules"
branch_labels = None
depends_on = None

PROTECTED = ("trades", "holdings", "prices")

STATEMENTS = [
    """
    CREATE TABLE instruments (                       -- fonds et titres, repris des documents
      isin        TEXT PRIMARY KEY CHECK (length(isin) = 12),
      name        TEXT NOT NULL,
      asset_class TEXT,                              -- 'Actions', 'Immobilier'… (rapport)
      sub_class   TEXT,                              -- 'Actions Suisse'…
      currency    TEXT,                              -- devise de cotation
      updated_at  TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE trades (                            -- achats (+) et ventes (−) de parts
      seq          INTEGER PRIMARY KEY,
      account_id   TEXT NOT NULL REFERENCES accounts(id),   -- compte titres
      trade_date   TEXT NOT NULL,                  -- date valeur de l'avis
      isin         TEXT NOT NULL,
      quantity     TEXT NOT NULL,                  -- Decimal signé, en texte
      amount_minor INTEGER NOT NULL,               -- montant comptabilisé, signé comme quantity
      currency     TEXT NOT NULL REFERENCES currencies(code),
      dedup_key    TEXT NOT NULL UNIQUE,
      import_id    TEXT REFERENCES imports(id),
      created_at   TEXT NOT NULL,
      hash_v       INTEGER NOT NULL
    )
    """,
    "CREATE INDEX trades_account_date ON trades(account_id, trade_date)",
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
      hash_v         INTEGER NOT NULL,
      UNIQUE (account_id, on_date, isin)
    )
    """,
    """
    CREATE TABLE prices (                            -- cours unitaires, dans `currency`
      seq        INTEGER PRIMARY KEY,
      isin       TEXT NOT NULL,
      on_date    TEXT NOT NULL,
      price      TEXT NOT NULL,                    -- Decimal, en texte
      currency   TEXT NOT NULL REFERENCES currencies(code),
      source     TEXT NOT NULL,                    -- 'viac_report', 'viac_notice'
      import_id  TEXT REFERENCES imports(id),
      created_at TEXT NOT NULL,
      hash_v     INTEGER NOT NULL,
      UNIQUE (isin, on_date, source)
    )
    """,
    """
    CREATE TABLE rebuild_meta (                      -- base reconstruite par rejeu
      id          INTEGER PRIMARY KEY CHECK (id = 1),
      epoch       INTEGER NOT NULL,                  -- époque du journal de cette base
      source_head TEXT NOT NULL,                     -- tête du journal de la base d'origine
      rebuilt_at  TEXT NOT NULL
    )
    """,
    """
    INSERT INTO categories (id, name, grp) VALUES
      ('transfer-titres', 'Achats et ventes de titres', 'transfer'),
      ('rendement', 'Rendement des placements', 'income'),
      ('frais-placement', 'Frais de placement', 'fixed')
    """,
    # règles système des écritures VIAC, reconnues par leur code (jamais désactivables)
    """
    INSERT INTO rules (id, field, pattern, category_id, priority, created_at) VALUES
      ('system-viac-deposit', 'bank_tx_code', 'VIAC/DEPOSIT', 'transfer-own', 0, '2026-10-27T00:00:00.000Z'),
      ('system-viac-withdrawal', 'bank_tx_code', 'VIAC/WITHDRAWAL', 'transfer-own', 0,
       '2026-10-27T00:00:00.000Z'),
      ('system-viac-trade', 'bank_tx_code', 'VIAC/TRADE', 'transfer-titres', 0, '2026-10-27T00:00:00.000Z'),
      ('system-viac-income', 'bank_tx_code', 'VIAC/INCOME', 'rendement', 0, '2026-10-27T00:00:00.000Z'),
      ('system-viac-fee', 'bank_tx_code', 'VIAC/FEE', 'frais-placement', 0, '2026-10-27T00:00:00.000Z')
    """,
    "UPDATE rules_meta SET version = version + 1",
]


def _append_only(table: str) -> list[str]:
    return [
        f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END",
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END",
    ]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    for table in PROTECTED:
        for trigger in _append_only(table):
            op.execute(trigger)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
