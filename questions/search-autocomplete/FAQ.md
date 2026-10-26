# FAQ — Search Autocomplete

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?** (2026-10-25)  
A: For the prefix Kim has typed, return 5 full queries, sorted by how often people searched them. A tie breaks alphabetically. The client waits about 0.5 s after the last key, then calls. The server does not wait. A finished search (Enter) is recorded so the frequency can change later. The match is the start of the query. The returned text is the whole query, not only the untyped tail.

**Q: What scale numbers would you use, and why?** (2026-10-25)  
A: 10 million daily users is this session and Alex Xu Volume 1, chapter 13. The chapter then assumes 10 searches a day, 20 characters each, and a peak of 2 times the average. A request per character is about 48,000 a second at peak. One request per search, which the 0.5 s pause usually produces, is about 2,300 a second. Size the service for 48,000. The pause is headroom. Show the list within about 100 ms of the request. New query text is about 0.4 GB a day. The suggestion call stays up. Yesterday's frequencies are acceptable. The search log is durable. The suggestion structure can be rebuilt.

**Q: Is frequency the right sort, or is there a better rank?** (2026-10-25)  
A: Frequency is the interview default. Kim types `ki`. `kitchen` has been searched 5 million times, `kim` 4 million, `kitten` 3 million, and `kiosk` 20,000 times but 15,000 of those were in the last hour.

- **A:** frequency, then alphabetical. The list is `kitchen`, `kim`, `kitten`. The top 5 are stored with the prefix.
- **B:** alphabetical only. A rare word can outrank a common one.
- **C:** the last hour only. `kiosk` wins, and yesterday's searches vanish.
- **D:** Kim's own history first. One list per user. Left below the line.
- **E:** frequency plus a recency weight. A spike can rise without erasing `kitchen`.

Pick A at 48,000 requests a second. The request reads a stored list. It does not sort. E is the later change if a same-day spike must show up.

**Q: What would you explicitly cut from a 45-minute interview?** (2026-10-25)  
A: Hello Interview has no breakdown, so the cuts are the chapter's plus this session's. No spell check. English only. Drop characters other than lowercase letters and spaces. Match only the start of a query, not the middle. No personal ranking.

## 2. High-level design

**Q: Walk through a suggestion and a finished search.** (2026-10-25)  
A: Kim types `ki` and pauses. `GET /v1/suggestions` reads the top 10 for `ki` from memory on the query service and returns 5. The list was built from yesterday's counts. She presses Enter on `kitchen`. `POST /v1/searches` appends one row to `searches` and returns 202. The list does not change. A daily builder recounts the log, writes `suggestions`, and the query machines load the new snapshot.

**Q: Why not sort in the database on the request?** (2026-10-25)  
A: A `LIKE` plus `ORDER BY frequency` at about 48,000 requests a second does not return in 100 ms. The sort already happened when the snapshot was built. The request is one memory lookup. Postgres is the log and the stored snapshot, not the live read. Finished searches are only about 2,300 a second at the peak, so one table can append them.

## 3. Low-level design and deep dive

**Q: Hash map or trie?** (2026-10-25)  
A: Draw both. The `suggestions` table is the hash map: key `ki`, value the top 10. The query machine builds a trie from those rows. `kitchen` and `kim` share the nodes `k` and `i`. Each trie node stores its top 10, so the request stops there and does not sort the children. The interview drawing is the trie. The lab shows both lookups for `ki`.

**Q: How do you split a trie that does not fit on one machine?** (2026-10-25)  
A: Split on the first two characters, so the walk for `kitchen` stays on the `ki` machine. A split on the whole prefix would put `k` and `ki` on different machines and the walk would break. The first character alone is legal but uneven: more queries start with `s` than with `z`. Keep a second copy of each shard. One dead machine must not blank that prefix.

**Q: What do you return when the prefix is longer than the stored queries?** (2026-10-25)  
A: `kitchenx` matches nothing, so the list is empty. A walk cap is different. This session stops at 20 characters, the chapter's average query length. The node at that depth still holds the top 10 full strings. A longer type keeps the strings that start with the full text. It does not return empty only because the walk stopped.

**Q: So the browser caches the list and calls only when a full list filters below 5?** (2026-10-25)  
A: Yes, for a full list. `k` returned 5, and only 2 still start with `ki`, so the browser calls. `ki` returned 5, and all 5 still start with `kit`, so it does not call. The exception is a short list. If the server returned 3 for `k`, that was everything. Filtering it, even to empty, does not call. The first prefix always calls. Backspace uses an earlier cached list, or it calls. The server is still sized for a client that never skips.

**Q: The browser has the list for `k`. She types `i`. When can it skip the call?** (2026-10-25)  
A: Filter the cached list to queries that start with `ki`. Call the server when that leaves fewer than 5 and the cached list was full. Example: `k` returned `karate`, `kangaroo`, `kraft`, `kitchen`, `kim`. Only two start with `ki`. `kitten` can be missing from that five and still belong in the `ki` top 5, so the browser calls. If a later list for `ki` is `kitchen`, `kim`, `kitten`, `kite`, `kick`, all five start with `kit`. Those are the top 5 for `kit`, and the browser does not call. A short server list is already complete, so filtering it, even to empty, is safe. Backspace to `k` cannot be built from the `ki` list. The server is still sized for a call every time, about 48,000 a second.

**Q: Where is the bottleneck as traffic grows?**  
A: TBD

## 4. Component questions and special situations

