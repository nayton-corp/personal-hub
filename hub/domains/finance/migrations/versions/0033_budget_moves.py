"""finance.db : les déplacements de budget d'un mois (refonte du budget, lot D).

- `budget_moves` : un montant pris sur la cible d'une catégorie et mis sur une autre, pour un
  seul mois (`month`, 'AAAA-MM'). La somme des cibles du mois ne change pas ; le mois suivant
  repart des cibles saisies. Annuler un déplacement en ajoute un en sens inverse. En ajout seul.

Revision ID: 0033_budget_moves
Revises: 0032_budget_plan
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0033_budget_moves"
down_revision = "0032_budget_plan"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE budget_moves (
      seq           INTEGER PRIMARY KEY,
      month         TEXT NOT NULL,                     -- 'AAAA-MM'
      from_category TEXT NOT NULL REFERENCES categories(id),
      to_category   TEXT NOT NULL REFERENCES categories(id),
      amount_minor  INTEGER NOT NULL CHECK (amount_minor > 0),
      currency      TEXT NOT NULL REFERENCES currencies(code),
      proposal_id   TEXT,
      created_at    TEXT NOT NULL,
      CHECK (from_category <> to_category)
    )
    """,
    "CREATE INDEX budget_moves_month ON budget_moves (month)",
    *(
        f"CREATE TRIGGER budget_moves_no_{what} BEFORE {what.upper()} ON budget_moves "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END"
        for what in ("update", "delete")
    ),
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
