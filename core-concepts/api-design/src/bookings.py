"""One idempotency key returns the first booking result."""

from __future__ import annotations

from src.catalog import find_event
from src.errors import ApiError
from src.inventory_client import check_seats

_keys: dict[tuple[int, str], tuple[int, dict]] = {}
_next_id = 1


def reset() -> None:
    global _next_id
    _keys.clear()
    _next_id = 1


def book(account_id: int, event_id: int, quantity: int, key: str) -> tuple[int, dict]:
    global _next_id
    if not key:
        raise ApiError(400, "MISSING_KEY", "Send an Idempotency-Key header")
    if quantity < 1:
        raise ApiError(400, "BAD_QUANTITY", "Quantity must be at least 1")
    find_event(event_id)
    slot = (account_id, key)
    previous = _keys.get(slot)
    if previous is not None:
        old_quantity, payload = previous
        if old_quantity != quantity:
            raise ApiError(409, "KEY_REUSED", "This key already belongs to a different booking")
        replay = dict(payload)
        replay["replayed"] = True
        status = 201 if "booking" in payload else 409
        return status, replay
    grpc_result = check_seats(event_id, quantity)
    if not grpc_result["ok"]:
        payload = {
            "replayed": False,
            "grpc": grpc_result,
            "error": {
                "code": "SEATS_UNAVAILABLE",
                "message": f"Only {grpc_result['remaining']} seats remain",
            },
        }
        _keys[slot] = (quantity, payload)
        return 409, payload
    booking_id = _next_id
    _next_id += 1
    payload = {
        "replayed": False,
        "grpc": grpc_result,
        "booking": {"id": booking_id, "account_id": account_id, "event_id": event_id, "quantity": quantity},
    }
    _keys[slot] = (quantity, payload)
    return 201, payload
