"""La conversation (spec §5, §6) : une phrase, qui la dit et d'où ; la voie rapide d'abord, le modèle et ses outils
sinon. Rend {answer, done[], proposals[], confirm} : la réponse courte, ce qui a été fait, et la question posée avant
un geste qui touche toute la maison (la phrase suivante « oui » le joue, « non » l'oublie)."""

from __future__ import annotations

import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import grammar
from .domia import Domia, DomiaError
from .llm import Model, ModelError
from .memory import Memory
from .settings import PROPOSAL_TTL
from .tools import FAMILIES, Speaker, Toolbox

LOG = logging.getLogger("assistant")

CONFIRM_TTL_SEC = 60
SYNONYM = re.compile(r"^\s*(?P<phrase>.{2,40}?)\s*,?\s+c'?\s*est\s+(?P<target>.{2,60}?)\s*[.!]?\s*$", re.IGNORECASE)

SYSTEM = """Tu es l'assistant de la maison, un membre discret du foyer. Tu réponds en français, en une ou deux phrases.
Tu ne fais que ce que tes outils permettent ; les gestes partent au nom de la personne qui parle.
La maison et les id de ses objets sont listés plus bas ; leur état du moment (allumé, position, température) se lit
avec `house`. Ne devine jamais un id. Pour agir, appelle l'outil du geste : je dis moi-même à la personne ce que
les gestes ont fait ; ta réponse ne le redit pas, elle ajoute seulement le reste (ce qu'on t'a demandé de lire, une
question), ou rien. Si l'objet demandé n'existe pas dans la pièce nommée, dis-le au lieu d'agir sur un autre.
Une demande ambiguë : pose une question courte au lieu d'agir. Une demande dangereuse ou hors de la maison : refuse.
La liste ne porte que les objets pilotés. Les autres appareils du foyer et le logement (manuels, fiches, garanties,
bail) sont dans la bibliothèque : pour une panne, un entretien, une garantie ou une question sur le logement,
cherche-y (`search_library`, `object_card`) avant de répondre, même si l'appareil n'est pas dans la liste.
Où une chose est rangée, ce que le foyer a noté : cherche avec `recall`, ne l'invente jamais.
« Pourquoi » un objet ou une pièce est dans son état : appelle `why` avec son id avant de répondre.
L'heure du coucher, du lever, d'un départ : `situations` (ce qui s'est passé) ou `habits` (l'habitude). « Tout va bien ? », un point sur la maison : `observations`.
Un geste agit tout de suite et ne se programme pas. Ce qui doit valoir plus tard ou à chaque fois (un délai, un seuil,
une loi, une plage) est un réglage : `settings` le lit, `explain` dit le sens de ses champs.{write}
Ce qui s'est passé ces dernières heures : `activity`. Domia lui-même (HA, disque, capteurs muets) : `system_status`.
Demain, la météo : `plan_tomorrow`, `weather`. Un « oui » à une proposition en attente (listée plus bas) : `accept_planned` ;
« qu'as-tu prévu ? » : `planned` ; « annule le robot » : `cancel_planned` avec son id.
Nomme la situation en français : Jour, Nuit, Absent.
Quand tu réponds avec un document, dis ce qu'il dit (la cause, quoi faire), puis sa source (fichier et page). « Je ne sais pas » est une bonne réponse.
Ne parle jamais de tes outils ni de JSON."""
# changer un réglage : seulement quand l'assistant en a le droit (`assistant.settings_write`) ; sinon il dit où le changer
WRITE = """ Choisis le champ par son sens,
puis `propose_settings` avec les seuls champs qui changent (délais en secondes). Je pose moi-même la question, n'appelle
jamais `apply_settings` toi-même. « Annule » : `undo_settings`."""
READ_ONLY = """ Tu ne changes pas un réglage : dis sa valeur
actuelle, puis qu'il se change dans Réglages."""


RESULT_CHARS = 3000


@dataclass
class Pending:
    token: str
    calls: list[tuple[str, dict]]  # (outil, arguments) ; "_gesture" pour un geste de la voie rapide
    answer: str
    expires: float


