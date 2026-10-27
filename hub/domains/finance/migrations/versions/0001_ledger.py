"""finance.db : registre en ajout seul, journal chaîné (spécification, section 2, revue incluse).

Revision ID: 0001_ledger
Revises:
Create Date: 2026-10-27
"""

from alembic import op

revision = "0001_ledger"
down_revision = None
branch_labels = None
depends_on = None

# tables couvertes par le journal chaîné et les déclencheurs d'ajout seul ; `journal` reçoit
# aussi les déclencheurs
PROTECTED = (
    "entries",
    "categorizations",
    "categorization_lines",
    "notes",
    "checkpoints",
    "budgets",
    "tags",
    "taggings",
    "applied_proposals",
    "events",
    "journal",
)

STATEMENTS = [
    """
    CREATE TABLE currencies (
      code     TEXT PRIMARY KEY CHECK (length(code) = 3),
      exponent INTEGER NOT NULL CHECK (exponent BETWEEN 0 AND 4)
    )
    """,
    """
    CREATE TABLE accounts (
      id             TEXT PRIMARY KEY,               -- ULID
      institution    TEXT NOT NULL,                  -- 'BCF', 'VIAC', 'IBKR'
      name           TEXT NOT NULL,
      kind           TEXT NOT NULL CHECK (kind IN ('cash','securities','pension','crypto')),
      currency       TEXT NOT NULL REFERENCES currencies(code),
      iban           TEXT UNIQUE,                    -- compact, majuscules ; NULL hors banque
      external_ref   TEXT UNIQUE,                    -- clé d'un compte sans IBAN
      liquid         INTEGER NOT NULL DEFAULT 0 CHECK (liquid IN (0, 1)),
      budget_account INTEGER NOT NULL DEFAULT 0 CHECK (budget_account IN (0, 1)),
      opened_on      TEXT,
      closed_on      TEXT,
      created_at     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE imports (
      id           TEXT PRIMARY KEY,                 -- ULID
      source       TEXT NOT NULL,                    -- 'camt053', 'viac_pdf', 'ibkr_flex'
      file_sha256  TEXT NOT NULL UNIQUE,             -- un fichier n'est jamais importé deux fois
      file_name    TEXT NOT NULL,
      received_at  TEXT NOT NULL,
      status       TEXT NOT NULL CHECK (status IN
                     ('staged','applied','rejected','needs_review','voided')),
      stats_json   TEXT NOT NULL DEFAULT '{}',       -- compteurs et motifs, jamais de contenu
      archive_path TEXT,                             -- fichier chiffré par age
      updated_at   TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE import_statements (                 -- un relevé d'un fichier ; une transaction
      import_id     TEXT NOT NULL REFERENCES imports(id),
      stmt_index    INTEGER NOT NULL,
      account_id    TEXT REFERENCES accounts(id),
      opbd_date     TEXT,
      clbd_date     TEXT,
      status        TEXT NOT NULL CHECK (status IN ('pending','applied','needs_review')),
      reasons_json  TEXT NOT NULL DEFAULT '[]',      -- anomalies en liste fermée
      new_entries   INTEGER NOT NULL DEFAULT 0,
      duplicates    INTEGER NOT NULL DEFAULT 0,
      updated_at    TEXT NOT NULL,
      PRIMARY KEY (import_id, stmt_index)
    )
    """,
    """
    CREATE TABLE entries (
      seq               INTEGER PRIMARY KEY,         -- ordre d'insertion
      id                TEXT NOT NULL UNIQUE,        -- déterministe, tiré de dedup_key
      account_id        TEXT NOT NULL REFERENCES accounts(id),
      kind              TEXT NOT NULL CHECK (kind IN ('movement','opening','correction')),
      booking_date      TEXT NOT NULL,
      value_date        TEXT,
      amount_minor      INTEGER NOT NULL,
      currency          TEXT NOT NULL REFERENCES currencies(code),
      counterparty      TEXT,
      counterparty_iban TEXT,
      label             TEXT NOT NULL DEFAULT '',
      remittance        TEXT NOT NULL DEFAULT '',    -- RmtInf / référence QR
      bank_ref          TEXT,                        -- AcctSvcrRef
      bank_tx_code      TEXT,                        -- 'PMNT/ICDT/ESCT'
      fx_json           TEXT,                        -- CcyXchg réel si la banque a changé
      search_text       TEXT NOT NULL,               -- normalize(counterparty + label + remittance)
      dedup_key         TEXT NOT NULL UNIQUE,
      corrects_seq      INTEGER REFERENCES entries(seq),
      import_id         TEXT REFERENCES imports(id),
      proposal_id       TEXT,                        -- pour une correction
      created_at        TEXT NOT NULL,
      hash_v            INTEGER NOT NULL,
      row_hash          TEXT NOT NULL,               -- sha256 du JSON canonique, selon hash_v
      CHECK ((kind = 'correction') = (corrects_seq IS NOT NULL))
    )
    """,
    "CREATE INDEX entries_account_date ON entries(account_id, booking_date)",
    "CREATE INDEX entries_date ON entries(booking_date)",
    """
    CREATE TABLE categories (
      id      TEXT PRIMARY KEY,                      -- slug stable : 'alimentation'
      name    TEXT NOT NULL,
      grp     TEXT NOT NULL CHECK (grp IN ('fixed','variable','savings','income','transfer')),
      active  INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
    )
    """,
    """
    CREATE TABLE rules (
      id          TEXT PRIMARY KEY,
      field       TEXT NOT NULL CHECK (field IN ('search_text','counterparty_iban','bank_tx_code',
                    'own_account')),
      pattern     TEXT NOT NULL,                     -- sous-chaîne normalisée, ou IBAN exact
      direction   TEXT NOT NULL DEFAULT 'any' CHECK (direction IN ('any','debit','credit')),
      category_id TEXT NOT NULL REFERENCES categories(id),
      priority    INTEGER NOT NULL DEFAULT 100,      -- plus petit = testé en premier
      active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
      proposal_id TEXT,
      created_at  TEXT NOT NULL
    )
    """,
    "CREATE TABLE rules_meta (version INTEGER NOT NULL)",
    """
    CREATE TABLE categorizations (
      seq         INTEGER PRIMARY KEY,
      entry_seq   INTEGER NOT NULL REFERENCES entries(seq),
      category_id TEXT NOT NULL REFERENCES categories(id),
      source      TEXT NOT NULL CHECK (source IN
                    ('rule','user','suggestion_accepted','suggestion_corrected')),
      rule_id     TEXT REFERENCES rules(id),
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      hash_v      INTEGER NOT NULL
    )
    """,
    "CREATE INDEX categorizations_entry ON categorizations(entry_seq, seq)",
    """
    CREATE TABLE categorization_lines (              -- ventilation d'une catégorisation
      categorization_seq INTEGER NOT NULL REFERENCES categorizations(seq),
      line               INTEGER NOT NULL,
      category_id        TEXT NOT NULL REFERENCES categories(id),
      amount_minor       INTEGER NOT NULL,
      hash_v             INTEGER NOT NULL,
      PRIMARY KEY (categorization_seq, line)
    )
    """,
    """
    CREATE TABLE notes (
      seq         INTEGER PRIMARY KEY,
      entry_seq   INTEGER NOT NULL REFERENCES entries(seq),
      text        TEXT NOT NULL,
      search_text TEXT NOT NULL,                     -- normalize(text), pour notes_fts
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      hash_v      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE checkpoints (                       -- soldes annoncés par la banque
      account_id   TEXT NOT NULL REFERENCES accounts(id),
      on_date      TEXT NOT NULL,
      kind         TEXT NOT NULL CHECK (kind IN ('OPBD','CLBD')),
      amount_minor INTEGER NOT NULL,
      import_id    TEXT NOT NULL REFERENCES imports(id),
      hash_v       INTEGER NOT NULL,
      PRIMARY KEY (account_id, on_date, kind)
    )
    """,
    """
    CREATE TABLE budgets (                           -- versionné : la ligne la plus récente gagne
      seq           INTEGER PRIMARY KEY,
      category_id   TEXT NOT NULL REFERENCES categories(id),
      monthly_minor INTEGER NOT NULL CHECK (monthly_minor >= 0),
      currency      TEXT NOT NULL DEFAULT 'CHF' REFERENCES currencies(code),
      valid_from    TEXT NOT NULL,
      proposal_id   TEXT,
      created_at    TEXT NOT NULL,
      hash_v        INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE tags (
      id         TEXT PRIMARY KEY,                   -- slug : 'voyage-japon-2027'
      name       TEXT NOT NULL,
      kind       TEXT NOT NULL CHECK (kind IN ('project','asset','other')),
      created_at TEXT NOT NULL,
      hash_v     INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE taggings (                          -- un retrait est une ligne active = 0
      seq         INTEGER PRIMARY KEY,
      entry_seq   INTEGER NOT NULL REFERENCES entries(seq),
      tag_id      TEXT NOT NULL REFERENCES tags(id),
      active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      hash_v      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE applied_proposals (                 -- fait foi : écrite avec l'effet
      proposal_id TEXT PRIMARY KEY,
      kind        TEXT NOT NULL,
      result_json TEXT NOT NULL,
      applied_at  TEXT NOT NULL,
      hash_v      INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE events (                            -- boîte de sortie, lue par curseur
      seq          INTEGER PRIMARY KEY,
      type         TEXT NOT NULL,                    -- 'import.applied', 'entries.appended'
      urn          TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',       -- identifiants et compteurs seulement
      created_at   TEXT NOT NULL,
      hash_v       INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE journal (
      seq        INTEGER PRIMARY KEY,
      tbl        TEXT NOT NULL,
      row_seq    INTEGER NOT NULL,                   -- rowid de la ligne
      row_hash   TEXT NOT NULL,                      -- selon le hash_v de la ligne
      epoch      INTEGER NOT NULL DEFAULT 1,         -- +1 à chaque reconstruction par rejeu
      prev_hash  TEXT NOT NULL,                      -- '0'*64 au début
      chain_hash TEXT NOT NULL,                      -- sha256(prev_hash|tbl|row_seq|row_hash)
      UNIQUE (tbl, row_seq)
    )
    """,
    """
    CREATE TABLE fx_rates (
      on_date TEXT NOT NULL, base TEXT NOT NULL, quote TEXT NOT NULL,
      rate    TEXT NOT NULL,                         -- Decimal : 1 base = rate quote
      source  TEXT NOT NULL,                         -- 'snb' ou 'ecb', choisi au lot 5
      PRIMARY KEY (on_date, base, quote, source)
    )
    """,
    """
    CREATE VIEW v_entry_category AS
    SELECT c.entry_seq, c.category_id, c.source, c.seq AS categorization_seq
    FROM categorizations c
    WHERE c.seq = (SELECT max(seq) FROM categorizations WHERE entry_seq = c.entry_seq)
    """,
    """
    CREATE VIEW v_entry_allocation AS
    SELECT e.seq AS entry_seq, e.booking_date, e.account_id, e.currency,
           coalesce(l.category_id, vc.category_id) AS category_id,
           coalesce(l.amount_minor, e.amount_minor) AS amount_minor
    FROM entries e
    LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq
    LEFT JOIN categorization_lines l ON l.categorization_seq = vc.categorization_seq
    """,
    """
    CREATE VIEW v_taggings AS
    SELECT t.entry_seq, t.tag_id
    FROM taggings t
    WHERE t.active = 1 AND t.seq = (SELECT max(seq) FROM taggings
                                   WHERE entry_seq = t.entry_seq AND tag_id = t.tag_id)
    """,
    """
    CREATE VIEW v_balances AS
    SELECT account_id, currency, sum(amount_minor) AS balance_minor,
           max(booking_date) AS last_booking
    FROM entries GROUP BY account_id, currency
    """,
    """
    INSERT INTO currencies (code, exponent) VALUES
      ('CHF', 2), ('EUR', 2), ('USD', 2), ('GBP', 2), ('JPY', 0)
    """,
    "INSERT INTO rules_meta (version) VALUES (1)",
    """
    INSERT INTO categories (id, name, grp) VALUES
      ('salaire', 'Salaire', 'income'),
      ('autres-revenus', 'Autres revenus', 'income'),
      ('logement', 'Logement', 'fixed'),
      ('assurances', 'Assurances', 'fixed'),
      ('impots', 'Impôts', 'fixed'),
      ('telecom', 'Téléphone et internet', 'fixed'),
      ('transports', 'Transports', 'variable'),
      ('alimentation', 'Alimentation', 'variable'),
      ('restaurants', 'Restaurants', 'variable'),
      ('sante', 'Santé', 'variable'),
      ('loisirs', 'Loisirs', 'variable'),
      ('shopping', 'Shopping', 'variable'),
      ('voyages', 'Voyages', 'variable'),
      ('divers', 'Divers', 'variable'),
      ('epargne-3a', 'Pilier 3a', 'savings'),
      ('investissements', 'Investissements', 'savings'),
      ('transfer-own', 'Virement entre mes comptes', 'transfer')
    """,
    # règle système (lot 1) : contrepartie dont l'IBAN est l'un de mes comptes
    """
    INSERT INTO rules (id, field, pattern, category_id, priority, created_at) VALUES
      ('system-transfer-own', 'own_account', '*', 'transfer-own', 0, '2026-10-27T00:00:00.000Z')
    """,
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
