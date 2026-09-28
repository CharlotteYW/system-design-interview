# Database Indexing

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Database indexing](https://www.hellointerview.com/learn/system-design/core-concepts/db-indexing) · Alex Xu Vol 1 (data stores, URL shortener lookup by code)  
**Slug:** `database-indexing`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-09-27 session.

A table lives in pages. An index is a second structure that maps a column value to those rows so Postgres can jump there. It does not change the answer. It changes how many pages are read.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| No index / seq scan | Read table pages until the rows match. “Compare one by one” is the right picture. | Tiny tables, or the query needs most of the rows (a scan is then cheaper than jumping around) | Selective lookup on a large table (`WHERE code = ?` on millions of links) |
| B-tree | Sorted tree of pages. A write finds the leaf and updates it in place (a page split if the leaf is full). Equality, range, and `ORDER BY`. Postgres default | Point reads, ranges, and a moderate write rate on one machine (this lab’s `events` table) | A log of writes that never stops. In-place leaf updates become random disk I/O |
| LSM tree | The storage format of the whole table, sorted by the primary key. Writes append to a log and a memtable, then flush to immutable SSTables. A secondary index is a separate structure and is slower than the primary key | Ingest that dwarfs reads: metrics, audit logs, IoT. Cassandra, RocksDB, DynamoDB | A user-facing page that reads on every load. Also skip it as “an index I add in Postgres.” Postgres stays a B-tree |
| Hash index | Equality only (`=`). No range, no `ORDER BY` | A proven equality-only hot column where you have measured a win | The default choice. A B-tree already does `=` well and also does ranges |
| Composite index | One index on several columns, in order: `(user_id, created_at)` | Leftmost prefixes: `user_id = 5`, and `user_id = 5 AND created_at > …` | `created_at` alone. The second column is not a starting point. Put equality columns first, then the range column |
| Covering / INCLUDE | Index holds every column the query needs, so Postgres need not read the table page | A hot query that only needs those columns | Wide rows you rarely read; the index becomes a second copy of the table |
| Inverted index (GIN) | Word → document ids (a posting list). The lab’s GIN index is that map. A full search is `body LIKE '%redis%'`, which reads every document even after the GIN exists. Elasticsearch is the same map plus ranking and typo tolerance | “Which documents contain `redis`?” | `code = ?`, which stays a B-tree. Also skip Elasticsearch when the lesson is the comparison: a search engine has no full-scan side to show |
| Geospatial | Location is two-dimensional. Three interview structures: geohash (one string, B-tree on the prefix), quadtree (split the map into four), R-tree / GiST (nested boxes). The lab runs the R-tree | “Within 200 meters,” a map tile, a polygon | A B-tree on latitude alone. That is a band around the Earth. `id = ?` stays a B-tree |
| Write cost | Every `INSERT` / `UPDATE` / `DELETE` maintains every index on the table | A few indexes that match real queries | Indexing every column “to be safe” |

## Interview default

Name a **B-tree** on the column in `WHERE`, `JOIN`, or `ORDER BY` that selects few rows. Composite: equality columns first, range column last. The primary key is already a B-tree. Add an index only for a query you actually run.

Switch engines or index types only when the predicate changes. Write-heavy ingest: an LSM engine, sorted by primary key. “Within N meters”: geohash or quadtree on a whiteboard, PostGIS GiST when the store is Postgres. “Contains this word”: inverted index. `id = ?` stays a B-tree.

## LSM, in interview words

Source: [Hello Interview — Database indexing](https://www.hellointerview.com/learn/system-design/core-concepts/db-indexing). This is a paraphrase of that section, tied to the lab.

A B-tree write finds the leaf, reads the page, changes it, and writes it back. A few thousand writes per second is fine. Around 10^5 writes per second the random page updates dominate. A metrics pipeline (CPU, memory, error counts from many hosts) is that workload. Sequential writes on disk are much cheaper than random ones, including on SSDs.

An LSM tree is the way the whole table is stored, ordered by the primary key. You do not `CREATE INDEX` an LSM on an arbitrary column the way you add a B-tree. A lookup by that primary key is the fast path. A second access pattern (another column, or another sort) is an extra structure. Cassandra has those. DynamoDB exposes them as a local or global secondary index, and they cost more than the primary key.

Write path:

1. The key lands in the **memtable**, a sorted structure in RAM (a tree or a skip list).
2. The same write is appended to a **write-ahead log** so a crash can replay it. That append is sequential.
3. When the memtable is large enough, it freezes and is written once as an **SSTable**, an immutable sorted file. One sequential write replaces many random leaf updates.
4. **Compaction** merges those files in the background, drops overwritten values and deletion markers, and keeps the file count from growing forever.

Read path, newest data first: the live memtable, then any frozen memtable that has not been flushed, then SSTables from newest to oldest. A B-tree point read is about two or three pages. An LSM point read can open many files. Three tools cut that down:

- A **bloom filter** per file says “this key is definitely absent,” so most files are skipped. “Maybe” still means you open the file.
- A **sparse index** stores the key range of each block. A file whose range is 1000–2000 is skipped when the key is 500.
- **Compaction policy.** Size-tiered compaction rewrites less and can leave more files to check. Leveled compaction keeps fewer files and rewrites more.

Use an LSM when writes dwarf reads: metrics, audit logs, IoT. Use a B-tree when each page load issues several queries. Cassandra stores high-volume event streams this way. RocksDB is the embedded engine many databases put underneath. DynamoDB is treated as LSM-style storage. It does not swap in a B-tree when a key becomes hot.

The lab button is only steps 1–3 on one node: eight keys flush to one SSTable, then `k3` is written again and the read returns `v3-new` from RAM. Bloom filters, sparse indexes, and the two compaction policies are in these notes. They are not running code.

## Geospatial indexes

Same source. Latitude and longitude are two axes, and “near me” is a distance on a sphere. A B-tree has one sort order. The lab’s latitude band 37.79–37.80 returns the Ferry Building and the Atlantic point at longitude 10, because both share the latitude. A hand-built box on `(lat, lon)` is a rectangle in degrees. It is not a circle in meters, a degree of longitude shrinks toward the poles, and the range breaks when the box crosses ±180.

Three structures show up in interviews:

| Approach | How a point is stored | How “nearby” runs | Where it hurts |
| --- | --- | --- | --- |
| Geohash | Interleave lat and lon bits into one string. A longer string is a smaller cell. A normal B-tree indexes that string | Points in the same cell share a prefix. A radius also queries the neighboring cells, because two close points on a cell edge can have different prefixes | Cells are rectangles. Boundary misses if you forget the neighbors |
| Quadtree | The map is a square, split into four, and split again where many points sit. A city is a deeper tree than an ocean | Walk every square that overlaps the search disk | Depth follows density, so one hot downtown cell can be much deeper than the rest |
| R-tree (GiST in PostGIS) | Nearby objects sit inside a bounding rectangle. Rectangles nest | Walk rectangles that overlap the query, then test real distance (`ST_DWithin`) | An update can reshape several rectangles. Heavier writes than appending a geohash |

The lab’s places table is that restaurants example: a B-tree on `lat` (`idx_lat`) and a B-tree on `lon` (`idx_lng`). One click compares them with a geohash, a quadtree, and the GiST R-tree for “within 200 meters.”

| Approach | What the lab returns |
| --- | --- |
| `idx_lat` only | Ferry Building, the Atlantic point at the same latitude, and the corner of the degree rectangle |
| `idx_lng` only | Ferry Building, a restaurant far north on the same longitude, and the rectangle corner |
| Both B-trees | The degree rectangle: Ferry Building and the corner. The corner is inside the rectangle and outside 200 meters |
| Geohash | One string per point. The **Show lat/lon → index code** button cuts the world in half, writes one character per five bits, then retrieves `WHERE geohash LIKE 'prefix%'`. The full 7-character code of the query matches no restaurant; the first 6 characters match the Ferry Building and the rectangle corner |
| Quadtree | The search square prunes the Atlantic point and the far-north point. A point inside the square can still be outside the circle |
| R-tree / GiST | Ferry Building only |

## URL shortener

`links.code` is the primary key, so Postgres already has a B-tree on `code`. `GET /{code}` is an index lookup. `url` is not unique and we do not look up by it, so we do not add an index on `url`. A query `WHERE url = ?` on a large table with no index is a sequential scan.

## Pitfalls

- Expecting an index to speed a query that returns most of the table.
- A composite `(user_id, created_at)` used as if `created_at` alone were indexed.
- `LIKE '%foo%'` on a B-tree. The leading wildcard cannot walk the sort order. That query wants an inverted index.
- A B-tree on latitude described as a “near me” index. Same latitude is a ring around the Earth.
- Calling Postgres an LSM because writes are heavy. The write path is still an in-place B-tree leaf. LSM means a different store.
- Indexing every column. Writes pay for each index, and the planner can pick a useless one.
- Treating a hash index as a faster B-tree for ranges.

## Local demo

Postgres with 100,000 `events` rows. The `id` primary key is a B-tree from the start. The UI creates and drops a composite B-tree on `(user_id, created_at)` and shows `EXPLAIN` for the three predicates above.

The same page adds three structures the first session skipped:

- **LSM.** A small in-process story, not Postgres. Eleven writes, memtable limit 8. `k1` is read from the frozen file. `k3` was written again after the flush, so the read hits the memtable and returns `v3-new`.
- **Geospatial.** One button compares `idx_lat`, `idx_lng`, both of them as a degree rectangle, a geohash prefix, a quadtree over the four teaching restaurants, and the GiST R-tree. Only the R-tree returns the Ferry Building alone.
- **Inverted.** Two buttons on the same `notes` table. Full search is `body LIKE '%redis%'` and stays a sequential scan. The GIN index is the inverted index: `redis` → those document ids. Elasticsearch is the same posting list with ranking. It is not running here, because it would only show one side.

**Cut vs production:** no hash index, no Elasticsearch, no RocksDB. The LSM button stops at one flush. Bloom filters, sparse indexes, and size-tiered versus leveled compaction are notes only. The geohash and quadtree run in the app process on the four teaching restaurants. The B-trees and the R-tree run in Postgres. S2 and H3 are named in the notes and are not buttons. The covering demo is still Index Only Scan versus a heap fetch on `(user_id, created_at)`.

## How to run

Leave the stack up while you read `EXPLAIN`.

```bash
cd core-concepts/database-indexing
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
```

Open http://localhost:8000. Drop the composite index, run the three queries (sequential scans), create the index, run them again. `user_id` and `user_id AND created_at` should mention an index. The June 1 `created_at` query should stay a sequential scan.

Stop later with `./scripts/stop.sh`.

## Session notes

**2026-09-27**

**Q: No index, B-tree, hash, composite, write cost?**  
A (user): No index compares one by one. B-tree filters in log n. Hash forgotten. Composite combines two columns into one index. Writes must update the index too.

Taught: seq scan is right, and it is still fine when the table is small or the query wants most rows. B-tree is also for ranges and `ORDER BY`, and it is the Postgres default. Hash is equality only. Composite order matters: `(user_id, created_at)` serves `user_id` and `user_id + created_at`, not `created_at` alone. Write cost is real, so index the queries you run.

**Q: Does `(user_id, created_at)` hit no index, because it is not built on `user_id` or `created_at`?**  
A (user): None of the three queries use an index.

Taught: `CREATE INDEX ON t (user_id, created_at)` **is** an index on those columns, sorted by `user_id` first. `WHERE user_id = 5` and `WHERE user_id = 5 AND created_at > …` walk it. `WHERE created_at > …` alone does not, because dates are not in one global order inside that index.

**Q: Which query misses `(user_id, created_at)`?**  
A (user): `WHERE created_at > Jan 4`.

Taught: that is the one. The lab’s June 1 `created_at` query stays a sequential scan after the composite index exists. The two `user_id` queries switch to an index scan.

**Q: Can the lab show a covering index?**  
A: Yes. `SELECT user_id, created_at` is an Index Only Scan on `(user_id, created_at)`. `SELECT body` uses the same index to find rows, then a heap fetch for `body`. `VACUUM` builds the visibility map so the index-only plan is valid.

**Q: Wrap up?**  
A: User has the leftmost-prefix rule and the covering split. Session closed 2026-09-27. `./scripts/stop.sh` ran.

**2026-09-27, continued**

**Q: LSM writes, a geo index versus a B-tree on latitude, an inverted index?**  
A (user): LSM is for a heavy-write database. Geo was unfamiliar. An inverted index stores a keyword’s documents so a keyword lookup is faster.

Taught: “heavy write” is the right reason to *choose another engine*, and it does not turn Postgres into an LSM. An LSM write appends to a log and a memtable; a full memtable becomes an immutable SSTable. A B-tree write updates a leaf page in place. The radius query needs boxes around points (GiST). A B-tree on latitude returns the whole band, including the Atlantic point at the same latitude. An inverted index is word → row ids. `code = ?` stays a B-tree. The lab now runs all three.

**Q: Put the Hello Interview LSM summary, and the geospatial section, into our notes?**  
A: The LSM section is paraphrased under **LSM, in interview words**: table format by primary key, memtable, WAL, SSTable, compaction, the slower read, bloom filter, sparse index, size-tiered versus leveled, Cassandra / RocksDB / DynamoDB. The geospatial section is paraphrased under **Geospatial indexes**: geohash, quadtree, and R-tree. The lab still executes only the R-tree (GiST) against the latitude band.

**Q: Should the inverted-index demo be Elasticsearch? Postgres looks like a bad full-search example.**  
A (user): Compare full search with the inverted index, so a keyword maps to documents.

Taught: Postgres GIN is a real inverted index (word → document ids). The weak query is `LIKE '%redis%'`, which reads every body and ignores that map. Elasticsearch stores the same map and adds ranking and typos. It does not also demonstrate the full scan, so the lab keeps both buttons on Postgres. Full search stays a sequential scan after the word index exists. The inverted button lists `redis →` the document ids and uses `notes_body_gin`.

**Q: For geospatial, compare separate latitude and longitude B-trees with geohash, quadtree, and R-tree in the UI.**  
A (user): The restaurants table with `idx_lat` and `idx_lng` should sit next to the other indexes so the difference is visible.

Taught: each B-tree is one strip. Both together are a rectangle in degrees, so the rectangle corner is a hit and is still outside 200 meters. Geohash is one string and a prefix; neighbors still matter. The quadtree prunes squares that miss the search square, then still checks distance. The R-tree returns the Ferry Building only. The compare button writes that result under Geospatial.

**Q: Show how lat/lon becomes an index code, then how that code is retrieved.**  
A: The button **Show lat/lon → index code** cuts the world in half, writes one character per five bits, and looks up `WHERE geohash LIKE 'prefix%'`. The full code matches no restaurant. The first 6 characters match the Ferry Building and the rectangle corner.

**Close:** User said the lab looks good. Session closed 2026-09-28. `./scripts/stop.sh` ran.
