"""Rappels et Calendrier (spec §10), par le pont EventKit (`assistant/eventkit/`, un service à part sur le Mac) : lire,
ajouter, cocher ; jamais supprimer. Sans le pont, ou sans l'autorisation de macOS, chaque outil le dit au lieu
d'échouer en silence."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

SHOPPING = "Courses"


class AgendaUnavailable(Exception):
    pass


class Agenda:
    def __init__(self, base_url: str | None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        if not self.base_url:
            raise AgendaUnavailable("pas de pont Rappels/Calendrier sur cette machine")
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as e:
            try:
                message = json.loads(e.read())["error"]
            except (ValueError, KeyError, TypeError):
                message = f"HTTP {e.code}"
            raise AgendaUnavailable(message) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise AgendaUnavailable(f"le pont Rappels/Calendrier ne répond pas ({e})") from None

    def status(self) -> dict:
        return self._call("GET", "/health")

    def reminders(self, list_name: str | None = None, include_done: bool = False) -> list[dict]:
        query = urllib.parse.urlencode(
            {k: v for k, v in (("list", list_name), ("done", "1" if include_done else None)) if v}
        )
        return self._call("GET", "/reminders" + (f"?{query}" if query else ""))

    def add_reminder(
        self,
        title: str,
        list_name: str | None = None,
        due: str | None = None,
        recurrence: str | None = None,
        interval: int | None = None,
        notes: str | None = None,
    ) -> dict:
        """Sans liste : la liste par défaut de Rappels ; les courses vont dans « Courses » (SHOPPING)."""
        body = {
            "title": title,
            "list": list_name,
            "due": due,
            "recurrence": recurrence,
            "interval": interval,
            "notes": notes,
        }
        return self._call("POST", "/reminders", {k: v for k, v in body.items() if v is not None})

    def complete_reminder(self, reminder_id: str) -> dict:
        return self._call("POST", f"/reminders/{urllib.parse.quote(reminder_id, safe='')}/complete")

    def calendar(self, start: str, end: str) -> list[dict]:
        return self._call("GET", "/events?" + urllib.parse.urlencode({"from": start, "to": end}))

    def add_event(
        self, title: str, start: str, end: str, calendar: str | None = None, notes: str | None = None
    ) -> dict:
        body = {"title": title, "start": start, "end": end, "calendar": calendar, "notes": notes}
        return self._call("POST", "/events", {k: v for k, v in body.items() if v is not None})
