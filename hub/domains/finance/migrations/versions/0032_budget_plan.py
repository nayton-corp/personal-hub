"""finance.db : le plan du mois et les réglages des catégories (refonte du budget, lots A et Q).

- `plan_income` : les revenus attendus du mois tels que saisis, datés comme les cibles (la ligne
  la plus récente en vigueur au début du mois gagne) ; un montant NULL revient à la moyenne des
  revenus des trois derniers mois. En ajout seul.
- `categories.mode` : `target` (avec cible), `tracked` (suivie sans cible) ou `off_budget`
  (hors budget) ; NULL prend le mode par défaut du pack qui a créé la catégorie.
- `categories.icon` : une icône choisie (NULL : celle du pack) ; `categories.archived_at` :
  une catégorie archivée sort des listes et du classement, son historique reste.

Revision ID: 0032_budget_plan
Revises: 0031_fund_fee_origin
Create Date: 2026-11-17
"""

from __future__ import annotations

from alembic import op

revision = "0032_budget_plan"
down_revision = "0031_fund_fee_origin"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE plan_income (                        -- versionné : la ligne la plus récente gagne
      seq          INTEGER PRIMARY KEY,
      amount_minor INTEGER CHECK (amount_minor IS NULL OR amount_minor >= 0),
      currency     TEXT NOT NULL REFERENCES currencies(code),
      valid_from   TEXT NOT NULL,                     -- 'AAAA-MM-01'
      proposal_id  TEXT,
      created_at   TEXT NOT NULL
    )
    """,
    *(
        f"CREATE TRIGGER plan_income_no_{what} BEFORE {what.upper()} ON plan_income "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END"
        for what in ("update", "delete")
    ),
    "ALTER TABLE categories ADD COLUMN mode TEXT "
    "CHECK (mode IS NULL OR mode IN ('target', 'tracked', 'off_budget'))",
    "ALTER TABLE categories ADD COLUMN icon TEXT",
    "ALTER TABLE categories ADD COLUMN archived_at TEXT",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
