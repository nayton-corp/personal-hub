"""Rapprochement du patrimoine et ses ruptures (docs/finance-politique.md, « aucun solde ne vient
de nulle part »).

Par compte à positions et par actif, les parts relevées se comparent aux opérations connues :

- un compte crypto : les parts du dernier relevé moins tous les mouvements jusqu'à ce relevé
  (`trades`) et les lots de tes décisions. Plus de parts que d'opérations : des parts sans
  historique ; moins : des sorties que l'historique ne montre pas ;
- un compte de titres ou de prévoyance : d'un relevé au suivant, les parts doivent bouger comme
  les opérations entre les deux (le premier relevé fait l'ouverture), à l'arrondi du relevé
  près (moins d'un centième de part, pour des parts fractionnées).

Une crypto renommée (RNDR devenu RENDER, MATIC devenu POL) se compte sous son nouveau nom.

Un écart au-delà de la tolérance (1 CHF) est une rupture `unexplained`. S'y ajoutent, pour les
cryptos, les envois vers un portefeuille non suivi (`sent_outside`) et les arrivées d'un
portefeuille non suivi (`arrived_outside`) que tu n'as pas classés, et pour toute position un
cours absent (`no_price`) ou trop ancien (`stale_price`). Les ruptures se recalculent à chaque
lecture ; seules tes décisions se gardent (decisions.py). Des agrégats : un compte, un actif,
des parts et une valeur, jamais une opération.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from itertools import pairwise
from typing import Any

from sqlalchemy import Connection, text

from hub.core.errors import Problem
from hub.domains.finance.patrimoine.app import crypto_cost, decisions, valuation
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.registre.model.amounts import money
from hub.kernel.money import CURRENCY_EXPONENTS, DECIMAL_CONTEXT, base_currency

TOLERANCE_MINOR = 100  # 1 CHF par compte et par actif
ROUNDING = Decimal("0.01")  # un relevé de fonds arrondit ses parts au centième
# une crypto renommée : ses parts sorties sous l'ancien nom rentrent sous le nouveau
RENAMED = {"CRYPTO:RNDR": "CRYPTO:RENDER", "CRYPTO:MATIC": "CRYPTO:POL"}
STALE_DAYS = {"crypto": 3}  # âge d'un cours au-delà duquel il est « ancien »
STALE_DAYS_OTHER = 14
STALE_FX_DAYS = 7  # un change plus vieux se signale comme un cours ancien (audit M6)
ZERO = Decimal(0)
# les gestes de l'app pour chaque rupture, dans l'ordre où elle les propose
ACTIONS = {
    "unexplained+": ["import", "cost", "accept"],
    "unexplained-": ["import", "accept"],
    "sent_outside": ["add_wallet", "gone"],
    "arrived_outside": ["add_wallet", "accept"],
    "no_price": ["accept"],
    "stale_fx": ["accept"],
    "stale_price": ["accept"],
}


@dataclass
class Break:
    kind: str
    account_id: str
    asset: str
    quantity: Decimal | None
    value: int | None  # centimes de la devise de base ; None sans cours
    since: str
    cause: str

    @property
    def id(self) -> str:
        return f"{self.kind}|{self.account_id}|{self.asset}"

    def public(self, names: dict[str, str]) -> dict[str, Any]:
        sign = "+" if (self.quantity or ZERO) >= 0 else "-"
        acts = ACTIONS[f"{self.kind}{sign}" if self.kind == "unexplained" else self.kind]
        return {
            "id": self.id,
            "kind": self.kind,
            "account_id": self.account_id,
            "account": names.get(self.account_id, self.account_id),
            "asset": self.asset,
            "symbol": instruments.symbol_of(self.asset),
            "quantity": None if self.quantity is None else str(self.quantity.normalize()),
            "value": None if self.value is None else money(self.value, base_currency()),
            "since": self.since,
            "cause": self.cause,
            "actions": acts,
        }


@dataclass
class Report:
    on_date: str
    breaks: list[Break]
    total: int  # valeur des placements suivis
    explained: int  # dont expliquée et cotée

    def public(self, names: dict[str, str]) -> dict[str, Any]:
        ccy = base_currency()
        open_value = sum(abs(b.value or 0) for b in self.breaks)
        return {
            "on_date": self.on_date,
            "currency": ccy,
            "items": [b.public(names) for b in self.breaks],
            "count": len(self.breaks),
            "open_value": money(open_value, ccy),
            "invested": money(self.total, ccy),
            "explained": money(self.explained, ccy),
            # part de la valeur des placements expliquée par des opérations et cotée
            "completeness": None
            if self.total <= 0
            else str((Decimal(self.explained) / Decimal(self.total)).quantize(Decimal("0.001"))),
            "tolerance": money(TOLERANCE_MINOR, ccy),
        }


Decided = dict[tuple[str, str, str], tuple[str, Decimal | None]]  # (rupture, compte, actif) →
# (jusqu'à quand, quantité couverte ; None : décision d'avant la quantité, couvre tout)


def _accounts(conn: Connection) -> list[tuple[str, str, str, bool, str]]:
    rows = conn.execute(
        text(
            "SELECT id, kind, coalesce(nullif(name, ''), institution, id), hidden, currency "
            "FROM accounts"
        )
    ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2]), bool(r[3]), str(r[4])) for r in rows]


def _unit(positions: valuation.Positions, key: str, on: str) -> Decimal | None:
    """Valeur d'une part en centimes de la devise de base, au dernier cours connu."""
    known = positions.price(key, on)
    if known is None:
        return None
    _d, price, ccy = known
    rate = positions.fx.rate(ccy, on)
    if rate is None:
        return None
    with localcontext(DECIMAL_CONTEXT):
        unit: Decimal = price * rate * 10 ** CURRENCY_EXPONENTS.get(base_currency(), 2)
        return unit


