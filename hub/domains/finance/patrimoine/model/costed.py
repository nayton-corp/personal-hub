"""Les lignes d'un compte crypto dans la série (engine.py) : le flux d'un jour, ce
sont ses opérations (crypto_cost.walk), et le reste de la variation des parts, que rien
n'explique (une rupture, reconcile.py), au cours du jour."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

from hub.kernel.money import DECIMAL_CONTEXT


class Costed:
    """Les lignes d'un compte crypto : le flux d'un jour, ce sont ses opérations (crypto_cost.walk),
    et le reste de la variation des parts, que rien n'explique (une rupture, reconcile.py), au
    cours du jour. Les opérations d'un jour sans cours attendent le premier cours : la ligne
    entre alors à ce qu'elle a coûté, pas à sa valeur du jour."""

    def __init__(
        self,
        account: str,
        legs: Mapping[tuple[str, str], Mapping[str, tuple[Decimal, Decimal]]],
        line: Any,
    ) -> None:
        self.line = line
        self.legs = {key: days for (acc, key), days in legs.items() if acc == account}
        self.priced: dict[str, Decimal] = {}  # parts au dernier jour valorisé
        self.pending: dict[str, tuple[Decimal, Decimal]] = {}  # opérations depuis ce jour
        self.unit: dict[str, Decimal] = {}  # valeur d'une part ce jour-là

    def collect(self, on: str) -> None:
        """Les opérations du jour, en attente du jour valorisé qui les compte."""
        zero = Decimal(0)
        with localcontext(DECIMAL_CONTEXT):
            for key, days in self.legs.items():
                if on in days:
                    pq, pf = self.pending.get(key, (zero, zero))
                    dq, df = days[on]
                    self.pending[key] = (pq + dq, pf + df)

    def day(self, k: int, on: str, values: dict[str, tuple[Decimal, int | None]]) -> None:
        zero = Decimal(0)
        line = self.line
        self.collect(on)
        with localcontext(DECIMAL_CONTEXT):
            for key, (q, value) in values.items():
                ln = line(key)
                if value is None:
                    ln.missing[k] = 1
                    continue
                pq, pf = self.pending.pop(key, (zero, zero))
                unit = Decimal(value) / q
                rest = q - self.priced.get(key, zero) - pq  # parts que rien n'explique
                ln.value[k] = value
                ln.flow[k] = int((pf + rest * unit).to_integral_value())
                ln.costed.add(k)
                self.priced[key], self.unit[key] = q, unit
            for key in [x for x in self.pending if x not in values]:
                # tout vendu, ou un aller-retour du jour : valeur 0, ses opérations font le flux
                pq, pf = self.pending.pop(key)
                had = self.priced.pop(key, zero)
                rest = -had - pq
                ln = line(key)
                ln.value[k] = 0
                ln.flow[k] = int((pf + rest * self.unit.get(key, zero)).to_integral_value())
                ln.costed.add(k)
            for key in [x for x in self.priced if x not in values]:  # sorti sans opération
                had = self.priced.pop(key)
                ln = line(key)
                ln.value[k] = 0
                ln.flow[k] = int((-had * self.unit.get(key, zero)).to_integral_value())
                ln.costed.add(k)
