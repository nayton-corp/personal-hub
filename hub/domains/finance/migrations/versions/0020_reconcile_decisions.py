"""finance.db : décisions sur les ruptures du rapprochement.

Le rapprochement (patrimoine/app/reconcile.py) compare chaque jour les parts relevées d'un
compte à ses opérations connues ; un écart est une *rupture*, recalculée à chaque lecture, jamais
stockée. Ce qui se garde, c'est ta décision sur une rupture (docs/finance-politique.md) :

- `cost` : le prix de revient de parts sans historique (saisi), qui entrent alors à ce coût ;
- `accept` : garder tel quel (des parts au cours du jour de leur arrivée, une sortie non vue) ;
- `gone` : un envoi vers un portefeuille que le hub ne suit pas, marqué « parti ».

Une décision couvre des parts (`quantity`) ou les opérations jusqu'à une date (`on_date`) ; ce
qui arrive ensuite rouvre la rupture. Comme les dettes, la table est recopiée par la
reconstruction (rebuild.py).

Revision ID: 0020_reconcile_decisions
Revises: 0019_intraday_holdings
Create Date: 2026-11-02
"""

from alembic import op

revision = "0020_reconcile_decisions"
down_revision = "0019_intraday_holdings"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE reconcile_decisions (
      id           TEXT PRIMARY KEY,                 -- ULID
      account_id   TEXT NOT NULL REFERENCES accounts(id),
      asset        TEXT NOT NULL,                    -- instrument (`CRYPTO:BTC`, ISIN)
      break_kind   TEXT NOT NULL CHECK (break_kind IN
                     ('unexplained','sent_outside','arrived_outside','no_price','stale_price')),
      decision     TEXT NOT NULL CHECK (decision IN ('cost','accept','gone')),
      on_date      TEXT NOT NULL,                    -- arrivée des parts, ou fin de ce qui est couvert
      quantity     TEXT,                             -- parts couvertes (Decimal en texte)
      cost_minor   INTEGER CHECK (cost_minor >= 0),  -- prix de revient saisi (`cost`)
      currency     TEXT NOT NULL REFERENCES currencies(code),
      note         TEXT,
      created_at   TEXT NOT NULL,
      actor        TEXT NOT NULL
    )
    """,
    "CREATE INDEX reconcile_decisions_line ON reconcile_decisions(account_id, asset, break_kind)",
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