class Assistant:
    def __init__(
        self,
        domia: Domia,
        model: Model,
        memory: Memory,
        toolbox: Callable[[], Toolbox],
        timezone: str = "Europe/Zurich",
        max_steps: int = 6,
        clock: Callable[[], float] = time.monotonic,
        engagements: Any | None = None,
        route: bool = False,
    ):
        self.domia = domia
        self.model = model
        self.memory = memory
        self.toolbox = toolbox
        self.zone = ZoneInfo(timezone)
        self.max_steps = max_steps
        self.clock = clock
        self.pending: dict[str, Pending] = {}
        self.lock = threading.Lock()
        self.engagements = engagements
        self.route = route

    def talk(self, text: str, who: Speaker, voice: bool = False) -> dict:
        text = text.strip()
        answer = self._talk(text, who)
        self.memory.log(who.person, who.room, text, answer.get("answer", ""), voice=voice, done=answer.get("done"))
        return answer

    def _talk(self, text: str, who: Speaker) -> dict:
        key = who.client or who.person or who.room or "_"
        with self.lock:
            pending = self.pending.pop(key, None)
        if pending and grammar.is_no(text):
            # un « non » clôt la proposition, même après le délai : un oui plus tard ne la rejouera pas
            for name, args in pending.calls:
                if name == "apply_settings":
                    self.memory.settings_refused(int(args["proposal"]))
            return reply("D'accord, je ne fais rien.")
        if pending and pending.expires > self.clock() and grammar.is_yes(text):
            return self._play(pending, who)
        answered = self._answer_plan(text, who)
        if answered:
            return answered
        house = self.domia.house()
        lex = grammar.Lexicon.of(house, self.memory.synonyms())
        learned = self._learn(text, lex, who)
        if learned:
            return learned
        reading = grammar.read(text, lex, house, who.room)
        if reading is not None:
            return reply(reading)
        plan = grammar.parse(text, lex, who.room)
        if plan is not None:
            calls = [
                ("_gesture", {"method": g.method, "path": g.path, "body": g.body, "label": g.label})
                for g in plan.gestures
            ]
            if plan.confirm:
                return self._ask(key, calls, plan.confirm, plan.answer)
            return self._play(Pending("", calls, plan.answer, 0), who)
        return self._model(text, who, house, key)

    def _answer_plan(self, text: str, who: Speaker) -> dict | None:
        """« Oui » ou « non » juste après le plan du soir : la première phrase de la personne depuis les propositions.
        Après un autre échange, un « oui » peut répondre à autre chose : le modèle décide (`accept_planned`)."""
        if self.engagements is None or not (grammar.is_yes(text) or grammar.is_no(text)):
            return None
        now = datetime.now(UTC)
        waiting = self.engagements.waiting(now)
        if not waiting:
            return None
        last = self.memory.last_talk(who.person)
        if last and last > max(e["offered_at"] for e in waiting):
            return None
        if grammar.is_no(text):
            self.engagements.refuse(now)
            return reply("D'accord, je ne prévois rien.")
        accepted = self.engagements.accept(None, who.person, now)
        return reply(
            "C'est noté pour demain." if len(accepted) > 1 else "C'est noté.",
            [f"prévu : {e['kind']}" for e in accepted],
        )

    def _learn(self, text: str, lex: grammar.Lexicon, who: Speaker) -> dict | None:
        """« La baie, c'est le volet du salon » : un synonyme pour la voie rapide, seulement s'il nomme un seul objet."""
        m = SYNONYM.match(text)
        if not m:
            return None
        target = lex.resolve(m.group("target"))
        if target is None or lex.resolve(m.group("phrase")) is not None:
            return None
        phrase = " ".join(grammar.strip_articles(grammar.words(m.group("phrase"))))
        if not phrase:
            return None
        self.memory.learn(phrase, target.kind, target.id, who.person)
        return reply(f"Noté : {m.group('phrase').strip()}, c'est {target.name}.")

    def _ask(self, key: str, calls: list[tuple[str, dict]], question: str, answer: str) -> dict:
        token = secrets.token_hex(4)
        # un réglage se relit et se pèse : son oui attend autant que la proposition (15 min), un geste une minute
        ttl = PROPOSAL_TTL.total_seconds() if any(n == "apply_settings" for n, _ in calls) else CONFIRM_TTL_SEC
        with self.lock:
            self.pending[key] = Pending(token, calls, answer, self.clock() + ttl)
        return {"answer": question, "done": [], "proposals": [], "confirm": token}

    def _play(self, pending: Pending, who: Speaker) -> dict:
        done, errors = [], []
        tools = None
        for name, args in pending.calls:
            if name == "_gesture":
                try:
                    self.domia.gesture(args["method"], args["path"], args["body"], who.person)
                    done.append(args["label"])
                except DomiaError as e:
                    errors.append(f"{args['label']} : {e.message or e.code}")
            else:
                tools = tools or self.toolbox()
                result = tools.run(name, args, who)
                if isinstance(result, dict) and "error" in result:
                    errors.append(str(result["error"]))
                else:
                    done.append(_label(name, args))
        if errors and not done:
            return reply("Je n'ai pas pu : " + "; ".join(errors))
        if errors:
            return reply(pending.answer + " Sauf : " + "; ".join(errors), done)
        return reply(pending.answer, done)

    def _context(self, house: dict, who: Speaker) -> str:
        now = datetime.now(self.zone)
        people = {p.get("id"): p for p in house.get("people", []) or []}
        speaker = people.get(who.person, {}).get("name") if who.person else None
        home = [p.get("name") for p in people.values() if p.get("home")]
        room = next((r.get("name") for r in house.get("rooms", []) if r["id"] == who.room), None)
        situation = (house.get("situation") or {}).get("value")
        lines = [
            f"Maintenant : {now:%A %d %B %Y, %H:%M}.",
            f"Situation : {SITUATIONS.get(situation or '', situation)}.",
            f"Qui parle : {speaker or ('une voix dans la pièce' if who.room else 'inconnu')}.",
            f"Qui est là : {', '.join(home) or 'personne de connu'}.",
        ]
        if room:
            lines.append(f"Pièce où l'on parle : {room} ({who.room}).")
        if self.engagements is not None:
            waiting = self.engagements.waiting(datetime.now(UTC))
            if waiting:
                lines.append(
                    "Propositions en attente d'un oui : " + " | ".join(f"[{e['id']}] {e['question']}" for e in waiting)
                )
        recent = self.memory.recent(who.person, 4)
        if recent:
            lines.append("Derniers échanges : " + " | ".join(f"« {r['text']} » → « {r['answer']} »" for r in recent))
        return "\n".join(lines)

    def _families(self, text: str, person: str | None = None) -> frozenset[str] | None:
        """Le premier temps : un appel court, sans outils, qui nomme le ou les types de la demande (avec l'échange
        d'avant, pour « et dans la chambre ? »). Rien de reconnu : tous les outils, comme sans routage."""
        last = self.memory.recent(person, 1) if person else []
        before = f"Échange précédent : « {last[0]['text']} » → « {last[0]['answer']} »\n" if last else ""
        try:
            said = self.model.chat([ROUTER, {"role": "user", "content": before + "Demande : " + text}], [])
        except ModelError:
            return None
        named = grammar.normalize(said.get("content") or "")
        found = frozenset(f for f in FAMILIES if grammar.normalize(f) in named)
        LOG.info("route families=%s", ",".join(sorted(found)) or "toutes")
        return found or None

    def warm(self) -> None:
        """Charge le modèle et calcule son préfixe (système, maison, outils) avant la première vraie question : sans ça,
        la première phrase après un redémarrage du Mac attend ~40 s. Lève ModelError si le modèle ne répond pas."""
        house = self.domia.house()
        box = self.toolbox()
        system = self._system(house, box)
        ok = {"role": "user", "content": "Demande : rien, réponds juste ok."}
        if not self.route:
            self.model.chat([system, ok], box.schemas())
            return
        self._families("rien")
        for family in FAMILIES:  # un préfixe par type de demande, chacun dans son cache
            self.model.chat([system, ok], box.schemas(frozenset({family})))

    @staticmethod
    def _system(house: dict, tools: Toolbox) -> dict:
        prompt = SYSTEM.format(write=WRITE if "propose_settings" in tools.tools else READ_ONLY)
        return {"role": "system", "content": prompt + "\n\nLa maison :\n" + "\n".join(inventory(house))}

    def _model(self, text: str, who: Speaker, house: dict, key: str) -> dict:
        tools = self.toolbox()
        families = self._families(text, who.person) if self.route else None
        messages: list[dict] = [
            # Le système et les outils restent les mêmes d'une phrase à l'autre : le serveur de modèle garde leur calcul
            # (le préfixe), seul le moment (heure, qui parle, derniers échanges) est relu, avec la demande.
            self._system(house, tools),
            {"role": "user", "content": self._context(house, who) + "\n\nDemande : " + text},
        ]
        done: list[str] = []
        acts: list[str] = []  # ce que les gestes ont fait, dit par l'assistant et non par le modèle
        missed: list[str] = []
        names = _names(house)
        seen: dict[str, Any] = {}  # un appel répété mot pour mot dans une phrase ne repart pas (deux rappels « lait »)
        try:
            for _ in range(self.max_steps):
                message = self.model.chat(messages, tools.schemas(families))
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return reply(_told(acts, missed, (message.get("content") or "").strip()), done)
                messages.append({"role": "assistant", "content": message.get("content"), "tool_calls": tool_calls})
                wide = []
                for call in tool_calls:
                    name = call["function"]["name"]
                    args = _arguments(call["function"].get("arguments"))
                    tool = tools.get(name)
                    if tool is not None and tool.gesture and tool.house_wide(args):
                        wide.append((name, args))
                        result: Any = {"status": "en attente du oui de la personne"}
                    elif (call_key := name + json.dumps(args, sort_keys=True, ensure_ascii=False)) in seen:
                        result = {"status": "déjà fait dans cette demande, ne pas le refaire", "result": seen[call_key]}
                    else:
                        started = time.monotonic()
                        result = seen[call_key] = tools.run(name, args, who)
                        failed = isinstance(result, dict) and "error" in result
                        LOG.info(
                            "tool name=%s args=%s ms=%d %s",
                            name,
                            json.dumps(args, ensure_ascii=False)[:200],
                            (time.monotonic() - started) * 1000,
                            f"error={result['error']}" if failed else "ok",
                        )
                        if tool is not None and tool.gesture:
                            if failed:
                                missed.append(f"{_act(args, names)} ({result['error']})")
                            else:
                                done.append(_label(name, args))
                                acts.append(_act(args, names))
                                result = {"résultat": result, "déjà dit à la personne": acts[-1]}
                        if name in SETTLERS and not failed and "proposition" in result:
                            # le Oui ne passe pas par le modèle : la question part tout de suite, le oui joue apply
                            return self._ask(
                                key,
                                [("apply_settings", {"proposal": result["proposition"]})],
                                result["question"],
                                SETTLED,
                            )
                    # un long résultat se recalcule à chaque étape (le cache ne couvre que le début) : court
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.get("id", name),
                            "content": json.dumps(result, ensure_ascii=False, default=str)[:RESULT_CHARS],
                        }
                    )
                if wide:
                    question = (
                        "Je passe la maison en Absent ?"
                        if any(a.get("value") == "AWAY" for _, a in wide)
                        else "Je le fais pour toute la maison ?"
                    )
                    if any(n == "apply_settings" for n, _ in wide):
                        question = "J'applique ce réglage ?"
                    answer = self._ask(key, wide, question, "C'est fait.")
                    answer["done"] = done
                    return answer
            return reply("Je n'y arrive pas en peu d'étapes ; tu peux reformuler ?", done)
        except ModelError as e:
            return reply(f"Je ne peux pas réfléchir pour l'instant ({e}).", done)


