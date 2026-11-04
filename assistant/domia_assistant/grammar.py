"""La voie rapide (spec §5.1) : une grammaire fermée construite depuis la maison (`GET /api/house`) et les synonymes
appris, sans modèle. Une phrase reconnue devient des gestes existants du catalogue (jamais `Toggle`) ; une phrase
ambiguë, inconnue ou avec un mot de trop rend None et part au modèle : mieux vaut ne rien faire que mal faire.

Pur : la maison et les synonymes entrent, un `Plan` sort ; aucun appel réseau ici.
"""

from __future__ import annotations

import re
from typing import Any

from .grammar_acts import (
    _act,
    _all_but,
    _num,
    _room,
    _simple,
    _situation,
)
from .grammar_lexicon import (
    CLITICS,
    KEEP,
    LEAD,
    ROOM,
    TENS,
    UNITS,
    VERBS,
    Gesture,
    Lexicon,
    Plan,
    Target,
    is_no,
    is_yes,
    normalize,
    strip_articles,
    words,
)

__all__ = [
    "Gesture",
    "Lexicon",
    "Plan",
    "Target",
    "is_no",
    "is_yes",
    "normalize",
    "parse",
    "read",
    "strip_articles",
    "words",
]


def parse(text: str, lex: Lexicon, room: str | None = None) -> Plan | None:
    """La phrase en gestes, ou None (le modèle la prend). `room` : la pièce d'où l'on parle, si on la connaît."""
    ws = _spoken(list(words(text)))
    if not ws:
        return None
    plan = _one(ws, lex, room)
    if plan is None:
        plan = _both(ws, lex, room)
    return plan


def _spoken(ws: list[str]) -> list[str]:
    """La phrase dite comme on parle : sans la politesse de tête (« tu peux », « vas-y »), le pronom collé au verbe
    retiré, les nombres en lettres en chiffres."""
    out: list[str] = []
    for w in ws:
        head, _, tail = w.partition("-")
        if tail and (tail in CLITICS or tail.split("-")[0] in CLITICS) and head in VERBS | KEEP:
            out.append(head)
        elif tail and all(p in UNITS or p in TENS or p == "et" for p in w.split("-")):
            out.extend(w.split("-"))
        else:
            out.append(w)
    while out and out[0] in LEAD and len(out) > 1:
        out = out[1:]
    return _numbers(out)


def _numbers(ws: list[str]) -> list[str]:
    """« à quarante » → « à 40 », « dix neuf degrés » → « 19 degrés » : seulement après « à » ou « sur », ou devant
    une unité, pour ne pas lire « les deux lampes » comme une valeur."""
    out: list[str] = []
    i = 0
    while i < len(ws):
        j, total, last = i, 0, None
        while j < len(ws):
            w = ws[j]
            if w in UNITS:
                total += UNITS[w]
            elif w == "cent":
                total = (total or 1) * 100
            elif w in TENS:
                total = total - 4 + 80 if last == "quatre" else total + TENS[w]
            elif w in {"un", "une"} and last == "et":
                total += 1
            elif w == "et" and last in TENS and j + 1 < len(ws) and ws[j + 1] in {"un", "une", "onze"}:
                pass
            else:
                break
            last, j = w, j + 1
        after = ws[j : j + 2]
        unit = after[:1] in (["%"], ["degres"], ["degre"]) or after == ["pour", "cent"]
        if j > i and (unit or (out and out[-1] in {"a", "sur"})):
            out.append(str(total))
            i = j
        else:
            out.append(ws[i])
            i += 1
    return out


def _both(ws: list[str], lex: Lexicon, room: str | None) -> Plan | None:
    """Deux demandes reliées par « et » ou « puis » (« ferme les stores puis passe en nuit ») : chacune reconnue
    seule, sinon le modèle prend toute la phrase."""
    for k, w in enumerate(ws):
        if w not in {"et", "puis"} or k == 0:
            continue
        left, right = ws[:k], ws[k + 1 :]
        if right[:1] == ["puis"]:
            right = right[1:]
        first = _one(left, lex, room) if left else None
        second = (_one(right, lex, room) or _both(right, lex, room)) if right else None
        if first and second:
            return Plan(first.gestures + second.gestures, "C'est fait.", first.confirm or second.confirm)
    return None


