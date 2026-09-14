# FAQ — URL Shortener

Practice these out loud. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: POST mints a **new unique code** every time (same long URL can have many shorts). GET short URL **302**s to the long URL. Uniqueness is on the **code**, not the long URL. TTL is nice-to-have. No auth — “different people” means different POSTs.

**Q: What scale numbers would you use, and why?**  
A: This session: **~10k QPS on redirects**, creates much lower, HA + low redirect latency. 10k QPS × 86,400 ≈ 864M redirects/day if sustained — that is why the read path needs a cache, not “more POST servers.” Local Docker is a tiny subset of that number.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: User accounts/auth, click analytics, **user-defined short URLs**. TTL is optional.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: Write: validate → monotonic ID → base62 `code` → INSERT (retry on `code` collision) → return short URL. Never reuse a **code**. Same long URL gets a **new** code each POST. Read: L1 → Redis → Postgres, then **302**. Fill caches on miss.

**Q: Why these major boxes and not fewer/more?**  
A: App + Postgres is enough to be correct. L1 + Redis exist because ~10k redirect QPS is read-heavy. No alias service (custom codes out). No queue (create is one insert). CDN is optional later, not required for the first picture.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: `code` PK, `url` not unique. Extra `updated_at` / `expires_at` for later TTL/edits; unused now (`expires_at` NULL = forever). KV store would also work; Postgres gives unique `code` cheaply.

**Q: Where is the bottleneck as traffic grows?**  
A: Redirect reads. Cache before you shard. Writes (Snowflake + insert) stay small vs 10k QPS clicks.

**Q: Snowflake + 7 base62 — any catch?**  
A: 7 chars cannot hold a 64-bit Snowflake without truncation → extra collisions. Use ~11 chars for a lossless encode, or 7 chars only with a smaller id space. Always retry INSERT on unique violation.

**Q: 301 or 302?**  
A: **302**. 301 is cached by the client; we would lose server-side control (TTL, destination change, future analytics).

**Q: Reddit-hot, L1 and Redis miss together?**  
A: Not “one heavy first hit.” Many parallel misses = **thundering herd** on Postgres. Coalesce: one loader per code (singleflight / Redis lock), then fill L1+L2.

## 4. Component questions and special situations

**Q: Postgres is down. Create? Redirect?**  
A: Create: **503**. Redirect: cache hit **302**; miss **503, not 404**.

**Q: Redis is down?**  
A: Create: still OK (no Redis on write). Redirect: L1 then Postgres. Optional extra rate-limit so PG survives. Do not fail POST because Redis is down.

**Q: 10× redirects. Why not only add app servers?**  
A: More app boxes increase 302 capacity but also increase **miss traffic** to Redis/Postgres. After singleflight: scale **L2** (hit rate / Redis cluster), then app replicas, then PG read replicas, then CDN. Not “replicas first, PG last” as the only story.

**Q: Snowflake clock skew — nothing breaks because distributed?**  
A: Distributed does not imply unique. Backward clock can reuse ids. DB unique + retry is the backstop. Sort-by-id can be wrong; `created_at` is the timestamp we trust.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: Cache can serve a stale mapping; Redis down can overload Postgres; Snowflake clock skew can collide without UNIQUE+retry; single region; TTL not enforced.

**Q: What would you add with more time?**  
A: TTL enforcement, custom aliases, analytics, CDN for 302s, Redis cluster, Postgres read replicas, Redis lock across app boxes.

## Session questions

Questions asked during / at the end of a practice session. Append with a date.

### 2026-09-13

**Q: What is “L1 + L2 plus singleflight,” and why does it help a sudden hot key on read?**  
A: L1 = in-process LRU (per app instance). L2 = Redis (shared). Cache-aside: L1 → Redis → Postgres, then fill caches. Singleflight = **coalesce concurrent loads of the same `code`**: many GETs wait on **one** DB (or Redis) fetch instead of each missing independently. Sudden Reddit traffic with empty caches is a **thundering herd**; cache filling “quickly” is the steady state *after* the first successful fill. Singleflight (per process) plus optional Redis lock (across processes) is what makes the first millisecond cheap. See README deep dive.

**Q: Recap: what does our length/ID choice do, and what if we must use 7 chars?**  
A: We mint a Snowflake-style 64-bit id, **base62-encode all of it (~11 chars)**, INSERT `code` as PK, retry on unique violation. Uniqueness of ids ≈ uniqueness of codes. If the interviewer/product demands **7 chars**: do **not** truncate Snowflake. Switch to a **smaller id space** that fits in \(62^7\) (e.g. Postgres sequence / compact counter) → 7-char base62, still INSERT-retry. Truncating 64 bits to 7 chars makes collisions routine. See README Step 3.

**Q: Where in the local code is (1) short URL generation, (2) create INSERT, (3) singleflight, (4) L1, (5) Redis?**  
A: All in `src/main.py`. (1) `Snowflake.next_id` + `to_base62` + `mint_code`. (2) `shorten()` loop: `mint_code()` then `INSERT INTO links`, retry on `UniqueViolation`. (3) `Singleflight.do` used from `redirect()` on cache miss. (4) `_l1` OrderedDict LRU via `l1_get` / `l1_set`. (5) `_redis`; `cache_get` / `cache_set` wrap L1 then Redis (`GET`/`SET` with TTL; Redis errors ignored).

**Q: Any remaining questions on this design or local build?**  
A: None at close. Follow-up later the same day (below).

**Q: Why does the singleflight waiter use `event.wait` once instead of a `while` loop?**  
A: `threading.Event` is a **latch**. The leader writes `box["value"]` or `box["exc"]`, then `event.set()` in `finally`. Waiters sleep until that bit flips (or 10s timeout). There is no predicate to recheck: once set, Event stays set, and CPython `Event.wait` is not the “spurious wakeup + while pred” pattern of `Condition.wait`. A `while not event.is_set(): event.wait()` would be redundant. Timeout here is a hole (`box["value"]` may be missing) — not something a while-on-Event fixes. See `Singleflight.do` in `src/main.py`.

**Q: Singleflight lock: does only one request hold it? Does `event.set` wake `event.wait`? Why `pop` under the lock?**  
A: (1) `threading.Lock` is exclusive: one thread inside `with self._lock` at a time; others block on acquire, then enter one-by-one only to register leader vs waiter, then **drop the lock** before `wait()` / `fn()`. They do not all hold it together, and they do not hold it for the whole Postgres round-trip. (2) Yes: `event.set()` unblocks every `event.wait()` on that Event. (3) `pop` removes this `code` from `_inflight` so a **later** miss can start a new flight. The lock makes `get`/`insert`/`pop` atomic vs each other so you cannot get two leaders or a waiter holding a popped event that never gets a twin registration bug. See `Singleflight.do`.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: An existing Docker volume still had `UNIQUE(url)` from the first pass — `CREATE TABLE IF NOT EXISTS` would not fix that; the app has to `DROP CONSTRAINT`. Redis being optional on create is a `try/except` around `SET`, not a second code path. Singleflight is a few dozen lines of `Event` + waiter map; it only helps **same `code` concurrent misses**, not the create path.
