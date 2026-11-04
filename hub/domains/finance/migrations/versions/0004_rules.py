"""finance.db : catégories reprises de `bcf_aggregate.py` (ticket L3-01).

Les catégories de l'ancien script qui manquaient sont ajoutées et trois noms sont alignés sur
ceux du script. Jusqu'au chantier « hub générique » (G2), cette révision installait aussi le
fichier de départ du script en règles « seed- » ; une base créée depuis reçoit ses règles des
packs (`hub/domains/finance/packs/`), une base plus ancienne garde les siennes.

Revision ID: 0004_rules
Revises: 0003_snapshots
Create Date: 2026-10-27
"""

from alembic import op
from sqlalchemy import text

revision = "0004_rules"
down_revision = "0003_snapshots"
branch_labels = None
depends_on = None

# les catégories de l'ancien script (identifiant, nom, groupe), figées ici : une migration ne
# lit pas le code vivant (la reprise est devenue `scripts/legacy_rules.py`, audit m10)
CATEGORIES = (
    ("logement", "Logement", "fixed"),
    ("assurances", "Assurances", "fixed"),
    ("impots", "Impôts", "fixed"),
    ("transports", "Transports", "variable"),
    ("abonnements", "Abonnements", "fixed"),
    ("alimentation", "Alimentation", "variable"),
    ("restaurants", "Restaurants et sorties", "variable"),
    ("loisirs", "Loisirs et sport", "variable"),
    ("sante", "Santé", "variable"),
    ("shopping", "Shopping", "variable"),
    ("voyages", "Vacances", "variable"),
    ("cadeaux", "Cadeaux et dons", "variable"),
    ("frais-bancaires", "Frais bancaires", "fixed"),
    ("retraits", "Retraits d'espèces", "variable"),
    ("soins", "Soins et beauté", "variable"),
    ("formation", "Formation et outils", "variable"),
    ("twint-particuliers", "TWINT entre particuliers", "variable"),
    ("virements-particuliers", "Virements à des particuliers", "variable"),
    ("a-qualifier", "Virements à qualifier", "variable"),
    ("salaire", "Salaire", "income"),
    ("remboursements", "Remboursements", "income"),
    ("autres-revenus", "Autres revenus", "income"),
    ("transfer-own", "Virement entre mes comptes", "transfer"),
    ("epargne-3a", "Pilier 3a", "savings"),
    ("investissements", "Investissements", "savings"),
    ("crypto", "Crypto", "savings"),
)
# comptes de l'ancien script, pas des catégories pour tout le monde
PERSONAL = frozenset({"transfer-revolut", "transfer-raiffeisen"})
RENAMED = {
    "restaurants": "Restaurants et sorties",
    "loisirs": "Loisirs et sport",
    "voyages": "Vacances",
}


def upgrade() -> None:
    conn = op.get_bind()
    for c_id, c_name, c_grp in CATEGORIES:
        if c_id in PERSONAL:
            continue
        conn.execute(
            text("INSERT OR IGNORE INTO categories (id, name, grp) VALUES (:i, :n, :g)"),
            {"i": c_id, "n": c_name, "g": c_grp},
        )
    for cid, name in RENAMED.items():
        conn.execute(text("UPDATE categories SET name = :n WHERE id = :i"), {"n": name, "i": cid})
    conn.execute(text("UPDATE rules_meta SET version = version + 1"))


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
