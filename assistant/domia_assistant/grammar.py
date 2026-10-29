"""La voie rapide (spec §5.1) : une grammaire fermée construite depuis la maison (`GET /api/house`) et les synonymes
appris, sans modèle. Une phrase reconnue devient des gestes existants du catalogue (jamais `Toggle`) ; une phrase
ambiguë, inconnue ou avec un mot de trop rend None et part au modèle : mieux vaut ne rien faire que mal faire.

Pur : la maison et les synonymes entrent, un `Plan` sort ; aucun appel réseau ici.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ROOM, LIGHT, APPLIANCE, COVER, EMITTER, MACHINE = "room", "light", "appliance", "cover", "emitter", "machine"
ROUTES = {
    ROOM: "/api/rooms/{id}/commands",
    LIGHT: "/api/lights/{id}/commands",
    APPLIANCE: "/api/appliances/{id}/commands",
    COVER: "/api/covers/{id}/commands",
    EMITTER: "/api/emitters/{id}/commands",
    MACHINE: "/api/machines/{id}/commands",
}

# les mots qui ne changent pas le sens : leur présence n'empêche pas la voie rapide
FILLER = set(
    [
        "le",
        "la",
        "les",
        "l",
        "du",
        "de",
        "des",
        "d",
        "un",
        "une",
        "au",
        "aux",
        "a",
        "en",
        "dans",
        "sur",
        "pour",
        "moi",
        "nous",
        "stp",
        "svp",
        "merci",
        "please",
        "s",
        "il",
        "te",
        "plait",
        "vous",
        "est-ce",
        "que",
        "peux",
        "tu",
        "pourrais",
        "tu",
        "veux",
        "bien",
    ]
)
FILLER |= {"te", "plait", "tu", "peux", "pourrais", "veux", "bien", "est", "ce", "que", "et", "puis", "aussi"}
KIND_WORDS = {
    LIGHT: {"lumiere", "lumieres", "lampe", "lampes", "eclairage"},
    COVER: {"volet", "volets", "store", "stores", "rideau", "rideaux"},
    EMITTER: {"chauffage", "radiateur", "radiateurs", "thermostat"},
    MACHINE: {"robot", "aspirateur"},
}
ON = {"allume", "allumer", "eclaire", "eclairer", "rallume"}
OFF = {"eteins", "eteint", "eteindre", "coupe", "couper"}
OPEN = {"ouvre", "ouvrir", "monte", "remonte"}
CLOSE = {"ferme", "fermer", "baisse", "descends", "descend"}
SET = {"mets", "met", "mettre", "regle", "regler", "passe", "monte", "baisse"}
KEEP = {"garde", "garder", "laisse", "laisser"}
YES = {"oui", "ok", "vas-y", "vas y", "d accord", "daccord", "confirme", "go", "c est bon", "ouais"}
NO = {"non", "annule", "laisse tomber", "pas maintenant", "stop"}
VERBS = ON | OFF | OPEN | CLOSE | SET
# « éteins-la », « garde-le » : le pronom collé au verbe ne change pas le geste
CLITICS = {"la", "le", "les", "lui", "leur", "moi", "toi", "nous", "vous", "y", "en"}
LEAD = FILLER | {"vas-y", "vas", "y", "allez", "alors", "bon", "eh", "hey"}
# les nombres dits en toutes lettres (« à quarante », « dix-neuf degrés ») ; « un » n'est un nombre qu'après « et »
UNITS = dict(
    zip(
        [
            "zero",
            "deux",
            "trois",
            "quatre",
            "cinq",
            "six",
            "sept",
            "huit",
            "neuf",
            "dix",
            "onze",
            "douze",
            "treize",
            "quatorze",
            "quinze",
            "seize",
        ],
        [0, *range(2, 17)],
        strict=False,
    )
)
TENS = {"vingt": 20, "vingts": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100}
EXCEPT = {"sauf", "excepte", "hormis"}
EVERYTHING = r"(tout|toute la maison|toutes les pieces|toutes les lumieres|partout)"


def normalize(text: str) -> str:
    """minuscules, sans accents, l'apostrophe et la ponctuation en espaces ; « 20,5 » garde sa virgule en point."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    text = re.sub(r"\ba(\d)", r"a \1", text)  # « à33% », tapé vite
    text = text.replace("°", " degres ").replace("%", " % ")
    text = re.sub(r"[’'`]", " ", text)
    text = re.sub(r"[^a-z0-9.% -]", " ", text)
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def words(text: str) -> tuple[str, ...]:
    return tuple(normalize(text).split())


def strip_articles(ws: tuple[str, ...]) -> tuple[str, ...]:
    while ws and ws[0] in {"le", "la", "les", "l", "du", "de", "des", "d", "un", "une"}:
        ws = ws[1:]
    return ws


def is_yes(text: str) -> bool:
    n = normalize(text)
    return n in YES or n.split()[:1] == ["oui"]


def is_no(text: str) -> bool:
    n = normalize(text)
    return n in NO or n.split()[:1] == ["non"]


@dataclass(frozen=True)
class Target:
    kind: str
    id: str
    name: str
    room: str | None = None
    dimmable: bool = True


@dataclass(frozen=True)
class Gesture:
    method: str
    path: str
    body: dict | None
    label: str


@dataclass(frozen=True)
class Plan:
    gestures: tuple[Gesture, ...]
    answer: str
    confirm: str | None = None  # la question posée avant de jouer un geste qui touche toute la maison


