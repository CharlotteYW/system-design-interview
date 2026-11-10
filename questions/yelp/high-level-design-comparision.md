# Yelp design comparison

The public Hello Interview page verifies the requirements and deep dives. Its full solution is behind the premium gate. The Alex Xu column uses ByteByteGo's public companion guide. The production column uses Yelp's public filing and its published search engine. It describes only what those sources disclose.

## 1. Database choice

| Data | Hello Interview Yelp | Alex Xu, Proximity Service | This session | Production Yelp |
| --- | --- | --- | --- | --- |
| Business profile | Store not disclosed in public text | Business catalog, engine unverified | PostgreSQL `businesses` | Primary store unverified |
| Search fields | The learner's excerpt covers spatial, inverted text, and B-tree category indexes. Store choice is unverified. | SQL example with a geohash index | PostgreSQL with PostGIS, trigram or full-text indexes for the name, and a category B-tree when selective | Yelp documents a proprietary indexing and ranking path and publishes the Lucene-based nrtSearch engine |
| User | Store not disclosed in public text | Not in that source | PostgreSQL `users` | Unverified |
| Review | Store not disclosed in public text | Not in that source | PostgreSQL `reviews` | Primary store unverified |
| Submission job and status | Store not disclosed in public text | Not in that source | PostgreSQL `review_submissions` | Unverified |
| Rating summary | Public deep dive asks for a fast search read | Not in that source | PostgreSQL `business_rating_stats` | Unverified |
| City and neighborhood shapes | Public deep dive asks for named areas | Public guide covers coordinates and radius | PostgreSQL `places` | Unverified |
| Rating event during a burst | Not disclosed in public text | Not in that source | PostgreSQL `rating_outbox` in the batch variant | Unverified |
| Cached page during a read spike | Not disclosed in public text | Not disclosed in the public guide | Search Service cache in the traffic variant | Unverified |

## 2. High-level design choice

| Source | Main path |
| --- | --- |
| Hello Interview Yelp | The public page separates search, profile and review reads, and review submission. The write acknowledgment and queue choices are unverified. |
| Alex Xu, Proximity Service | The public guide uses a location service for nearby queries and a business service for details and catalog changes. |
| This session | The gateway routes to Search, Business, or Review. The Review Service commits a pending job and a worker publishes it. Direct save is the simpler production starting point if it meets peak latency. |
| Production Yelp | Yelp discloses a search and ranking layer. The review write and acknowledgment path is unverified. |

## 3. Feature paths

### Search businesses

| Source | Steps and store |
| --- | --- |
| Hello Interview Yelp | Search with name, coordinates, and category. A deep dive adds cities and neighborhoods. The public text does not disclose the store. |
| Alex Xu, Proximity Service | Use coordinates and a radius in the location service. The public guide illustrates candidate lookup with a geohash prefix in SQL. |
| This session | Use the Search Service. Resolve a named place in PostgreSQL when needed. Filter with PostGIS and name or category, then page the matches and join rating summaries. |
| Production Yelp | Yelp reports proprietary indexing and ranking for search. The exact location filter and business query are unverified. |

The separate Elasticsearch index is a scale alternative. Copy the business name, category, location, and rating summary together so one query can apply every filter before paging. PostgreSQL remains the source of truth. See the [search engine comparison](README.md#postgresql-or-elasticsearch-for-business-search).

The named-area excerpt supplied by the learner also proposes precomputing memberships. PostgreSQL can store them in a business-to-place table, and Elasticsearch can index the same IDs as keywords. See the [membership comparison](README.md#compute-place-membership-at-search-time-or-ahead-of-time).

### Read a business profile and its reviews

| Source | Steps and store |
| --- | --- |
| Hello Interview Yelp | The user opens the business and its reviews. The public text does not disclose the calls or stores. |
| Alex Xu, Proximity Service | The Business Service returns business details. Review reads are outside the public guide. |
| This session | Open the profile through Business Service. In parallel, page the business's reviews through Review Service. Both read PostgreSQL by business ID. |
| Production Yelp | Yelp describes reviews and business pages. The primary read path is unverified. |

### Read my reviews

| Source | Steps and store |
| --- | --- |
| Hello Interview Yelp | Not in the public requirements. |
| Alex Xu, Proximity Service | Not in that source. |
| This session | Review Service uses the signed-in author ID. PostgreSQL pages the author's reviews and joins the business names for the page. |
| Production Yelp | The internal read path and store are unverified. |

### Submit a review and check status

| Source | Steps and store |
| --- | --- |
| Hello Interview Yelp | Accept a rating and optional review text. A deep dive asks for one review per author and business. The public text does not disclose acknowledgment or persistence details. |
| Alex Xu, Proximity Service | Not in that source. |
| This session | Review Service commits a pending job in PostgreSQL and returns an ID. The worker commits the review, totals, and outcome. The author checks that outcome using the submission ID. |
| Production Yelp | Yelp describes user reviews. The queue, acknowledgment, and source store are unverified. |

## 4. What this session keeps

Use 10 million businesses and 100 million daily users. Our assumptions give about 29,000 peak searches per second and a target search p95 below 500 ms. Estimate review writes separately. The feature split is closest to Hello Interview Yelp. The search and profile roles also follow ByteByteGo's Proximity Service shape. The PostgreSQL queue, author's review list, and failover exercise are choices for this session.

## 5. Sources

- [Hello Interview Yelp breakdown](https://www.hellointerview.com/learn/system-design/problem-breakdowns/yelp)
- [ByteByteGo Proximity Service guide](https://bytebytego.com/guides/proximity-service/) and [Alex Xu Volume 2 references](https://github.com/alex-xu-system/bytebytego/blob/main/system_design_links_vol2.md)
- [Yelp's annual report](https://www.sec.gov/Archives/edgar/data/1345016/000134501625000007/yelp-20241231.htm) and [Yelp nrtSearch repository](https://github.com/Yelp/nrtsearch)
