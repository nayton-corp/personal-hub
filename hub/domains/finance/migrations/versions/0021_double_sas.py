"""finance.db : tout passe par le Double Sas (audit du 2026-11-03, R2).

- `budget_period_rules` : le jour de début du mois budgétaire devient un réglage daté, posé
  par une proposition (`set_month_start`) ; une règle vaut pour les mois à partir de
  `valid_from` (« AAAA-MM »), la dernière posée sur un même mois l'emporte. Le réglage de
  `budget_period` est repris comme règle depuis toujours ; la table reste, plus rien ne l'écrit.
- `reconcile_decisions.proposal_id` et `reconcile_withdrawals` : une décision sur une rupture
  vient d'une proposition (`decide_break`) et se retire par une autre (ligne de retrait, rien
  d'effacé).
- `debt_balance_records` : les soldes constatés des dettes en ajout seul ; le dernier relevé
  d'un même jour fait foi. Les lignes de `debt_balances` sont reprises ; la table reste, plus
  rien ne l'écrit.

Revision ID: 0021_double_sas
Revises: 0020_reconcile_decisions
Create Date: 2026-11-03
"""

from alembic import op

revision = "0021_double_sas"
down_revision = "0020_reconcile_decisions"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE budget_period_rules (
      id          TEXT PRIMARY KEY,                     -- ULID
      valid_from  TEXT NOT NULL CHECK (length(valid_from) = 7),  -- premier mois couvert
      start_day   INTEGER NOT NULL CHECK (start_day BETWEEN 1 AND 28),
      created_at  TEXT NOT NULL,
      actor       TEXT NOT NULL,
      proposal_id TEXT
    )
    """,
    "INSERT INTO budget_period_rules (id, valid_from, start_day, created_at, actor) "
    "SELECT 'legacy-budget-period', '1900-01', start_day, updated_at, actor "
    "FROM budget_period WHERE start_day != 1",
    "ALTER TABLE reconcile_decisions ADD COLUMN proposal_id TEXT",
    """
    CREATE TABLE reconcile_withdrawals (
      decision_id TEXT PRIMARY KEY REFERENCES reconcile_decisions(id),
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      actor       TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE debt_balance_records (                 -- soldes constatés, en ajout seul
      id           TEXT PRIMARY KEY,
      debt_id      TEXT NOT NULL REFERENCES debts(id),
      on_date      TEXT NOT NULL,                       -- solde au soir de cette date
      amount_minor INTEGER NOT NULL CHECK (amount_minor >= 0),
      source       TEXT NOT NULL CHECK (source IN ('opening','statement')),
      entry_id     TEXT,                                -- écriture du versement reçu, s'il y en a une
      proposal_id  TEXT,
      created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX debt_balance_records_day ON debt_balance_records(debt_id, on_date)",
    "INSERT INTO debt_balance_records (id, debt_id, on_date, amount_minor, source, entry_id, "
    "proposal_id, created_at) SELECT 'legacy|' || debt_id || '|' || on_date, debt_id, on_date, "
    "amount_minor, source, entry_id, proposal_id, created_at FROM debt_balances",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
