# FAQ — Unique ID Generator

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: Return one 64-bit integer. It is unique across servers and usually sorts by time. Account registration and the record the ID points at are out of scope.

**Q: What scale numbers would you use, and why?**  
A: 10,000 IDs per second, the rate named for this chapter. One machine can mint that in memory. 62^7 is about 3.5 trillion values, enough for about ten years of sequential IDs at that rate, and too small once the ID also carries a timestamp and a machine number. The ID is 64 bits.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Signup, login, and storing tweets, orders, or URLs. Also a gap-free 1, 2, 3 sequence across every server.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: There is no stored object to read. The caller asks any app server, and that server returns a new ID. The lab runs four generators on that path: one Postgres sequence, ticket blocks from that sequence, a random UUID, and a 64-bit time-plus-worker ID. The 64-bit generator is the chapter’s answer.

**Q: Why these major boxes and not fewer/more?**  
A: One generator would hide the tradeoff. The counter shows strict order and a single row. Tickets show order without a call per ID. UUID shows uniqueness without time order. The 64-bit ID shows both uniqueness and rough time order with no call per ID. A fifth base62 counter would repeat the shortener.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: The counter stores one integer in Postgres and calls it for every ID. Tickets store only the next block start, and the rest of the block lives in the server. UUID v4 and the 64-bit ID store nothing durable. The 64-bit fields are the clock delta, the worker, and the sequence, packed into one integer.

**Q: Where is the bottleneck as traffic grows?**  
A: The counter’s one sequence. Tickets move that call to once per block. UUID and the 64-bit generator do not have that call. A single worker’s sequence tops out at 4096 IDs in one millisecond.

## 4. Component questions and special situations

**Q: What fails if this component dies, and how do you recover?**  
A: IDs already returned stay valid. A dead 64-bit worker skips only the unused sequence numbers in the current millisecond. Other workers keep minting. A dead ticket server wastes the rest of its block. A dead Postgres stops the counter and the ticket path, and leaves the 64-bit path running.

**Q: What would you change for 10x traffic or rush hour?**  
A: 100,000 IDs/s stays inside one worker. The cap is 4096 IDs in one millisecond on one worker, about 4 million IDs/s. Past that, the worker waits for the next millisecond. More app servers spread a burst. Each server needs its own worker number. The bit layout stays.

**Q: How do you handle a hot key or a single hot partition?**  
A: There is no key. The hotspot is one worker’s sequence, or the single Postgres sequence on the counter path. The 64-bit path spreads load by adding workers, not by splitting a key.

**Q: The clock jumps backward. Do we add a central clock?**  
A: Each server keeps the timestamp of its last ID. A backward jump stays on that timestamp and advances the sequence. NTP keeps clocks close in the background. A central clock on every ID would put the network back on the success path. Example, server 1: the first ID is `709521886412804096` (sequence 0). The clock jumps back 5 seconds. The next ID stays on that same millisecond and is `709521886412804097` (sequence 1). Using the jumped-back clock with sequence 0 could repeat an ID from 5 seconds ago.

**Q: Two servers share a worker number. Do we record that in a distributed key-value store?**  
A: A lease of 1024 worker slots, taken once at process start. The store does not hold IDs. Reuse a slot only after the old process can no longer mint. Host A locks slot 0. Host B finds slot 0 taken and locks slot 1. Same millisecond and sequence 0, the IDs differ by 4096 because the worker bits differ. A second writer cannot commit the same slot while the lease is valid.

**Q: If A dies 1 second into a 30-second lease, how many IDs do we lose?**  
A: At most 4096 in the crash millisecond, the unused sequences on that server. The slot then sits unused for about 29 seconds. Other servers keep minting, so callers are still served. The unused numbers on slot 0 are a gap. One server can issue at most 4096 per millisecond, so 29 seconds of that slot is about 119 million unused numbers. The time field lasts about 69 years, and the chapter rate is 10,000 IDs/s, so that gap is acceptable.

**Q: One server dies. What happens, and what do we do?**  
A: IDs already returned stay valid. Unused sequence numbers in that millisecond are skipped. Other servers keep minting with their own server numbers. We leave the dead server’s slot reserved until the lease ends, then a new process may take it and start at the current millisecond, sequence 0. We do not continue the dead server’s sequence, and we do not revoke issued IDs.

**Q: What is the answer when one app server dies?**  
A: IDs already handed out stay valid. Numbers not handed out yet are skipped. Every other server keeps minting with its own worker number. The dead server’s slot stays reserved for 30 seconds. On tickets, a half-used block is thrown away (reserved 1–4, issued 1 and 2, lost 3 and 4, next server starts at 5).

**Q: In one example, what is the lease of 1024 slots?**  
A: A sign-up sheet with lines 0 through 1023. A writes its name on line 0. B finds line 0 taken and writes on line 1. Same millisecond and same sequence 0. The IDs differ in the server bits, which shows up as the last 5 decimal digits: A ends in 00000, B ends in 04096. The first 13 digits are the time and match. A second process that also wants line 0 is refused.

**Q: In production, is the slot sheet in DynamoDB or Postgres?**  
A: Either can hold 1024 rows. The sheet is written when a process starts, not on every ID, so it does not need a high-throughput store. Postgres wins when it is already running. DynamoDB wins on AWS when you do not want Postgres for this sheet. ZooKeeper or etcd is the usual interview lease: the entry vanishes when the process session dies. This lab keeps the list in memory. The four generator buttons use fixed workers A = 1 and B = 2.

