"""Le service de l'assistant (spec §6) : `POST /talk` (relayé par Domia), `GET /health`, et l'horloge de l'observateur
(toutes les heures, et le brief du soir). Pour l'écran Assistant (spec de l'écran §7) : `GET /history`, `GET /planned`,
`POST /planned/{id}` et `POST /voice`. Seules les adresses de `allow_from` parlent : le Pi et la machine elle-même."""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from . import VERSION
from .assistant import Assistant
from .observer import Observer
from .tools import Speaker
from .voice import SPEECH_MIME, Voice, VoiceUnavailable, kind

LOG = logging.getLogger("assistant")
MAX_BODY = 16 * 1024
MAX_AUDIO = 1024 * 1024  # 30 s de parole compressée tiennent largement
PLANNED = re.compile(r"^/planned/(\d+)$")
DECISIONS = ("ACCEPT", "REFUSE", "CANCEL")


def handler(assistant: Assistant, allow_from: tuple[str, ...], status: Callable[[], dict], voice: Voice | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"domia-assistant/{VERSION}"

        def log_message(self, fmt, *args):  # les accès vont au journal, pas sur stderr
            LOG.debug("http %s", fmt % args)

        def _send(self, code: int, body: dict) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _allowed(self) -> bool:
            if self.client_address[0] in allow_from:
                return True
            self._send(403, {"error": "adresse non autorisée"})
            return False

        def do_GET(self):
            if not self._allowed():
                return
            url = urlsplit(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            if url.path == "/health":
                self._send(
                    200,
                    {"version": VERSION, **status(), "voice": (voice.available() if voice else "pas de voix") or "ok"},
                )
            elif url.path == "/history":
                self._send(200, self._history(query))
            elif url.path == "/planned":
                self._send(200, self._planned())
            else:
                self._send(404, {"error": "route inconnue"})

        def _history(self, query: dict) -> dict:
            now = datetime.now(UTC)
            days = min(max(_int(query.get("days"), 7), 1), 90)
            limit = min(max(_int(query.get("limit"), 60), 1), 200)
            items = assistant.memory.history(query.get("person") or None, now - timedelta(days=days), limit)
            waiting = assistant.engagements.waiting(now) if assistant.engagements is not None else []
            return {"items": items, "waiting": [{"id": e["id"], "question": e["question"]} for e in waiting]}

        def _planned(self) -> dict:
            now = datetime.now(UTC)
            listing = assistant.engagements.listing(now) if assistant.engagements is not None else []
            return {"planned": listing, "remarks": assistant.memory.messages(now - timedelta(days=7))}

        def _json_body(self) -> dict | None:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._send(400, {"error": "corps absent ou trop long"})
                return None
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                body = None
            if not isinstance(body, dict):
                self._send(400, {"error": "corps illisible"})
                return None
            return body

        def do_POST(self):
            if not self._allowed():
                return
            url = urlsplit(self.path)
            if url.path == "/voice":
                self._voice({k: v[0] for k, v in parse_qs(url.query).items()})
                return
            planned = PLANNED.match(url.path)
            if planned:
                self._decide(int(planned.group(1)))
                return
            if url.path != "/talk":
                self._send(404, {"error": "route inconnue"})
                return
            body = self._json_body()
            if body is None:
                return
            try:
                text = str(body["text"]).strip()
            except KeyError:
                self._send(400, {"error": "corps illisible"})
                return
            who = Speaker(person=body.get("person"), room=body.get("room"), client=body.get("client"))
            started = time.monotonic()
            try:
                answer = assistant.talk(text, who)
            except Exception:  # une phrase ne fait jamais tomber le service
                LOG.exception("talk_failed correlation_id=%s", body.get("correlation_id"))
                self._send(500, {"error": "l'assistant a trébuché"})
                return
            LOG.info(
                "talk correlation_id=%s person=%s room=%s ms=%d done=%d",
                body.get("correlation_id"),
                who.person,
                who.room,
                (time.monotonic() - started) * 1000,
                len(answer.get("done", [])),
            )
            self._send(200, answer)

        def _decide(self, engagement_id: int) -> None:
            body = self._json_body()
            if body is None:
                return
            decision = body.get("decision")
            if decision not in DECISIONS or assistant.engagements is None:
                self._send(400, {"error": "décision inconnue"})
                return
            done = assistant.engagements.decide(engagement_id, decision, body.get("person"), datetime.now(UTC))
            LOG.info("planned_decision id=%d decision=%s done=%s", engagement_id, decision, done)
            self._send(
                200 if done else 409, {"done": done} if done else {"error": "rien à faire : déjà réglé ou expiré"}
            )

        def _voice(self, query: dict) -> None:
            """Un son relayé par Domia : transcrit, joué comme une phrase dite, la réponse dite en retour. Le son
            n'est gardé nulle part ; seule la phrase transcrite entre dans la conversation."""
            length = int(self.headers.get("Content-Length") or 0)
            mime = kind(self.headers.get("Content-Type"))
            if length <= 0 or length > MAX_AUDIO or mime is None:
                self._send(400, {"error": "son absent, trop long ou d'un type inconnu"})
                return
            audio = self.rfile.read(length)
            if voice is None:
                self._send(503, {"error": "pas de voix sur cette machine", "code": "VOICE_UNAVAILABLE"})
                return
            started = time.monotonic()
            try:
                heard = voice.transcribe(audio, mime)
            except VoiceUnavailable as e:
                self._send(503, {"error": str(e), "code": "VOICE_UNAVAILABLE"})
                return
            except Exception:
                LOG.exception("transcribe_failed correlation_id=%s", query.get("correlation_id"))
                self._send(500, {"error": "la transcription a trébuché"})
                return
            heard_ms = (time.monotonic() - started) * 1000
            who = Speaker(
                person=query.get("person") or None, room=query.get("room") or None, client=query.get("client") or None
            )
            answer: dict[str, Any]
            if not heard:
                answer = {"answer": "Je n'ai rien entendu.", "done": [], "proposals": [], "confirm": None}
            else:
                try:
                    answer = assistant.talk(heard, who, voice=True)
                except Exception:
                    LOG.exception("talk_failed correlation_id=%s", query.get("correlation_id"))
                    self._send(500, {"error": "l'assistant a trébuché"})
                    return
            spoken = voice.speak(str(answer.get("answer") or ""))
            answer = {
                **answer,
                "heard": heard,
                "speech": {"mime": SPEECH_MIME, "data": base64.b64encode(spoken).decode()} if spoken else None,
            }
            LOG.info(
                "voice correlation_id=%s person=%s bytes=%d heard_ms=%d ms=%d",
                query.get("correlation_id"),
                who.person,
                length,
                heard_ms,
                (time.monotonic() - started) * 1000,
            )
            self._send(200, answer)

    return Handler


def _int(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


def serve(
    assistant: Assistant,
    host: str,
    port: int,
    allow_from: tuple[str, ...],
    status: Callable[[], dict],
    voice: Voice | None = None,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), handler(assistant, allow_from, status, voice))
    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()
    return server


def clock(
    observer: Observer,
    zone: str,
    brief_at: str | None,
    stop: threading.Event,
    tick: float = 30.0,
    engagements=None,
    daily: dict[str, Callable[[], Any]] | None = None,
) -> None:
    """L'horloge de l'observateur : à chaque heure pile, un réveil ; à `brief_at`, le brief du soir ; à chaque tour, les
    engagements dus ; `daily` : une tâche par jour à son heure (HH:MM), le classement du hub. Une erreur est
    journalisée, l'horloge continue."""
    tz = ZoneInfo(zone)
    done: set[str] = set()
    while not stop.wait(tick):
        local = datetime.now(tz)
        for at, job in (daily or {}).items():
            key = f"daily-{at}-{local:%Y%m%d}"
            if local.strftime("%H:%M") == at and key not in done:
                done.add(key)
                try:
                    LOG.info("daily at=%s %s", at, job())
                except Exception:
                    LOG.exception("daily_failed at=%s", at)
        hour_key = local.strftime("obs-%Y%m%d%H")
        try:
            if brief_at and local.strftime("%H:%M") == brief_at and f"brief-{local:%Y%m%d}" not in done:
                done.add(f"brief-{local:%Y%m%d}")
                observer.brief(datetime.now(UTC), local.date() + timedelta(days=1))
            elif local.minute == 0 and hour_key not in done:
                done.add(hour_key)
                remark = observer.run_once()
                if remark:
                    LOG.info("remark subject=%s", remark.subject)
        except Exception:
            LOG.exception("observer_failed")
        if engagements is not None:
            try:
                engagements.tick(datetime.now(UTC))
            except Exception:
                LOG.exception("engagements_failed")
        if len(done) > 200:
            done.clear()


def warm(assistant: Assistant, stop: threading.Event, every: float = 30.0, tries: int = 20) -> bool:
    """Au démarrage, prépare le modèle avant la première question. Après un redémarrage du Mac, Ollama ou Domia peuvent
    arriver après nous : on réessaie toutes les 30 s, 10 minutes au plus."""
    for _ in range(tries):
        started = time.monotonic()
        try:
            assistant.warm()
            LOG.info("warm ms=%d", (time.monotonic() - started) * 1000)
            return True
        except Exception as e:  # le modèle ou Domia pas encore là
            LOG.info("warm_retry error=%s", e)
        if stop.wait(every):
            return False
    LOG.warning("warm_failed")
    return False
