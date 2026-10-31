"""Événements de la courbe du patrimoine : les gros versements et retraits, et les revenus
(dividendes, coupons), un agrégat par jour, jamais une écriture.

Sur une sélection qui contient des placements, seuls les comptes qui ne sont pas des comptes
bancaires comptent : un salaire ou un loyer n'est pas un événement de l'épargne, un versement sur
le compte de titres ou de prévoyance en est un. Une sélection de comptes bancaires seuls n'a donc
pas d'événement. Un flux n'est retenu qu'à partir d'un seuil, le plus grand de 1 500 de la
devise de base et de 4 % de la valeur de la sélection la veille ; un revenu, à partir de 10.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from hub.domains.finance.patrimoine.app.perf_lines import Engine, Line
from hub.domains.finance.registre.model.amounts import money

FLOOR = 150_000  # 1 500 de la devise de base, en centimes
SHARE_PCT = 4  # % de la valeur de la veille
INCOME_FLOOR = 1_000  # 10 de la devise de base
MAX_EVENTS = 80  # les plus gros, puis remis dans l'ordre des dates


def events(
    eng: Engine, chosen: Sequence[Line], ks: int, ke: int, value: Sequence[int]
) -> list[dict[str, Any]]:
    """Événements entre les jours `ks` et `ke` ; `value` : la valeur de la sélection, jour par
    jour depuis `ks`."""
    lines = [ln for ln in chosen if ln.kind != "debt" and ln.account_id not in eng.banks]
    found: list[tuple[int, int, str, int]] = []  # (poids, jour, sorte, montant)
    if not lines:
        return []
    for j in range(1, ke - ks + 1):
        k = ks + j
        flow = sum(ln.flow[k] for ln in lines)
        income = sum(ln.income[k] for ln in lines)
        floor = max(FLOOR, max(value[j - 1], 0) * SHARE_PCT // 100)
        if abs(flow) >= floor:
            found.append((abs(flow), k, "in" if flow > 0 else "out", flow))
        if income >= INCOME_FLOOR:
            found.append((income, k, "income", income))
    found.sort(reverse=True)
    kept = sorted(found[:MAX_EVENTS], key=lambda e: (e[1], e[2]))
    return [
        {"on_date": eng.days[k], "kind": kind, "amount": money(amount, eng.currency)}
        for _w, k, kind, amount in kept
    ]
