"""Les actes de la voie rapide : d'une phrase déjà découpée et d'un lexique, le plan d'un geste (tout sauf,
situation, allumer/éteindre/ouvrir/fermer, une valeur, un robot). Pur ; `grammar` les enchaîne."""

from __future__ import annotations

import re

from .grammar_lexicon import (
    APPLIANCE,
    CLOSE,
    COVER,
    EMITTER,
    EVERYTHING,
    EXCEPT,
    FILLER,
    LIGHT,
    MACHINE,
    NUMBER,
    OFF,
    ON,
    OPEN,
    ROOM,
    ROUTES,
    VERBS,
    Gesture,
    Lexicon,
    Plan,
    Target,
    _clean,
    _targets,
)


def _all_but(ws: list[str], lex: Lexicon) -> Plan | None:
    """« éteins tout sauf le salon » : les pièces nommées après « sauf » (ou « à part ») gardent leur état."""
    cut = next((k for k, w in enumerate(ws) if w in EXCEPT or ws[k : k + 2] == ["a", "part"]), None)
    if cut is None or ws[0] not in ON | OFF or not re.fullmatch(EVERYTHING, " ".join(ws[1:cut])):
        return None
    got = _targets(lex, ws[cut + (2 if ws[cut] == "a" else 1) :])
    if got is None or not got[0] or not _clean(got[1]) or any(t.kind != ROOM for t in got[0]):
        return None
    kept = {t.id for t in got[0]}
    on = ws[0] in ON
    gestures = tuple(
        _room(t, "TurnOnRoom" if on else "TurnOffRoom", t.name)
        for t in lex.targets
        if t.kind == ROOM and t.id not in kept
    )
    return Plan(gestures, "C'est fait.") if gestures else None


def _situation(joined: str) -> Plan | None:
    def to(value: str, answer: str, confirm: str | None = None) -> Plan:
        return Plan((Gesture("PUT", "/api/situation", {"value": value}, answer.rstrip(".")),), answer, confirm)

    # « passe en nuit », « mets la maison en mode nuit », « active le mode nuit » : un verbe ou le mot « mode »
    switch = r"((on )?(passe|mets|met|active|bascule)( la maison)? (en |au |le )?(mode )?|(le |en )?mode )"
    home = r"( a la maison| chez nous| chez moi)?"
    if re.fullmatch(switch + r"nuit|bonne nuit( la maison)?|on va (se )?coucher", joined):
        return to("NIGHT", "Mode Nuit.")
    if re.fullmatch(
        switch + r"jour|(je suis|on est|nous sommes) rentres?" + home + r"|bonjour la maison|on se leve", joined
    ):
        return to("DAY", "Mode Jour.")
    if re.fullmatch(switch + r"absent|(on part|je pars|nous partons|on s en va|on y va)" + home, joined):
        return to("AWAY", "Mode Absent.", "Je passe la maison en Absent ?")
    return None


def _room(t: Target, action: str, label: str) -> Gesture:
    return Gesture("POST", ROUTES[ROOM].format(id=t.id), {"action": action}, label)


def _simple(lex: Lexicon, ws: list[str], action: str, answer: str) -> Plan | None:
    """Garder, rendre la main : un geste sans valeur sur des pièces ou des lampes."""
    got = _targets(lex, ws)
    if got is None:
        return None
    targets, rest, _ = got
    if not targets or not _clean(rest) or any(t.kind not in (ROOM, LIGHT, APPLIANCE, COVER, EMITTER) for t in targets):
        return None
    return Plan(
        tuple(Gesture("POST", ROUTES[t.kind].format(id=t.id), {"action": action}, t.name) for t in targets), answer
    )


def _act(lex: Lexicon, ws: list[str]) -> Plan | None:
    # le verbe où qu'il soit (« la chambre, éteins ») ; deux verbes : pas pour la voie rapide
    at = [k for k, w in enumerate(ws) if w in VERBS]
    if len(at) > 1:
        return None
    verb = ws[at[0]] if at else ws[0]
    value = None
    unit = None
    tail = ws[: at[0]] + ws[at[0] + 1 :] if at else ws
    for i, w in enumerate(tail):
        if NUMBER.match(w):
            if value is not None:
                return None
            value = float(w)
            after = tail[i + 1 : i + 3]
            if after[:1] == ["%"] or after[:2] == ["pour", "cent"]:
                unit = "%"
            elif after[:1] in (["degres"], ["degre"]):
                unit = "C"
    if "%" in tail and ({"degres", "degre"} & set(tail)):
        return None  # deux unités : on ne choisit pas
    if value is not None:
        tail = [w for w in tail if not NUMBER.match(w) and w not in {"%", "degres", "degre", "pour", "cent"}]
    got = _targets(lex, tail)
    if got is None:
        return None
    targets, rest, kind = got
    if kind == MACHINE or any(t.kind == MACHINE for t in targets):
        return _robot(ws, targets, rest) if value is None else None
    if not targets or not _clean(rest):
        return None
    if value is not None:
        return _value(lex, targets, value, unit, kind)
    if verb in OPEN | CLOSE:
        if not all(t.kind == COVER for t in targets):
            return None
        position = 100 if verb in OPEN else 0
        return Plan(
            tuple(
                Gesture("POST", ROUTES[COVER].format(id=t.id), {"action": "SetPosition", "position": position}, t.name)
                for t in targets
            ),
            "C'est fait.",
        )
    if verb in ON | OFF:
        on = verb in ON
        gestures = []
        for t in targets:
            if t.kind == ROOM:
                gestures.append(_room(t, "TurnOnRoom" if on else "TurnOffRoom", t.name))
            elif t.kind in (LIGHT, APPLIANCE):
                gestures.append(
                    Gesture("POST", ROUTES[t.kind].format(id=t.id), {"action": "TurnOn" if on else "TurnOff"}, t.name)
                )
            else:
                return None
        return Plan(tuple(gestures), "C'est fait.")
    return None


