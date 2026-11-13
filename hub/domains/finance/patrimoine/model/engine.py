"""La série du patrimoine, sans base : le seul calcul de la valeur et des flux (audit C2).

Une *ligne* est un instrument d'un compte à positions, le solde d'un compte, ou une dette. Chaque
jour depuis la première écriture, elle a une valeur dans la devise de base et un *flux* : l'argent
qui y entre ou en sort ; le reste de la variation est l'effet marché (performance.py). La valeur
du patrimoine à une date (valuation.py) est la somme des lignes ce jour-là ; le rapprochement et
le résultat des cryptos lisent les mêmes parts et les mêmes cours (positions.py).

- Solde d'un compte : le flux, ce sont les écritures du jour converties au change du jour, sauf
  les revenus et les frais, qui sont de l'effet marché comme la variation du change.
- Instrument : le flux, ce sont les parts achetées ou vendues, au cours du jour ; pour une crypto,
  ses opérations (costed.py).
- Dette (valeur négative) : le flux, ce sont les paiements ; l'effet marché, les intérêts.
- Une ligne qui devient valorisable ou cesse de l'être entre ou sort par un flux, jamais par un
  effet marché. Une ligne qui devrait avoir une valeur mais n'a pas de cours (ou pas de change)
  est marquée `missing` : la période est alors incomplète, jamais 0 en silence.
- Versements : chaque versement est converti au change de son jour et cumulé par compte (audit
  M1) ; un versement d'un jour sans change attend le premier jour qui en a, comme la ligne.

La série est gelée une fois construite : des lecteurs en même temps, aucun ne la change.
"""

from __future__ import annotations

from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any, Protocol

from hub.domains.finance.patrimoine.model.costed import Costed
from hub.domains.finance.patrimoine.model.positions import Holding, Positions
from hub.kernel.money import DECIMAL_CONTEXT

ABSENT = -(2**63)  # la ligne n'est pas dans le patrimoine ce jour-là
# enveloppes de by_envelope_json (spécification, section 2), tirées du type de compte
ENVELOPES = {"cash": "cash", "pension": "pilier3a", "securities": "titres", "crypto": "crypto"}
ENVELOPE_ORDER = ("cash", "pilier3a", "titres", "crypto", "dettes")


@dataclass(frozen=True)
class Account:
    id: str
    kind: str
    currency: str
    liquid: bool
    hidden: bool = False

    @property
    def envelope(self) -> str:
        return ENVELOPES[self.kind]


class Liability(Protocol):
    """Une dette vue par la série : sa clé `debt:<id>`, sa devise, son solde et son paiement
    d'un jour (debts.py les calcule)."""

    @property
    def key(self) -> str: ...

    @property
    def currency(self) -> str: ...

    def balance(self, on: str) -> int | None: ...

    def paid(self, on: str) -> int | None: ...


Moves = tuple[int, int, int, int]  # écritures d'un jour : total, revenus, frais, versements
Flows = Mapping[tuple[str, str], Mapping[str, tuple[Decimal, Decimal]]]


@dataclass(frozen=True)
class Inputs:
    days: tuple[str, ...]
    currency: str
    accounts: tuple[Account, ...]
    moves: Mapping[str, Mapping[str, Moves]]  # compte → jour → sommes (devise du compte)
    positions: Positions
    liabilities: Sequence[Liability]
    crypto_flows: Flows  # (compte, clé) → jour → (parts expliquées, flux), crypto_cost.walk
    goods: Sequence[Liability] = ()  # biens hors comptes : `balance` est leur valeur


@dataclass(frozen=True)
class Line:
    id: str  # "<compte>|<instrument>", "<compte>|cash" ou "debt:<id>"
    account_id: str  # le compte, ou la clé de la dette
    asset: str  # "isin:<instrument>", "ccy:<devise>" ou "debt:<id>" (vue Actifs de l'app)
    kind: str  # "position" | "cash" | "debt" | "good"
    hidden: bool
    value: Sequence[int]  # centimes ; ABSENT hors du patrimoine ce jour-là
    flow: Sequence[int]
    income: Sequence[int]
    fees: Sequence[int]
    missing: Sequence[int]  # 1 : aurait une valeur, mais pas de cours ou change
    costed: frozenset[int]  # jours au flux tiré des opérations (crypto)


class _Draft:
    """Une ligne en construction : ses tableaux se remplissent, puis se gèlent (`freeze`)."""

    def __init__(self, id_: str, account_id: str, asset: str, kind: str, hidden: bool, n: int):
        self.id, self.account_id, self.asset, self.kind, self.hidden = (
            id_,
            account_id,
            asset,
            kind,
            hidden,
        )
        self.value = array("q", [ABSENT]) * n
        self.flow = array("q", [0]) * n
        self.income = array("q", [0]) * n
        self.fees = array("q", [0]) * n
        self.missing = bytearray(n)
        self.costed: set[int] = set()

    def used(self) -> bool:
        return (
            any(v != ABSENT for v in self.value)
            or any(self.missing)
            or any(self.income)
            or any(self.fees)
        )

    def freeze(self) -> Line:
        return Line(
            self.id,
            self.account_id,
            self.asset,
            self.kind,
            self.hidden,
            memoryview(self.value).toreadonly(),
            memoryview(self.flow).toreadonly(),
            memoryview(self.income).toreadonly(),
            memoryview(self.fees).toreadonly(),
            bytes(self.missing),
            frozenset(self.costed),
        )