def _value(q: Decimal, unit: Decimal | None) -> int | None:
    if unit is None:
        return None
    with localcontext(DECIMAL_CONTEXT):
        return int((q * unit).to_integral_value())


def _unexplained(
    positions: valuation.Positions,
    account: str,
    kind: str,
    on: str,
    covered: dict[tuple[str, str], Decimal],
) -> list[Break]:
    reports = [(d, held) for d, held in positions.reports.get(account, []) if d <= on]
    if not reports:
        return []
    trades = [(d, k, q) for d, k, q in positions.trades.get(account, []) if d <= on]
    last_day, last = reports[-1]
    out = []
    with localcontext(DECIMAL_CONTEXT):
        if kind == "crypto":
            gaps: dict[str, Decimal] = {}
            for k, (q, _v, _c) in last.items():
                gaps[RENAMED.get(k, k)] = gaps.get(RENAMED.get(k, k), ZERO) + q
            for d, k, q in trades:
                if d <= last_day:
                    gaps[RENAMED.get(k, k)] = gaps.get(RENAMED.get(k, k), ZERO) - q
            first: dict[str, str] = {}
            for d, held in reports:
                for k in held:
                    first.setdefault(RENAMED.get(k, k), d)
        else:  # d'un relevé au suivant ; le premier fait l'ouverture
            gaps, first = {}, {}
            for (d0, before), (d1, after) in pairwise(reports):
                moved: dict[str, Decimal] = {}
                for d, k, q in trades:
                    if d0 < d <= d1:
                        moved[k] = moved.get(k, ZERO) + q
                for k in set(before) | set(after) | set(moved):
                    was = before[k][0] if k in before else ZERO
                    now = after[k][0] if k in after else ZERO
                    gap = now - was - moved.get(k, ZERO)
                    fractional = any(x % 1 for x in (was, now))
                    if fractional and abs(gap) < ROUNDING:
                        continue  # l'arrondi du relevé, pas une opération qui manque
                    if gap:
                        gaps[k] = gaps.get(k, ZERO) + gap
                        first.setdefault(k, d1)
        for k, gap in sorted(gaps.items()):
            if instruments.known_currency(instruments.symbol_of(k)):
                continue  # des francs en attente chez la plateforme
            rest = gap - covered.get((account, k), ZERO)
            if not rest:
                continue
            value = _value(rest, _unit(positions, k, on))
            if value is not None and abs(value) < TOLERANCE_MINOR:
                continue
            cause = "no_history" if rest > 0 else "missing_out"
            out.append(Break("unexplained", account, k, rest, value, first.get(k, last_day), cause))
    return out


def _outside(legs: list[crypto_cost.Leg], decided: Decided, accounts: set[str]) -> list[Break]:
    """Envois et arrivées crypto sans autre côté connu, après ta dernière décision."""
    sums: dict[tuple[str, str, str], tuple[int, str]] = {}
    for on, role, amount, symbol, _q, internal, account in legs:
        if internal or role not in ("in", "out") or account not in accounts:
            continue
        kind = "arrived_outside" if role == "in" else "sent_outside"
        key = instruments.crypto_key(symbol)
        if on <= decided.get((kind, account, key), ("", None))[0]:
            continue
        total, since = sums.get((kind, account, key), (0, on))
        sums[(kind, account, key)] = (total + abs(amount), min(since, on))
    return [
        Break(kind, account, key, None, total, since, "untracked_wallet")
        for (kind, account, key), (total, since) in sorted(sums.items())
        if total >= TOLERANCE_MINOR
    ]


def _covers(decided: Decided, key: tuple[str, str, str], quantity: Decimal | None) -> str:
    """Jusqu'à quand une décision couvre cette rupture : une décision porte sur une quantité,
    elle se rouvre si les parts changent (audit M7) ; une décision d'avant la quantité couvre
    les parts telles qu'elles sont."""
    until, covered = decided.get(key, ("", None))
    return until if covered is None or covered == quantity else ""


