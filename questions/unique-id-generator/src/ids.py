"""Four ID generators. Each returns the steps a reader can follow."""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field

EPOCH_MS = 1577836800000  # 2020-01-01 UTC
BLOCK = 4
WORKERS = {"A": 1, "B": 2}
LEASE_SLOTS = 1024
LEASE_TTL_MS = 30_000
DEMO_MS = 1_747_000_000_000


def counter_steps(server: str, value: int) -> list[str]:
    return [
        f"Server {server} asks Postgres for the next value of id_seq.",
        "Postgres increments the sequence and returns that value. No other server can receive it.",
        f"The ID is {value}.",
    ]


@dataclass
class TicketHolder:
    start: int | None = None
    end: int | None = None
    cursor: int | None = None

    def take(self, server: str, allocate) -> tuple[int, list[str]]:
        steps: list[str] = []
        if self.cursor is None or self.end is None or self.cursor > self.end:
            start, end = allocate()
            self.start, self.end, self.cursor = start, end, start
            steps.append(
                f"Server {server} has no remaining block. Postgres reserved {start}–{end} and moved the global cursor to {end + 1}."
            )
        else:
            steps.append(f"Server {server} still holds block {self.start}–{self.end}.")
        value = self.cursor
        assert value is not None and self.end is not None
        self.cursor = value + 1
        left = self.end - value
        steps.append(f"Handed out {value} from memory. {left} value(s) left in this block.")
        return value, steps


@dataclass
class Snowflake:
    worker: int
    last_ms: int = -1
    sequence: int = 0

    def take(self, server: str, now_ms: int | None = None) -> tuple[int, list[str], dict]:
        ms = int(time.time() * 1000) if now_ms is None else now_ms
        steps = [f"Server {server} reads the clock: {ms} ms since 1970."]
        # Clock moved backward: keep this server's previous timestamp and advance the sequence below.
        if ms < self.last_ms:
            ms = self.last_ms
            steps.append("The clock moved backward. This server waits at its last timestamp instead of reusing old IDs.")
        if ms == self.last_ms:
            self.sequence += 1
            if self.sequence > 4095:
                ms += 1
                self.sequence = 0
                steps.append("This millisecond already issued 4096 IDs. Wait for the next millisecond and start the sequence at 0.")
            else:
                steps.append(f"Same millisecond as the previous ID on this server. Sequence is {self.sequence}.")
        else:
            self.sequence = 0
            steps.append("New millisecond. Sequence starts at 0.")
        self.last_ms = ms
        # EPOCH_MS is the fixed date 2020-01-01. A clock before that date would make delta negative.
        # Clamp to 0 so the time field is the epoch itself. This is not the backward-clock stay.
        delta = ms - EPOCH_MS
        if delta < 0:
            delta = 0
        id_value = (delta << 22) | (self.worker << 12) | self.sequence
        steps.append(
            f"Delta from 2020-01-01 is {delta} ms. Pack (delta << 22) | (worker {self.worker} << 12) | sequence {self.sequence}."
        )
        steps.append(f"The ID is {id_value}.")
        steps.append(
            "The ID is the sum (time × 2^22) + (server × 2^12) + sequence. The decimal digits are not pasted together. "
            + bit_fields(id_value)
        )
        fields = {"timestamp_ms": ms, "delta_ms": delta, "worker": self.worker, "sequence": self.sequence}
        return id_value, steps, fields


def new_uuid(server: str) -> tuple[str, list[str], dict]:
    raw = bytearray(os.urandom(16))
    before = raw[6]
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    value = str(uuid.UUID(bytes=bytes(raw)))
    steps = [
        f"Server {server} draws 16 random bytes.",
        f"Byte 6 was {before:#04x}. Its high 4 bits are replaced with 0100, so the version is 4.",
        "Byte 8 has its high 2 bits set to 10. That is the RFC variant.",
        f"The remaining bits stay random. Formatted ID: {value}.",
        "The first character of the third group is the version. Here it is 4.",
    ]
    return value, steps, {"version": 4, "variant": "10"}


