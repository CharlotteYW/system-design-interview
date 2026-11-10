# FAQ — Yelp

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: Search by coordinates with name and category filters. Open the business profile and read its reviews. Submit a rating from one to five stars, with optional text.

**Q: What scale numbers would you use, and why?**  
A: The [Hello Interview prompt](https://www.hellointerview.com/learn/system-design/problem-breakdowns/yelp) gives 100 million daily users, 10 million businesses, and a search latency goal below 500 ms. Assume five searches per user per day and a peak of five times the average. That gives about 5,800 searches per second on average and 29,000 at peak. Our p95 target means at least 95% of searches finish within the latency budget at peak load.

**Q: What can be eventually consistent after Lee submits a review?**

A: Acknowledge the submission after the queue commits. Kim can see the old average while Lee's review is pending. The worker saves the review and its summary in one transaction. A future search cache or separate index can catch up later. A retry after a lost response must not create a second copy.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Skip registration and admin tools by starting with an existing catalog. Return a list instead of a map. Match explicit search terms without personalized suggestions. Keep basic sign-in, but skip detailed privacy and GDPR workflows. Keep the availability and durability goals, but skip a full region recovery design. Check review input, but skip spam and abuse detection.

## 2. High-level design

**Q: Can I get nearby IDs and then filter by name or category?**

A: Yes, if you filter all relevant candidates before building the page. For example, only two of the nearest 20 businesses may be ramen restaurants, but more matching restaurants may be within the radius. If you limit to 20 nearby businesses first, you miss those other matches. Start with a single Search Service query that applies every supplied filter before paging.

**Q: Does the client need one Business Service call per result?**

A: No. The search response includes the fields needed for the list. If a future search index returns only IDs, fetch the details for one page in a single batch. Fetch the full profile when the user opens a result.

**Q: Walk through a write and a read at a high level.**  
A: The Business Service reads the profile by business ID. The Review Service reads a page of reviews for that business ID, newest first. On a write, the Review Service gets the author from the session, checks the input, and stores a job in `review_submissions`. It returns `202 Accepted` and the submission ID. A worker saves the review and marks the job `saved` in one transaction. The author checks that status using the submission ID.

**Q: Why these major boxes and not fewer/more?**  
A: Search filters catalog entries. Business returns a full profile. Review serves review pages and accepts submissions. The worker saves reviews from the queue. One PostgreSQL database holds the three core tables, `users`, `businesses`, and `reviews`, and the queue table `review_submissions`.

**Q: How do I read a business's reviews and the reviews I wrote?**

A: The business page calls the Business Service for the profile and the Review Service for its first review page. The Review Service filters by `business_id`. The My reviews page calls `GET /v1/me/reviews`. The same service filters by the session's `user_id` and joins the page to the business names. Both paths read saved rows from `reviews` and return a cursor. Separate indexes start with the business ID or author ID and then use timestamp and review ID for the page order. See the [review list indexes](README.md#review-list-indexes).

## 3. Low-level design and deep dive

**Q: Should search start from 300 name matches or 5,000 nearby businesses?**

A: Start from the 300 name matches if you must choose one and the lookup costs are similar. Check category and distance on those candidates, then sort and page the matches. In the design, send all filters in one SQL query. PostgreSQL can pick the spatial index for a tighter radius, the name index for a rare phrase, or intersect candidate row locations from both. Inspect the chosen plan on representative data. See the [search index comparison](README.md#combine-name-category-and-distance-filters).

**Q: Do location, name, and category need different indexes or a separate search database?**

A: They benefit from different index types. PostgreSQL can hold a PostGIS spatial index, a name index, and a category B-tree on the same table. Use an inverted word index for word search and a trigram index for name fragments. Elasticsearch is a separate read index worth considering if search needs independent capacity or richer relevance. Put the location and category on the same Elasticsearch document as the name so all filters run before paging. Keep PostgreSQL as the source of truth and update the search copy from committed changes. See the [search engine comparison](README.md#postgresql-or-elasticsearch-for-business-search).

**Q: How does the PostgreSQL name filter match part of a business name?**

A: Use `WHERE name ILIKE $1` and bind `%ram%` for the input `ram`. The percent signs allow characters on either side, so `Sunny Ramen` matches. `ILIKE` makes the match case insensitive. Apply this condition with the location and category filters before paging. Create the trigram index once so PostgreSQL can use it for substring queries. A very short fragment or a pattern that matches many rows may still need a scan. [PostgreSQL trigram indexes](https://www.postgresql.org/docs/current/pgtrgm.html).

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX businesses_name_trgm
    ON businesses USING GIN (name gin_trgm_ops);
```

**Q: What if two submissions use different keys for the same user and business?**

A: Both jobs can enter the queue. The unique pair `(user_id, business_id)` in `reviews` lets only one insert succeed, even when two workers run at the same time. The worker marks the winning submission saved and the other failed with `REVIEW_ALREADY_EXISTS`. This keeps the first saved rating. A retry with the same key uses the original submission ID instead. See the [review uniqueness comparison](README.md#allow-one-review-per-user-and-business).

**Q: Do we have to read all reviews again when Lee adds a rating?**

A: Keep one `business_rating_stats` row per rated business. Add Lee's five stars to `rating_sum` and one to `review_count`. Update both fields in the same transaction that inserts the review and marks the job saved. A duplicate does not change the totals. Search reads the summary and divides the sum by the count. A full scan can rebuild the summary if needed. See the [rating options](README.md#update-the-average-rating-and-show-it-in-search).

**Q: Can we look up a city's latitude and longitude and reuse the radius search?**

A: Yes, for a search near the city center. For a search inside the city, look up its boundary in `places` and check whether each business point falls inside or on the boundary. A circle can miss businesses in the city and include businesses in a neighboring city. Use the region label to resolve ambiguous place names. See the [named-area search comparison](README.md#search-by-city-or-neighborhood-name).

The boundary is the city's outline. Store it as a shape made from a closed chain of latitude and longitude points. A business has one point for its location. In a simplified example, a business 6 km from the center still matches if its point is inside the outline. A business 4 km from the center is excluded if its point is outside. PostGIS performs this check with `ST_Covers(place.boundary, business.location)`.

**Q: What does the PostGIS boundary query look like?**

A: Resolve San Francisco to a place ID. The example uses WGS 84 geometry columns for the polygon, center, and business points. Bind the place ID, `%ramen%`, and `restaurant` to the three parameters.

```sql
SELECT b.business_id, b.name,
       ST_Distance(b.location::geography, p.center::geography) AS distance_m
FROM places AS p
JOIN businesses AS b
  ON ST_Covers(p.boundary, b.location)
WHERE p.place_id = $1
  AND b.name ILIKE $2
  AND b.category = $3
ORDER BY distance_m, b.business_id
LIMIT 20;
```

`ST_Covers` decides which points match the boundary. `ST_Distance` measures distance in meters after the cast to `geography`. That distance orders the matches. [PostGIS boundary check](https://postgis.net/docs/ST_Covers.html) and [distance calculation](https://postgis.net/docs/ST_Distance.html).

**Q: How does a San Francisco search return business IDs?**

1. The client sends `GET /v1/places?name=San%20Francisco`. The Search Service looks up the name in `places` and returns the matching place IDs with their region labels. In the example, the user selects San Francisco, California, with ID `sf-ca`.
2. The client sends `GET /v1/businesses/search?placeId=sf-ca`. To filter for ramen restaurants, it also sends `name=ramen&category=restaurant`. The Search Service reads the boundary and center for `sf-ca` from PostgreSQL.
3. PostgreSQL finds matching business rows. `ST_Covers` checks the stored boundary against `businesses.location`. A spatial index can narrow the candidate points before this check. Optional name and category filters apply before paging.
4. The query sorts the matches by distance to the place center and then by business ID. It selects a page and returns the IDs, for example `b101` and `b205`. The search API includes each ID with its business summary. The client can use an ID to open the full profile.

The place ID identifies the area. Each business ID identifies one result. A search for the city alone uses the boundary query above with the name and category conditions omitted. See the [place lookup and search flows](FLOW.md#find-a-named-place).

**Q: Where does San Francisco's polygon come from, and how does it find businesses?**

1. Import the San Francisco feature from a published city boundary dataset, such as [California City Boundaries and Identifiers](https://data.ca.gov/@california-department-of-technology/california-city-boundaries-and-identifiers). It offers a GeoJSON export. Read the feature's `geometry` field and load it into `places.boundary` for `sf-ca`. The import runs before users search. [PostGIS GeoJSON import](https://postgis.net/docs/ST_GeomFromGeoJSON.html).
2. Store each business's location as a point in `businesses.location`. Use the same coordinate system for the points and the boundary. If the catalog gives only addresses, turn them into coordinates when loading the catalog.
3. At search time, join the stored city boundary to the business points with `ST_Covers(p.boundary, b.location)`. A GiST index on the business points can narrow the search to the rectangle that encloses the city. PostGIS checks the actual outline on the candidates. Return the `business_id` from each matching row. [PostGIS boundary check](https://postgis.net/docs/ST_Covers.html).

**Q: Can we precompute which cities and neighborhoods a business belongs to?**

A: Yes. Use the imported polygons to compute membership when a business is added or moved. For example, store `["bay-area", "sf-ca", "sf-mission"]` for business `123`. PostgreSQL can store one row per membership. Elasticsearch can index the IDs as keywords and find the business with an exact `term` filter on `sf-mission`. A bounding box only checks a rectangle. Use the polygon to decide which IDs to assign. If a polygon changes, recompute the affected memberships. Keep the point for searches with a custom radius. See the [membership comparison](README.md#compute-place-membership-at-search-time-or-ahead-of-time).

**Q: Why this storage model over the alternative?**  
A: TBD

**Q: Where is the bottleneck as traffic grows?**  
A: TBD

## 4. Component questions and special situations

**Q: What happens if review workers are down for 10 minutes?**

A: While there is room, commit the job, return `202 Accepted`, and show pending. Pause new intake if the pending count or oldest job age passes the configured limit. Return `503` with `Retry-After`. Existing receipts and status checks still work. If the queue starts empty and accepts all 50 jobs per second, it contains 30,000 jobs when the workers recover. With 150 completions and 50 arrivals per second, the backlog clears at 100 per second, so it takes 5 minutes.

With an example cap of 15,000 pending jobs, stop accepting new jobs after five minutes at 50 submissions per second if the workers are still down. Pause sooner if the oldest job reaches the maximum acceptable pending age. Resume as the workers drain the queue below the configured limits.

**Q: Why limit the queue if workers can save 150 reviews per second?**

A: The queue stores work that still needs to run. If a new review has 30,000 jobs ahead of it and workers process oldest jobs first at 150 per second, it waits about 200 seconds after recovery to reach the front. The whole backlog takes 300 seconds to clear because 50 new jobs arrive each second. If 200 jobs per second arrive while workers complete 150, the queue grows by 50 jobs every second. More space buys time, but it cannot make workers catch up.

Thirty thousand rows can be fine if PostgreSQL has room and users can wait. Set the limit from the allowed delay and the database's measured capacity. A cap controls how much new work we promise to finish. Jobs already accepted stay in the queue.

**Q: What runs the queue, and how does it remember what it saved?**

A: A Python process polls the submission table directly. It picks an eligible pending row in creation order and uses `FOR UPDATE SKIP LOCKED` to claim it. A second worker can skip the claimed row. The order is approximate because workers run in parallel and a retry may become eligible later. The job row holds the state, so a restarted worker can find pending jobs without remembering its previous position. The worker commits the review, rating totals, and saved status together. A temporary job failure can schedule a retry. A permanent failure records a failed status. If Lee misses the POST response, retry with the same key. If Lee misses a status response, repeat the GET. See the [worker query and failure paths](README.md#how-the-worker-claims-and-saves-a-review).

**Q: How would you confirm the database bottleneck and test a cache at ten times the traffic?**

A: Measure API p95, database connection wait, and query time separately. Check database CPU, disk I/O, and locks. Sample the most costly query plans and measure how often search inputs repeat. Cache popular results in front of PostgreSQL if the hit rate supports it. At 290,000 searches per second, a 90% hit rate would leave about 29,000 misses per second with one query per miss. Compare p95, database queries, and errors under the same load. Tune expensive queries or add read capacity if too many requests miss the cache.

**Q: What if 500 identical searches miss the cache at once?**

A: The database could receive 500 queries. Group simultaneous requests by the exact cache key. The first request queries PostgreSQL and fills the cache. The rest wait for that result. With one group per process, ten processes could still issue ten queries for the same page. Use shared coordination if that is too much. See the [rush hour options](README.md#rush-hour-cache-expiry).

**Q: How do you update the average for a business with a burst of reviews?**

A: Keep the review write independent of the summary row during the burst. Insert a rating event with the new review in one transaction. A rating worker groups events by business, adds each group's star sum and count, and marks those events applied in the same transaction. A retry cannot apply a committed batch twice. At 500 reviews per second, five seconds can produce 2,500 ratings. Use a shorter batch interval if the five-second target includes processing and cache delay. See the [hot business comparison](README.md#one-business-gets-a-burst-of-reviews).

**Q: What if Lee got an acceptance receipt and the new primary cannot find it?**

A: Return a temporary status error during failover. A missing row may be waiting for replay or may have been lost under asynchronous replication. If recovery confirms loss, explain it and offer a retry with the same payload and key. To survive one server failure, wait for a synchronous standby in a separate failure domain to flush the commit to durable storage before returning `202`. Promote a standby with that commit and replay it before serving status. This adds latency and can pause acceptance if the required standby is unavailable. See the [failover comparison](README.md#database-failover).

**Q: When does Option B return 503, 404, or 200 for a status check?**

A: Return `503 REVIEW_STATUS_UNAVAILABLE` while the service cannot verify the status during failover. The app keeps the receipt and retries the GET. Once the promoted standby has replayed Lee's accepted submission, return `200 OK` with its current status. Use `404 Not Found` for an unknown submission ID when the database can answer the lookup. [HTTP 503](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.6.4) and [HTTP 404](https://www.rfc-editor.org/rfc/rfc9110.html#section-15.5.5).

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: Hot businesses can serialize rating updates. A stale standby can be missing a recent acceptance. Repeated search misses can also overload PostgreSQL. Compare rating batches, durable standby acknowledgment, and coalescing against the measured problem.

**Q: What would you add with more time?**  
A: Measure peak review writes. Start with direct writes if they meet the target, and use a queue if a short wait is worth smoothing bursts. For direct writes, use an atomic SQL increment for rating sum and count. Use an optimistic version check for edits that need to detect stale state.

## Session questions

Questions you asked at the end of a practice session. Append new ones with a date. Do not delete old entries unless a later design change superseded them.

### 2026-11-08

**Q: Why choose a queue for review submission?**

A: During a burst, Lee can get a durable acceptance receipt while the worker saves reviews at a controlled rate. Lee sees `pending` until the worker commits the review. If the response is lost, the same retry key returns the same submission ID. If the worker crashes before commit, the pending job can run again. The queue adds a write and a status check, and the PostgreSQL queue depends on the database being available.

**Q: Does our Yelp scale require a review queue?**

A: The numbers we have do not show that a queue is required. The 29,000 peak requests per second estimate is for search. The 50 submissions per second figure is a worker outage exercise. Start with a direct transaction in production if it meets the review write latency target at peak. It gives Lee a saved review ID as soon as the database commits. We keep the queue in the lab to practice durable acceptance, retries, and worker recovery. In production, the queue can smooth short bursts when Lee can wait for publication. It adds database work and does not help accept jobs when the shared PostgreSQL database is unavailable. See the [submission comparison](README.md#submit-a-review-1).

**Q: What tables do we need for the queued review design?**

A: Use `users` for authors, `businesses` for profiles and search fields, `reviews` for saved reviews, and `review_submissions` for the durable queue and the author's status. The API adds pending submission `s17`. The worker creates review `r42` and updates `s17` with its review ID in one transaction. See the [data model](README.md#data-model) for the columns.

**Q: Can we put the review on the queue and return Accepted?**

A: Yes. In our design, the API inserts only the queue job before returning `202 Accepted`. The worker later writes the public review. A typical work queue lets the worker acknowledge a job when it finishes. The business page needs a permanent record it can query by business ID, and Lee needs a status record he can check after the worker finishes.

- **Option A — Use one table for the queue and published reviews.** Insert a pending row, return its ID, then let the worker change its status to saved. Keep saved rows and filter the public list to saved rows. This works in PostgreSQL. Queue and public queries share the same table, so each path must apply the right status filter.
- **Option B — Keep separate tables.** Insert a job in `review_submissions` and return its ID. The worker creates the public row in `reviews` and updates the submission in one transaction. Each table has its own access pattern and retention policy. This adds a write and stores some fields twice.

**We pick Option B for this design.** The queue keeps pending and failed attempts separate from the public list. Option A is a simpler starting point if one table serves both paths well.

**Q: Does the API write to both the submission table and a queue before replying?**

A: The `review_submissions` table is the queue in our design. The API commits one pending row and replies `202 Accepted` with the submission ID. The worker reads pending rows from that table. Once it saves the public review, it marks the submission saved in the same transaction. A later status request returns `200 OK` with the current status.

If we later add a separate message broker, we can save the submission and an outbox event in one database transaction. A background publisher sends the event to the broker and retries if the send fails. This keeps the worker notification recoverable if the API stops after commit.

**Q: How could we shard Yelp later?**

A: Start by routing each business and its reviews, submission jobs, and rating totals to one shard by `business_id`. That keeps the review transaction and one-review rule local. Use a copy of saved reviews keyed by `user_id` for My reviews, and consider a search view routed by geography. Update these views through a durable outbox. The submission status endpoint and author-wide retry keys need their own routing decisions. See the [sharding options and migration notes](README.md#future-sharding-by-business-or-author).

### 2026-11-09

**Q: Where can I see all of the Yelp lab's tables and what each one does?**

A: The [README data model](README.md#data-model) lists all eight tables, their key fields, and their purpose. It includes `business_places` for precomputed place membership and `rating_outbox` for batched rating updates. The [SQL schema](src/schema.sql) has the exact types, constraints, and indexes.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: Run the same search through polygon, membership, and radius modes. The seeded boundary and membership give the same businesses, while the circle can miss a business inside the area. The review buttons show the difference between an acceptance receipt and a committed review ID. The tests verify retry behavior and that concurrent direct writes keep both rating increments.
