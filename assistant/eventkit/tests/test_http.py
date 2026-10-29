"""L'API du pont contre un faux magasin (EventKit n'existe que sur macOS) : les routes, les refus, jamais de
suppression, et l'autorisation perdue dite en clair."""

import json
import threading
import urllib.error
import urllib.request

import pytest
from ekbridge.http import NotAuthorized, serve


class FakeStore:
    def __init__(self):
        self.allowed = True
        self.items = [{"id": "r1", "title": "Lait", "list": "Courses", "done": False}]

    def _need(self):
        if not self.allowed:
            raise NotAuthorized("Rappels non autorisés")

    def access(self):
        return {"reminders": self.allowed, "calendar": self.allowed}

    def reminders(self, list_name, done):
        self._need()
        return [r for r in self.items if (list_name is None or r["list"] == list_name) and (done or not r["done"])]

    def add_reminder(self, title, list_name, due, recurrence, interval, notes):
        self._need()
        item = {
            "id": f"r{len(self.items) + 1}",
            "title": title,
            "list": list_name or "Rappels",
            "done": False,
            "due": due,
            "recurrence": recurrence,
            "interval": interval,
        }
        self.items.append(item)
        return item

    def complete(self, reminder_id):
        self._need()
        item = (
            next(r for r in self.items if r["id"] == reminder_id)
            if any(r["id"] == reminder_id for r in self.items)
            else None
        )
        if item is None:
            raise KeyError(reminder_id)
        item["done"] = True
        return item

    def events(self, start, end):
        self._need()
        return [{"id": "e1", "title": "Chez mes parents", "start": "2026-10-31T10:00", "end": "2026-10-31T18:00"}]

    def add_event(self, title, start, end, calendar, notes):
        self._need()
        return {"id": "e2", "title": title, "start": start, "end": end}


@pytest.fixture
def bridge():
    store = FakeStore()
    server = serve(store, 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield store, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def send(url, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_add_list_and_complete(bridge):
    _store, url = bridge
    assert send(url + "/reminders", "POST", {"title": " Pain ", "list": "Courses"})[0] == 201
    status, items = send(url + "/reminders?list=Courses")
    assert status == 200 and [r["title"] for r in items] == ["Lait", "Pain"]
    # sans liste : la liste par défaut de Rappels, pas les courses ; « toutes les 2 semaines »
    status, item = send(url + "/reminders", "POST", {"title": "Détartrer", "recurrence": "weekly", "interval": 2})
    assert status == 201 and item["list"] == "Rappels" and item["interval"] == 2
    assert send(url + "/reminders", "POST", {"title": "x", "recurrence": "weekly", "interval": 99})[0] == 400
    assert send(url + "/reminders/r1/complete", "POST")[1]["done"] is True
    assert [r["title"] for r in send(url + "/reminders")[1]] == ["Pain", "Détartrer"]
    assert send(url + "/reminders/zz/complete", "POST")[0] == 404


def test_refusals(bridge):
    _, url = bridge
    assert send(url + "/reminders", "POST", {"title": " "})[0] == 400
    assert send(url + "/reminders", "POST", {"title": "x", "recurrence": "hourly"})[0] == 400
    assert send(url + "/events")[0] == 400
    assert send(url + "/reminders/r1", "DELETE") == (405, {"error": "le pont ne supprime jamais"})


def test_lost_authorization_is_said(bridge):
    store, url = bridge
    store.allowed = False
    assert send(url + "/health")[1] == {"reminders": False, "calendar": False}
    assert send(url + "/reminders") == (403, {"error": "Rappels non autorisés"})


def test_events(bridge):
    _, url = bridge
    assert send(url + "/events?from=2026-10-31&to=2026-11-01")[1][0]["title"] == "Chez mes parents"
    assert (
        send(url + "/events", "POST", {"title": "Dentiste", "start": "2026-11-02T09:00", "end": "2026-11-02T10:00"})[0]
        == 201
    )