@dataclass
class GeneratorSet:
    lock: threading.Lock = field(default_factory=threading.Lock)
    tickets: dict[str, TicketHolder] = field(default_factory=dict)
    snow: dict[str, Snowflake] = field(default_factory=dict)

    def reset_memory(self) -> None:
        with self.lock:
            self.tickets = {name: TicketHolder() for name in WORKERS}
            self.snow = {name: Snowflake(worker) for name, worker in WORKERS.items()}

    def ensure(self) -> None:
        if not self.tickets:
            self.reset_memory()


@dataclass
class LeaseTable:
    """1024 worker slots. One row is written when a process starts."""

    ttl_ms: int = LEASE_TTL_MS
    slots: list[tuple[str | None, int]] = field(default_factory=lambda: [(None, 0) for _ in range(LEASE_SLOTS)])

    def acquire(self, owner: str, now_ms: int) -> tuple[int, list[str]]:
        steps: list[str] = []
        for index, (holder, expires) in enumerate(self.slots):
            if holder == owner and expires > now_ms:
                steps.append(f"{owner} already holds slot {index} until {expires}.")
                return index, steps
        for index, (holder, expires) in enumerate(self.slots):
            if holder is not None and expires > now_ms:
                continue
            if holder is not None:
                steps.append(f"Slot {index} was held by {holder} until {expires}. That lease has ended.")
            self.slots[index] = (owner, now_ms + self.ttl_ms)
            steps.append(
                f"{owner} locks slot {index} and holds it until {now_ms + self.ttl_ms}. Worker bits for {owner} are now {index}."
            )
            return index, steps
        raise RuntimeError("every worker slot is leased")

    def claim(self, owner: str, slot: int, now_ms: int) -> tuple[bool, list[str]]:
        holder, expires = self.slots[slot]
        if holder is not None and expires > now_ms and holder != owner:
            return False, [
                f"{owner} asks for slot {slot} because its config also says worker {slot}.",
                f"{holder} holds slot {slot} until {expires}. The row lock refuses {owner}.",
            ]
        self.slots[slot] = (owner, now_ms + self.ttl_ms)
        return True, [f"{owner} takes slot {slot}."]

    def preview(self, count: int = 4) -> list[str]:
        lines = []
        for index, (holder, expires) in enumerate(self.slots[:count]):
            if holder is None or expires == 0:
                lines.append(f"slot {index}: empty")
            else:
                lines.append(f"slot {index}: {holder} until {expires}")
        lines.append(f"slots {count}–{LEASE_SLOTS - 1}: empty")
        return lines


def bit_fields(value: int) -> str:
    bits = f"{value:064b}"
    sequence = value & 0xFFF
    worker = (value >> 12) & 0x3FF
    return (
        f"time {bits[1:42]}  server {bits[42:52]} ({worker})  sequence {bits[52:]} ({sequence})"
    )


def digit_compare(left_name: str, left: int, right_name: str, right: int) -> list[str]:
    a, b = str(left), str(right)
    mark = "".join("^" if x != y else " " for x, y in zip(a, b))
    return [f"{left_name} {a}", f"{right_name} {b}", f"  {mark}"]


def situation_clock() -> dict:
    snow = Snowflake(worker=1)
    now = DEMO_MS
    jumped = now - 5000
    first, steps1, fields1 = snow.take("A", now)
    second, steps2, fields2 = snow.take("A", jumped)
    lines = [
        "Server A, worker 1, mints an ID, then its wall clock jumps back 5 seconds.",
        *steps1,
        f"The next call reads the wall clock as {jumped}, which is 5000 ms earlier.",
        *steps2,
        f"The second ID is {second}, one greater than {first}. Same worker, same millisecond, next sequence.",
        "A central clock is not on this path. The process kept its own last timestamp.",
    ]
    return {
        "title": "Clock moves backward",
        "lines": lines,
        "facts": {
            "first_id": str(first),
            "second_id": str(second),
            "first_sequence": fields1["sequence"],
            "second_sequence": fields2["sequence"],
            "timestamp_ms": fields1["timestamp_ms"],
            "second_timestamp_ms": fields2["timestamp_ms"],
            "clock_read_ms": jumped,
        },
    }