ROUTER = {
    "role": "system",
    "content": "Tu ranges une demande faite à l'assistant d'une maison dans un ou deux types. "
    "Réponds seulement par leurs noms, séparés par une virgule, sans rien d'autre.\n"
    + "\n".join(f"{name} : {what}" for name, what in FAMILIES.items()),
}

# proposer ou annuler un réglage finit la phrase sur la question ; le oui suivant l'applique (spec de l'assistant complet §5)
SETTLERS = ("propose_settings", "undo_settings")
SETTLED = "C'est réglé. Dis « annule » si ça ne te va pas."
SITUATIONS = {"DAY": "Jour", "NIGHT": "Nuit", "AWAY": "Absent"}
KINDS = (("lights", "lampes"), ("appliances", "appareils"), ("covers", "volets/stores"), ("emitters", "chauffage/clim"))


def inventory(house: dict) -> list[str]:
    """Une ligne par pièce : ses objets, nom [id], par sorte ; puis les robots. Sans état : il vit dans `house`."""
    lines = []
    for room in house.get("rooms", []):
        kinds = []
        for key, label in KINDS:
            objects = room.get(key, []) or []
            if objects:
                kinds.append(f"{label} " + ", ".join(f"{o.get('name') or o['id']} [{o['id']}]" for o in objects))
        lines.append(
            f"- {room.get('name') or room['id']} [{room['id']}] : " + ("; ".join(kinds) or "rien de pilotable")
        )
    for m in house.get("machines", []) or []:
        lines.append(f"- robot {m.get('name') or m['id']} [{m['id']}]")
    return lines


