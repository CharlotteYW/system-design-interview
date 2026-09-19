# Key Technologies

Labs for Hello Interview **[Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)**. Pick **one product you can defend** in each category. Original notes only; no cloud accounts (local Docker mocks).

These are **not** product interviews. Each subfolder explains the building block and later a small demo when you prompt that topic.

Prompt by name, e.g. `relational database` or `message queue`. Commit previous work first. Follow `.cursor/rules/12-prepare-a-concept.mdc`.

| # | Topic | Folder | Status | Local default when implemented |
| --- | --- | --- | --- | --- |
| 1 | Relational database | [relational-database](relational-database/) | Stub | Postgres |
| 2 | NoSQL database | [nosql-database](nosql-database/) | Stub | Redis and/or JSONB stand-in |
| 3 | Blob storage | [blob-storage](blob-storage/) | Stub | MinIO |
| 4 | Search index | [search-index](search-index/) | Stub | Postgres FTS first |
| 5 | API gateway | [api-gateway](api-gateway/) | Stub | nginx or FastAPI facade |
| 6 | Load balancer | [load-balancer](load-balancer/) | Stub | nginx + two app replicas |
| 7 | Message queue | [message-queue](message-queue/) | Stub | Redis list / RabbitMQ |
| 8 | Streams | [stream-processing](stream-processing/) | Stub | Redis streams or Kafka |
| 9 | Distributed lock | [distributed-lock](distributed-lock/) | Stub | Redis SET NX |
| 10 | Distributed cache | [distributed-cache](distributed-cache/) | Stub | Redis |
| 11 | CDN | [cdn](cdn/) | Stub | nginx cache (not global PoPs) |
