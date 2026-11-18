"""finance.db : les choix sur les abonnements repérés.

- `recurring_choices` : pour un abonnement de `recurring` (sa clé), le nom et la catégorie
  choisis (NULL : ceux repérés) et s'il est retiré (« ce n'est pas un abonnement »). Le dernier
  choix d'une clé fait foi ; `recurring` reste dérivé et recalculé en entier. En ajout seul.
- `v_recurring` : `recurring` avec ces choix appliqués, que lisent le budget et les alertes.

Revision ID: 0034_recurring_choices
Revises: 0033_budget_moves
Create Date: 2026-11-18
"""

from __future__ import annotations

from alembic import op

revision = "0034_recurring_choices"
down_revision = "0033_budget_moves"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE recurring_choices (
      seq          INTEGER PRIMARY KEY,
      key          TEXT NOT NULL,                     -- clé de `recurring`
      hidden       INTEGER NOT NULL CHECK (hidden IN (0, 1)),
      label        TEXT CHECK (label IS NULL OR length(label) BETWEEN 1 AND 80),
      category_id  TEXT REFERENCES categories(id),
      proposal_id  TEXT,
      created_at   TEXT NOT NULL
    )
    """,
    "CREATE INDEX recurring_choices_key ON recurring_choices (key, seq)",
    *(
        f"CREATE TRIGGER recurring_choices_no_{what} BEFORE {what.upper()} ON recurring_choices "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END"
        for what in ("update", "delete")
    ),
    """
    CREATE VIEW v_recurring AS
    SELECT r.key, r.account_id, COALESCE(c.label, r.label) AS label,
           COALESCE(c.category_id, r.category_id) AS category_id, r.cadence, r.amount_minor,
           r.last_minor, r.currency, r.occurrences, r.first_date, r.last_date, r.next_date,
           r.active, r.last_seq, COALESCE(c.hidden, 0) AS hidden, r.label AS found_label
    FROM recurring r
    LEFT JOIN recurring_choices c
      ON c.seq = (SELECT max(x.seq) FROM recurring_choices x WHERE x.key = r.key)
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