# ce que fait chaque geste du catalogue, dit à la personne : le vocabulaire de Domia, pas des phrases à reconnaître
DID = {
    "TurnOn": "allumé",
    "TurnOff": "éteint",
    "TurnOnRoom": "allumée",
    "TurnOffRoom": "éteinte",
    "SetBrightness": "à {brightness_pct} %",
    "SetColor": "en {color}",
    "SetPosition": "à {position} %",
    "Open": "ouvert",
    "Close": "fermé",
    "Stop": "arrêté",
    "Release": "rendu à l'automatique",
    "SetSetpoint": "à {setpoint_c} °C",
    "SetMode": "en {mode}",
    "StartCleaning": "parti nettoyer",
    "Pause": "en pause",
    "Resume": "reparti",
    "ReturnToBase": "rentre à sa base",
    "Locate": "se signale",
    "StartProgram": "lancé",
}


def _names(house: dict) -> dict[str, str]:
    names = {}
    for room in house.get("rooms", []):
        names[room["id"]] = room.get("name") or room["id"]
        for key, _ in KINDS:
            for o in room.get(key, []) or []:
                names[o["id"]] = f"{names[room['id']]} › {o.get('name') or o['id']}"
    names.update({m["id"]: m.get("name") or m["id"] for m in house.get("machines", []) or []})
    return names


