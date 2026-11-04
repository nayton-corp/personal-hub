"""Le lexique de la voie rapide (spec §5.1) : les mots (verbes, nombres, remplissage), la normalisation d'une
phrase, et le lexique de la maison (`Lexicon`, construit de `GET /api/house` et des synonymes appris) avec ses
cibles, gestes et plans. Pur."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

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
    body: dict[str, Any] | None
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
    def of(cls, house: dict[str, Any], synonyms: dict[str, tuple[str, str]] | None = None) -> Lexicon:
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
