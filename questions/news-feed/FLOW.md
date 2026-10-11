# System flow — News Feed

The happy path uses fan-out on read. Each chart runs from the client to the load balancer, the gateway, the service, and the database. Schemas are in [final-design-flow.md](final-design-flow.md).

## Overview

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  post[PostService]
  follow[FollowService]
  like[LikeService]
  comment[CommentService]
  feed[FeedService]
  pg[Postgres]
  s3[S3]
  client --> lb --> gw
  gw --> post
  gw --> follow
  gw --> like
  gw --> comment
  gw --> feed
  post --> pg
  post --> s3
  follow --> pg
  like --> pg
  comment --> pg
  comment --> s3
  feed --> follow
  feed --> post
```

## Create a post

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  post[PostService]
  pg[Postgres]
  s3[S3]
  client --> s3
  client --> lb --> gw --> post
  post --> pg
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as PostService
  participant S as S3
  participant P as Postgres
  C->>S: upload image or video
  S-->>C: media URL
  C->>L: POST /v1/posts
  L->>G: forward
  G->>A: session ok
  A->>P: insert posts row
  P-->>A: post id
  A-->>C: the new post
```

## Follow

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  follow[FollowService]
  pg[Postgres]
  client --> lb --> gw --> follow --> pg
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as FollowService
  participant P as Postgres
  C->>L: POST /v1/users/{id}/follow
  L->>G: forward
  G->>A: session ok
  A->>P: insert follows pair
  P-->>A: one pair, or the pair that already exists
  A-->>C: followed
```

## Home feed and page

The first page omits the cursor. The next page sends the time and the id of the last post. Feed service calls Follow service, then Post service.

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  feed[FeedService]
  follow[FollowService]
  post[PostService]
  pg[Postgres]
  s3[S3]
  client --> lb --> gw --> feed
  feed --> follow --> pg
  feed --> post --> pg
  client --> s3
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as FeedService
  participant F as FollowService
  participant P as PostService
  participant D as Postgres
  participant S as S3
  C->>L: GET /v1/home
  L->>G: forward
  G->>A: session ok
  A->>F: accounts this user follows
  F->>D: read follows
  D-->>F: followee ids
  F-->>A: followee ids
  A->>P: posts older than the cursor
  P->>D: read posts
  D-->>P: one page, newest first
  P-->>A: posts and like counts
  A-->>C: the page and the next cursor
  C->>S: file for a card on screen
```

## Like

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  like[LikeService]
  pg[Postgres]
  client --> lb --> gw --> like --> pg
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as LikeService
  participant P as Postgres
  C->>L: POST /v1/posts/{id}/likes
  L->>G: forward
  G->>A: session ok
  A->>P: insert likes pair
  A->>P: add one to posts.like_count when the pair is new
  P-->>A: the count
  A-->>C: the like count
```

## Comment

```mermaid
flowchart LR
  client[Client]
  lb[LoadBalancer]
  gw[APIGateway]
  comment[CommentService]
  pg[Postgres]
  s3[S3]
  client --> lb --> gw --> comment
  comment --> pg
  comment --> s3
```

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as CommentService
  participant P as Postgres
  C->>L: POST /v1/posts/{id}/comments
  L->>G: forward
  G->>A: session ok
  A->>P: insert comments row
  P-->>A: comment id
  A-->>C: the new comment
```

The home card shows the like count. The comment thread is a separate page. That page uses the same road: client, load balancer, gateway, Comment service, Postgres.

## Hybrid path at 5,000 reads per second

Lee follows Kim, a normal account, and Bea, a famous account. A famous account has more than 10,000 followers.

```mermaid
flowchart LR
  kim[Kim]
  lb[LoadBalancer]
  gw[APIGateway]
  post[PostService]
  q[Queue]
  worker[Worker]
  feed[FeedService]
  pg[Postgres]
  redis[Redis]
  kim --> lb --> gw --> post --> pg
  post --> q --> worker --> pg
  feed --> pg
  feed --> redis
```

```mermaid
sequenceDiagram
  participant Kim
  participant Post as PostService
  participant Q as Queue
  participant W as Worker
  participant P as Postgres
  participant Bea
  Kim->>Post: publish
  Post->>P: store Kim's post
  Post->>Q: one job, post id and author id
  Q->>W: the job
  W->>P: one inbox row per follower
  Bea->>Post: publish
  Post->>P: store Bea's post
  Note over Post,Q: no queue job for Bea
```

Lee opens home. Feed service reads the precomputed inbox ids, then the recent posts of famous accounts Lee follows. It asks Post service for those post rows and sorts by time.

```mermaid
sequenceDiagram
  participant C as Client
  participant L as LoadBalancer
  participant G as APIGateway
  participant A as FeedService
  participant P as Postgres
  participant R as Redis
  participant Post as PostService
  C->>L: GET /v1/home
  L->>G: forward
  G->>A: session ok
  A->>P: precomputed inbox ids, newest 200
  A->>R: recent posts from famous accounts Lee follows
  A->>Post: post rows for the merged ids
  Post-->>A: one page, newest first
  A-->>C: page and next cursor
```

## Failure / overload path

A late merge is acceptable for a follower. The author still sees their own row on the next home load. A failed media upload does not block a text post. A second like from the same user returns the first row.

At about 1,700 likes per second on one post, Like service writes the pair to Postgres and the count to Redis. A worker copies the Redis number back about once a second.

At 5,000 home reads per second, the worker has already copied each normal post into the follower inbox. Each inbox keeps the newest 200 post ids. Feed service loads that inbox and merges famous accounts, above 10,000 followers. A page older than those 200 ids loads normal accounts with fan-out on read.

Five million posts in one day is about 58 writes per second. Those posts stay on one posts table. A month partition is for a disk near 2 TB. The inbox shards by reader id when that table fills.