**Q: Is the slot table a YAML file, an in-memory structure, or a database?**  
A: In this lab it is a Python list of 1024 pairs, `(owner, expires)`, created in memory by the “Show two servers taking slots” button. It is not YAML and not Postgres. The four generator buttons skip it and use fixed workers A = 1 and B = 2. A real deployment would put those same rows in a small shared table so every process sees one sheet.

**Q: What does the slot table mean, if different server numbers already make different IDs?**  
A: The table is the sign-up sheet that assigns those server numbers. One row per number, 0 through 1023. A starting server writes its name on the first empty row and uses that number in the sum. The next server takes the next empty row. Two servers cannot hold the same row, so they cannot add the same server term.

**Q: Is the ID a sum of the 64-bit fields, or are the digits concatenated?**  
A: It is a sum: `(time × 2^22) + (server × 2^12) + sequence`. The shifts put the fields in different bits, so the code’s `|` is the same number as that addition. The decimal digits are the spelling of the sum. They are not pasted together from the time, the server, and the sequence.

**Q: How many digits is the ID, and how is each digit composed?**  
A: One integer, 64 bits: 1 sign bit kept at 0, then 41 bits of time, 10 bits of server, 12 bits of sequence. `ID = (time × 2^22) + (server × 2^12) + sequence`. This example is 18 decimal digits, `709521886412800000`. The largest ID is 19 digits. Decimal digits are the base-10 spelling of that sum. They are not each assigned to time, server, or sequence.

**Q: Why does 709521886412800000 show no server digits? Should there be zeros for the server?**  
A: Server 0 is in the ID. Its 10 bits are `0000000000`, and that value is 0, so it adds nothing you can see as its own digits. The last `00000` is server 0 and sequence 0 added together. Server 1 uses the same slot of bits and prints `04096`, because `1 << 12` is 4096.

**Q: In one millisecond, what do server A’s IDs look like from sequence 1 to 1000?**  
A: A is server 0, so the ID is the base plus the sequence. Base `709521886412800000`. Sequence 1 is `…00001`, sequence 2 is `…00002`, sequence 10 is `…00010`, sequence 100 is `…00100`, sequence 1000 is `…01000`. Each step adds 1. The time digits `7095218864128` stay fixed. 1000 is under the 4095 cap, so this stays in the same millisecond.

**Q: Why is 04096 server 1? Is it because of (server 0 << 12)?**  
A: It is server 1 shifted left by 12. `0 << 12` is 0, which is A’s `00000`. `1 << 12` is 4096, which is B’s `04096`. The shift is 12 because the sequence occupies the lowest 12 bits, and the server sits just above them.

**Q: Which digit is the server, if A and B share the time and the sequence?**  
A: No single decimal digit is the server. The order is time, then 10 server bits, then 12 sequence bits. Same time and sequence 0: A is 709521886412800000 and B is 709521886412804096. The first 13 digits match (the time). The last 5 digits are 00000 versus 04096, which is server 0 versus server 1 with sequence 0. The server bits are 0000000000 versus 0000000001.

**Q: For A, is 709521886412800000 an input, or the ID A generates?**  
A: It is the ID. Slot demo, server 0, sequence 0, one fixed millisecond. The next IDs A generates in that same millisecond are 709521886412800001 and 709521886412800002. The 64-bit button hard-codes A as worker 1, so that button’s A does not end in 00000.

**Q: Which digits are time, server, and sequence when a server dies?**  
A: A hands out IDs ending 00000, 00001, 00002 (server 0, sequence 0, 1, 2). Skipped IDs end 00003 through 04095. B’s ID ends 04096 (server 1, sequence 0) and shares A’s first 13 digits because the time matches. A replacement 30 seconds later changes those time digits.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: Gaps. A dead server skips at most 4096 IDs in that millisecond, then its slot is unused for the rest of the lease, about 29 seconds if it dies one second in. Other servers still mint. We also accept one region, and a backward clock that stays on the last timestamp.

**Q: What would you add with more time?**  
A: Signup can call `POST /v1/ids` and store the user under that integer. The user is not packed into the ID. The generator topics worth extra time are the bit budget (41/10/12), a second region (5 datacenter bits + 5 machine bits), and the sheet being down: processes that already have a slot keep minting, and a new process cannot take a slot until the sheet returns.

**Q: If we have more time, which topics do we discuss?**  
A: Three. First, the 64-bit budget: 41 time, 10 server, 12 sequence. More than 4096 IDs in one millisecond on one server means shrinking time or server bits. Second, a second region, by splitting the 10 server bits. Third, the sheet’s failure: existing servers keep minting from memory, and only startup needs the sheet. Time-ordered IDs are also guessable if a signup puts them in a URL.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: The page runs the four generators and five situations. Clock jump: the second ID is the first plus one, on the same millisecond. Lease: A gets slot 0, B gets slot 1, a second claim on slot 0 is refused, and the two sequence-0 IDs differ by 4096. A full millisecond moves the next ID forward by 1 ms with sequence 0. A dead server leaves sequences 3–4095 unused, wastes ticket numbers 3 and 4, and the next ticket is 5. Postgres not answering stops the counter and the tickets only.