def situation_lease() -> dict:
    table = LeaseTable()
    now = DEMO_MS
    slot_a, steps_a = table.acquire("A", now)
    slot_b, steps_b = table.acquire("B", now)
    refused, steps_refuse = table.claim("A2", slot_a, now)
    slot_a2, steps_a2 = table.acquire("A2", now)
    id_a, _, fields_a = Snowflake(slot_a).take("A", now)
    id_b, _, fields_b = Snowflake(slot_b).take("B", now)
    id_a2, _, _ = Snowflake(slot_a2).take("A2", now)
    lines = [
        f"The lease table has {LEASE_SLOTS} rows, slots 0 through {LEASE_SLOTS - 1}. A row stores the owner and when the hold ends. It does not store IDs.",
        *steps_a,
        "That was the only write for A. Later IDs on A read A's clock and A's sequence.",
        *steps_b,
        *steps_refuse,
        *steps_a2,
        *table.preview(),
        f"Both mint sequence 0 in millisecond {now}.",
        f"A packs (delta << 22) | ({slot_a} << 12) | 0 = {id_a}.",
        f"B packs (delta << 22) | ({slot_b} << 12) | 0 = {id_b}.",
        f"The IDs differ by {id_b - id_a}. One step in the worker field is {1 << 12}.",
        "Same millisecond. Same sequence, 0. The server slot is the field that differs.",
        *digit_compare("A", id_a, "B", id_b),
        "The first 13 digits match. Those are the time.",
        "The server is not one decimal digit. It is the 10 bits between the time and the sequence.",
        "In this pair that server change shows up in the last 5 digits: 00000 versus 04096.",
        "00000 is server 0 and sequence 0. 04096 is server 1 and sequence 0. The sequence bits are the same.",
        f"A bits: {bit_fields(id_a)}",
        f"B bits: {bit_fields(id_b)}",
        f"A2 on slot {slot_a} and sequence 0 would have packed {id_a}, the same integer A returned. A2 is on slot {slot_a2}, so its ID is {id_a2}.",
    ]
    return {
        "title": "Worker slot lease",
        "lines": lines,
        "facts": {
            "slot_a": slot_a,
            "slot_b": slot_b,
            "refused": (not refused),
            "slot_a2": slot_a2,
            "id_a": str(id_a),
            "id_b": str(id_b),
            "difference": id_b - id_a,
            "worker_a": fields_a["worker"],
            "worker_b": fields_b["worker"],
        },
    }


def situation_overflow() -> dict:
    snow = Snowflake(worker=1)
    now = DEMO_MS
    first, _, first_fields = snow.take("A", now)
    while snow.sequence < 4095:
        snow.take("A", now)
    nxt, steps, fields = snow.take("A", now)
    lines = [
        f"Server A, worker 1, is asked for IDs while the clock stays at {now}.",
        f"The first ID uses sequence {first_fields['sequence']}: {first}.",
        "The server keeps issuing in that same millisecond until sequence 4095. That is 4096 IDs, numbered 0 through 4095.",
        f"The next call still reads the clock as {now}.",
        *steps,
        f"The ID after the full millisecond is {nxt}. Its timestamp is {fields['timestamp_ms']} and its sequence is {fields['sequence']}.",
        "100,000 IDs/s is about 100 IDs in one millisecond, under 4096. This wait happens when one worker is asked for more than 4096 IDs in a single millisecond.",
    ]
    return {
        "title": "One millisecond is full",
        "lines": lines,
        "facts": {
            "first_sequence": first_fields["sequence"],
            "filled": 4096,
            "next_sequence": fields["sequence"],
            "next_timestamp_ms": fields["timestamp_ms"],
            "requested_timestamp_ms": now,
        },
    }


