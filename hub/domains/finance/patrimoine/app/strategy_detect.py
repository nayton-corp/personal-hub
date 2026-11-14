"""Stratégies repérées : chaque nuit, le hub cherche dans le journal des achats réguliers (un DCA)
et propose la stratégie dans « À valider ». Il ne l'écrit jamais seul : une carte `save_strategy`
avec `since` (le premier achat de la série), validée d'un Face ID, ou refusée.

Où chercher :
- chaque crypto (les achats du journal crypto) et chaque titre d'un compte de titres (IBKR) ;
- un compte de prévoyance (3a) au niveau du compte : ce sont les versements qui sont réguliers,
  le compte achète seul ses fonds. Ses achats de fonds ne sont pas lus un par un (sinon, un faux
  DCA par fonds).

Les règles d'une série (assez d'achats, rythme, montants proches, en cours, pas de vente) sont
dans model/regular_buys.py. Une cible qui a déjà une stratégie d'achat régulier n'est pas
proposée. Une carte refusée (ou laissée expirer) ne revient pas : la demande porte une clé
(`create_key`) faite de la cible, du rythme et d'une tranche de montant ; le cœur ne recrée
jamais une carte de même clé. Si le montant change nettement (autre tranche) ou le rythme, c'est
une autre clé : la série est reproposée.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import crypto_moves, strategy_history
from hub.domains.finance.patrimoine.app.strategies import ACCOUNT, DEPOSITS_SQL, Today
from hub.domains.finance.patrimoine.model import regular_buys as rb
from hub.domains.finance.patrimoine.model.instruments import crypto_key
from hub.domains.finance.patrimoine.model.positions import STABLECOINS
from hub.domains.finance.registre.app import ledger
from hub.kernel.ids import urn

LOOKBACK_DAYS = 2 * 366
KIND = "save_strategy"


@dataclass(frozen=True)
class Found:
    scope: str
    series: rb.Series

    @property
    def key(self) -> str:
        band = rb.amount_band(self.series.amount)
        return f"finance:strategy-detect:{self.scope}:{self.series.cadence}:{band}"

    def params(self) -> dict[str, object]:
        s = self.series
        return {
            "kind": "recurring",
            "scope": self.scope,
            "cadence": s.cadence,
            "day": s.day,
            "amount_minor": s.amount,
            "since": strategy_history.first_due(s.cadence, s.day, s.first).isoformat(),
        }


def _crypto(now: Today, since: str) -> dict[str, tuple[list[rb.Buy], list[date]]]:
    out: dict[str, tuple[list[rb.Buy], list[date]]] = {}
    for m in crypto_moves.moves(now.conn, now.day):
        key = crypto_key(m.symbol)
        if m.role != "trade" or m.on < since or key in STABLECOINS:
            continue
        buys, sold = out.setdefault(key, ([], []))
        if m.quantity > 0:
            buys.append(rb.Buy(date.fromisoformat(m.on), abs(m.amount)))
        else:
            sold.append(date.fromisoformat(m.on))
    return out


def _securities(now: Today, since: str) -> dict[str, tuple[list[rb.Buy], list[date]]]:
    """Les titres des comptes de titres ; ceux d'un compte de prévoyance sont achetés par le
    compte lui-même, ils ne disent rien d'une décision."""
    out: dict[str, tuple[list[rb.Buy], list[date]]] = {}
    for isin, on, minor, ccy, qty in now.conn.execute(
        text(
            "SELECT t.isin, t.trade_date, t.amount_minor, t.currency, CAST(t.quantity AS REAL) "
            "FROM trades t JOIN accounts a ON a.id = t.account_id "
            "WHERE a.kind = 'securities' AND t.trade_date >= :s AND t.trade_date <= :d "
            "AND t.isin NOT LIKE 'CRYPTO:%'"
        ),
        {"s": since, "d": now.day},
    ):
        buys, sold = out.setdefault(str(isin), ([], []))
        day = date.fromisoformat(str(on))
        if qty > 0:
            base = now.positions.fx.to_base(int(minor), str(ccy), str(on))
            if base:
                buys.append(rb.Buy(day, abs(base)))
        elif qty < 0:
            sold.append(day)
    return out


def _pension(now: Today, since: str) -> dict[str, tuple[list[rb.Buy], list[date]]]:
    """Les versements sur chaque compte de prévoyance (les retraits comptent comme des ventes)."""
    out: dict[str, tuple[list[rb.Buy], list[date]]] = {}
    ids = now.conn.execute(text("SELECT id FROM accounts WHERE kind = 'pension'")).scalars()
    for account_id in list(ids):
        buys: list[rb.Buy] = []
        rows = now.conn.execute(text(DEPOSITS_SQL), {"i": account_id, "s": since, "d": now.day})
        for on, minor, ccy in rows:
            base = now.positions.fx.to_base(int(minor), str(ccy), str(on))
            if base:
                buys.append(rb.Buy(date.fromisoformat(str(on)), abs(base)))
        out_rows = now.conn.execute(
            text(
                "SELECT booking_date FROM entries WHERE account_id = :i AND bank_tx_code LIKE "
                "'%/WITHDRAWAL' AND booking_date >= :s AND booking_date <= :d"
            ),
            {"i": account_id, "s": since, "d": now.day},
        ).scalars()
        out[f"{ACCOUNT}{account_id}"] = (buys, [date.fromisoformat(str(d)) for d in out_rows])
    return out


def candidates(conn: Connection, today: date, only: str | None = None) -> list[Found]:
    """Les séries d'achats réguliers en cours, sur des cibles sans stratégie d'achat régulier
    (`only` : cette cible seulement, pour l'aperçu de la carte)."""
    now = Today(conn, today)
    since = date.fromordinal(today.toordinal() - LOOKBACK_DAYS).isoformat()
    taken = set(
        conn.execute(text("SELECT scope FROM strategies WHERE kind = 'recurring'")).scalars()
    )
    found: list[Found] = []
    for source in (_crypto, _securities, _pension):
        for scope, (buys, sold) in sorted(source(now, since).items()):
            if scope in taken or (only is not None and scope != only):
                continue
            series = rb.detect(buys, sold, today)
            if series is not None:
                found.append(Found(scope, series))
    return found


def request(conn: Connection, today: date) -> int:
    """Demande au cœur une carte par série repérée ; rend le nombre de demandes."""
    found = candidates(conn, today)
    for f in found:
        n = len(f.series.buys)
        ledger.append_event(
            conn,
            "proposal.request",
            urn("finance", "strategy", "detect"),
            {
                "kind": KIND,
                "params": f.params(),
                "reason": f"{n} achats réguliers repérés au journal",
                "create_key": f.key,
            },
        )
    return len(found)
