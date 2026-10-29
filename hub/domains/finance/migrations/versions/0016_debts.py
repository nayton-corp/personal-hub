"""finance.db : dettes (crédit, hypothèque, leasing, prêt étudiant…).

Une dette n'est pas un compte du registre : aucun relevé n'en arrive (un prêt d'un particulier
n'a pas de connecteur). `debts` la décrit ; `debt_balances` garde les soldes constatés, celui
de l'ouverture puis ceux d'un relevé du prêteur. Le solde à une date part du dernier solde
constaté, gagne les intérêts courus au taux de la dette, et baisse de chaque paiement : les
écritures de la catégorie de la dette (`category_id`), depuis `account_id` s'il est donné
(voir debts.py). Le patrimoine retranche ce solde (enveloppe « dettes »).

Revision ID: 0016_debts
Revises: 0015_exchange_journal
Create Date: 2026-10-29
"""

from alembic import op

revision = "0016_debts"
down_revision = "0015_exchange_journal"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE debts (
      id            TEXT PRIMARY KEY,                -- ULID
      name          TEXT NOT NULL,                   -- 'Crédit voiture'
      lender        TEXT NOT NULL,                   -- prêteur : banque ou particulier
      kind          TEXT NOT NULL CHECK (kind IN
                      ('loan','mortgage','leasing','student','credit','other')),
      currency      TEXT NOT NULL REFERENCES currencies(code),
      original_minor INTEGER CHECK (original_minor > 0),   -- montant emprunté (progression)
      rate          TEXT,                            -- taux annuel, Decimal en texte ; NULL : 0
      payment_minor INTEGER CHECK (payment_minor > 0),     -- mensualité actuelle, facultative
      ends_on       TEXT,                            -- échéance du contrat, facultative
      category_id   TEXT REFERENCES categories(id),  -- paiements : écritures de cette catégorie
      account_id    TEXT REFERENCES accounts(id),    -- … depuis ce compte seulement
      closed_on     TEXT,                            -- soldée ou sortie du patrimoine
      created_at    TEXT NOT NULL,
      updated_at    TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE debt_balances (                     -- soldes constatés
      debt_id      TEXT NOT NULL REFERENCES debts(id),
      on_date      TEXT NOT NULL,                    -- solde au soir de cette date
      amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
      source       TEXT NOT NULL CHECK (source IN ('opening','statement')),
      entry_id     TEXT,                             -- écriture du versement reçu, s'il y en a une
      proposal_id  TEXT,
      created_at   TEXT NOT NULL,
      PRIMARY KEY (debt_id, on_date)
    )
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