**Q: The `ki` machine dies. Does the request fall through to Postgres?** (2026-10-25)  
A: No. The other `ki` machine already has the trie in memory, and the load balancer sends Kim there. A replacement loads `suggestions` from Postgres in the background. Her `GET` does not read Postgres. An empty list would blank every `ki` dropdown.

**Q: `ki` gets most of the 48,000 requests. Is a cache in front of the database the fix?** (2026-10-25)  
A: Not at this rate. A memory lookup of all 48,000 requests is about 10 MB a second, which one machine can do. The limit is the size of the `ki` tree. Split it again, into `kit` and `kim`, so each piece fits in RAM. More copies add request capacity. They do not shrink the tree. A cache in front of Postgres misses the point, because the live path does not read Postgres.

**Q: The builder does not finish. What is stale?** (2026-10-25)  
A: The dropdown stays on yesterday's snapshot, so the list is one extra day old. The new `searches` rows stay in the log. The next build that finishes counts both days. Reads never stop.

**Q: What would you change for 10x traffic or rush hour?** (2026-10-25)  
A: About 480,000 requests a second. Cache `GET /v1/suggestions?q=ki` at the edge until the next daily snapshot, because every user gets the same list. Then add trie copies for the prefixes that miss. The browser skip remains a per-client help. Postgres stays off the request.

**Q: How do you handle a hot key or a single hot partition?** (2026-10-25)  
A: The hot key is a short prefix such as `ki`. If the tree does not fit, split that pair by one more character. If the request rate does not fit, add copies and cache that exact GET at the edge.

## 5. Summary and future improvements

**Q: Walk Kim from `ki` to the five rows.** (2026-10-25)  
A: She pauses. The browser calls if a cached full list no longer has 5 matches. The `ki` machine reads the trie in memory and returns the stored top 5. Postgres is not on that call. Enter appends `kitchen` to `searches`. Tomorrow's build loads a new trie.

**Q: What risk is left?** (2026-10-25)  
A: A same-day spike stays off the list until the next daily snapshot. A cache that omits the snapshot id can also serve the old list after the new one is published.

**Q: What would you add with more time?** (2026-10-25)  
A: Frequency is already the popularity rank. A lambda layout adds today. The batch layer stays the daily snapshot. The speed layer adds today's counts every 2 minutes and refreshes only the prefixes that changed. The GET still reads a stored list, in about 100 ms. When the daily build includes today, those counts leave the speed layer, or the same searches are counted twice. Personal rank stays out.

## Session questions

Questions you asked at the end of a practice session. Append new ones with a date. Do not delete old entries unless a later design change superseded them.

### YYYY-MM-DD

**Q:**  
A:

## Local system

**Q: What is the hash map for?** (2026-10-25)  
A: It is the other layout of the same top-10 lists, kept in memory next to the trie. The key is the whole prefix, such as `ki`. The value is the ten queries. A lookup hashes `ki` and returns that list. It does not walk `k` then `i`. The trie stores each character once. The map stores the prefix string again at every key. The lab builds both from `query_freq` so the page can show they return the same five strings. The interview drawing is the trie. The map is there so the two lookups can be compared.

**Q: Does the daily batch build both `query_freq` and the memory trie?** (2026-10-25)  
A: The daily batch builds yesterday's column and then the memory layouts. It adds every row in `searches` onto `query_freq.yesterday`, sets `folded_today` to 0, deletes the log, and builds the trie and the hash map again. The fold is the other job. Every 20 seconds in the lab, and every 2 minutes in the design, it adds pending rows onto `folded_today` only, and it also rebuilds memory. A GET reads that memory. It does not run either job.

**Q: The log has each search, Postgres has one aggregated query row, and the five prefixes exist only in the trie?** (2026-10-25)  
A: The log and the aggregate are right. `searches` has one row per Enter. `query_freq` has one row per full query, such as `apple` with yesterday 5300. The five prefixes are not in Postgres. They are built in memory from that one row, in both layouts. The trie has nodes `a`, `ap`, `app`, `appl`, `apple`. The hash map has those same five keys. A fold updates the one `apple` row, then both layouts are built again.

**Q: Is Postgres one row per prefix? Does searching apple update 5 rows?** (2026-10-25)  
A: No. Postgres has two tables. `query_freq` is one row per full query: `apple`, yesterday 5300, folded today 0. `searches` is one row per recorded search. A POST of `apple` inserts one `searches` row. A fold adds that count onto the one `apple` row. The five prefixes `a`, `ap`, `app`, `appl`, and `apple` are built in memory after the fold. They are not five Postgres rows. The interview snapshot table would be different: one row per prefix and position, written by the daily builder, not by the search call.

**Q: Is the trie a service, a database, or data in memory?** (2026-10-25)  
A: Data in memory inside the query process. A node is one character plus a map of child nodes and the top 10 queries. `kitchen` and `kim` share the nodes `k` and `i`. Postgres stores one frequency per query, not the trie. A fold builds a new trie from those rows and the next GET reads it. If the process dies, the trie is gone until the next load. The interview design is the same idea on each shard machine. There is no trie database.

**Q: What did the simplified implementation teach you that the diagram did not?** (2026-10-25)  
A: A recorded search stays pending. The dropdown does not move until fold. After 4500 `kiosk` rows, the fold puts `kiosk` into the `ki` top 5, between `kitchen` (5000) and `kim` (4000), because 100 + 4500 = 4600. The daily build moves that 4500 into yesterday. The next fold leaves the list unchanged, so the same searches are not counted twice. The trie and the hash map returned the same five strings. The seed produced 488 prefixes.
