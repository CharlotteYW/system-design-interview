# FAQ — Rate Limiter

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: Identify caller (IP, optional client id). **Per-endpoint** caps. Over limit → **429** with **Retry-After** and **X-RateLimit-*** headers. Check is **middleware on every request**, not a client-called `/check`.

**Q: What scale numbers would you use, and why?**  
A: **~10k QPS** of checks (peak up to ~100k). That is Redis-sized, not Postgres. **p99 of the check &lt; ~5 ms** because it sits on every request. Soft overshoot OK. Redis down → **fail open**.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Billing plans, geo, CDN/WAF, multi-region exact counts, a separate limiter process. Algorithm details wait for step 3.

**Q: Library vs gateway?**  
A: Interview picture: **gateway**. Local lab: **FastAPI middleware + Redis** so two workers share counts without nginx.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: There is no separate “write limiter” API. Every request: middleware **INCR** Redis → if over limit **429**, else run the handler. `/api/ping` is the cheap read; `/api/work` is the tight write-like route. Product DB only after **allow**.

**Q: Why these major boxes and not fewer/more?**  
A: App + Redis is the limiter. Postgres is the product store, not the counter. Extra limiter service or GET-then-INCR adds hops or races. Fail open: Redis down → skip check, do not use Postgres as a counter.

## Session questions

### 2026-09-27 (high-level)

**Q: In-process only means the counter is in replica memory?**  
A: Yes. Each app process has its own dict. Limit 10 with 4 boxes ⇒ up to 40 allows. Redis is what makes the cap **global**.

**Q: What does RTT mean? Why “one RTT”?**  
A: **Round-trip time**: app sends a command, waits for Redis’s reply. `INCR` is **one** RTT (~1 ms in-DC). GET then INCR is **two**. That is the p99 story.

**Q: Soft overshoot from Redis’s single-threaded INCR?**  
A: Correction: **INCR is atomic**. Two INCR commands become 10 then 11; only `count ≤ limit` runs the handler. You do **not** overshoot **200s** on one Redis. Soft overshoot we still accept: fail open, window-edge burst, multi-region. GET-then-INCR **does** race (two GETs see 9). “429s consume quota” is separate: rejected calls still `INCR`.

**Q: INCR then compare: increase from what? Native INCR? One call?**  
A: Missing key starts at **0**. Redis **`INCR`** is native: first call creates the key and returns **1**, then 2, 3, … The reply **is** the new count; app compares to `limit` in memory. **One command** to decide allow vs 429. Window reset needs **TTL** (`EXPIRE` when count==1, or pipeline INCR+EXPIRE). Forget TTL ⇒ counter never resets. **INCRBY** if you ever add >1.

**Q: Should the lab load a rules YAML, like production?**  
A: Yes. `src/rules.yaml` is read once when the process starts and kept in memory. A request does not open the file or query Postgres for the limit. Changing a number means restart. A database of rules is only worth it if non-engineers edit limits, and the check path would still use the in-memory copy.

**Q: Is Redis what demonstrates the five algorithms?**  
A: Yes, while Redis is up. The UI sends `X-Rate-Algorithm`. Fixed window and sliding counter are integer keys. The log is a sorted set of timestamps. Token bucket and leaky bucket are hashes (tokens or level, plus a timestamp). The in-process counter is only the emergency path when Redis errors, or the “already blocked until window end” flag after Redis has already said no. That fallback is always a small fixed window, so the five-way comparison needs Redis.

**Q: Wrap up?**  
A: User understands the rate limiter and the tests. Session closed 2026-09-27. `./scripts/stop.sh` ran.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: Redis key `rl:{identity}:{route}:{window_start}` + `INCR` + TTL = **fixed window**. One command, resets when the key expires. Sliding log (sorted set of timestamps) is exact and heavy. Token bucket is one key with tokens + timestamp, not a window id.

**Q: Where is the bottleneck as traffic grows?**  
A: One hot identity+route is **one Redis key** (single thread on that node). 10k spread-out users are fine on one Redis (~100k ops/s). A celebrity key does not shard away: hash still lands on one slot. Mitigate with a stricter local cap or a coarser key, not “more Postgres.”

