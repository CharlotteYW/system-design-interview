# Components — Proximity Service

Updated 2026-11-02 after step 2. The learner selected Search Service and Business Service. The initial database choice is PostgreSQL with PostGIS. No local system is implemented yet.

| Component | Definition | Responsibility in this design |
| --- | --- | --- |
| Client | Caller of product APIs | Register with an owner session and stable attempt key, search near a point, and open a profile |
| Load balancer | Distributor across healthy application instances | Route control requests and support application-instance redundancy |
| API gateway | Public route boundary | Route nearby calls to Search Service and business calls to Business Service |
| Search Service | Reader for geographic queries | Validate center/radius/page inputs; query the spatial index; return distance-checked result summaries |
| Business Service | Writer and profile reader | Validate owner creation; persist one business per retryable attempt; serve profiles by ID |
| Existing identity provider / lab mock | Trusted identity source | Supply ownerId; account management and legal ownership proof remain outside scope |
| PostgreSQL business catalog | Authoritative relational data | Retain business identity, owner, profile, location, and times |
| PostGIS | PostgreSQL extension for geographic data | Supply point types, geographic distance/radius functions, and spatial operator support |
| GiST spatial index | PostgreSQL index framework with spatial operators | Prune geographic candidates; database maintains entries during table writes |
| Geographic radius predicate | ST_DWithin over geography values | Reject candidates outside the requested meter-based radius inside the SQL query |
| Coordinate B-tree, comparison only | Index ordered by latitude, optionally followed by longitude | Supports coordinate range filters before a separate radius test |
| S2 cell IDs, comparison only | Ordered geographic keys at a chosen storage level | Support candidate reads by descendant range when the query cover uses a coarser level |
| H3 cell IDs, comparison only | Geographic keys for mostly hexagonal cells | Support candidate reads from overlapping cells at the selected resolution |
| Nearby result cache, scale experiment | Short-lived first pages keyed by center, radius, and page size | Avoid repeated spatial queries when measurements show enough reuse |
| Search admission limits, scale variant | Global in-flight cap and budgets by search area | Bound database work from misses and preserve capacity for other areas |
| Cache request coalescing, scale variant | One in-flight refresh per query key on each instance | Share a fill result with identical callers and cap their wait time |
| Geographic distance | ST_Distance over geography values | Supply meters for display and distance ordering; business ID resolves ties |
| Primary-key index | Lookup by business ID | Support direct profile reads |
| Creation-attempt records | Durable owner-scoped retry state | Store request identity and the completed result in the same transaction as business creation |
| Optional catalog import / fixture loader | Controlled source of records | Support local demonstrations and optional imports without expanding the owner API |
| Separate search projection, comparison only | Derived geographic read model | If selected later, requires durable propagation, retries, and reconciliation |
| Search outbox, separate-store variant | Durable jobs committed with business records | Supply pending work to a worker that upserts search documents by business ID |
| Base and recent-change indexes, comparison only | Read-only tree plus a smaller index updated by a worker | Serve the batch snapshot and recent registrations together |
| Profile cache, comparison only | Reusable profile copies keyed by business ID | Deferred until measured reuse justifies expiry and invalidation work |
| Search read replicas, capacity variant | PostgreSQL copies on separate servers | Serve native spatial reads with separate read capacity; replication delay needs monitoring |
| Compact search table, comparison only | Small geographic rows beside full profiles | Can reduce row width; same-server tables still share resources |

The two services share one initial database contract. Business Service owns writes; Search Service has the read access required for its query. This simplifies consistency but couples schema changes and leaves shared database capacity to plan.

No Redis, message broker, outbox worker, or external search engine is required on the initial native-index path. Those remain explicit alternatives, not hidden dependencies. Source: [PostgreSQL index maintenance](https://www.postgresql.org/docs/current/indexes-intro.html), [PostGIS queries](https://postgis.net/docs/using_postgis_query.html).

## Data responsibilities

- businesses: stable ID, owner ID, display fields, location, and creation/update times.
- creation requests: composite primary key of owner ID and client-generated UUIDv4. Store the request fingerprint, business ID, original status and response body, and creation time. Business Service claims the key and completes the row in the same transaction as business creation.
- Native primary-key and spatial indexes: database-managed lookup state, not a second application write.
- The search cursor carries the last returned distance and business ID. Search Service validates it against the search parameters. Each request uses a pooled database connection.
- The [Step 3 data model](README.md#data-model) lists the catalog columns and constraints. The [final design flow](final-design-flow.md) records the selected schemas and comparison paths.

The lab adds a stored four-character geohash column and a B-tree on that column for the Geohash comparison. Multiple business rows can share a key. Each result reads the business ID from the matching row.

The advanced page uses two additional Python libraries, S2Sphere and H3. Business Service maintains `business_cell_keys` during registration. Search Service reads it by S2 ID range or H3 key. Its Quadtree and k-d tree variants build from a read-only snapshot of the catalog.

## Read-capacity follow-up — 2026-11-02

The initial lab keeps one indexed catalog table. A second table on the same server does not add independent CPU, memory, or disk capacity. Shared-table reads do not serialize merely because they use the same table.

Search replicas are the first production capacity variant to evaluate. Business Service writes the primary. Search Service can read replicas with native PostGIS indexes. PostgreSQL replication carries the committed changes; no application outbox is required for this path.

During a primary outage, eligible replica reads continue within the freshness policy. Business Service uses 503 for an unconfirmed profile miss and for writes while no writable primary is available. Promotion requires a candidate that meets the durability policy and a way to prevent the old primary from writing.

The regional durability variant adds a designated synchronous standby in a second region. Business Service waits for durable confirmation before returning 201. The failover controller verifies the candidate, fences the old writer, and changes routing. Read replicas can serve after replay within the freshness policy.

A fresh primary query can see the committed business. A replica can lag. The normal five-minute visibility target needs lag monitoring and a later failure policy. The proposed 29000 search requests/s does not establish a fixed replica count.

An independent search projection is a different variant. It needs durable propagation and recovery, but can use its own schema and indexes. See [search-approaches.md](search-approaches.md) for labeled options and source links.

## Radius-correctness follow-up — 2026-11-02

Index candidates can include points outside the requested circle. The radius predicate rejects those points. Candidate pruning, qualification, and ordering run inside PostgreSQL/PostGIS for one Search Service query. No application-side per-candidate call is required. The final page limit does not guarantee a fixed number of candidate distance checks. Detailed spatial-tree traversal is the next learner probe.

## Geohash comparison — 2026-11-07

Derive a cell key from the business coordinates and index that key. Search Service chooses a complete cell cover for the query. The stored coordinates support the final radius check. The Geohash lesson in the README compares the precision and lookup costs.

## Quadtree comparison

The exercise uses adaptive subdivision. A cell with more than 20 businesses can split into four children up to a maximum depth. The leaf can hold more entries when subdivision cannot separate their coordinates. An in-memory tree can be rebuilt from the durable catalog.
