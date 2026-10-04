"""Events list, filters, sort, and versioned field names."""

from __future__ import annotations

from src.errors import ApiError

EVENTS = [
    {"id": 1, "name": "Concert", "city": "NYC", "status": "upcoming", "date": "2026-10-01"},
    {"id": 2, "name": "Play", "city": "NYC", "status": "past", "date": "2026-09-01"},
    {"id": 3, "name": "Fair", "city": "SF", "status": "upcoming", "date": "2026-11-01"},
]


def filter_events(city: str | None, status: str | None, sort: str | None) -> list[dict]:
    rows = [dict(event) for event in EVENTS]
    if city:
        rows = [event for event in rows if event["city"] == city]
    if status:
        rows = [event for event in rows if event["status"] == status]
    field = "date"
    reverse = True
    if sort:
        reverse = sort.startswith("-")
        field = sort[1:] if reverse else sort
    if field not in ("date", "name", "city"):
        raise ApiError(400, "BAD_SORT", "Sort must be date, name, or city")
    rows.sort(key=lambda event: event[field], reverse=reverse)
    return rows


def for_version(event: dict, version: str) -> dict:
    if version == "v1":
        return dict(event)
    if version == "v2":
        renamed = dict(event)
        renamed["title"] = renamed.pop("name")
        return renamed
    raise ApiError(404, "UNKNOWN_VERSION", "Use /v1 or /v2")


def find_event(event_id: int) -> dict:
    for event in EVENTS:
        if event["id"] == event_id:
            return dict(event)
    raise ApiError(404, "EVENT_NOT_FOUND", f"Event {event_id} does not exist")
