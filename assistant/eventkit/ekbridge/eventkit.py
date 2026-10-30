"""Le magasin EventKit (macOS seulement, `pyobjc-framework-EventKit`) : l'interface officielle d'Apple vers Rappels et
Calendrier, les mêmes listes que l'iPhone par iCloud. macOS demande l'autorisation une fois, au premier lancement
depuis le Terminal ; au démarrage, le pont vérifie qu'il l'a toujours (§10) et /health le dit."""

from __future__ import annotations

import threading
from datetime import datetime

from .http import NotAuthorized

# EKAuthorizationStatus : 3 = autorisé (« fullAccess » depuis macOS 14), 4 = écriture seule
FULL = {3}


def _date(value: str):
    from Foundation import NSDate

    dt = datetime.fromisoformat(value)
    return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())


def _components(value: str):
    from Foundation import NSDateComponents

    dt = datetime.fromisoformat(value)
    c = NSDateComponents.alloc().init()
    c.setYear_(dt.year)
    c.setMonth_(dt.month)
    c.setDay_(dt.day)
    if len(value) > 10:
        c.setHour_(dt.hour)
        c.setMinute_(dt.minute)
    return c


def _iso(nsdate) -> str | None:
    return (
        None if nsdate is None else datetime.fromtimestamp(nsdate.timeIntervalSince1970()).isoformat(timespec="minutes")
    )


class EventKitStore:
    def __init__(self):
        import EventKit

        self.ek = EventKit
        self.store = EventKit.EKEventStore.alloc().init()
        self.lock = threading.Lock()

    def request(self) -> None:
        """Demande l'accès (une fenêtre de macOS la première fois) ; à lancer depuis le Terminal."""
        done = threading.Event()
        for kind in (self.ek.EKEntityTypeReminder, self.ek.EKEntityTypeEvent):
            done.clear()
            if (
                hasattr(self.store, "requestFullAccessToRemindersWithCompletion_")
                and kind == self.ek.EKEntityTypeReminder
            ):
                self.store.requestFullAccessToRemindersWithCompletion_(lambda ok, err: done.set())
            elif hasattr(self.store, "requestFullAccessToEventsWithCompletion_") and kind == self.ek.EKEntityTypeEvent:
                self.store.requestFullAccessToEventsWithCompletion_(lambda ok, err: done.set())
            else:
                self.store.requestAccessToEntityType_completion_(kind, lambda ok, err: done.set())
            done.wait(120)

    def access(self) -> dict:
        status = self.ek.EKEventStore.authorizationStatusForEntityType_
        return {
            "reminders": status(self.ek.EKEntityTypeReminder) in FULL,
            "calendar": status(self.ek.EKEntityTypeEvent) in FULL,
        }

    def _need(self, what: str) -> None:
        if not self.access()[what]:
            raise NotAuthorized("Rappels non autorisés" if what == "reminders" else "Calendrier non autorisé")

    def _list(self, name: str | None):
        calendars = self.store.calendarsForEntityType_(self.ek.EKEntityTypeReminder)
        if name is None:
            return None
        for c in calendars:
            if c.title() == name:
                return c
        raise KeyError(f"liste {name} (listes : {', '.join(sorted(c.title() for c in calendars))})")

    def _reminder(self, r) -> dict:
        due = r.dueDateComponents()
        return {
            "id": r.calendarItemIdentifier(),
            "title": r.title(),
            "list": r.calendar().title(),
            "done": bool(r.isCompleted()),
            "due": _iso(due.date()) if due is not None and due.date() is not None else None,
            "notes": r.notes(),
            "recurring": bool(r.hasRecurrenceRules()),
        }

    def reminders(self, list_name: str | None, done: bool) -> list[dict]:
        self._need("reminders")
        cal = self._list(list_name)
        predicate = self.store.predicateForRemindersInCalendars_([cal] if cal else None)
        got: list = []
        finished = threading.Event()

        def receive(items):
            got.extend(items or [])
            finished.set()

        self.store.fetchRemindersMatchingPredicate_completion_(predicate, receive)
        finished.wait(30)
        return [self._reminder(r) for r in got if done or not r.isCompleted()]

    def add_reminder(
        self,
        title: str,
        list_name: str | None,
        due: str | None,
        recurrence: str | None,
        interval: int,
        notes: str | None,
    ) -> dict:
        self._need("reminders")
        with self.lock:
            r = self.ek.EKReminder.reminderWithEventStore_(self.store)
            r.setTitle_(title)
            r.setCalendar_(self._list(list_name) if list_name else self.store.defaultCalendarForNewReminders())
            if notes:
                r.setNotes_(notes)
            if due:
                r.setDueDateComponents_(_components(due))
            if recurrence:
                frequency = {"daily": 0, "weekly": 1, "monthly": 2, "yearly": 3}[recurrence]
                rule = self.ek.EKRecurrenceRule.alloc().initRecurrenceWithFrequency_interval_end_(
                    frequency, interval, None
                )
                r.addRecurrenceRule_(rule)
            ok, error = self.store.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise ValueError(str(error))
            return self._reminder(r)

    def complete(self, reminder_id: str) -> dict:
        self._need("reminders")
        with self.lock:
            r = self.store.calendarItemWithIdentifier_(reminder_id)
            if r is None:
                raise KeyError(reminder_id)
            r.setCompleted_(True)
            ok, error = self.store.saveReminder_commit_error_(r, True, None)
            if not ok:
                raise ValueError(str(error))
            return self._reminder(r)

    def events(self, start: str, end: str) -> list[dict]:
        self._need("calendar")
        predicate = self.store.predicateForEventsWithStartDate_endDate_calendars_(_date(start), _date(end), None)
        return [
            {
                "id": e.eventIdentifier(),
                "title": e.title(),
                "start": _iso(e.startDate()),
                "end": _iso(e.endDate()),
                "all_day": bool(e.isAllDay()),
                "calendar": e.calendar().title(),
                "location": e.location(),
            }
            for e in self.store.eventsMatchingPredicate_(predicate)
        ]

    def add_event(self, title: str, start: str, end: str, calendar: str | None, notes: str | None) -> dict:
        self._need("calendar")
        with self.lock:
            e = self.ek.EKEvent.eventWithEventStore_(self.store)
            e.setTitle_(title)
            e.setStartDate_(_date(start))
            e.setEndDate_(_date(end))
            target = self.store.defaultCalendarForNewEvents()
            if calendar:
                target = next(
                    (c for c in self.store.calendarsForEntityType_(self.ek.EKEntityTypeEvent) if c.title() == calendar),
                    None,
                )
                if target is None:
                    raise KeyError(f"calendrier {calendar}")
            e.setCalendar_(target)
            if notes:
                e.setNotes_(notes)
            ok, error = self.store.saveEvent_span_commit_error_(e, 0, True, None)
            if not ok:
                raise ValueError(str(error))
            return {"id": e.eventIdentifier(), "title": title, "start": start, "end": end, "calendar": target.title()}
