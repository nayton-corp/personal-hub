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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from sqlalchemy import Connection, text

from hub.domains.finance.patrimoine.app import decisions
from hub.domains.finance.patrimoine.app.market_data import Positions
from hub.domains.finance.patrimoine.model import instruments
from hub.domains.finance.patrimoine.model.fx import FxRates
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


Leg = tuple[str, str, int, str, Decimal, bool, str]


def _legs(conn: Connection, on_date: str) -> list[Leg]:
    """(jour, rôle, montant, symbole, quantité signée, entre mes comptes, compte) des écritures
    crypto."""
    rows = conn.execute(
        text(
            "SELECT e.seq, e.booking_date, e.amount_minor, e.bank_tx_code, e.account_id, "
            "json_extract(e.fx_json, '$.currency'), json_extract(e.fx_json, '$.quantity'), "
            "json_extract(e.fx_json, '$.peer'), json_extract(e.fx_json, '$.stake') "
            "FROM entries e JOIN accounts a ON a.id = e.account_id "
            "WHERE a.kind = 'crypto' AND e.booking_date <= :d AND e.fx_json IS NOT NULL "
            "ORDER BY e.booking_date, e.seq"
        ),
        {"d": on_date},
    ).fetchall()
    linked = {int(r[7]) for r in rows if r[7] is not None}
    out = []
    for seq, on, amount, code, account, symbol, qty, peer, stake in rows:
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
        if stake and kind in ("in", "out"):
            kind, internal = "stake", True
        out.append((str(on), kind, int(amount), str(symbol).upper(), q, internal, str(account)))
    return _transfers(_staking_exits(out))


TRANSFER_FEE = Decimal("0.05")  # part d'un virement que les frais de retrait peuvent prendre


def _transfers(legs: list[Leg]) -> list[Leg]:
    """Un envoi et une arrivée sans autre côté, entre deux de mes comptes, de la même crypto, à
    quelques jours (links) et à frais de retrait près (l'arrivée reçoit au plus 5 % de moins) :
    un virement entre mes comptes, apparié ici même s'il a été écrit avant d'être reconnu. Les
    parts perdues en route sont des frais : le coût reste sur les autres."""
    from hub.domains.finance.patrimoine.app.links import SLACK_DAYS, WINDOW_DAYS

    out = list(legs)
    for i, (on, kind, a, symbol, q, internal, account) in enumerate(legs):
        if kind != "in" or internal or q <= 0:
            continue
        day = date.fromisoformat(on)
        start = (day - timedelta(days=WINDOW_DAYS)).isoformat()
        end = (day + timedelta(days=SLACK_DAYS)).isoformat()
        best: tuple[int, Decimal, int] | None = None
        for j, (d, k, _a, s, sq, inner, acc) in enumerate(out):
            if (k, inner, s) != ("out", False, symbol) or acc == account or not start <= d <= end:
                continue
            if -sq * (1 - TRANSFER_FEE) <= q <= -sq:
                gap = abs((date.fromisoformat(d) - day).days)
                if best is None or (gap, -sq - q) < best[:2]:
                    best = (gap, -sq - q, j)
        if best is not None:
            j = best[2]
            out[j] = (*out[j][:5], True, out[j][6])
            out[i] = (on, kind, a, symbol, q, True, account)
    return out


STAKE_DAYS = 60  # d'une demande de sortie de staking à son claim
STAKE_GAIN = Decimal("1.25")  # le claim rend la mise et ses récompenses, pas plus


def _staking_exits(legs: list[Leg]) -> list[Leg]:
    """Une sortie de staking enregistrée avant que le hub reconnaisse le staking (un envoi sans
    marque) devient une jambe de staking quand un claim marqué du même compte la suit : la mise
    revient avec ses récompenses, les parts n'ont jamais quitté tes comptes."""
    out = list(legs)
    for i, (on, kind, _a, symbol, q, _int, account) in enumerate(legs):
        if kind != "stake" or q <= 0:
            continue
        start = (date.fromisoformat(on) - timedelta(days=STAKE_DAYS)).isoformat()
        for j in range(i - 1, -1, -1):
            d, k, a, s, sq, internal, acc = out[j]
            if d < start:
                break
            if (k, internal, s, acc) == (
                "out",
                False,
                symbol,
                account,
            ) and -sq <= q <= -sq * STAKE_GAIN:
                out[j] = (d, "stake", a, s, sq, True, acc)
                break
    return out