def _value(lex: Lexicon, targets: list[Target], value: float, unit: str | None, kind: str | None) -> Plan | None:
    if len(targets) != 1 and kind is None:
        return None
    gestures = []
    head = targets[0]
    if unit == "C" or kind == EMITTER or all(t.kind == EMITTER for t in targets):
        if unit == "%":
            return None
        emitters = [
            e
            for t in targets
            for e in ([t] if t.kind == EMITTER else lex.in_room(EMITTER, t.id) if t.kind == ROOM else [])
        ]
        if not emitters or len(emitters) != len({e.id for e in emitters}):
            return None
        for e in emitters:
            gestures.append(
                Gesture("POST", ROUTES[EMITTER].format(id=e.id), {"action": "SetSetpoint", "setpoint_c": value}, e.name)
            )
        return Plan(tuple(gestures), f"{head.name} à {_num(value)} °C.")
    pct = int(value)
    if value != pct or not 0 <= pct <= 100:
        return None
    if all(t.kind == COVER for t in targets):
        gestures = [
            Gesture("POST", ROUTES[COVER].format(id=t.id), {"action": "SetPosition", "position": pct}, t.name)
            for t in targets
        ]
        return Plan(tuple(gestures), f"{head.name} à {pct} %.")
    lights = [
        lamp
        for t in targets
        for lamp in ([t] if t.kind == LIGHT else lex.in_room(LIGHT, t.id) if t.kind == ROOM else [])
    ]
    if len(lights) == 0 or any(t.kind not in (ROOM, LIGHT) for t in targets):
        return None
    dimmable = [lamp for lamp in lights if lamp.dimmable]
    if not dimmable:
        return None
    gestures = [
        Gesture("POST", ROUTES[LIGHT].format(id=lamp.id), {"action": "SetBrightness", "brightness_pct": pct}, lamp.name)
        for lamp in dimmable
    ]
    return Plan(tuple(gestures), f"{head.name} à {pct} %.")


ROBOT_WORDS = {
    "lance",
    "demarre",
    "nettoie",
    "aspire",
    "base",
    "rentre",
    "retour",
    "pause",
    "reprends",
    "reprend",
    "arrete",
    "stop",
}


def _robot(ws: list[str], targets: list[Target], rest: list[str]) -> Plan | None:
    """Le robot (spec des robots) : rentrer, pause, reprendre, arrêter, ou nettoyer des pièces nommées."""
    machines = [t for t in targets if t.kind == MACHINE]
    if len(machines) != 1 or not all(w in FILLER or w in ROBOT_WORDS for w in rest):
        return None
    m = machines[0]
    path = ROUTES[MACHINE].format(id=m.id)
    joined = " ".join(ws)
    for pattern, action, answer in (
        (r"\b(a la base|rentre|retour)\b", "ReturnToBase", "Le robot rentre à la base."),
        (r"\bpause\b", "Pause", "Le robot fait une pause."),
        (r"\breprends?\b", "Resume", "Le robot reprend."),
        (r"\b(arrete|stop)\b", "Stop", "Le robot s'arrête."),
    ):
        if re.search(pattern, joined):
            return Plan((Gesture("POST", path, {"action": action}, m.name),), answer)
    if ws[0] in {"lance", "demarre", "nettoie", "aspire"} or (
        rest and rest[0] in {"lance", "demarre", "nettoie", "aspire"}
    ):
        rooms_named = [t for t in targets if t.kind == ROOM]
        if not rooms_named:
            return None  # quel programme ? le modèle demande
        ids = [r.id for r in rooms_named]
        names = ", ".join(r.name for r in rooms_named)
        return Plan(
            (Gesture("POST", path, {"action": "StartCleaning", "room_ids": ids}, m.name),), f"Le robot part : {names}."
        )
    return None


def _num(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value).replace(".", ",")
