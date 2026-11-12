"""Stratégies (migration 0027) : ce que la base en dit, et les chiffres du jour qui les
concernent. Une stratégie ne passe jamais d'ordre : elle dit où on en est (niveau par rapport
au prix d'achat, prochaine échéance, baisse depuis le plus haut) et ce que le journal montre
depuis une étape. Les règles sont dans model/strategy.py ; la vérification de nuit dans
strategy_watch.py."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import crypto_cost, crypto_moves, price_history
from hub.domains.finance.patrimoine.app.market_data import Positions
from hub.domains.finance.patrimoine.model import strategy as rules
from hub.domains.finance.patrimoine.model.instruments import crypto_key
from hub.domains.finance.patrimoine.model.positions import STABLECOINS
from hub.domains.finance.registre.model.amounts import in_base
from hub.kernel.money import Money, base_currency

PENDING = ("open", "later")
STALE_PRICE_DAYS = 5  # un cours plus vieux ne déclenche pas une « grosse baisse »
WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
WINDOW_LABEL = {90: "des 3 derniers mois", 365: "des 12 derniers mois"}
COLS = "id, kind, scope, name, params_json, note, status, created_on"
STEP_COLS = (
    "id, strategy_id, step_key, state, opened_on, planned_minor, done_minor, detail_json, "
    "closed_on, closed_by"
)


@dataclass(frozen=True)
class Strategy:
    id: str
    kind: str
    scope: str
    name: str
    params: dict[str, object]
    note: str | None
    status: str
    created_on: str

    def tiers(self) -> list[rules.Tier]:
        raw = self.params.get("tiers")
        return [rules.Tier(int(t["at_pct"]), int(t["sell_pct"])) for t in _list(raw)]

    def number(self, key: str) -> int:
        return int(str(self.params[key]))


@dataclass(frozen=True)
class Step:
    id: str
    strategy_id: str
    key: str
    state: str
    opened_on: str
    planned: int | None
    done: int
    detail: dict[str, object]
    closed_on: str | None
    closed_by: str | None


def _list(raw: object) -> list[dict[str, int]]:
    return list(raw) if isinstance(raw, list) else []


def read(conn: Connection, strategy_id: str | None = None) -> list[Strategy]:
    rows = conn.execute(
        text(
            f"SELECT {COLS} FROM strategies WHERE (:i IS NULL OR id = :i) "  # noqa: S608
            "ORDER BY status = 'ended', created_at, id"
        ),
        {"i": strategy_id},
    )
    return [Strategy(r[0], r[1], r[2], r[3], json.loads(r[4]), r[5], r[6], r[7]) for r in rows]


def steps(conn: Connection, strategy_id: str | None = None) -> dict[str, list[Step]]:
    """Les étapes par stratégie, de la plus ancienne à la plus récente."""
    out: dict[str, list[Step]] = {}
    for r in conn.execute(
        text(
            f"SELECT {STEP_COLS} FROM strategy_steps "  # noqa: S608
            "WHERE (:i IS NULL OR strategy_id = :i) ORDER BY opened_on, created_at, id"
        ),
        {"i": strategy_id},
    ):
        step = Step(r[0], r[1], r[2], r[3], r[4], r[5], int(r[6]), json.loads(r[7]), r[8], r[9])
        out.setdefault(step.strategy_id, []).append(step)
    return out


def is_crypto(scope: str) -> bool:
    return scope in rules.GROUPS or scope.startswith("CRYPTO:")


def in_scope(scope: str, key: str) -> bool:
    """Cet instrument fait-il partie de la cible ? Un groupe ne compte jamais un stablecoin."""
    if scope not in rules.GROUPS:
        return key == scope
    if not key.startswith("CRYPTO:") or key in STABLECOINS:
        return False
    return scope == rules.GROUP_ALL or key != rules.BITCOIN


def scope_name(conn: Connection, scope: str) -> str | None:
    """Le nom affiché d'une cible, ou None si elle n'existe pas."""
    if scope in rules.GROUPS:
        return rules.GROUPS[scope]
    name = conn.execute(text("SELECT name FROM instruments WHERE isin = :i"), {"i": scope}).scalar()
    return None if name is None else str(name)


@dataclass(frozen=True)
class Level:
    """Où en est une cible crypto par rapport à son prix d'achat. La part sans prix de revient
    connu est laissée de côté : on ne compare que ce dont on sait ce qu'il a coûté."""

    value: int
    cost: int
    ratio: Decimal | None
    rows: tuple[tuple[str, int, int], ...]  # (instrument, valeur, prix d'achat), par niveau


