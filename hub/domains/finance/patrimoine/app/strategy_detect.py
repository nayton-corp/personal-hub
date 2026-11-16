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

from hub.domains.finance.patrimoine.app import crypto_moves, platform_deposits, strategy_history
from hub.domains.finance.patrimoine.app.strategies import ACCOUNT, DEPOSITS_SQL, Today, scope_name
from hub.domains.finance.patrimoine.model import regular_buys as rb
from hub.domains.finance.patrimoine.model.instruments import crypto_key
from hub.domains.finance.patrimoine.model.positions import STABLECOINS
from hub.domains.finance.registre.app import ledger
from hub.kernel.ids import urn

LOOKBACK_DAYS = 2 * 366 - 40  # le début d'une série (une échéance) reste dans les deux ans
KIND = "save_strategy"
# un compte crypto tenu par un relevé déposé à la main : connu jusqu'à son dernier dépôt
STATEMENT_ACCOUNTS = {"crypto:swissborg": "swissborg"}
Seen = dict[str, tuple[list[rb.Buy], list[date]]]


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


def _statement_day(now: Today, account_ids: set[str]) -> date | None:
    """Le jour jusqu'où des comptes tenus par un relevé déposé à la main sont connus (le dernier
    dépôt), ou None si l'un d'eux se lit tout seul : une série n'est pas « arrêtée » parce que
    le dernier relevé date un peu."""
    days = []
    for account_id in sorted(account_ids):
        ref = now.conn.execute(
            text("SELECT external_ref FROM accounts WHERE id = :i"), {"i": account_id}
        ).scalar()
        source = STATEMENT_ACCOUNTS.get(str(ref))
        if source is None:
            return None
        last = now.conn.execute(
            text("SELECT max(received_at) FROM imports WHERE status = 'applied' AND source = :s"),
            {"s": source},
        ).scalar()
        if not last:
            return None
        days.append(date.fromisoformat(str(last)[:10]))
    return min([*days, now.today]) if days else None


def _crypto(now: Today, since: str, as_of: dict[str, date]) -> Seen:
    out: Seen = {}
    where: dict[str, set[str]] = {}
    for m in crypto_moves.moves(now.conn, now.day):
        key = crypto_key(m.symbol)
        if m.role != "trade" or m.on < since or key in STABLECOINS:
            continue
        where.setdefault(key, set()).add(m.account_id)
        buys, sold = out.setdefault(key, ([], []))
        if m.quantity > 0:
            buys.append(rb.Buy(date.fromisoformat(m.on), abs(m.amount)))
        else:
            sold.append(date.fromisoformat(m.on))
    for key, accounts in where.items():
        day = _statement_day(now, accounts)
        if day is not None:
            as_of[key] = day
    return out


def _securities(now: Today, since: str, as_of: dict[str, date]) -> Seen:
    """Les titres des comptes de titres ; ceux d'un compte de prévoyance sont achetés par le
    compte lui-même, ils ne disent rien d'une décision."""
    out: Seen = {}
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


def _pension(now: Today, since: str, as_of: dict[str, date]) -> Seen:
    """Les versements sur chaque compte de prévoyance (les retraits comptent comme des ventes)."""
    out: Seen = {}
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


def _platforms(now: Today, since: str, as_of: dict[str, date]) -> Seen:
    """Les virements de la banque vers chaque plateforme (IBKR, SwissBorg…) : un versement
    régulier se voit sans attendre la plateforme (platform_deposits.py)."""
    out: Seen = {}
    for p in platform_deposits.platforms(now.conn):
        paid, back = platform_deposits.dated(platform_deposits.moves(now.conn, p, since, now.day))
        buys = []
        for d, minor, ccy in paid:
            base = now.positions.fx.to_base(minor, ccy, d.isoformat())
            if base:
                buys.append(rb.Buy(d, abs(base)))
        out[f"{ACCOUNT}{p.account_id}"] = (buys, back)
    return out


@dataclass(frozen=True)
class Tried:
    """Une cible regardée sans série retenue : ses achats, la plus longue série essayée, ce qui
    lui manque. Des compteurs et des raisons, jamais un montant ni une date."""

    scope: str
    name: str
    buys: int
    longest: int
    why: tuple[str, ...]


def _sources(now: Today, since: str) -> list[tuple[str, list[rb.Buy], list[date], date]]:
    """(cible, achats, ventes, jour jusqu'où la cible est connue)."""
    out: list[tuple[str, list[rb.Buy], list[date], date]] = []
    for source in (_crypto, _securities, _pension, _platforms):
        as_of: dict[str, date] = {}
        for scope, (buys, sold) in sorted(source(now, since, as_of).items()):
            out.append((scope, buys, sold, as_of.get(scope, now.today)))
    return out


def explain(conn: Connection, today: date) -> list[Tried]:
    """Pourquoi rien n'est proposé : chaque cible sans stratégie d'achat régulier, la plus proche
    d'une série d'abord."""
    now = Today(conn, today)
    since = date.fromordinal(today.toordinal() - LOOKBACK_DAYS).isoformat()
    taken = _taken(conn)
    out = []
    for scope, buys, sold, known in _sources(now, since):
        if scope in taken or rb.detect(buys, sold, known) is not None:
            continue
        longest, why = rb.explain(buys, sold, known)
        name = scope_name(conn, scope) or scope.removeprefix("CRYPTO:")
        out.append(Tried(scope, name, len(rb.by_day(buys)), longest, tuple(why)))
    return sorted(out, key=lambda t: (-t.longest, -t.buys, t.name))


def _taken(conn: Connection) -> set[str]:
    return set(
        conn.execute(text("SELECT scope FROM strategies WHERE kind = 'recurring'")).scalars()
    )


def candidates(conn: Connection, today: date, only: str | None = None) -> list[Found]:
    """Les séries d'achats réguliers en cours, sur des cibles sans stratégie d'achat régulier
    (`only` : cette cible seulement, pour l'aperçu de la carte)."""
    now = Today(conn, today)
    since = date.fromordinal(today.toordinal() - LOOKBACK_DAYS).isoformat()
    taken = _taken(conn)
    found: list[Found] = []
    for scope, buys, sold, known in _sources(now, since):
        if scope in taken or (only is not None and scope != only):
            continue
        series = rb.detect(buys, sold, known)
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