def _one(ws: list[str], lex: Lexicon, room: str | None) -> Plan | None:
    joined = " ".join(ws)
    plan = _situation(joined)
    if plan:
        return plan
    if re.fullmatch(r"(eteins|eteint|coupe) (tout|toute la maison|toutes les lumieres|la maison)( stp| svp)?", joined):
        rooms = [t for t in lex.targets if t.kind == ROOM]
        gestures = tuple(_room(t, "TurnOffRoom", f"{t.name} éteint") for t in rooms)
        return Plan(gestures, "C'est fait.", f"J'éteins les {len(rooms)} pièces ?") if rooms else None
    plan = _all_but(ws, lex)
    if plan:
        return plan
    if ws and ws[0] == "ici" and room is None:
        return None
    if "ici" in ws:
        here = lex.room(room) if room else None
        if here is None:
            return None
        ws = [w for w in ws if w != "ici"] + list(words(here.name))
    if ws[:3] == ["rends", "la", "main"]:
        return _simple(lex, ws[3:], "Release", "C'est rendu à l'auto.")
    if ws[0] in KEEP:
        tail = ws[1:]
        if tail and tail[-1] in {
            "allume",
            "allumee",
            "allumes",
            "allumees",
            "eteint",
            "eteinte",
            "eteints",
            "eteintes",
            "ainsi",
        }:
            tail = tail[:-1]
        elif tail[-2:] == ["comme", "ca"]:  # « garde le salon comme ça » : deux mots, jamais un
            tail = tail[:-2]
        return _simple(lex, tail, "KeepAsIs", "Je garde comme ça.")
    return _act(lex, ws)


TEMPERATURE = re.compile(
    r"(quelle?|combien)( est| de)? (la )?(temperature|degres)( fait il| il fait| fait-il)?"
    r"( au| a la| a l| dans le| dans la| dans l| de la| du| en)? (?P<room>.+?)( stp| svp)?"
)


LIT = re.compile(
    r"(qu est ce qui est|qu est ce qui est encore|quoi est|qui est|quelles? (lumieres?|lampes?) (sont|est)|"
    r"(est ce qu |y a t il |il y a )(il y a )?des (lumieres?|lampes?|trucs?|choses?))"
    r" allume(e|s|es)?( encore)?( dans la maison| a la maison| chez nous)?"
)


def read(text: str, lex: Lexicon, house: dict[str, Any], room: str | None = None) -> str | None:
    """Une lecture simple, sans modèle : la température d'une pièce, ce qui est allumé. None sinon."""
    joined = " ".join(words(text.replace("-", " ")))
    if LIT.fullmatch(joined):
        return _lit(house)
    m = TEMPERATURE.fullmatch(joined)
    if not m:
        return None
    name = tuple(m.group("room").split())
    if name == ("ici",):
        target = lex.room(room) if room else None
    else:
        targets = [t for t in lex.aliases.get(strip_articles(name), []) if t.kind == ROOM]
        target = targets[0] if len(targets) == 1 else None
    if target is None:
        return None
    value = next((r.get("temperature") for r in house.get("rooms", []) if r["id"] == target.id), None)
    if value is None:
        return f"{target.name} : pas de température connue."
    return f"{target.name} : {_num(round(float(value), 1))} °C."


def _lit(house: dict[str, Any]) -> str:
    rooms = []
    for r in house.get("rooms", []):
        on = [lamp for lamp in r.get("lights", []) if lamp.get("on")] + [
            a for a in r.get("appliances", []) or [] if a.get("on")
        ]
        if on:
            names = ", ".join(o.get("name") or o["id"] for o in on)
            rooms.append(f"{r.get('name') or r['id']} ({names})")
    return "Allumé : " + " ; ".join(rooms) + "." if rooms else "Tout est éteint."
