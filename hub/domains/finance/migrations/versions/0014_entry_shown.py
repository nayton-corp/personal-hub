"""finance.db : un virement apparié passe avant la règle « tout le reste ».

Les règles « tout le reste » (motif vide, comme « tout crédit restant → Autres revenus »)
catégorisent à l'import, avant l'appariement des virements : le versement vers une poche Revolut
devenait un revenu. `v_entry_shown` donne la catégorie affichée : celle du registre, sauf pour un
côté de virement apparié qui n'a pas de catégorie ou n'a que celle d'une règle « tout le reste »,
montré comme « Virement entre mes comptes » (source `transfer`). Une catégorie choisie ou posée
par une règle précise reste la sienne. `v_entry_allocation` (budget, flux) suit cette vue.

Revision ID: 0014_entry_shown
Revises: 0013_account_settings
Create Date: 2026-10-29
"""

from alembic import op

revision = "0014_entry_shown"
down_revision = "0013_account_settings"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE VIEW v_entry_shown AS
    SELECT e.seq AS entry_seq,
           CASE WHEN o.seq IS NOT NULL THEN 'transfer-own' ELSE vc.category_id END AS category_id,
           CASE WHEN o.seq IS NOT NULL THEN 'transfer' ELSE vc.source END AS source,
           CASE WHEN o.seq IS NOT NULL THEN NULL ELSE vc.categorization_seq END
             AS categorization_seq
    FROM entries e
    LEFT JOIN v_entry_category vc ON vc.entry_seq = e.seq
    LEFT JOIN (
      SELECT p.seq FROM (
        SELECT debit_seq AS seq FROM transfer_links UNION SELECT credit_seq FROM transfer_links
      ) p
      LEFT JOIN v_entry_category pc ON pc.entry_seq = p.seq
      LEFT JOIN categorizations c ON c.seq = pc.categorization_seq
      LEFT JOIN rules r ON r.id = c.rule_id
      WHERE pc.category_id IS NULL
         OR (pc.source = 'rule' AND r.field = 'search_text' AND trim(r.pattern) = '')
    ) o ON o.seq = e.seq
    """,
    "DROP VIEW v_entry_allocation",
    """
    CREATE VIEW v_entry_allocation AS
    SELECT e.seq AS entry_seq, e.booking_date, e.account_id, e.currency,
           coalesce(l.category_id, vs.category_id) AS category_id,
           coalesce(l.amount_minor, e.amount_minor) AS amount_minor
    FROM entries e
    LEFT JOIN v_entry_shown vs ON vs.entry_seq = e.seq
    LEFT JOIN categorization_lines l ON l.categorization_seq = vs.categorization_seq
    """,
]


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
