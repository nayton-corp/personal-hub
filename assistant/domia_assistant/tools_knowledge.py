"""Les outils du savoir du foyer : la bibliothèque (recherche, photo d'une plaque signalétique, fiches), les
réglages avec un Oui (proposer, appliquer, annuler), et la mémoire (retenir, oublier)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .domia import Domia
from .library import Library, LibraryUnavailable
from .memory import Memory
from .settings import NOUNS, Settler
from .tools_base import Speaker, Tool, obj

NAMEPLATE = "Lis cette plaque signalétique ou cette facture. Rends en JSON : brand, model, serial, et si visibles bought_at, shop, price_chf. Rien d'inventé : null si illisible."
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".heic": "image/heic"}


def library_tools(library: Library, look: Callable[[bytes, str, str], str] | None = None) -> list[Tool]:
    def guarded(fn: Callable[[dict[str, Any], Speaker], Any]) -> Callable[[dict[str, Any], Speaker], Any]:
        def run(args: dict[str, Any], who: Speaker) -> Any:
            try:
                return fn(args, who)
            except LibraryUnavailable as e:
                return {"error": str(e)}

        return run

    def search(args: dict[str, Any], who: Speaker) -> Any:
        return [{"source": p.cite(), "text": p.text} for p in library.search(args["question"], int(args.get("k", 5)))]

    def photo(args: dict[str, Any], who: Speaker) -> Any:
        path = next((p for p in library.inbox() if p.name == args["file"]), None)
        if look is None or path is None or path.suffix.lower() not in MIME:
            return {"error": "photo introuvable dans à-trier"}
        return {"file": path.name, "read": look(path.read_bytes(), MIME[path.suffix.lower()], NAMEPLATE)}

    def card(args: dict[str, Any], who: Speaker) -> Any:
        found = library.card(args["id"])
        return found if found is not None else {"error": "fiche inconnue", "cards": sorted(library.cards())}

    return [
        Tool(
            "search_library",
            "Cherche dans les manuels, factures et documents du foyer ; rend les passages avec leur source et page. Toujours citer la source.",
            obj({"question": {"type": "string"}, "k": {"type": "integer", "minimum": 1, "maximum": 10}}, ["question"]),
            guarded(search),
        ),
        Tool(
            "list_cards",
            "Les fiches des objets du ménage (id et nom).",
            obj({}),
            guarded(lambda a, w: {k: v.get("name") or k for k, v in library.cards().items()}),
        ),
        Tool(
            "object_card",
            "La fiche d'un objet : marque, modèle, achat, garantie, entretien, pièces, documents.",
            obj({"id": {"type": "string"}}, ["id"]),
            guarded(card),
        ),
        Tool(
            "update_card",
            "Propose de créer ou de compléter la fiche d'un objet (champs : name, room, brand, model, serial, bought_at, shop, price_chf, warranty_until, domia, maintenance, parts, notes) : une carte à valider dans l'app du hub.",
            obj({"id": {"type": "string"}, "fields": {"type": "object"}}, ["id", "fields"]),
            guarded(lambda a, w: library.save_card(a["id"], a["fields"])),
        ),
        Tool(
            "maintenance_due",
            "Les tâches d'entretien des objets dont l'échéance est passée.",
            obj({}),
            guarded(lambda a, w: library.maintenance_due(datetime.now().date())),
        ),
        Tool(
            "inbox",
            "Les photos déposées dans « à-trier » (inventaire en photos).",
            obj({}),
            lambda a, w: [p.name for p in library.inbox()],
        ),
    ] + (
        [
            Tool(
                "read_photo",
                "Lit une photo de « à-trier » (plaque signalétique, facture) : marque, modèle, numéro de série. Ensuite, créer la fiche et ne demander que ce qui manque.",
                obj({"file": {"type": "string"}}, ["file"]),
                photo,
            )
        ]
        if look
        else []
    )


def settings_tools(domia: Domia, memory: Memory) -> list[Tool]:
    """Régler avec un Oui (spec de l'assistant complet §5) : proposer, puis appliquer après le oui, ou annuler."""
    settler = Settler(domia, memory)
    kinds = sorted(NOUNS)
    change = {
        "type": "object",
        "properties": {
            "op": {"type": "string", "enum": ["set", "add", "remove"]},
            "kind": {"type": "string", "enum": kinds},
            "id": {
                "type": "string",
                "description": "l'objet (set, remove) ; rien pour house, notifications, situation_changes",
            },
            "room": {"type": "string", "description": "la pièce d'un objet ajouté (add)"},
            "fields": {
                "type": "object",
                "description": "les champs de la config (noms de settings, délais en secondes, « a.b » pour un champ imbriqué, null retire) ; jamais d'id à l'ajout",
            },
        },
        "required": ["op", "kind"],
    }
    return [
        Tool(
            "propose_settings",
            "Propose de changer des réglages de Domia : Domia vérifie sans rien écrire, puis je demande son oui à la personne. Lis d'abord l'objet avec settings.",
            obj({"changes": {"type": "array", "items": change}}, ["changes"]),
            lambda a, w: settler.propose(a["changes"], w.person),
        ),
        Tool(
            "apply_settings",
            "Applique une proposition de réglage, seulement après le oui de la personne.",
            obj({"proposal": {"type": "integer"}}, ["proposal"]),
            lambda a, w: settler.apply(a["proposal"], w.person),
            gesture=True,
            house_wide=lambda a: True,
        ),
        Tool(
            "undo_settings",
            "Propose d'annuler le dernier réglage fait par l'assistant pour cette personne (« annule »).",
            obj({}),
            lambda a, w: settler.undo(w.person),
        ),
    ]


def memory_tools(memory: Memory) -> list[Tool]:
    def remember(args: dict[str, Any], who: Speaker) -> Any:
        personal = bool(args.get("personal"))
        if personal and not who.person:
            return {"error": "une note personnelle a besoin de savoir qui parle"}
        return {"id": memory.remember(args["fact"], who.person, personal)}

    def forget(args: dict[str, Any], who: Speaker) -> Any:
        return {"forgotten": memory.forget(int(args["id"]), who.person)}

    return [
        Tool(
            "remember",
            "Retient une note du foyer (« les ampoules E14 sont dans le placard de l'entrée ») ou une préférence personnelle de la personne qui parle (personal: true).",
            obj({"fact": {"type": "string"}, "personal": {"type": "boolean"}}, ["fact"]),
            remember,
        ),
        Tool(
            "recall",
            "Retrouve les notes du foyer (et celles de la personne qui parle) liées à une question.",
            obj({"question": {"type": "string"}}, ["question"]),
            lambda a, w: memory.recall(a["question"], w.person),
        ),
        Tool(
            "what_you_know_about_me",
            "Ce que l'assistant sait de la personne qui parle.",
            obj({}),
            lambda a, w: memory.about(w.person) if w.person else [],
        ),
        Tool(
            "forget",
            "Oublie une note par son id (une note du foyer, ou une note de la personne qui parle).",
            obj({"id": {"type": "integer"}}, ["id"]),
            forget,
        ),
        Tool(
            "not_now",
            "La personne ne veut plus entendre parler de ce sujet pour l'instant (un constat, une remarque) : il se tait une semaine, puis plus longtemps.",
            obj({"subject": {"type": "string"}}, ["subject"]),
            lambda a, w: {"quiet_until": memory.refuse(a["subject"], datetime.now(UTC)).isoformat()},
        ),
    ]