def _prices(
    positions: valuation.Positions, account: str, kind: str, on: str, decided: Decided
) -> tuple[list[Break], int, int, set[str]]:
    """Cours absents ou anciens d'un compte, (valeur du compte, dont au cours ancien), et les
    devises de ses cours."""
    out, total, stale, currencies = [], 0, 0, set()
    limit = (
        date.fromisoformat(on) - timedelta(days=STALE_DAYS.get(kind, STALE_DAYS_OTHER))
    ).isoformat()
    for x in positions.lines(account, on):
        if instruments.known_currency(instruments.symbol_of(x.isin)):
            continue
        total += x.value
        if x.price is None:
            if not _covers(decided, ("no_price", account, x.isin), x.quantity):
                out.append(Break("no_price", account, x.isin, x.quantity, None, on, "no_price"))
            continue
        currencies.add(x.currency)
        if x.price_date and x.price_date < limit and x.value >= TOLERANCE_MINOR:
            if _covers(decided, ("stale_price", account, x.isin), x.quantity) >= x.price_date:
                continue
            stale += x.value
            out.append(
                Break("stale_price", account, x.isin, x.quantity, x.value, x.price_date, "stale")
            )
    return out, total, stale, currencies


def _fx(
    fx: valuation.FxTable, account: str, currencies: set[str], on: str, decided: Decided
) -> list[Break]:
    """Un change plus vieux que `STALE_FX_DAYS` convertit encore, mais se dit (audit M6) ; une
    décision le couvre jusqu'au jour du change qu'elle a vu."""
    out = []
    limit = (date.fromisoformat(on) - timedelta(days=STALE_FX_DAYS)).isoformat()
    for ccy in sorted(currencies - {fx.base}):
        known = fx.dated(ccy, on)
        if known is None or known[0] >= limit:
            continue  # sans change du tout, la valeur est déjà marquée manquante
        if _covers(decided, ("stale_fx", account, ccy), None) >= known[0]:
            continue
        out.append(Break("stale_fx", account, ccy, None, None, known[0], "stale_fx"))
    return out


def report(conn: Connection, on: str) -> Report:
    positions = valuation.Positions(conn)
    found = decisions.read(conn)
    covered: dict[tuple[str, str], Decimal] = {}
    decided: Decided = {}
    for d in found:  # dans l'ordre des décisions : la dernière sur une rupture l'emporte
        if d.break_kind == "unexplained" and d.quantity is not None:
            k = (d.account_id, d.asset)
            covered[k] = covered.get(k, ZERO) + d.quantity
        else:
            k3 = (d.break_kind, d.account_id, d.asset)
            decided[k3] = (max(decided.get(k3, ("", None))[0], d.on_date), d.quantity)
    breaks: list[Break] = []
    total = unexplained = stale = 0
    shown = [a for a in _accounts(conn) if not a[3] and a[0] in positions.accounts]
    for account, kind, _name, _hidden, currency in shown:
        gaps = _unexplained(positions, account, kind, on, covered)
        priced, value, old, currencies = _prices(positions, account, kind, on, decided)
        breaks += gaps + priced + _fx(positions.fx, account, currencies | {currency}, on, decided)
        total += value
        stale += old
        unexplained += sum(b.value or 0 for b in gaps if (b.quantity or ZERO) > 0)
    crypto = {a[0] for a in shown if a[1] == "crypto"}
    if crypto:
        breaks += _outside(crypto_cost._legs(conn, on), decided, crypto)
    order = {k: i for i, k in enumerate(ACTIONS)}
    breaks.sort(key=lambda b: (-(abs(b.value or 0)), order.get(b.kind, 9), b.account_id, b.asset))
    explained = max(0, total - unexplained - stale)
    return Report(on, breaks, total, explained)


def names(conn: Connection) -> dict[str, str]:
    return {a[0]: a[2] for a in _accounts(conn)}


def summary(conn: Connection, on: str) -> dict[str, Any]:
    return report(conn, on).public(names(conn))


def decide(
    conn: Connection,
    on: str,
    break_id: str,
    decision: str,
    *,
    cost_minor: int | None,
    note: str | None,
    actor: str,
    proposal_id: str | None = None,
) -> decisions.Decision:
    """Ta décision sur une rupture ouverte aujourd'hui (proposition `decide_break`) ; elle
    couvre ses parts ou ses opérations jusqu'à aujourd'hui."""
    found = {b.id: b for b in report(conn, on).breaks}
    b = found.get(break_id)
    if b is None:
        raise Problem("not_found", "rupture inconnue ou déjà réglée")
    quantity = b.quantity  # une décision couvre ces parts-là : elle se rouvre si elles changent
    on_date = b.since if b.kind == "unexplained" else on
    if b.kind == "unexplained" and decision == "accept" and quantity and quantity > 0:
        # garder tel quel : les parts entrent à leur valeur du jour où elles sont apparues
        positions = valuation.Positions(conn)
        cost_minor = max(0, _value(quantity, _unit(positions, b.asset, b.since)) or 0)
    return decisions.add(
        conn,
        account_id=b.account_id,
        asset=b.asset,
        break_kind=b.kind,
        decision=decision,
        on_date=on_date,
        quantity=quantity,
        cost_minor=cost_minor,
        currency=base_currency(),
        note=note,
        actor=actor,
        proposal_id=proposal_id,
    )