@dataclass
class Walk:
    """Le prix de revient de chaque crypto (clé `CRYPTO:<symbole>`), si le dollar est connu à
    chaque date, et le flux de chaque jour par compte et par crypto pour la performance : ce que
    les parts ont coûté ou rapporté, selon la politique de calcul (une récompense n'est pas un
    apport, un envoi vers l'extérieur sort à son coût)."""

    books: dict[str, Book]
    usd_ok: bool
    # (compte, clé) → jour → (parts expliquées, flux en centimes de la devise de base)
    flows: dict[tuple[str, str], dict[str, tuple[Decimal, Decimal]]] = field(default_factory=dict)


def walk(conn: Connection, on_date: str, fx: FxRates, lots: Sequence[Leg] = ()) -> Walk:
    """Les jambes crypto dans l'ordre, et les lots de tes décisions (decisions.lots) avant les
    jambes de leur jour."""
    out: dict[str, Book] = {}
    flows: dict[tuple[str, str], dict[str, tuple[Decimal, Decimal]]] = {}
    usd_ok = True
    legs = sorted(
        [*(x for x in lots if x[0] <= on_date), *_legs(conn, on_date)], key=lambda x: x[0]
    )
    with localcontext(DECIMAL_CONTEXT):
        for on, kind, amount, symbol, q, internal, account in legs:
            key = instruments.crypto_key(symbol)
            b = out.setdefault(key, Book())
            day = flows.setdefault((account, key), {})
            v = Decimal(abs(amount))
            rate = fx.rate(USD, on)
            if rate is None:
                usd_ok = False
                rate = Decimal(1)
            vu = v / rate
            had_q, had_f = day.get(on, (ZERO, ZERO))
            if kind == "stake":  # mise, sortie, claim : le coût reste, la récompense est du gain
                b.held += q
                day[on] = (had_q + q, had_f)
                continue
            if internal:
                b.held += q  # les parts changent de compte, le coût reste
                day[on] = (had_q + q, had_f + (v if q > 0 else -v))  # au cours, s'annule au total
                continue
            if q > 0:
                if kind == "income" or kind == "fee":  # récompense, remise de frais : sans coût
                    b.add(q, ZERO, ZERO)
                    b.income += v
                    day[on] = (had_q + q, had_f)  # du gain, pas un apport
                else:
                    b.add(q, v, vu)
                    day[on] = (had_q + q, had_f + v)
                    if kind == "in":
                        b.arrived += v
                continue
            c, cu, unknown = b.remove(-q)
            flow = -v if kind == "trade" else ZERO  # frais : des parts en moins, une perte
            if kind == "out":  # au coût ; des parts sans historique, à leur valeur
                flow = -(c + v * unknown / -q)
            day[on] = (had_q + q, had_f + flow)
            if kind == "trade":
                known = (-q - unknown) / -q
                b.realized += v * known - c
                b.realized_usd += vu * known - cu
                b.sold_unknown += v * (1 - known)
            elif kind == "out":
                b.out_cost += c
            # frais : des parts en moins, le coût reste sur les autres
    return Walk(out, usd_ok, flows)


def books(
    conn: Connection, on_date: str, fx: FxRates, lots: Sequence[Leg] = ()
) -> tuple[dict[str, Book], bool]:
    w = walk(conn, on_date, fx, lots)
    return w.books, w.usd_ok


def _m(x: Decimal, ccy: str) -> dict[str, Any]:
    return money(int(quantize(x, 0)), ccy)


def result(conn: Connection, on_date: str, positions: Positions) -> dict[str, Any] | None:
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
    bk, usd_ok = books(conn, on_date, fx, decisions.lots(decisions.read(conn)))
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
