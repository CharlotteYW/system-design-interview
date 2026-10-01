# Components — Unique ID Generator

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Caller | The page, or any app that needs an ID | Asks for an ID. Does not store a user or an order |
| App server | A or B | Runs all four generators. A’s worker number is 1. B’s is 2 |
| Postgres sequence | `id_seq` | One integer for the counter path. Each `nextval` is one ID |
| Ticket table | `ticket_state.next_start` | Reserves blocks of 4. Servers mint the block from memory |
| UUID v4 | 16 random bytes in the process | Version nibble 4, variant bits 10. No shared state |
| 64-bit generator | Clock, worker, sequence in the process | The interview choice. No database call per ID |

## Why these pieces

- The sequence and the ticket table exist so the lab can show a shared counter. The 64-bit path does not use them.
- A ticket block that is only partly used is lost if that server dies. The sequence never loses a value, and it is called on every ID.
- UUID v4 needs no coordination and does not sort by time.
- The 64-bit ID sorts by time for one worker, and two workers stay unique because their worker bits differ.
- A backward clock stays on this process’s last timestamp. A central clock is not on the mint path.
- Worker numbers come from a lease of 1024 slots at process start. The lab hard-codes A=1 and B=2.
- One dead app server leaves already issued IDs valid. Ticket leftovers in memory are wasted. The 64-bit path skips only unused sequence numbers in that millisecond.
