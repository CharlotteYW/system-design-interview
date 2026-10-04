"""The API calls the inventory service. This hop is gRPC."""

from __future__ import annotations

import os

import grpc

from src import inventory_pb2, inventory_pb2_grpc
from src.errors import ApiError


def check_seats(event_id: int, quantity: int) -> dict:
    address = os.environ.get("INVENTORY_ADDR", "inventory:50051")
    try:
        with grpc.insecure_channel(address) as channel:
            stub = inventory_pb2_grpc.InventoryStub(channel)
            reply = stub.CheckSeats(
                inventory_pb2.CheckRequest(event_id=str(event_id), quantity=quantity),
                timeout=2,
            )
    except grpc.RpcError as exc:
        raise ApiError(503, "INVENTORY_DOWN", "The inventory service did not answer") from exc
    return {
        "service": "inventory",
        "method": "CheckSeats",
        "transport": "grpc",
        "ok": reply.ok,
        "remaining": reply.remaining,
    }
