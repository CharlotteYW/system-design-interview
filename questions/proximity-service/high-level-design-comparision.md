# High-level design comparison — Proximity Service

Prepared 2026-11-02 after the learner's high-level proposal. These are original study notes. The README records what the local lab implements.

Source limits matter. Hello Interview has a related technical article, not a standalone matching product breakdown. The full paid Alex Xu chapter was not available. ByteByteGo's public guide verifies the two-service shape and a geohash example, not the chapter's complete persistence or recovery design. The production reference is Uber's H3 engineering article; it does not disclose a full business-registration architecture.

## 1. Database choice

| Data | Hello Interview Proximity Search | Alex Xu Vol. 2 Ch. 1 / verified public material | This session | Production: Uber H3 article |
| --- | --- | --- | --- | --- |
| Business records and profiles | No complete product catalog schema selected | Chapter store not verified; public guide mentions a database without naming its product in the text | PostgreSQL businesses | Not specified in the cited article |
| Geographic lookup | Compares spatial trees and encoded cells, including PostGIS and geohash/S2/H3 | Public guide gives a geohash index and SQL-prefix example; full chapter choice remains unverified | PostGIS geography and GiST; ST_DWithin radius filtering | H3 hierarchical hexagonal cells for marketplace analysis and optimization; backing catalog store not specified |
| Registration retry results | Not covered by this technical article | Not verified in accessible chapter material or guide text | Owner-scoped creation-attempt results in PostgreSQL | Not specified |
| Native index maintenance | Describes database index families; does not establish our creation transaction | Full registration commit boundary not verified | PostgreSQL maintains the native spatial index during row writes | Not a business-publication specification |
| Optional separate projection work | No complete catalog/outbox implementation selected | Not verified | Deferred comparison: durable catalog event or equivalent recovery before derived updates | Not specified |

The PostgreSQL and PostGIS choices are supported by their official product documentation. They are not claims about Uber's or Yelp's private storage schema.

## 2. High-level design choice

| Source | Happy-path components and publication |
| --- | --- |
| Hello Interview related technical article | Explains geographic lookup structures and candidate filtering; does not provide our complete three-feature service lifecycle |
| Alex Xu chapter / ByteByteGo public guide | The public guide separates business management/details from location search and illustrates geohash lookup. The full chapter's exact stores and atomic publication are unverified |
| This session | Client → load balancer → gateway → Search Service or Business Service → shared PostgreSQL/PostGIS. Registration commits business and attempt result; native index maintenance follows the database transaction |
| Uber H3 engineering article | Describes a production geographic grid used for ride-marketplace analysis, pricing, and optimization. It does not specify our business APIs or publication transaction |

## 3. Search for nearby businesses

| Source | Steps and store |
| --- | --- |
| Hello Interview related article | Narrow candidates through a spatial tree or encoded cells, then apply geographic predicates or distance checks. Several supporting systems are discussed |
| Alex Xu chapter / public guide | Public example encodes coordinates into geohash and queries an index prefix in SQL. Complete chapter read path is unverified |
| This session | Gateway routes GET /v1/nearby to Search Service. PostGIS prunes candidates and applies the radius predicate. SQL returns distance-ordered business summaries and a bounded page |
| Uber H3 article | H3 supplies grid cells and neighbor relationships for its documented marketplace analysis. The post does not specify our paginated business-search endpoint |

No source proves one instance meets this session's peak of about 29000 search requests/s. Geographic density, radius, page behavior, and query plans need measurement.

## 4. View a business profile

| Source | Steps and store |
| --- | --- |
| Hello Interview related article | Not a product-profile API specification |
| Alex Xu chapter / public guide | Public guide assigns business details to Business Service. Exact chapter storage path is unverified |
| This session | Gateway routes GET /v1/businesses/{id} to Business Service. PostgreSQL primary-key lookup returns the authoritative profile. A missing ID returns 404 |
| Uber H3 article | Business profiles are not covered |

Profile caching is a later comparison. The initial path avoids another mutable copy until measured reuse justifies one.

## 5. Owner registers a business

| Source | Steps and store |
| --- | --- |
| Hello Interview related article | Registration and retry transactions are not specified |
| Alex Xu chapter / public guide | The public guide assigns adding/updating/removing business information to Business Service. Exact durability and idempotency rules are unverified |
| This session | Authenticated POST /v1/businesses validates the payload, saves business and attempt result in one PostgreSQL transaction, and returns 201 after commit. PostgreSQL maintains the native index. A repeated attempt returns the same business ID |
| Uber H3 article | The post does not describe business registration |

The session selects owner creation only. Edits, deletion, and a full administration console remain outside the product scope. The five-minute normal freshness allowance does not require an asynchronous index. A fresh matching query against the primary can see a committed row in the selected path.

## 6. What this session keeps

- Keep the learner's two-service split. It is closest to the public ByteByteGo guide at the service level.
- Use PostgreSQL/PostGIS native indexing initially instead of the guide's geohash example.
- Keep ten million businesses and one hundred million daily users as the learner's chosen workload.
- Keep explicit teacher assumptions: five searches/user/day, five-times peak, API p95 at most 500 ms, and normal visibility within five minutes.
- Keep full scan as a correctness comparison and teach encoded-cell/tree alternatives in steps 3–4. The lab must show important feasible variants.
- Native-index registration needs no catalog-to-search outbox. A separate projection variant needs reliable propagation if selected.
- Leave hot locations, caching, database read capacity, sharding, regional failure, and concurrent pagination for their dedicated probes.
- The chapter is not complete. Full schemas and final-design-flow.md follow step 4; implementation follows the five-step interview.

Follow-up on 2026-11-02: two same-server tables do not supply separate server capacity. The initial lab still uses one indexed table. Dedicated PostgreSQL search replicas are the first production read-capacity variant to evaluate. Replica searches can lag; the earlier post-commit visibility statement applies to fresh primary queries. Replica count remains unsized. See [the algorithm, product, and capacity comparison](search-approaches.md). This is our session analysis, not a claim about another source's architecture.

## 7. Sources

- [ByteByteGo — Proximity Service](https://bytebytego.com/guides/proximity-service/): public service split and geohash example.
- Alex Xu, System Design Interview, Vol. 2, Ch. 1. [Author's reference list](https://github.com/alex-xu-system/bytebytego/blob/main/system_design_links_vol2.md). The full chapter was not verified here.
- [Hello Interview — Proximity Search](https://www.hellointerview.com/learn/system-design/deep-dives/proximity-search): related index families, not a matching product scope.
- [PostgreSQL index maintenance](https://www.postgresql.org/docs/current/indexes-intro.html).
- [PostGIS spatial query guidance](https://postgis.net/docs/using_postgis_query.html) and [ST_DWithin](https://postgis.net/docs/ST_DWithin.html).
- Isaac Brodsky, [H3: Uber's Hexagonal Hierarchical Spatial Index](https://www.uber.com/us/en/blog/h3/), Uber Engineering, June 27, 2018. Production grid evidence, not an inferred PostgreSQL business catalog.
