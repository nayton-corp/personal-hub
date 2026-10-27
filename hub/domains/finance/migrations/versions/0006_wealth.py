"""finance.db : patrimoine complet (lot 6).

- `instruments` accepte d'autres clés qu'un ISIN : `CRYPTO:BTC` pour une crypto,
  `IBKR:<conid>` pour un titre IBKR sans ISIN, `SYM:<symbole>` pour une position saisie à la
  main. Elle gagne le type d'instrument et les symboles des fournisseurs de cours.
- `compositions` : la transparence des fonds (région, secteur, devise, lignes principales),
  reprise des fichiers des émetteurs ; une métadonnée, remplacée à chaque fichier plus récent.
- `transfer_links` et `recurring` sont dérivés du registre (virements appariés, abonnements) et
  recalculés en entier avec les instantanés, comme `snapshots`.
- `v_entry_allocation` : une écriture sans catégorie mais appariée à son autre côté compte comme
  un virement entre mes comptes.
- Devises : quelques devises de courtage de plus ; règles système des écritures IBKR.

Revision ID: 0006_wealth
Revises: 0005_viac
Create Date: 2026-10-27
"""

# ledger-migration: reviewed (DROP TABLE de `instruments_old` et de la vue, tables non protégées)

from alembic import op

revision = "0006_wealth"
down_revision = "0005_viac"
branch_labels = None
depends_on = None

STATEMENTS = [
    "ALTER TABLE instruments RENAME TO instruments_old",
    """
    CREATE TABLE instruments (                       -- fonds, titres et cryptos
      isin        TEXT PRIMARY KEY CHECK (length(isin) BETWEEN 3 AND 40),  -- ISIN ou clé typée
      name        TEXT NOT NULL,
      asset_class TEXT,                              -- 'Actions', 'Immobilier'… (rapport)
      sub_class   TEXT,                              -- 'Actions Suisse'…
      currency    TEXT,                              -- devise de cotation
      kind        TEXT NOT NULL DEFAULT 'fund' CHECK (kind IN
                    ('fund','etf','stock','bond','crypto','other')),
      symbol      TEXT,                              -- 'VT', 'BTC'
      quote_ref   TEXT,                              -- symbole chez le fournisseur de cours
      updated_at  TEXT NOT NULL
    )
    """,
    """
    INSERT INTO instruments (isin, name, asset_class, sub_class, currency, kind, updated_at)
    SELECT isin, name, asset_class, sub_class, currency, 'fund', updated_at FROM instruments_old
    """,
    "DROP TABLE instruments_old",
    """
    CREATE TABLE compositions (                      -- transparence d'un fonds, par dimension
      isin      TEXT NOT NULL,
      dimension TEXT NOT NULL CHECK (dimension IN ('region','sector','currency','holding')),
      bucket    TEXT NOT NULL,                       -- 'Amérique du Nord', 'Technologie', 'USD'
      weight    TEXT NOT NULL,                       -- Decimal entre 0 et 1, en texte
      on_date   TEXT NOT NULL,                       -- date de la composition publiée
      import_id TEXT REFERENCES imports(id),
      PRIMARY KEY (isin, dimension, bucket)
    )
    """,
    """
    CREATE TABLE transfer_links (                    -- virements appariés (dérivé)
      debit_seq   INTEGER PRIMARY KEY REFERENCES entries(seq),
      credit_seq  INTEGER NOT NULL UNIQUE REFERENCES entries(seq),
      method      TEXT NOT NULL CHECK (method IN ('iban','code','amount')),
      days        INTEGER NOT NULL,                  -- écart entre les deux dates
      computed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE recurring (                         -- abonnements et paiements réguliers (dérivé)
      key           TEXT PRIMARY KEY,                -- contrepartie normalisée
      account_id    TEXT NOT NULL REFERENCES accounts(id),
      label         TEXT NOT NULL,
      category_id   TEXT REFERENCES categories(id),
      cadence       TEXT NOT NULL CHECK (cadence IN
                      ('weekly','monthly','quarterly','semiannual','yearly')),
      amount_minor  INTEGER NOT NULL,                -- montant habituel (médiane), négatif
      last_minor    INTEGER NOT NULL,                -- dernier montant payé
      currency      TEXT NOT NULL REFERENCES currencies(code),
      occurrences   INTEGER NOT NULL,
      first_date    TEXT NOT NULL,
      last_date     TEXT NOT NULL,
      next_date     TEXT NOT NULL,
      active        INTEGER NOT NULL CHECK (active IN (0, 1)),
      last_seq      INTEGER NOT NULL REFERENCES entries(seq),
      computed_at   TEXT NOT NULL
    )
    """,
    "DROP VIEW v_entry_allocation",
    """
    CREATE VIEW v_entry_allocation AS
    SELECT e.seq AS entry_seq, e.booking_date, e.account_id, e.currency,
           coalesce(l.category_id, vc.category_id,
                    CASE WHEN tl.debit_seq IS NOT NULL OR tc.credit_seq IS NOT NULL
                         THEN 'transfer-own' END) AS category_id,
           coalesce(l.amount_minor, e.amount_minor) AS amount_minor
    FROM entries e
    LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq
    LEFT JOIN categorization_lines l ON l.categorization_seq = vc.categorization_seq
    LEFT JOIN transfer_links tl ON tl.debit_seq = e.seq
    LEFT JOIN transfer_links tc ON tc.credit_seq = e.seq
    """,
    """
    INSERT INTO currencies (code, exponent) VALUES
      ('AUD', 2), ('CAD', 2), ('CZK', 2), ('DKK', 2), ('HKD', 2), ('NOK', 2), ('PLN', 2),
      ('SEK', 2), ('SGD', 2)
    """,
    # règles système des écritures IBKR, reconnues par leur code (préfixe)
    """
    INSERT INTO rules (id, field, pattern, category_id, priority, created_at) VALUES
      ('system-ibkr-deposit', 'bank_tx_code', 'IBKR/DEPOSIT', 'transfer-own', 0,
       '2026-10-27T00:00:00.000Z'),
      ('system-ibkr-trade', 'bank_tx_code', 'IBKR/TRADE', 'transfer-titres', 0,
       '2026-10-27T00:00:00.000Z'),
      ('system-ibkr-fx', 'bank_tx_code', 'IBKR/FX', 'transfer-own', 0, '2026-10-27T00:00:00.000Z'),
      ('system-ibkr-income', 'bank_tx_code', 'IBKR/INCOME', 'rendement', 0,
       '2026-10-27T00:00:00.000Z'),
      ('system-ibkr-fee', 'bank_tx_code', 'IBKR/FEE', 'frais-placement', 0,
       '2026-10-27T00:00:00.000Z')
    """,
    "UPDATE rules_meta SET version = version + 1",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
