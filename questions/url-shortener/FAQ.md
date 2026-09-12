# FAQ — URL Shortener

Practice these out loud. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: Create a short URL from a long one; redirect `GET /{code}` to the original; store a durable mapping.

**Q: What scale numbers would you use, and why?**  
A: Interview ballpark ~100M creates/month and ~10B redirects/month, read-heavy. The local app is a teaching subset of that.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Custom aliases, analytics, expiry, accounts, multi-region.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: Write: validate → generate code → insert Postgres → return short URL. Read: L1 → Redis → Postgres → 302, then fill caches.

**Q: Why these major boxes and not fewer/more?**  
A: App + Postgres is enough to work. Redis (and a tiny L1) exist because redirects dominate. No queue: create is a single insert.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: `code` PK + unique `url` is a simple KV. Unique URL makes create idempotent with hash codes. Alternative: auto ID → base62 if you want many shorts per destination.

**Q: Where is the bottleneck as traffic grows?**  
A: Redirect reads. Cache before you shard. Writes stay small.

**Q: Hash then rehash on collision — any catch?**  
A: Same URL always maps to the same code. Collision means two *different* URLs hashing to one code — increment salt. 7 base62 chars is enough space for this problem.

**Q: 301 or 302?**  
A: 301 = permanent, browsers cache, you may never see later clicks. 302 = temporary, we keep control. We use 302.

## 4. Component questions and special situations

**Q: Postgres is down. Create? Redirect?**  
A: Create: 503. Redirect: cache hit 302; miss 503, not 404 (404 would claim the link does not exist).

**Q: 10× redirects. Why not only add app servers?**  
A: Extra app processes still all query Postgres for the same keys. Cache the mapping first (L1 + Redis). Scale app after for CPU and connections.

**Q: Front page of Reddit (hot key)?**  
A: Cache that code in Redis (shared). L1 on each process also helps after the first hit. Guard the first miss so a herd does not stampede Postgres. One Redis key is fine; the danger is the DB.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: Hash cannot offer two aliases for one URL; cache can serve a stale mapping; single region.

**Q: What would you add with more time?**  
A: Custom aliases, analytics, CDN for 302s, ID-based codes, replication.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: TBD after you run `./scripts/setup.sh`, click through the UI, and pass the test scripts.
