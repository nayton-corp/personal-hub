"""Stratégies : la phrase qui dit une stratégie (sur quoi, quand, le geste prévu) et ses
morceaux. Le même texte sert à la carte « À valider », à la liste et au détail."""

from __future__ import annotations

from hub.domains.finance.patrimoine.model import strategy as rules
from hub.kernel.money import Money, base_currency

WEEKDAYS = ("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
WINDOW_LABEL = {90: "des 3 derniers mois", 365: "des 12 derniers mois"}


def _list(raw: object) -> list[dict[str, int]]:
    return list(raw) if isinstance(raw, list) else []


def shown(minor: int) -> str:
    """« 200 CHF » pour un montant rond, « 212.50 CHF » sinon."""
    ccy = base_currency()
    shown_ = Money(minor, ccy).display()
    units, _dot, cents = shown_.partition(".")
    return f"{units if not cents.strip('0') else shown_} {ccy}"


def day_label(day: int) -> str:
    return "1er" if day == 1 else str(day)


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


def phrase(kind: str, name: str, params: dict[str, object], *, account: bool = False) -> str:
    """La stratégie en une phrase : sur quoi, quand, le geste prévu. `account` : une cible
    compte (on y verse, on n'achète pas)."""
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
        weekly = params["cadence"] == "weekly"
        when = f"Chaque {WEEKDAYS[day]}" if weekly else f"Le {day_label(day)} du mois"
        if account:
            return f"{when}, je verse {amount} sur {name}."
        return f"{when}, j'achète pour {amount} de {name}."
    window = WINDOW_LABEL[int(str(params["window_days"]))]
    return (
        f"Si {name} baisse de {params['drop_pct']} % depuis son plus haut {window}, "
        f"j'en achète pour {amount}."
    )
