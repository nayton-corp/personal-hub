"""`python -m domia_assistant <commande>` :

serve     le service (POST /talk, l'observateur, le brief du soir) ; ce que lance launchd
mcp       le serveur MCP sur stdio (pour Claude Desktop ou un autre client), --person pour qui il parle
check     Domia, le modèle, la bibliothèque du hub et le pont Rappels répondent-ils ?
observe   un réveil de l'observateur, tout de suite
say       une phrase, comme si elle venait de Domia (--person, --room)
voice     la voix est-elle prête ? Charge Whisper (le télécharge la première fois), transcrit et dit une phrase
classify  le classement du hub, tout de suite : --mode suggest (défaut), catchup ou direct ; --dry-run
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path
from typing import cast

from . import server
from .agenda import Agenda, AgendaUnavailable
from .assistant import Assistant
from .config import Settings, load
from .domia import Domia, DomiaError, Noting
from .engagements import Engagements
from .hub import MODES, HubModule, classify, connect, library
from .library import INBOX, LibraryUnavailable
from .llm import ModelError, OpenAICompatible
from .memory import Memory
from .observer import Observer
from .tools import Speaker, build
from .voice import Voice

HERE = Path(__file__).resolve().parent.parent
HUB_RETRY_S = 300


class Parts:
    def __init__(self, s: Settings):
        self.settings = s
        self._hub: HubModule | None = None
        self._hub_retry = 0.0
        self.memory = Memory(s.database)
        auth = (s.config_user, s.config_password) if s.config_password else None
        # Noting relaie tout à Domia (__getattr__) : pour le typage, c'est un Domia
        self.domia = cast(Domia, Noting(Domia(s.domia_url, s.domia_token, config_auth=auth), self.memory))
        self.model = OpenAICompatible(s.model_url, s.model, keep_alive=s.keep_alive, reasoning=s.reasoning)
        # la bibliothèque vit dans le hub (domaine Documents) ; seules les photos à trier restent ici
        self.library = library(s.hub, s.library_dir / INBOX) if s.hub is not None else None
        self.voice = Voice(s.stt_model, "fr", s.say_voice) if s.voice else None
        self.agenda = Agenda(s.eventkit_url)
        self.engagements = Engagements(self.domia, self.memory, self.agenda, s.timezone)
        self.observer = Observer(self.domia, self.memory, self.library, self.agenda, self.engagements, s.timezone)
        self.assistant = Assistant(
            self.domia,
            self.model,
            self.memory,
            self.toolbox,
            s.timezone,
            s.max_steps,
            engagements=self.engagements,
            route=s.route,
        )

    def hub(self) -> HubModule | None:
        """Les outils du hub, gardés d'une phrase à l'autre (leur préfixe reste en cache) ; un hub qui ne répondait
        pas est retenté toutes les 5 minutes."""
        cfg = self.settings.hub
        if cfg is None:
            return None
        if self._hub is None and time.monotonic() >= self._hub_retry:
            self._hub = connect(cfg)
            self._hub_retry = time.monotonic() + HUB_RETRY_S
        return self._hub

    def classify(self, mode: str = "suggest", dry_run: bool = False) -> dict:
        s = self.settings
        if s.hub is None:
            raise SystemExit("classify : pas de section hub dans config.yaml")
        return classify(s.hub, s.model_url, s.model, mode, dry_run)

    def daily(self) -> dict:
        """Les tâches du matin : le classement du hub, à `hub.classify_at`."""
        cfg = self.settings.hub
        return {cfg.classify_at: self.classify} if cfg is not None and cfg.classify_at else {}

    def toolbox(self):
        vision = self.settings.vision_model
        look = (lambda image, mime, question: self.model.look(image, mime, question, vision)) if vision else None
        return build(
            self.domia,
            self.library,
            self.memory,
            self.agenda,
            self.settings.web_search_url,
            look,
            self.settings.timezone,
            self.observer.plan,
            self.engagements,
            self.settings.settings_write,
            self.hub(),
        )

    def status(self) -> dict:
        out: dict = {}
        try:
            house = self.domia.house()
            out["domia"] = {"ok": True, "situation": (house.get("situation") or {}).get("value")}
        except DomiaError as e:
            out["domia"] = {"ok": False, "error": str(e)}
        try:
            access = self.agenda.status() or {}
            out["reminders"] = {"ok": bool(access.get("reminders")), "calendar": bool(access.get("calendar"))}
            if not all(out["reminders"].values()):
                out["reminders"]["error"] = (
                    "le pont répond, mais macOS ne lui a pas donné l'accès (Réglages Système → Confidentialité)"
                )
        except AgendaUnavailable as e:
            out["reminders"] = {"ok": False, "error": f"Rappels non autorisés ou injoignables : {e}"}
        out["model"] = self.settings.model
        if self.settings.hub is not None:
            hub = self.hub()
            out["hub"] = {"ok": hub is not None, "domains": sorted(hub.families) if hub else []}
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="domia_assistant", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["serve", "mcp", "check", "observe", "say", "voice", "classify"])
    parser.add_argument("text", nargs="?")
    parser.add_argument("--config", type=Path, default=HERE / "config.yaml")
    parser.add_argument("--person")
    parser.add_argument("--room")
    parser.add_argument("--mode", choices=MODES, default="suggest")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stderr)
    parts = Parts(load(args.config))

    if args.command == "serve":
        s = parts.settings
        httpd = server.serve(parts.assistant, s.listen_host, s.listen_port, s.allow_from, parts.status, parts.voice)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        logging.getLogger("assistant").info("listening host=%s port=%d model=%s", s.listen_host, s.listen_port, s.model)
        threading.Thread(target=server.warm, args=(parts.assistant, stop), name="warm", daemon=True).start()
        with contextlib.suppress(KeyboardInterrupt):
            server.clock(
                parts.observer, s.timezone, s.brief_at, stop, engagements=parts.engagements, daily=parts.daily()
            )
        httpd.shutdown()
        return 0
    if args.command == "mcp":
        from .mcp_server import run

        run(parts.toolbox, Speaker(person=args.person, client="mcp"))
        return 0
    if args.command == "check":
        status = parts.status()
        try:
            parts.model.chat([{"role": "user", "content": "Réponds juste : ok"}], [])
            status["model_ok"] = True
        except ModelError as e:
            status["model_ok"] = str(e)
        if parts.settings.embedding_model:
            try:
                parts.model.embed(["ok"], parts.settings.embedding_model)
                status["embeddings_ok"] = True
            except ModelError as e:
                status["embeddings_ok"] = f"{e} : ollama pull {parts.settings.embedding_model} ?"
        try:
            status["library_cards"] = len(parts.library.cards()) if parts.library else "pas de bibliothèque (hub)"
        except LibraryUnavailable as e:
            status["library_cards"] = str(e)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status["domia"]["ok"] else 1
    if args.command == "observe":
        remark = parts.observer.run_once()
        print(remark.message if remark else "rien à dire")
        return 0
    if args.command == "voice":
        return voice_check(parts.voice)
    if args.command == "classify":
        print(json.dumps(parts.classify(args.mode, args.dry_run), ensure_ascii=False))
        return 0
    if args.command == "say":
        if not args.text:
            parser.error("say demande une phrase")
        print(
            json.dumps(
                parts.assistant.talk(args.text, Speaker(args.person, args.room, "cli")), ensure_ascii=False, indent=2
            )
        )
        return 0
    return 2


def voice_check(voice: Voice | None) -> int:
    """Dit une phrase avec `say`, puis la fait transcrire par Whisper : la boucle entière de la voix, sur le Mac."""
    if voice is None:
        print("la voix est éteinte (assistant.voice: false dans config.yaml)")
        return 1
    missing = voice.available()
    if missing:
        print(f"voix indisponible : {missing} (voir le README, « La voix »)")
        return 1
    spoken = voice.speak("Bonjour, la voix de la maison est prête.")
    if not spoken:
        print("say n'a rien rendu : la synthèse de macOS manque ou la voix choisie n'existe pas (say -v '?')")
        return 1
    started = time.monotonic()
    heard = voice.transcribe(spoken, "audio/mp4")
    print(f"entendu : « {heard} » en {time.monotonic() - started:.1f} s")
    return 0 if heard else 1


if __name__ == "__main__":
    sys.exit(main())