class Today:
    """Les chiffres du jour, lus une fois pour toutes les stratégies."""

    def __init__(self, conn: Connection, today: date) -> None:
        self.conn = conn
        self.today = today
        self.day = today.isoformat()
        self._positions: Positions | None = None
        self._crypto: dict[str, tuple[int, int]] | None = None
        self._moves: list[crypto_moves.Move] | None = None

    @property
    def positions(self) -> Positions:
        if self._positions is None:
            self._positions = Positions(self.conn)
        return self._positions

    def crypto(self) -> dict[str, tuple[int, int]]:
        """Par crypto tenue : (valeur dont le prix d'achat est connu, prix d'achat)."""
        if self._crypto is None:
            found = crypto_cost.result(self.conn, self.day, self.positions)
            self._crypto = {}
            for key, row in (found["by_asset"] if found else {}).items():
                covered = int(row["value"]["minor"]) - int(row["unknown_cost_value"]["minor"])
                if covered > 0 and Decimal(row["quantity"]) > 0:
                    self._crypto[key] = (covered, int(row["cost"]["minor"]))
        return self._crypto

    def level(self, scope: str) -> Level:
        rows = [(k, v, c) for k, (v, c) in self.crypto().items() if in_scope(scope, k)]
        rows.sort(key=lambda r: (-(rules.ratio_pct(r[1], r[2]) or Decimal(0)), r[0]))
        value, cost = sum(r[1] for r in rows), sum(r[2] for r in rows)
        return Level(value, cost, rules.ratio_pct(value, cost), tuple(rows))

    def sold(self, scope: str, since: str) -> int:
        """Ce que le journal montre de vendu sur la cible depuis `since`, en devise de base."""
        return self._traded(scope, since, sign=-1)

    def bought(self, scope: str, since: str) -> int:
        if is_crypto(scope):
            return self._traded(scope, since, sign=1)
        total = 0
        for on, minor, ccy in self.conn.execute(
            text(
                "SELECT trade_date, amount_minor, currency FROM trades WHERE isin = :i "
                "AND trade_date >= :s AND trade_date <= :d AND CAST(quantity AS REAL) > 0"
            ),
            {"i": scope, "s": since, "d": self.day},
        ):
            total += abs(self.positions.fx.to_base(int(minor), str(ccy), str(on)) or 0)
        return total

    def _traded(self, scope: str, since: str, *, sign: int) -> int:
        if self._moves is None:
            self._moves = crypto_moves.moves(self.conn, self.day)
        return sum(
            abs(m.amount)
            for m in self._moves
            if m.role == "trade"
            and m.on >= since
            and m.quantity * sign > 0
            and in_scope(scope, crypto_key(m.symbol))
        )

    def dip(self, scope: str, window_days: int) -> rules.Dip | None:
        """La baisse depuis le plus haut de la fenêtre ; None sans cours récent."""
        since = (self.today - timedelta(days=window_days)).isoformat()
        found = price_history.history(self.conn, scope, since, self.day)
        prices = [(str(i["on_date"]), Decimal(str(i["price"]))) for i in found["items"]]
        d = rules.dip(prices, window_days, self.today)
        fresh = (self.today - timedelta(days=STALE_PRICE_DAYS)).isoformat()
        return d if d is not None and d.last_on >= fresh else None


def shown(minor: int) -> str:
    ccy = base_currency()
    return f"{Money(minor, ccy).display()} {ccy}"


def tier_label(at_pct: int) -> str:
    if at_pct == 100:
        return "revient à son prix d'achat"
    if at_pct > 100:
        return f"dépasse son prix d'achat de {at_pct - 100} %"
    return f"remonte à {100 - at_pct} % sous son prix d'achat"


def level_label(at_pct: int) -> str:
    if at_pct == 100:
        return "au prix d'achat"
    return f"à +{at_pct - 100} %" if at_pct > 100 else f"à −{100 - at_pct} %"


def phrase(kind: str, name: str, params: dict[str, object]) -> str:
    """La stratégie en une phrase : sur quoi, quand, le geste prévu."""
    if kind == "ladder":
        tiers = sorted(
            rules.Tier(int(t["at_pct"]), int(t["sell_pct"])) for t in _list(params["tiers"])
        )
        first, rest = tiers[0], tiers[1:]
        out = f"Quand {name} {tier_label(first.at_pct)}, j'en vends {first.sell_pct} %"
        for t in rest:
            out += f" ; {level_label(t.at_pct)}, {t.sell_pct} %"
        return out + "."
    amount = shown(int(str(params["amount_minor"])))
    if kind == "recurring":
        day = int(str(params["day"]))
        when = f"Chaque {WEEKDAYS[day]}" if params["cadence"] == "weekly" else f"Le {day} du mois"
        return f"{when}, j'achète pour {amount} de {name}."
    window = WINDOW_LABEL[int(str(params["window_days"]))]
    return (
        f"Si {name} baisse de {params['drop_pct']} % depuis son plus haut {window}, "
        f"j'en achète pour {amount}."
    )


