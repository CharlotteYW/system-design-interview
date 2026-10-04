"""GraphQL query and mutation. Strawberry exports each method as a field."""

from __future__ import annotations

import strawberry
from strawberry.fastapi import GraphQLRouter

from src import bookings
from src.catalog import filter_events
from src.errors import ApiError


@strawberry.type
class Event:
    id: int
    name: str
    city: str
    status: str


@strawberry.type
class Query:
    @strawberry.field
    def events_query(self, city: str | None = None, status: str | None = None) -> list[Event]:
        rows = filter_events(city, status, "date")
        return [Event(id=row["id"], name=row["name"], city=row["city"], status=row["status"]) for row in rows]


@strawberry.type
class BookingResult:
    code: str
    replayed: bool
    booking_id: int | None
    quantity: int


@strawberry.type
class Mutation:
    @strawberry.mutation
    def book_seat(self, event_id: int, quantity: int, idempotency_key: str) -> BookingResult:
        try:
            _status, payload = bookings.book(42, event_id, quantity, idempotency_key)
        except ApiError as exc:
            return BookingResult(code=exc.code, replayed=False, booking_id=None, quantity=quantity)
        if "error" in payload:
            return BookingResult(
                code=payload["error"]["code"],
                replayed=payload["replayed"],
                booking_id=None,
                quantity=quantity,
            )
        booking = payload["booking"]
        return BookingResult(
            code="CREATED",
            replayed=payload["replayed"],
            booking_id=booking["id"],
            quantity=booking["quantity"],
        )


schema = strawberry.Schema(query=Query, mutation=Mutation)
router = GraphQLRouter(schema)