def _act(args: dict, names: dict[str, str]) -> str:
    """Un geste dit d'après ce qui a été joué : l'objet, puis ce que le geste fait (« Couloir › Plafonnier éteint »)."""
    if "value" in args and "action" not in args:
        return f"maison en {SITUATIONS.get(args['value'], args['value'])}"
    action = args.get("action") or ""
    try:
        did = DID.get(action, action).format(**args)
    except (KeyError, IndexError):
        did = DID.get(action, action)
    return " ".join(p for p in (names.get(str(args.get("id") or ""), args.get("id")), did) if p)


def _told(acts: list[str], missed: list[str], said: str) -> str:
    """La réponse dit d'abord les gestes d'après leurs résultats, jamais d'après le texte du modèle (un geste joué ou
    raté se dit comme il s'est passé), puis ce que le modèle ajoute : une lecture demandée, une question."""
    parts = []
    if acts:
        parts.append("Fait : " + " ; ".join(acts) + ".")
    if missed:
        parts.append("Pas fait : " + " ; ".join(missed) + ".")
    if said:
        parts.append(said)
    return " ".join(parts) or "Je ne sais pas."


def reply(answer: str, done: list[str] | None = None) -> dict:
    return {"answer": answer, "done": list(done or []), "proposals": [], "confirm": None}


def _arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _label(name: str, args: dict) -> str:
    if name == "apply_settings":
        return "réglage"
    parts = [args.get("action") or name, args.get("id"), args.get("value")]
    return " ".join(str(p) for p in parts if p)
