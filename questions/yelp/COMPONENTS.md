# Components — Yelp

| Component | Responsibility |
| --- | --- |
| Client | Sends filters, shows profiles and pages of reviews, and submits reviews. |
| Load balancer | Sends requests to a healthy gateway instance. The local proxy can fill both ingress roles. |
| API gateway | Routes requests to the service that handles the route. |
| Search Service | Resolves named places. Queries the catalog by radius or place boundary, name, and category. Returns a page of summaries. |
| Business Service | Reads the full business profile by ID. |
| Review Service | Reads review pages by business ID or by the signed-in author's ID. Validates submissions, queues them durably, and returns status to the author. |
| Review worker | Claims pending jobs and saves each new review, its rating totals, and the job status in one transaction. |
| PostgreSQL with PostGIS | Stores users, businesses, reviews, named places, the durable review queue, and rating totals. PostGIS evaluates radius and boundary filters. |
| Search cache (traffic variant) | Reuses pages for identical searches and groups concurrent refreshes. |
| Rating batch worker (hot business variant) | Groups durable rating events and updates a business summary once per batch. |
| PostgreSQL standby (failover design) | Keeps a durable copy of accepted review work and replays it before taking over status reads. |

These service roles use one database in the starting design.