@dataclass(frozen=True)
class Series:
    days: tuple[str, ...]
    lines: Mapping[str, Line]
    currency: str
    banks: frozenset[str]  # comptes bancaires (type « cash ») : salaire et dépenses
    accounts: tuple[Account, ...]
    deposits: Mapping[str, Sequence[int]]  # compte → versements cumulés par jour (devise de base)
    missing_fx: Mapping[int, tuple[str, ...]]  # jour → comptes et dettes sans change
    unpriced: Mapping[int, tuple[tuple[str, str], ...]]  # jour → (compte, instrument) sans cours

    def index(self, on: str) -> int:
        """Indice du jour `on`, borné à la série."""
        if on <= self.days[0]:
            return 0
        if on >= self.days[-1]:
            return len(self.days) - 1
        return (date.fromisoformat(on) - date.fromisoformat(self.days[0])).days

    def default_ids(self) -> list[str]:
        """Les lignes de l'app : comptes non masqués et dettes."""
        return [i for i, ln in self.lines.items() if not ln.hidden]

    def account_lines(self, accounts: Sequence[str]) -> list[str]:
        """Toutes les lignes de ces comptes, d'hier comme d'aujourd'hui : une position vendue
        depuis garde son passé dans la performance du compte."""
        wanted = set(accounts)
        return [i for i, ln in self.lines.items() if ln.account_id in wanted]

    def values_at(self, k: int) -> dict[str, int]:
        """La valeur de chaque compte (et dette) le jour `k` : la somme de ses lignes."""
        out: dict[str, int] = {}
        for ln in self.lines.values():
            v = ln.value[k]
            if v != ABSENT:
                out[ln.account_id] = out.get(ln.account_id, 0) + v
        return out


def days(first: str, last: str) -> tuple[str, ...]:
    d, end = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return tuple(out)


def build(inp: Inputs) -> Series:
    b = _Builder(inp)
    for a in inp.accounts:
        b.account(a)
    for d in inp.liabilities:
        b.liability(d)
    for g in inp.goods:
        b.liability(g, good=True)
    return b.freeze()


