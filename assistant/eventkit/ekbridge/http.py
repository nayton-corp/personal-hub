"""L'API locale du pont (127.0.0.1 seulement) :

  GET  /health                        {reminders: bool, calendar: bool} : l'autorisation de macOS (TCC) tient-elle ?
  GET  /reminders?list=&done=1        les rappels (ouverts par défaut)
  POST /reminders                     {title, list?, due?, recurrence?, interval?, notes?} (sans liste : celle par défaut)
  POST /reminders/<id>/complete       coche
  GET  /events?from=&to=              les événements
  POST /events                        {title, start, end, calendar?, notes?}

Sans autorisation : 403 {error: "Rappels non autorisés"}. Aucune route ne supprime."""

from __future__ import annotations

import json
import logging
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

RECURRENCES = {"daily", "weekly", "monthly", "yearly"}
LOG = logging.getLogger("ekbridge")


class NotAuthorized(Exception):
    pass


class Store(Protocol):
    def access(self) -> dict: ...
    def reminders(self, list_name: str | None, done: bool) -> list[dict]: ...
    def add_reminder(
        self,
        title: str,
        list_name: str | None,
        due: str | None,
        recurrence: str | None,
        interval: int,
        notes: str | None,
    ) -> dict: ...
    def complete(self, reminder_id: str) -> dict: ...
    def events(self, start: str, end: str) -> list[dict]: ...
    def add_event(self, title: str, start: str, end: str, calendar: str | None, notes: str | None) -> dict: ...


def handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _send(self, code: int, body) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 64 * 1024:
                raise ValueError("corps trop long")
            return json.loads(self.rfile.read(length) or b"{}") if length else {}

        def _route(self, method: str) -> None:
            url = urllib.parse.urlparse(self.path)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            parts = [urllib.parse.unquote(p) for p in url.path.strip("/").split("/") if p]
            try:
                if method == "GET" and parts == ["health"]:
                    return self._send(200, store.access())
                if method == "GET" and parts == ["reminders"]:
                    return self._send(200, store.reminders(query.get("list"), query.get("done") == "1"))
                if method == "POST" and parts == ["reminders"]:
                    b = self._body()
                    if not str(b.get("title", "")).strip():
                        return self._send(400, {"error": "un titre"})
                    if b.get("recurrence") and b["recurrence"] not in RECURRENCES:
                        return self._send(400, {"error": "récurrence : daily, weekly, monthly ou yearly"})
                    interval = int(b.get("interval") or 1)
                    if not 1 <= interval <= 52:
                        return self._send(400, {"error": "intervalle : de 1 à 52"})
                    return self._send(
                        201,
                        store.add_reminder(
                            b["title"].strip(),
                            b.get("list") or None,
                            b.get("due"),
                            b.get("recurrence"),
                            interval,
                            b.get("notes"),
                        ),
                    )
                if method == "POST" and len(parts) == 3 and parts[0] == "reminders" and parts[2] == "complete":
                    return self._send(200, store.complete(parts[1]))
                if method == "GET" and parts == ["events"]:
                    if "from" not in query or "to" not in query:
                        return self._send(400, {"error": "from et to"})
                    return self._send(200, store.events(query["from"], query["to"]))
                if method == "POST" and parts == ["events"]:
                    b = self._body()
                    if not all(b.get(k) for k in ("title", "start", "end")):
                        return self._send(400, {"error": "title, start et end"})
                    return self._send(
                        201, store.add_event(b["title"], b["start"], b["end"], b.get("calendar"), b.get("notes"))
                    )
                return self._send(404 if method == "GET" or method == "POST" else 405, {"error": "route inconnue"})
            except NotAuthorized as e:
                return self._send(403, {"error": str(e) or "Rappels non autorisés"})
            except KeyError as e:
                return self._send(404, {"error": f"introuvable : {e}"})
            except ValueError as e:
                return self._send(400, {"error": str(e)})

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def send_response(self, code, message=None):
            if self.command == "POST":  # les écritures se relisent dans le journal ; les lectures non
                LOG.info("write path=%s code=%d", urllib.parse.urlparse(self.path).path, code)
            super().send_response(code, message)

        def do_DELETE(self):  # jamais de suppression (spec §10)
            self._send(405, {"error": "le pont ne supprime jamais"})

    return Handler


def serve(store: Store, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), handler(store))