**Q: Sliding window counter smooths bursts? 10 at 10:00:59 and 10 at 10:01:01 is fine because it is over a minute?**  
A (user): Chose sliding window counter to smooth bursts. Key = IP/user + route + epoch window start. Thought the two bursts are outside a 1-minute cap so both should pass.

Taught: those timestamps are **2 seconds** apart. Fixed window gives each clock minute its own counter, so **10 + 10 both allow** while any rolling 60s saw **20**. That **is** the bug if the product means “10 per rolling minute.” Sliding window counter **approximates** the rolling count (previous bucket weighted by time left); it does **not** queue traffic. **Leaky bucket** is what smooths.

**Q: Use a sliding window that slides 10 seconds, and implement every algorithm to compare?**  
A (user): 20 calls in one minute should be limited. Prefer sliding window, slide 10 seconds. Lab should include all algorithms.

Taught: the weight slides **continuously**, not in 10s jumps. `prev × (W − elapsed) / W + current`. Summing **10s buckets** is a coarser option. Interview answer: **sliding window counter**. Lab will expose **all five** on one UI after step 4, so the boundary, the log’s cost, token burst, and leaky queue are visible. Production still ships **one**.

## 4. Component questions and special situations

**Q: What fails if this component dies, and how do you recover?**  
A: Redis down → **in-process fixed window** with an **emergency** cap (about global/N), plus a metric. Not 429-for-everyone, not Postgres counters. Postgres down → limiter still works; product writes 503.

**Q: What would you change for 10x traffic or rush hour?**  
A: 10× means **10× checks**, including 429s. One Redis ≈ 100k ops/s, so add Redis capacity and app CPU when many keys are busy. Adding nothing lets the limiter time out and the backend take the flood.

**Q: How do you handle a hot key or a single hot partition?**  
A: Identity+route is already one key, so other users are isolated. Splitting that hot key (random suffix) **raises** the attacker’s limit. Cluster will not move one key. Local pre-check or edge block so 429s do not all hit Redis.

**Q: 10× — more replicas of the API, of Redis, or of a separate limiter? Local batch of 100?**  
A: The limiter is **middleware inside the API**, so more replicas means **more copies of that API**. The client never talks to Redis. Each call is: app accepts HTTP → Redis `INCR` → app writes **200 or 429**. At 100k checks/s you need both **app CPU** and **Redis** (many keys). A separate limiter fleet is only if you had chosen an extra `Check()` service.

The hot-user local counter means: after Redis has already returned “over limit,” this process remembers “blocked until the window ends” and **stops calling Redis** for that key. A batch `INCRBY 100` is different: it cuts Redis QPS but each replica can allow ~100 extra before it syncs. We do not use batching to stop a hot user.

**Q: Dead region?**  
A: Only apps that cannot reach Redis switch to the local emergency cap. The healthy region keeps Redis.

**Q: 10× is more API replicas and more Redis for many users? After a hot user is blocked, skip Redis until the next window, and keep skipping if the attack continues?**  
A: Yes on 10×: more copies of the **API** (the middleware lives there) and more Redis when keys are spread across users. Inside the current window, one “blocked until `window_end`” flag is enough. You do not add up every attack request. Those calls 429 in the process and skip Redis. At the next window the flag expires and the user gets a fresh budget, so the first calls hit Redis again until the cap trips. To ignore them across windows, add a longer ban (this process or the edge, minutes) on top of the rate limit. Each API replica learns the block on its own; the flag is not shared.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: Redis down replaces the global cap with a smaller per-process cap. Fixed window (if you ship it) allows 2× at the edge. A hot key still costs one Redis round trip per replica at the start of each window.

**Q: What would you add with more time?**  
A: Longer ban or edge block, Redis cluster, Lua so fixed-window 429s do not consume quota.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: The UI runs all five algorithms on the same routes. Fixed window allows 10+10 at the 60s boundary; sliding counter denies the second 10. After the first 429, the next call is `X-Rate-Path: local-block` and does not ask Redis. Allowed `POST /api/work` inserts a Postgres row; 429 does not.
