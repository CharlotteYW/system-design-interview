# System flow — Yelp

The [Hello Interview Yelp prompt](https://www.hellointerview.com/learn/system-design/problem-breakdowns/yelp) provides the search, profile, and review feature split. These sequences describe this session's design.

## Overview

```mermaid
flowchart LR
  C[Client] --> L[Load balancer] --> G[API Gateway]
  G --> S[Search Service]
  G --> B[Business Service]
  G --> R[Review Service]
  S --> D[(PostgreSQL with PostGIS)]
  B --> D
  R --> D
  W[Review worker] --> D
  S -.-> K[Optional search cache]
  A[Rating batch worker] -.-> D
  D -.-> T[(Synchronous standby)]
```

The cache, rating batch worker, and synchronous standby support the scenarios in Step 4. The load balancer and gateway are separate roles that one local proxy can fill.

## Request paths

A cursor marks where to continue a result list. The service gets the author from the signed-in session. The client reuses the same idempotency key when it retries the same submission.

### Search businesses

```text
GET /v1/businesses/search -> 200 OK { businesses: [{ businessId, name, category, distanceM, averageRating, reviewCount }], nextCursor }
Query: { name?, category?, cursor?, placeId?, areaMode?, nameMode?, cacheMode? }
Radius mode also requires: { lat, lon, radiusM }
Body: none
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant S as Search Service
  participant D as PostgreSQL catalog with PostGIS
  C->>L: GET search with radius or place ID and optional filters
  L->>G: Route request
  G->>S: Forward search request
  S->>D: Filter, order, page, and join rating summaries
  D-->>S: Matching business summaries
  S-->>G: Summaries and next cursor
  G-->>L: 200 OK
  L-->>C: 200 OK
```

Use either a place ID or coordinates and a radius. With a place ID, the query filters business points by the place boundary and measures distance from the stored center.

### Find a named place

```text
GET /v1/places -> 200 OK { places: [{ placeId, name, region, kind, centerLat, centerLon }] }
Query: { name }
Body: none
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant S as Search Service
  participant D as PostgreSQL
  C->>L: GET places by name
  L->>G: Route request
  G->>S: Forward the name
  S->>D: Find matching places and their regions
  D-->>S: Matching place rows
  S-->>G: Place choices
  G-->>L: 200 OK
  L-->>C: 200 OK
```

### Read a business profile

```text
GET /v1/businesses/{businessId} -> 200 OK { businessId, name, category, address }
Body: none
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant B as Business Service
  participant D as PostgreSQL
  C->>L: GET profile by business ID
  L->>G: Route request
  G->>B: Forward profile request
  B->>D: Read businesses by ID
  D-->>B: Business row
  B-->>G: Profile
  G-->>L: 200 OK
  L-->>C: 200 OK
```

### Read a business's reviews

```text
GET /v1/businesses/{businessId}/reviews -> 200 OK { reviews: [{ reviewId, rating, text, createdAt }], nextCursor }
Query: { cursor? }
Body: none
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant R as Review Service
  participant D as PostgreSQL
  C->>L: GET reviews by business ID
  L->>G: Route request
  G->>R: Forward request with optional cursor
  R->>D: Read one page using reviews_by_business
  D-->>R: Review rows
  R-->>G: Reviews and next cursor
  G-->>L: 200 OK
  L-->>C: 200 OK
```

When the client opens a search result, it can start the profile and review requests together. Both use the business ID already present in the search result.

### Read my reviews

```text
GET /v1/me/reviews -> 200 OK { reviews: [{ reviewId, businessId, businessName, rating, text, createdAt }], nextCursor }
Query: { cursor? }
Body: none
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant R as Review Service
  participant D as PostgreSQL
  C->>L: GET my reviews with optional cursor
  L->>G: Route request
  G->>R: Forward signed-in request
  R->>R: Get author ID from the session
  R->>D: Page using reviews_by_author and join business names
  D-->>R: Review rows and business names
  R-->>G: Reviews and next cursor
  G-->>L: 200 OK
  L-->>C: 200 OK
```

### Submit a review

```text
POST /v1/businesses/{businessId}/reviews -> 202 Accepted { submissionId, status: "accepted" }
Query: { mode? }  // queued (default) | queued-batch | direct
Header: Idempotency-Key
Body: { rating: 1–5, text? }
Direct mode: 200 OK { reviewId, status: "saved" }
Temporary overload: 503 Service Unavailable { errorCode: "REVIEW_QUEUE_BUSY" }
Response header on overload: Retry-After
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant R as Review Service
  participant D as PostgreSQL
  participant W as Review worker
  C->>L: POST rating and optional text
  L->>G: Route request
  G->>R: Forward signed-in request and retry key
  R->>R: Get author ID from session and validate rating
  R->>D: Commit pending job or find the existing job for this retry key
  D-->>R: Submission ID
  R-->>G: Acceptance receipt
  G-->>L: 202 Accepted
  L-->>C: 202 Accepted
  W->>D: Lock oldest eligible pending job with FOR UPDATE SKIP LOCKED
  W->>D: Insert review under the unique user and business constraint
  W->>D: Increment rating sum and count only for a new review
  W->>D: Mark submission saved or failed in the same transaction
  D-->>W: Commit
```

The worker runs independently once the job commits. It can save the review before the acceptance response reaches the client.

In direct mode, the Review Service saves the review and increments the rating totals in one transaction. It returns the saved review ID after commit. In queued-batch mode, the review worker saves a rating event with the review, then the rating batch worker applies the event. The local client uses `X-Demo-User` on signed-in requests.

### Check submission status

```text
GET /v1/review-submissions/{submissionId} -> 200 OK { submissionId, status, reviewId?, errorCode? }
Status: pending | saved | failed
Body: none
Temporary recovery error: 503 Service Unavailable { errorCode: "REVIEW_STATUS_UNAVAILABLE" }
```

If a different submission already saved this user's review for the business, return `failed` with `errorCode: REVIEW_ALREADY_EXISTS`.

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant R as Review Service
  participant D as PostgreSQL
  C->>L: GET submission status
  L->>G: Route request
  G->>R: Forward signed-in request
  R->>D: Read submission by ID and author
  D-->>R: Current status and result
  R-->>G: Submission status
  G-->>L: 200 OK
  L-->>C: 200 OK
```

## Failure / overload path

If the acceptance response is lost, retry with the same key and payload. The Review Service returns the original submission ID, including while intake is paused. If the worker crashes before commit, the review insert, rating summary update, and status change roll back together. The job can run again. If the queue is unavailable or exceeds its limit, return a temporary error for new submissions. Keep previously accepted jobs and serve status requests while PostgreSQL is healthy.

During database recovery, return a temporary error when the service cannot verify status. In the replicated design, require a durable copy on the standby before acknowledging acceptance. Serve status after replay on the promoted standby.

```mermaid
sequenceDiagram
  participant C as Client
  participant L as Load balancer
  participant G as API Gateway
  participant R as Review Service
  participant D as PostgreSQL
  C->>L: GET submission status
  L->>G: Route request
  G->>R: Check status as the signed-in author
  R->>D: Read the submission on the current primary
  D-->>R: Status cannot be verified during recovery
  R-->>G: 503 with REVIEW_STATUS_UNAVAILABLE
  G-->>L: Temporary error
  L-->>C: Keep the receipt and check again later
```
