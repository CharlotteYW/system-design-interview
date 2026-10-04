"""Seat check on its own process. The API calls this with gRPC."""

from __future__ import annotations

from concurrent import futures

import grpc

from src import inventory_pb2, inventory_pb2_grpc

REMAINING = 5


class InventoryService(inventory_pb2_grpc.InventoryServicer):
    def CheckSeats(self, request, context):  # noqa: N802
        ok = request.quantity <= REMAINING
        return inventory_pb2.CheckReply(ok=ok, remaining=REMAINING)


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    inventory_pb2_grpc.add_InventoryServicer_to_server(InventoryService(), server)
    server.add_insecure_port("0.0.0.0:50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