def _step_out(s: Step, level: Level | None, names: dict[str, str]) -> dict[str, object]:
    out: dict[str, object] = {
        "id": s.id,
        "key": s.key,
        "state": s.state,
        "opened_on": s.opened_on,
        "planned": None if s.planned is None else in_base(s.planned),
        "done": in_base(s.done),
        "detail": s.detail,
        "closed_on": s.closed_on,
        "closed_by": s.closed_by,
    }
    if level is not None:  # étape de palier en cours : les pièces du groupe, à choisir
        out["rows"] = [
            {
                "key": k,
                "name": names.get(k, k.split(":", 1)[-1]),
                "value": in_base(v),
                "cost": in_base(c),
                "ratio_pct": _pct(rules.ratio_pct(v, c)),
            }
            for k, v, c in level.rows
        ]
    return out


def _pct(x: Decimal | None) -> str | None:
    return None if x is None else str(x.quantize(Decimal("0.1")))


def live(s: Strategy, now: Today, closed: frozenset[str]) -> tuple[dict[str, object], Level | None]:
    """Où en est la stratégie aujourd'hui (ce que la carte affiche sous la phrase)."""
    if s.kind == "ladder":
        level = now.level(s.scope)
        ahead = [t for t in sorted(s.tiers()) if f"t{t.at_pct}" not in closed]
        return {
            "ratio_pct": _pct(level.ratio),
            "value": in_base(level.value),
            "cost": in_base(level.cost),
            "next_at_pct": ahead[0].at_pct if ahead else None,
        }, level
    if s.kind == "recurring":
        cadence, day = str(s.params["cadence"]), s.number("day")
        return {"next_on": rules.recurring_next(cadence, day, now.today).isoformat()}, None
    d = now.dip(s.scope, s.number("window_days"))
    return {
        "drop_pct": None if d is None else _pct(max(d.drop_pct, Decimal(0))),
        "peak_on": None if d is None else d.peak_on,
    }, None


def items(conn: Connection, today: date) -> list[dict[str, object]]:
    now = Today(conn, today)
    by_strategy = steps(conn)
    names = {str(r[0]): str(r[1]) for r in conn.execute(text("SELECT isin, name FROM instruments"))}
    out: list[dict[str, object]] = []
    for s in read(conn):
        mine = by_strategy.get(s.id, [])
        pending = next((x for x in mine if x.state in PENDING), None)
        closed = frozenset(x.key for x in mine if x.state not in PENDING)
        level, measured = live(s, now, closed) if s.status == "active" else ({}, None)
        state = s.status
        if s.status == "active":
            state = "reached" if pending else "active"
            if s.kind == "ladder" and not pending and level["next_at_pct"] is None:
                state = "complete"  # tous les paliers sont passés
        out.append(
            {
                "id": s.id,
                "kind": s.kind,
                "scope": s.scope,
                "name": s.name,
                "phrase": phrase(s.kind, s.name, s.params),
                "params": s.params,
                "note": s.note,
                "status": s.status,
                "state": state,
                "created_on": s.created_on,
                "level": level,
                "step": _step_out(pending, measured, names) if pending else None,
                "steps": [_step_out(x, None, names) for x in reversed(mine)],
                "kept": {
                    "done": sum(1 for x in mine if x.state == "done"),
                    "skipped": sum(1 for x in mine if x.state == "skipped"),
                },
            }
        )
    return out


def scopes(conn: Connection, today: date) -> list[dict[str, object]]:
    """Sur quoi une stratégie peut porter : les groupes crypto, puis chaque instrument tenu."""
    now = Today(conn, today)
    held: dict[str, int] = {}
    for account_id in sorted(now.positions.accounts):
        for x in now.positions.lines(account_id, now.day):
            if x.quantity > 0 and x.isin not in STABLECOINS and not x.isin.startswith("SYM:"):
                held[x.isin] = held.get(x.isin, 0) + x.value
    names = {str(r[0]): str(r[1]) for r in conn.execute(text("SELECT isin, name FROM instruments"))}
    out: list[dict[str, object]] = []
    if any(k.startswith("CRYPTO:") for k in held):
        for group, label in rules.GROUPS.items():
            value = sum(v for k, v in held.items() if in_scope(group, k))
            out.append({"key": group, "name": label, "kind": "group", "value": in_base(value)})
    for key, value in sorted(held.items(), key=lambda kv: (-kv[1], kv[0])):
        kind = "crypto" if key.startswith("CRYPTO:") else "security"
        out.append({"key": key, "name": names.get(key, key), "kind": kind, "value": in_base(value)})
    return out
