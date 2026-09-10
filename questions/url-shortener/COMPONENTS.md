# Components — URL Shortener

Each row is a piece you would name on the whiteboard. Fill definition and responsibility; drop unused rows.

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | App or caller of the API | Sends requests; displays results |
| Load balancer | Distributes traffic across service instances | TBD |
| API / application service | Stateless request handlers | TBD |
| Primary database | Source of truth for core entities | TBD |
| Cache | Fast memory store for hot reads | TBD |
| Message queue | Async buffer between producers and consumers | TBD |
| Worker | Background processor | TBD |
| Object store | Blob storage for large files | TBD |
| CDN | Edge cache for static content | TBD |

## Why these pieces

- TBD: which components are load-bearing vs optional for the interview
- TBD: what you would add only in a deep dive
