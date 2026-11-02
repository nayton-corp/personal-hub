"""Résultat des cryptos depuis l'achat, comme une app de suivi (CoinStats) mais en francs.

La performance du patrimoine (performance.py) mesure la variation de la valeur depuis que le hub
suit une ligne : une crypto qui arrive y entre à son cours du jour. Ici, chaque crypto garde son
prix de revient réel, commun à tous les comptes crypto, et le résultat se lit depuis l'achat :

- un achat (jambe `…/TRADE` positive) ajoute ce qu'il a coûté ; un échange crypto contre crypto
  est une vente suivie d'un achat, à la même valeur (exchange.py) ;
- une vente retire sa part du prix de revient (coût moyen) et réalise la différence ;
- un virement entre deux de mes comptes (une jambe appariée, `peer`, ou l'arrivée qu'elle
  désigne) déplace les parts sans toucher au coût : il ne repart pas au cours du jour ;
- une récompense (`…/INCOME`) entre sans coût : c'est du gain ; des frais en crypto retirent des
  parts sans retirer de coût ;
- une arrivée de l'extérieur (sans autre côté connu) coûte sa valeur du jour ; un envoi vers
  l'extérieur retire sa part du coût, sans gain ni perte ;
- les parts tenues sans historique qui les explique (relevé d'un portefeuille) n'ont pas de prix
  de revient : leur valeur est montrée à part et ne compte pas dans le résultat.

Le même calcul est tenu en dollars, chaque montant converti au change de son jour : le résultat en
dollars, converti au change d'aujourd'hui, est l'effet des cryptos ; le reste du résultat en
francs est l'effet du change. Des agrégats seulement : aucune opération n'en sort.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import valuation
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.registre.model.amounts import money
from hub.kernel.money import DECIMAL_CONTEXT, base_currency, quantize

USD = "USD"
ZERO = Decimal(0)
EPS = Decimal("1e-9")  # reste d'arrondi des quantités


def role(code: str | None) -> str | None:
    """Rôle d'une écriture crypto d'après son code (EXCHANGE/…, SWISSBORG/…, CRYPTO/…)."""
    c = code or ""
    if "/TRADE" in c:
        return "trade"
    if "/INCOME" in c:
        return "income"
    if "/FEE" in c:
        return "fee"
    if c.endswith("/DEPOSIT") or c == "CRYPTO/RECEIVE":
        return "in"
    if c.endswith("/WITHDRAWAL") or c == "CRYPTO/SEND":
        return "out"
    return None


@dataclass
class Book:
    """Prix de revient d'une crypto, en francs et en dollars (centimes, décimaux)."""

    held: Decimal = ZERO
    cost: Decimal = ZERO
    cost_usd: Decimal = ZERO
    realized: Decimal = ZERO
    realized_usd: Decimal = ZERO
    income: Decimal = ZERO
    sold_unknown: Decimal = ZERO  # ventes de parts que l'historique n'explique pas
    out_cost: Decimal = ZERO  # coût retiré par des envois vers l'extérieur
    arrived: Decimal = ZERO  # arrivées de l'extérieur, au cours du jour

    def add(self, q: Decimal, cost: Decimal, cost_usd: Decimal) -> None:
        self.held += q
        self.cost += cost
        self.cost_usd += cost_usd

    def remove(self, q: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """Retire `q` parts au coût moyen : (coût, coût en dollars, parts sans historique)."""
        known = min(q, max(self.held, ZERO))
        if known <= 0:
            self.held -= q
            return ZERO, ZERO, q
        share = known / self.held
        c, cu = self.cost * share, self.cost_usd * share
        self.cost -= c
        self.cost_usd -= cu
        self.held -= q
        if self.held <= EPS:  # plus rien : plus de coût (un reste négatif attend son arrivée)
            self.cost = self.cost_usd = ZERO
            if abs(self.held) <= EPS:
                self.held = ZERO
        return c, cu, q - known


def _legs(conn: Connection, on_date: str) -> list[tuple[str, str, int, str, Decimal, bool]]:
    """(jour, rôle, montant, symbole, quantité signée, entre mes comptes) des écritures crypto."""
    rows = conn.execute(
        text(
            "SELECT e.seq, e.booking_date, e.amount_minor, e.bank_tx_code, "
            "json_extract(e.fx_json, '$.currency'), json_extract(e.fx_json, '$.quantity'), "
            "json_extract(e.fx_json, '$.peer') "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "WHERE a.kind = 'crypto' AND e.booking_date <= :d AND e.fx_json IS NOT NULL "
            "ORDER BY e.booking_date, e.seq"
        ),
        {"d": on_date},
    ).fetchall()
    linked = {int(r[6]) for r in rows if r[6] is not None}
    out = []
    for seq, on, amount, code, symbol, qty, peer in rows:
        kind = role(code)
        if kind is None or not symbol or qty is None or instruments.known_currency(str(symbol)):
            continue  # une monnaie (francs en attente chez la plateforme) n'est pas une crypto
        try:
            q = Decimal(str(qty))
        except ArithmeticError:
            continue
        if not q:
            continue
        internal = kind in ("in", "out") and (peer is not None or int(seq) in linked)
        out.append((str(on), kind, int(amount), str(symbol).upper(), q, internal))
    return out


def books(conn: Connection, on_date: str, fx: valuation.FxTable) -> tuple[dict[str, Book], bool]:
    """Le prix de revient de chaque crypto (clé `CRYPTO:<symbole>`), et si le dollar est connu
    à chaque date."""
    out: dict[str, Book] = {}
    usd_ok = True
    with localcontext(DECIMAL_CONTEXT):
        for on, kind, amount, symbol, q, internal in _legs(conn, on_date):
            b = out.setdefault(instruments.crypto_key(symbol), Book())
            v = Decimal(abs(amount))
            rate = fx.rate(USD, on)
            if rate is None:
                usd_ok = False
                rate = Decimal(1)
            vu = v / rate
            if internal:
                b.held += q  # les parts changent de compte, le coût reste
                continue
            if q > 0:
                if kind == "income" or kind == "fee":  # récompense, remise de frais : sans coût
                    b.add(q, ZERO, ZERO)
                    b.income += v
                else:
                    b.add(q, v, vu)
                    if kind == "in":
                        b.arrived += v
                continue
            c, cu, unknown = b.remove(-q)
            if kind == "trade":
                known = (-q - unknown) / -q
                b.realized += v * known - c
                b.realized_usd += vu * known - cu
                b.sold_unknown += v * (1 - known)
            elif kind == "out":
                b.out_cost += c
            # frais : des parts en moins, le coût reste sur les autres
    return out, usd_ok


def _m(x: Decimal, ccy: str) -> dict[str, Any]:
    return money(int(quantize(x, 0)), ccy)


def result(conn: Connection, on_date: str, positions: valuation.Positions) -> dict[str, Any] | None:
    """Le résultat depuis l'achat de toutes les cryptos, par crypto et au total."""
    crypto = [r[0] for r in conn.execute(text("SELECT id FROM accounts WHERE kind = 'crypto'"))]
    fx = positions.fx
    held: dict[str, tuple[Decimal, int]] = {}
    missing = False
    for account_id in crypto:
        for x in positions.lines(account_id, on_date):
            if instruments.known_currency(instruments.symbol_of(x.isin)):
                continue  # des francs en attente chez la plateforme (SYM:CHF)
            if x.price is None:
                missing = True
                continue
            had, worth = held.get(x.isin, (ZERO, 0))
            held[x.isin] = (had + x.quantity, worth + x.value)
    bk, usd_ok = books(conn, on_date, fx)
    if not held and not bk:
        return None
    ccy = base_currency()
    now = fx.rate(USD, on_date)
    usd_ok = usd_ok and now is not None
    tot = dict.fromkeys(
        (
            "value",
            "cost",
            "unrealized",
            "realized",
            "income",
            "unknown",
            "value_usd",
            "cost_usd",
            "realized_usd",
            "out_cost",
            "arrived",
            "sold_unknown",
            "missing_out",
        ),
        ZERO,
    )
    by_asset: dict[str, Any] = {}
    with localcontext(DECIMAL_CONTEXT):
        for key in sorted(set(held) | set(bk)):
            q, value = held.get(key, (ZERO, 0))
            b = bk.get(key, Book())
            v = Decimal(value)
            unknown = ZERO
            missing_out = ZERO
            if q > 0 and q > b.held + EPS:  # des parts sans historique : sans prix de revient
                unknown = v * (q - max(b.held, ZERO)) / q
            elif b.held > q + EPS and b.held > 0:  # sorties que l'historique ne montre pas
                missing_out = b.cost * (b.held - q) / b.held
                b.cost_usd -= b.cost_usd * (b.held - q) / b.held
                b.cost -= missing_out
            if q <= 0 and b.held < 0:  # plus rien, sorties sans arrivée connue : rien à porter
                b.cost = b.cost_usd = ZERO
            covered = v - unknown
            unrealized = covered - b.cost if covered or b.cost else ZERO
            row = {
                "quantity": str(q),
                "value": _m(v, ccy),
                "cost": _m(b.cost, ccy),
                "unrealized": _m(unrealized, ccy),
                "realized": _m(b.realized, ccy),
                "income": _m(b.income, ccy),
                "result": _m(unrealized + b.realized, ccy),
                "unknown_cost_value": _m(unknown, ccy),
            }
            if any(c["minor"] for c in row.values() if isinstance(c, dict)):
                by_asset[key] = row
            for name, amt in (
                ("value", v),
                ("cost", b.cost),
                ("unrealized", unrealized),
                ("realized", b.realized),
                ("income", b.income),
                ("unknown", unknown),
                ("cost_usd", b.cost_usd),
                ("realized_usd", b.realized_usd),
                ("out_cost", b.out_cost),
                ("arrived", b.arrived),
                ("sold_unknown", b.sold_unknown),
                ("missing_out", missing_out),
            ):
                tot[name] += amt
            if usd_ok and now:
                tot["value_usd"] += covered / now
        res = tot["unrealized"] + tot["realized"]
        usd = crypto_effect = fx_effect = None
        if usd_ok and now:
            r_usd = tot["value_usd"] - tot["cost_usd"] + tot["realized_usd"]
            usd = money(int(quantize(r_usd, 0)), USD)
            crypto_effect = r_usd * now
            fx_effect = res - crypto_effect
    return {
        "on_date": on_date,
        "currency": ccy,
        "value": _m(tot["value"], ccy),
        "cost": _m(tot["cost"], ccy),
        "unrealized": _m(tot["unrealized"], ccy),
        "realized": _m(tot["realized"], ccy),
        "result": _m(res, ccy),
        "income": _m(tot["income"], ccy),
        "result_usd": usd,
        "crypto_effect": None if crypto_effect is None else _m(crypto_effect, ccy),
        "fx_effect": None if fx_effect is None else _m(fx_effect, ccy),
        # ce que le résultat ne sait pas lire : à montrer, jamais à cacher
        "unknown_cost_value": _m(tot["unknown"], ccy),
        "arrived_from_outside": _m(tot["arrived"], ccy),
        "sent_outside_cost": _m(tot["out_cost"], ccy),
        "unexplained_out_cost": _m(tot["missing_out"], ccy),
        "sold_without_history": _m(tot["sold_unknown"], ccy),
        "missing_prices": missing,
        "by_asset": by_asset,
    }