@dataclass
class Lexicon:
    targets: list[Target]
    aliases: dict[tuple[str, ...], list[Target]] = field(default_factory=dict)

    @classmethod
    def of(cls, house: dict, synonyms: dict[str, tuple[str, str]] | None = None) -> Lexicon:
        targets: list[Target] = []
        for room in house.get("rooms", []):
            targets.append(Target(ROOM, room["id"], room.get("name") or room["id"]))
            for light in room.get("lights", []):
                targets.append(
                    Target(
                        LIGHT,
                        light["id"],
                        light.get("name") or light["id"],
                        room["id"],
                        bool(light.get("dimmable", True)),
                    )
                )
            for kind, key in ((APPLIANCE, "appliances"), (COVER, "covers"), (EMITTER, "emitters")):
                for o in room.get(key, []) or []:
                    targets.append(Target(kind, o["id"], o.get("name") or o["id"], room["id"]))
        for m in house.get("machines", []) or []:
            targets.append(Target(MACHINE, m["id"], m.get("name") or m["id"], m.get("room")))
        lex = cls(targets)
        for t in targets:
            lex._alias(words(t.name.replace("_", " ")), t)
        by_id = {(t.kind, t.id): t for t in targets}
        for phrase, pair in (synonyms or {}).items():
            if pair in by_id:
                lex._alias(words(phrase), by_id[pair])
        return lex

    def _alias(self, ws: tuple[str, ...], target: Target) -> None:
        ws = strip_articles(ws)
        if ws and target not in self.aliases.setdefault(ws, []):
            self.aliases[ws].append(target)

    def room(self, room_id: str) -> Target | None:
        return next((t for t in self.targets if t.kind == ROOM and t.id == room_id), None)

    def in_room(self, kind: str, room_id: str) -> list[Target]:
        return [t for t in self.targets if t.kind == kind and t.room == room_id]

    def resolve(self, phrase: str) -> Target | None:
        """Une phrase qui nomme exactement un objet (pour apprendre un synonyme) ; sinon None."""
        got = _targets(self, list(words(phrase)))
        if got is None:
            return None
        targets, rest, kind = got
        if len(targets) != 1 or not _clean(rest) or (kind is not None and targets[0].kind != kind):
            return None
        return targets[0]

    def mentions(self, ws: list[str]) -> tuple[list[list[Target]], list[str]] | None:
        """Les objets nommés, du plus long nom au plus court, sans chevauchement ; et les mots restants."""
        used = [False] * len(ws)
        found: list[tuple[int, list[Target]]] = []
        for alias in sorted(self.aliases, key=len, reverse=True):
            n = len(alias)
            for i in range(len(ws) - n + 1):
                if tuple(ws[i : i + n]) == alias and not any(used[i : i + n]):
                    found.append((i, self.aliases[alias]))
                    for j in range(i, i + n):
                        used[j] = True
        found.sort(key=lambda f: f[0])
        rest = [w for w, u in zip(ws, used, strict=False) if not u]
        return [f[1] for f in found], rest


NUMBER = re.compile(r"^\d+(\.\d+)?$")


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


def read(text: str, lex: Lexicon, house: dict, room: str | None = None) -> str | None:
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


def _lit(house: dict) -> str:
    rooms = []
    for r in house.get("rooms", []):
        on = [lamp for lamp in r.get("lights", []) if lamp.get("on")] + [
            a for a in r.get("appliances", []) or [] if a.get("on")
        ]
        if on:
            names = ", ".join(o.get("name") or o["id"] for o in on)
            rooms.append(f"{r.get('name') or r['id']} ({names})")
    return "Allumé : " + " ; ".join(rooms) + "." if rooms else "Tout est éteint."


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


def _clean(rest: list[str]) -> bool:
    """Plus aucun mot qui compte : la phrase est entièrement comprise."""
    return all(w in FILLER for w in rest)


def _targets(lex: Lexicon, ws: list[str]) -> tuple[list[Target], list[str], str | None] | None:
    """Les objets visés et les mots restants. « le volet du salon » : les volets du salon ; « la lampe du salon » : la
    pièce. Un nom qui désigne plusieurs objets sans pièce pour trancher : None."""
    kind = None
    kept = []
    for w in ws:
        k = next((k for k, s in KIND_WORDS.items() if w in s), None)
        if k and kind is None:
            kind = k
        elif k:
            return None
        else:
            kept.append(w)
    mentioned = lex.mentions(kept)
    if mentioned is None:
        return None
    found, rest = mentioned
    rooms = {ts[0].id for ts in found if len(ts) == 1 and ts[0].kind == ROOM}
    out: list[Target] = []
    for ts in found:
        if len(ts) > 1:
            ts = [t for t in ts if t.room in rooms]
            if len(ts) != 1:
                return None
        out.append(ts[0])
    objects = [t for t in out if t.kind != ROOM]
    # « la lampe du salon » : la pièce nommée pour situer un objet nommé n'est pas une cible de plus
    if objects:
        out = [t for t in out if t.kind != ROOM or t.id not in {o.room for o in objects}]
    if kind == MACHINE:
        machines = [t for t in out if t.kind == MACHINE] or [t for t in lex.targets if t.kind == MACHINE]
        if len(machines) != 1 or any(t.kind not in (ROOM, MACHINE) for t in out):
            return None
        return [t for t in out if t.kind == ROOM] + machines, rest, kind
    if kind in (COVER, EMITTER):
        expanded: list[Target] = []
        for t in out:
            if t.kind == ROOM:
                expanded.extend(lex.in_room(kind, t.id))
            elif t.kind == kind:
                expanded.append(t)
            else:
                return None
        out = expanded
    return out, rest, kind


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
