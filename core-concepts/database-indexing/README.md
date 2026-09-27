# Database Indexing

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Core concepts](https://www.hellointerview.com/learn/system-design/in-a-hurry/core-concepts) · Alex Xu Vol 1 (data stores, URL shortener lookup by code)  
**Slug:** `database-indexing`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-09-27 session.

A table lives in pages. An index is a second structure that maps a column value to those rows so Postgres can jump there. It does not change the answer. It changes how many pages are read.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| No index / seq scan | Read table pages until the rows match. “Compare one by one” is the right picture. | Tiny tables, or the query needs most of the rows (a scan is then cheaper than jumping around) | Selective lookup on a large table (`WHERE code = ?` on millions of links) |
| B-tree | Sorted tree. Equality, range (`>`, `<`, `BETWEEN`), and `ORDER BY` on that column. About log₂(N) page hops, not one comparison per row. Postgres default for `PRIMARY KEY`, `UNIQUE`, and `CREATE INDEX` | Almost every interview filter or sort | A query that matches most rows; a column you never filter or sort |
| Hash index | Equality only (`=`). No range, no `ORDER BY` | A proven equality-only hot column where you have measured a win | The default choice. A B-tree already does `=` well and also does ranges |
| Composite index | One index on several columns, in order: `(user_id, created_at)` | Leftmost prefixes: `user_id = 5`, and `user_id = 5 AND created_at > …` | `created_at` alone. The second column is not a starting point. Put equality columns first, then the range column |
| Covering / INCLUDE | Index holds every column the query needs, so Postgres need not read the table page | A hot query that only needs those columns | Wide rows you rarely read; the index becomes a second copy of the table |
| Full-text (GIN / search engine) | Index of words, not a B-tree of the whole string. `LIKE '%foo%'` does not use a normal B-tree | Search boxes. Elasticsearch when Postgres full-text is not enough | Exact `code = ?`. That stays a B-tree |
| Geospatial | Index of points or shapes (PostGIS) | “Near me”, radius | Equality on an id. Do not use a geo index as the primary key |
| Write cost | Every `INSERT` / `UPDATE` / `DELETE` maintains every index on the table | A few indexes that match real queries | Indexing every column “to be safe” |

## Interview default

Name a **B-tree** on the column in `WHERE`, `JOIN`, or `ORDER BY` that selects few rows. Composite: equality columns first, range column last. The primary key is already a B-tree. Add an index only for a query you actually run. Switch to full-text or geo only when the predicate is words or “nearby”, not `id = ?`.

## URL shortener

`links.code` is the primary key, so Postgres already has a B-tree on `code`. `GET /{code}` is an index lookup. `url` is not unique and we do not look up by it, so we do not add an index on `url`. A query `WHERE url = ?` on a large table with no index is a sequential scan.

## Pitfalls

- Expecting an index to speed a query that returns most of the table.
- A composite `(user_id, created_at)` used as if `created_at` alone were indexed.
- `LIKE '%foo%'` on a B-tree. The leading wildcard cannot walk the sort order.
- Indexing every column. Writes pay for each index, and the planner can pick a useless one.
- Treating a hash index as a faster B-tree for ranges.

## Local demo

Postgres with 100,000 `events` rows. The `id` primary key is a B-tree from the start. The UI creates and drops a composite B-tree on `(user_id, created_at)` and shows `EXPLAIN` for the three predicates above.

**Cut vs production:** no hash, GIN, or PostGIS index. The covering demo is Index Only Scan versus a heap fetch on the same `(user_id, created_at)` index, after `VACUUM` builds the visibility map.

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
