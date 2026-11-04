"""finance.db : le modèle canonique des mouvements crypto (audit C1, R5).

- `crypto_moves` : la jambe crypto d'une écriture (rôle, actif, parts, txid…), écrite une fois
  par la source ; reprise depuis le détail `fx_json` des écritures des comptes crypto, qui garde
  son seul rôle de change.
- `crypto_links` : l'autre côté d'un mouvement (virement entre mes comptes, mise ou sortie de
  staking), écrit une fois : à l'import (même txid, même quantité, marque de la source), par une
  proposition validée (`link_crypto_moves`), ou ici même, une seule fois, par les anciennes
  règles de lecture (envoi et arrivée à quelques jours et frais de retrait près ; sortie de
  staking reliée au claim qui la suit dans les 60 jours). Plus jamais devinées à la lecture :
  les cas nouveaux deviennent des cartes « À valider ».
- `crypto_link_withdrawals` : un lien se retire par une ligne de retrait, rien d'effacé.

Revision ID: 0022_crypto_moves
Revises: 0021_double_sas
Create Date: 2026-11-04
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from alembic import op
from sqlalchemy import text

revision = "0022_crypto_moves"
down_revision = "0021_double_sas"
branch_labels = None
depends_on = None

STATEMENTS = [
    """
    CREATE TABLE crypto_moves (                      -- la jambe crypto d'une écriture
      entry_seq  INTEGER PRIMARY KEY REFERENCES entries(seq),
      role       TEXT NOT NULL CHECK (role IN ('trade','income','fee','in','out')),
      asset      TEXT NOT NULL,                      -- symbole (BTC) ou monnaie chez la plateforme
      quantity   TEXT NOT NULL,                      -- parts signées, décimal en texte
      txid       TEXT,
      address    TEXT,
      network    TEXT,
      usd        TEXT,                               -- contre-valeur en dollars donnée par la source
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE crypto_links (                      -- l'autre côté d'un mouvement, écrit une fois
      id          TEXT PRIMARY KEY,
      entry_seq   INTEGER NOT NULL REFERENCES crypto_moves(entry_seq),
      kind        TEXT NOT NULL CHECK (kind IN ('transfer','stake')),
      peer_seq    INTEGER REFERENCES crypto_moves(entry_seq),
      method      TEXT NOT NULL CHECK (method IN ('txid','quantity','source','window','claim')),
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      actor       TEXT NOT NULL
    )
    """,
    "CREATE INDEX crypto_links_entry ON crypto_links(entry_seq)",
    "CREATE INDEX crypto_links_peer ON crypto_links(peer_seq)",
    """
    CREATE TABLE crypto_link_withdrawals (
      link_id     TEXT PRIMARY KEY REFERENCES crypto_links(id),
      proposal_id TEXT,
      created_at  TEXT NOT NULL,
      actor       TEXT NOT NULL
    )
    """,
    *(
        f"CREATE TRIGGER {table}_no_{what} BEFORE {what.upper()} ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'ledger.append_only'); END"
        for table in ("crypto_moves", "crypto_links", "crypto_link_withdrawals")
        for what in ("update", "delete")
    ),
    # reprise des jambes crypto depuis le détail des écritures des comptes crypto
    """
    INSERT INTO crypto_moves (entry_seq, role, asset, quantity, txid, address, network, usd,
                              created_at)
    SELECT e.seq,
           CASE WHEN e.bank_tx_code LIKE '%/TRADE%' THEN 'trade'
                WHEN e.bank_tx_code LIKE '%/INCOME%' THEN 'income'
                WHEN e.bank_tx_code LIKE '%/FEE%' THEN 'fee'
                WHEN e.bank_tx_code LIKE '%/DEPOSIT' OR e.bank_tx_code = 'CRYPTO/RECEIVE' THEN 'in'
                ELSE 'out' END,
           upper(json_extract(e.fx_json, '$.currency')),
           json_extract(e.fx_json, '$.quantity'),
           json_extract(e.fx_json, '$.txid'),
           json_extract(e.fx_json, '$.address'),
           json_extract(e.fx_json, '$.network'),
           json_extract(e.fx_json, '$.usd'),
           e.created_at
    FROM entries e JOIN accounts a ON a.id = e.account_id
    WHERE a.kind = 'crypto' AND e.fx_json IS NOT NULL
      AND json_extract(e.fx_json, '$.currency') IS NOT NULL
      AND json_extract(e.fx_json, '$.quantity') IS NOT NULL
      AND (e.bank_tx_code LIKE '%/TRADE%' OR e.bank_tx_code LIKE '%/INCOME%'
           OR e.bank_tx_code LIKE '%/FEE%' OR e.bank_tx_code LIKE '%/DEPOSIT'
           OR e.bank_tx_code = 'CRYPTO/RECEIVE' OR e.bank_tx_code LIKE '%/WITHDRAWAL'
           OR e.bank_tx_code = 'CRYPTO/SEND')
    """,
    # l'autre côté relevé à l'import (`peer`), la marque de staking de la source (`stake`)
    """
    INSERT INTO crypto_links (id, entry_seq, kind, peer_seq, method, created_at, actor)
    SELECT 'legacy|transfer|' || e.seq, e.seq, 'transfer',
           CAST(json_extract(e.fx_json, '$.peer') AS INTEGER), 'quantity', e.created_at,
           'migration:0022'
    FROM entries e JOIN crypto_moves m ON m.entry_seq = e.seq
    WHERE json_extract(e.fx_json, '$.peer') IS NOT NULL
      AND CAST(json_extract(e.fx_json, '$.peer') AS INTEGER) IN (SELECT entry_seq FROM crypto_moves)
    """,
    """
    INSERT INTO crypto_links (id, entry_seq, kind, peer_seq, method, created_at, actor)
    SELECT 'legacy|stake|' || e.seq, e.seq, 'stake', NULL, 'source', e.created_at,
           'migration:0022'
    FROM entries e JOIN crypto_moves m ON m.entry_seq = e.seq
    WHERE json_extract(e.fx_json, '$.stake') IS NOT NULL AND m.role IN ('in', 'out')
    """,
]

# les anciennes règles de lecture (crypto_cost.py avant R5), appliquées une seule fois
WINDOW_DAYS = 5
SLACK_DAYS = 1
TRANSFER_FEE = Decimal("0.05")
STAKE_DAYS = 60
STAKE_GAIN = Decimal("1.25")
FIAT = {"CHF", "EUR", "USD", "GBP", "JPY", "CAD", "AUD", "SGD", "HKD", "SEK", "NOK", "DKK"}

Leg = tuple[
    int, str, str, str, Decimal, bool, str
]  # seq, jour, rôle, actif, parts, interne, compte


def _legs(conn: object) -> list[Leg]:
    rows = conn.execute(  # type: ignore[attr-defined]
        text(
            "SELECT m.entry_seq, e.booking_date, m.role, m.asset, m.quantity, e.account_id, "
            "EXISTS (SELECT 1 FROM crypto_links l WHERE l.entry_seq = m.entry_seq "
            "OR l.peer_seq = m.entry_seq), "
            "EXISTS (SELECT 1 FROM crypto_links l WHERE l.kind = 'stake' "
            "AND (l.entry_seq = m.entry_seq OR l.peer_seq = m.entry_seq)) "
            "FROM crypto_moves m JOIN entries e ON e.seq = m.entry_seq "
            "ORDER BY e.booking_date, e.seq"
        )
    ).fetchall()
    out: list[Leg] = []
    for seq, on, role, asset, qty, account, linked, stake in rows:
        if asset in FIAT:
            continue
        try:
            q = Decimal(str(qty))
        except ArithmeticError:
            continue
        if not q:
            continue
        kind = "stake" if stake and role in ("in", "out") else role
        out.append((int(seq), str(on), kind, str(asset), q, bool(linked), str(account)))
    return out


def _staking_exits(legs: list[Leg]) -> list[tuple[int, int]]:
    """(envoi, claim) : une sortie de staking sans marque reliée au claim qui la suit."""
    found = []
    out = list(legs)
    for i, (seq, on, kind, symbol, q, _int, account) in enumerate(legs):
        if kind != "stake" or q <= 0:
            continue
        start = (date.fromisoformat(on) - timedelta(days=STAKE_DAYS)).isoformat()
        for j in range(i - 1, -1, -1):
            pseq, d, k, s, sq, internal, acc = out[j]
            if d < start:
                break
            if (k, internal, s, acc) == (
                "out",
                False,
                symbol,
                account,
            ) and -sq <= q <= -sq * STAKE_GAIN:
                out[j] = (pseq, d, "stake", s, sq, True, acc)
                found.append((pseq, seq))
                break
    return found


def _transfers(legs: list[Leg]) -> list[tuple[int, int]]:
    """(arrivée, envoi) : un envoi et une arrivée de la même crypto entre deux de mes comptes, à
    quelques jours et à frais de retrait près."""
    found = []
    out = list(legs)
    for i, (seq, on, kind, symbol, q, internal, account) in enumerate(legs):
        if kind != "in" or internal or q <= 0:
            continue
        day = date.fromisoformat(on)
        start = (day - timedelta(days=WINDOW_DAYS)).isoformat()
        end = (day + timedelta(days=SLACK_DAYS)).isoformat()
        best: tuple[int, Decimal, int] | None = None
        for j, (_pseq, d, k, s, sq, inner, acc) in enumerate(out):
            if (k, inner, s) != ("out", False, symbol) or acc == account or not start <= d <= end:
                continue
            if -sq * (1 - TRANSFER_FEE) <= q <= -sq:
                gap = abs((date.fromisoformat(d) - day).days)
                if best is None or (gap, -sq - q) < best[:2]:
                    best = (gap, -sq - q, j)
        if best is not None:
            j = best[2]
            out[j] = (*out[j][:5], True, out[j][6])
            out[i] = (seq, on, kind, symbol, q, True, account)
            found.append((seq, out[j][0]))
    return found


def _once(conn: object) -> None:
    legs = _legs(conn)
    stakes = _staking_exits(legs)
    staked = {s for s, _c in stakes}
    legs = [
        (seq, on, "stake" if seq in staked else kind, s, q, internal or seq in staked, acc)
        for seq, on, kind, s, q, internal, acc in legs
    ]
    rows = [
        {"id": f"legacy|claim|{sent}", "e": sent, "k": "stake", "p": claim, "m": "claim"}
        for sent, claim in stakes
    ] + [
        {"id": f"legacy|window|{arrived}", "e": arrived, "k": "transfer", "p": sent, "m": "window"}
        for arrived, sent in _transfers(legs)
    ]
    for r in rows:
        conn.execute(  # type: ignore[attr-defined]
            text(
                "INSERT INTO crypto_links (id, entry_seq, kind, peer_seq, method, created_at, "
                "actor) VALUES (:id, :e, :k, :p, :m, :at, 'migration:0022')"
            ),
            {**r, "at": "2026-11-04T00:00:00.000Z"},
        )


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)
    _once(op.get_bind())


def downgrade() -> None:
    raise NotImplementedError("pas de retour arrière : restaurer la sauvegarde")