class _Builder:
    def __init__(self, inp: Inputs) -> None:
        self.inp = inp
        self.n = len(inp.days)
        self.fx = inp.positions.fx
        self.drafts: dict[str, _Draft] = {}
        self.deposits: dict[str, array[int]] = {}
        self.nofx: dict[int, list[str]] = {}
        self.unpriced: dict[int, list[tuple[str, str]]] = {}
        self.crypto = {a.id for a in inp.accounts if a.kind == "crypto"}

    def line(self, id_: str, account_id: str, asset: str, kind: str, hidden: bool) -> _Draft:
        if id_ not in self.drafts:
            self.drafts[id_] = _Draft(id_, account_id, asset, kind, hidden, self.n)
        return self.drafts[id_]

    def conv(self, minor: int, currency: str, on: str) -> int | None:
        return 0 if minor == 0 else self.fx.to_base(minor, currency, on)

    @staticmethod
    def take(ln: Any, k: int, field_: str, converted: int | None) -> None:
        """Un montant sans change ne vaut pas 0 : la ligne est marquée incomplète ce jour-là
        (audit M6), et la série se dit partielle."""
        if converted is None:
            ln.missing[k] = 1
        else:
            getattr(ln, field_)[k] = converted

    def account(self, a: Account) -> None:
        positions = self.inp.positions
        moves = self.inp.moves.get(a.id, {})
        cash = self.line(f"{a.id}|cash", a.id, f"ccy:{a.currency}", "cash", a.hidden)
        holding = positions.holding(a.id) if a.id in positions.accounts else None
        balance = pending = total_deposits = 0
        cum = array("q", [0]) * self.n
        prev_q: dict[str, Decimal] = {}
        costed = None
        if a.id in self.crypto:
            costed = Costed(
                a.id,
                self.inp.crypto_flows,
                lambda i, acc=a.id, h=a.hidden: self.line(
                    f"{acc}|{i}", acc, f"isin:{i}", "position", h
                ),
            )
        for k, on in enumerate(self.inp.days):
            total, inc, fee, dep = moves.get(on, (0, 0, 0, 0))
            balance += total
            pending += dep  # un versement d'un jour sans change attend le premier qui en a
            if pending:
                converted = self.conv(pending, a.currency, on)
                if converted is not None:
                    total_deposits += converted
                    pending = 0
            cum[k] = total_deposits
            values: dict[str, tuple[Decimal, int | None]] = {}
            if holding is not None:
                values = self._values(a.id, holding, k, on)
            # sans aucun cours, le compte garde son solde au registre (valuation.held)
            fallback = holding is None or not values or all(v is None for _q, v in values.values())
            if fallback:
                if costed is not None:
                    costed.collect(on)  # pas de cours : les opérations attendent le premier
                if holding is not None and not values and balance == 0:
                    pass  # compte à positions vide : hors du patrimoine
                else:
                    self._cash(cash, a, k, on, balance, total, inc, fee, bool(values))
            else:
                # revenus et frais du compte à positions : déjà dans la valeur des parts, gardés
                # pour décomposer le gain ; la ligne « cash » n'a pas de valeur ici
                self.take(cash, k, "income", self.conv(inc, a.currency, on))
                self.take(cash, k, "fees", self.conv(fee, a.currency, on))
                if costed is not None:
                    costed.day(k, on, values)
                else:
                    self._positions(a, k, values, prev_q)
            prev_q = {isin: q for isin, (q, _v) in values.items()}
        self.deposits[a.id] = cum

    def _values(
        self, account_id: str, holding: Holding, k: int, on: str
    ) -> dict[str, tuple[Decimal, int | None]]:
        holding.advance(on)
        valued = self.inp.positions.valued(account_id, holding, on)
        unpriced = [(account_id, x.isin) for x in valued if x.price is None]
        if unpriced:
            self.unpriced.setdefault(k, []).extend(unpriced)
        return {x.isin: (x.quantity, None if x.price is None else x.value) for x in valued}

    def _cash(
        self,
        cash: _Draft,
        a: Account,
        k: int,
        on: str,
        balance: int,
        total: int,
        inc: int,
        fee: int,
        approx: bool,
    ) -> None:
        v = self.conv(balance, a.currency, on)
        if v is None:
            cash.missing[k] = 1
            self.nofx.setdefault(k, []).append(a.id)
            return
        cash.value[k] = v
        inside = self.conv(total - inc - fee, a.currency, on)
        cash.flow[k] = v if inside is None else inside  # même change que la valeur : jamais None
        self.take(cash, k, "income", self.conv(inc, a.currency, on))
        self.take(cash, k, "fees", self.conv(fee, a.currency, on))
        if approx:  # des parts sans aucun cours : valeur approchée par le registre
            cash.missing[k] = 1

    def _positions(
        self,
        a: Account,
        k: int,
        values: dict[str, tuple[Decimal, int | None]],
        prev_q: dict[str, Decimal],
    ) -> None:
        for isin, (q, value) in values.items():
            ln = self.line(f"{a.id}|{isin}", a.id, f"isin:{isin}", "position", a.hidden)
            if value is None:
                ln.missing[k] = 1
                continue
            ln.value[k] = value
            dq = q - prev_q.get(isin, Decimal(0))
            if dq:
                with localcontext(DECIMAL_CONTEXT):
                    ln.flow[k] = int((Decimal(value) * dq / q).to_integral_value())
        # parts vendues jusqu'à zéro : la ligne vaut 0, la vente est un flux
        for isin in prev_q:
            if isin in values:
                continue
            sold = self.drafts.get(f"{a.id}|{isin}")
            if sold is None or k == 0 or sold.value[k - 1] == ABSENT:
                continue
            sold.value[k] = 0
            sold.flow[k] = -sold.value[k - 1]

    def liability(self, d: Liability, good: bool = False) -> None:
        """Une dette (retranchée, son paiement est un flux) ou un bien hors comptes (ajouté ;
        toute variation de son estimation est un flux, jamais un effet marché)."""
        ln = self.line(d.key, d.key, d.key, "good" if good else "debt", False)
        prev = ABSENT
        for k, on in enumerate(self.inp.days):
            b = d.balance(on)
            if b is None:
                continue
            v = self.fx.to_base(b, d.currency, on)
            if v is None:
                ln.missing[k] = 1
                self.nofx.setdefault(k, []).append(d.key)
                continue
            ln.value[k] = v if good else -v
            if good and prev != ABSENT:
                ln.flow[k] = v - prev
            prev = v
            paid = d.paid(on)
            if paid is not None:
                self.take(ln, k, "flow", self.fx.to_base(paid, d.currency, on))

    def freeze(self) -> Series:
        # entrées et sorties du patrimoine : le saut est un flux, jamais un effet marché
        for ln in self.drafts.values():
            prev = ABSENT
            for k in range(self.n):
                cur = ln.value[k]
                if prev == ABSENT and cur != ABSENT and k not in ln.costed:
                    ln.flow[k] = cur
                    ln.income[k] = ln.fees[k] = 0
                elif prev != ABSENT and cur == ABSENT:
                    ln.flow[k] = -prev
                elif cur == ABSENT:
                    ln.flow[k] = 0
                prev = cur
        inp = self.inp
        return Series(
            inp.days,
            {i: ln.freeze() for i, ln in self.drafts.items() if ln.used()},
            inp.currency,
            frozenset(a.id for a in inp.accounts if a.kind == "cash"),
            inp.accounts,
            {a: memoryview(c).toreadonly() for a, c in self.deposits.items()},
            {k: tuple(v) for k, v in self.nofx.items()},
            {k: tuple(v) for k, v in self.unpriced.items()},
        )
