"""finance.db : ce qu'une source n'a pas pu lire (audit M15). `source_gaps` garde, par compte
et par flux d'un collecteur, la fenêtre refusée par la plateforme (Binance : une fenêtre trop
ancienne pour ce flux, une paire retirée) ; le rapprochement la montre comme une rupture
« historique non lu » (`source_gap`), que l'on règle d'un geste (« garder tel quel ») ou en
important l'export de la plateforme. Une décision `source_gap` entre dans
`reconcile_decisions`, dont la contrainte s'élargit (rebâtie ligne pour ligne).

Revision ID: 0024_source_gaps
Revises: 0023_budget_cadence
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "0024_source_gaps"
down_revision = "0023_budget_cadence"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE source_gaps (
      account_id  TEXT NOT NULL REFERENCES accounts(id),
      step        TEXT NOT NULL,                     -- flux du collecteur : fiat, trades:BTCBUSD
      from_date   TEXT NOT NULL,
      to_date     TEXT NOT NULL,
      reason      TEXT NOT NULL,                     -- refused, delisted
      seen_at     TEXT NOT NULL,                     -- dernier passage qui l'a dit
      PRIMARY KEY (account_id, step, from_date)
    )
    """,
    # ledger-migration: reviewed — reconcile_decisions n'est pas un registre : recopiée ligne
    # pour ligne (SQLite ne sait pas élargir une contrainte CHECK autrement) ; les retraits,
    # qui la référencent, sont mis de côté le temps du rebâti et remis tels quels
    "CREATE TEMP TABLE withdrawals_kept AS SELECT * FROM reconcile_withdrawals",
    "DELETE FROM reconcile_withdrawals",
    """
    CREATE TABLE reconcile_decisions_v3 (
      id           TEXT PRIMARY KEY,                 -- ULID
      account_id   TEXT NOT NULL REFERENCES accounts(id),
      asset        TEXT NOT NULL,                    -- instrument, devise, ou flux (`source_gap`)
      break_kind   TEXT NOT NULL CHECK (break_kind IN ('unexplained','sent_outside',
                     'arrived_outside','no_price','stale_price','stale_fx','source_gap')),
      decision     TEXT NOT NULL CHECK (decision IN ('cost','accept','gone')),
      on_date      TEXT NOT NULL,                    -- arrivée des parts, ou fin de ce qui est couvert
      quantity     TEXT,                             -- parts couvertes (Decimal en texte)
      cost_minor   INTEGER CHECK (cost_minor >= 0),  -- prix de revient saisi (`cost`)
      currency     TEXT NOT NULL REFERENCES currencies(code),
      note         TEXT,
      created_at   TEXT NOT NULL,
      actor        TEXT NOT NULL,
      proposal_id  TEXT
    )
    """,
    "INSERT INTO reconcile_decisions_v3 (id, account_id, asset, break_kind, decision, on_date, "
    "quantity, cost_minor, currency, note, created_at, actor, proposal_id) SELECT id, "
    "account_id, asset, break_kind, decision, on_date, quantity, cost_minor, currency, note, "
    "created_at, actor, proposal_id FROM reconcile_decisions ORDER BY created_at, id",
    "DROP INDEX reconcile_decisions_line",
    "DROP TABLE reconcile_decisions",
    "ALTER TABLE reconcile_decisions_v3 RENAME TO reconcile_decisions",
    "CREATE INDEX reconcile_decisions_line ON reconcile_decisions(account_id, asset, break_kind)",
    "INSERT INTO reconcile_withdrawals (decision_id, proposal_id, created_at, actor) "
    "SELECT decision_id, proposal_id, created_at, actor FROM withdrawals_kept",
    "DROP TABLE withdrawals_kept",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