def situation_server_dies() -> dict:
    table = LeaseTable()
    now = DEMO_MS
    slot_a, steps_a = table.acquire("A", now)
    slot_b, steps_b = table.acquire("B", now)
    snow = Snowflake(slot_a)
    issued = []
    for _ in range(3):
        value, _, fields = snow.take("A", now)
        issued.append((value, fields["sequence"]))
    slot_c, steps_c = table.acquire("C", now)
    b_value, _, b_fields = Snowflake(slot_b).take("B", now)
    later = now + LEASE_TTL_MS
    slot_r, steps_r = table.acquire("R", later)
    r_value, _, r_fields = Snowflake(slot_r).take("R", later)

    next_start = 1

    def allocate() -> tuple[int, int]:
        nonlocal next_start
        start = next_start
        end = start + BLOCK - 1
        next_start = end + 1
        return start, end

    holder = TicketHolder()
    ticket_first, _ = holder.take("A", allocate)
    ticket_second, _ = holder.take("A", allocate)
    wasted_start = holder.cursor
    wasted_end = holder.end
    fresh = TicketHolder()
    ticket_next, ticket_steps = fresh.take("B", allocate)

    lines = [
        f"A holds worker slot {slot_a}. In millisecond {now} it returns three IDs, then the process exits.",
        *steps_a,
        *[f"A returns sequence {seq}: {value}." for value, seq in issued],
        "A exits. Callers already stored those three integers. Nothing revokes them.",
        f"Skipped IDs, still server {slot_a} and the same millisecond: {issued[0][0] + 3} through {issued[0][0] + 4095}.",
        "Last digits of A's IDs: 00000, 00001, 00002 were handed out. 00003 through 04095 were skipped.",
        "Those last digits are the sequence. The server is 0, so it adds nothing in front of the sequence.",
        f"A bits: {bit_fields(issued[0][0])}",
        *steps_b,
        f"B returns sequence {b_fields['sequence']} on worker {b_fields['worker']}: {b_value}. B does not share a counter with A.",
        *digit_compare("A", issued[0][0], "B", b_value),
        "Same time, so the first 13 digits match. B's last 5 digits are 04096: server 1, sequence 0.",
        f"B bits: {bit_fields(b_value)}",
        f"C starts while A's lease is still in the future. Slot {slot_a} stays with A.",
        *steps_c,
        f"{LEASE_TTL_MS // 1000} seconds later the lease on slot {slot_a} has ended.",
        *steps_r,
        f"R's first ID uses millisecond {r_fields['timestamp_ms']} and sequence {r_fields['sequence']}: {r_value}.",
        *digit_compare("A", issued[0][0], "R", r_value),
        "The carets are the time. R is still server 0, sequence 0, but 30 seconds later.",
        f"R bits: {bit_fields(r_value)}",
        "Ticket path, same crash, fresh cursor at 1. Blocks are 4 wide.",
        f"A reserved 1–4 and handed out {ticket_first} and {ticket_second}. A exits.",
        f"{wasted_start} and {wasted_end} are never issued.",
        *ticket_steps,
        f"B's first ticket ID is {ticket_next}.",
    ]
    return {
        "title": "One app server dies",
        "lines": lines,
        "facts": {
            "issued": [str(value) for value, _ in issued],
            "sequences": [seq for _, seq in issued],
            "b_id": str(b_value),
            "b_worker": b_fields["worker"],
            "c_slot": slot_c,
            "replacement_slot": slot_r,
            "replacement_sequence": r_fields["sequence"],
            "replacement_timestamp_ms": r_fields["timestamp_ms"],
            "wasted_tickets": [wasted_start, wasted_end],
            "next_ticket": ticket_next,
        },
    }


def situation_postgres_down() -> dict:
    value, steps, fields = Snowflake(worker=1).take("A", DEMO_MS)
    lines = [
        "Postgres does not answer. This is a simulated outage. The database process is still up.",
        "Counter: no ID. nextval('id_seq') has nowhere to run.",
        "Tickets: no block. The row that reserves the next range cannot be locked.",
        "64-bit generator: the ID is built in this process.",
        *steps,
        f"Worker {fields['worker']}, sequence {fields['sequence']}, ID {value}.",
    ]
    return {
        "title": "Postgres does not answer",
        "lines": lines,
        "facts": {
            "counter_ok": False,
            "ticket_ok": False,
            "snowflake_ok": True,
            "snowflake_id": str(value),
        },
    }
