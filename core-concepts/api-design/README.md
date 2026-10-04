# API Design

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — API Design](https://www.hellointerview.com/learn/system-design/core-concepts/api-design) · Alex Xu Vol 1 Ch 4 is the rate-limiter chapter; this repo’s [rate limiter](../../questions/rate-limiter/) is that lab. API shape itself is not its own Alex Xu chapter.  
**Slug:** `api-design`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-10-03 session. The local demo is not built yet.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

The API is the contract between a caller and your system: which URL, which verb, what goes in, what comes back, and what a retry is allowed to do. In a system-design interview this is a few minutes. A reasonable contract is enough. The storage and the failure path are the rest of the hour.

Spend that few minutes on the user-facing calls. Internal service calls can be named as RPC later, during the high-level sketch.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| REST | Resources as plural nouns. GET reads, POST creates, PUT replaces, PATCH changes a part, DELETE removes. JSON over HTTP. | The interview default for a public or mobile client. CRUD maps onto it. Tooling is everywhere. | The call is an internal procedure (`checkPermission`) and the resource shape is fake. Or the client must subscribe to a stream. |
| RPC / gRPC | A function call over the network. gRPC uses protobuf and HTTP/2. | Service-to-service, where both sides are yours, and you want a small binary payload and generated types. | The public API. Browsers do not speak gRPC. Sketching every internal method eats the five minutes. |
| GraphQL | One endpoint. The client names the fields it wants. | Mobile and web need different shapes of the same graph, and you would otherwise grow a new REST route per screen. | A 45-minute design with one or two screens. Caching and the N+1 query problem become the topic. |
| Offset pagination | `?offset=20&limit=10`. Skip 20, return 10. | Admin pages, “jump to page 5,” data that is not changing under the reader. | A feed or an order list that receives inserts while the user scrolls. Rows shift, so a page repeats or skips. A large offset still makes the database walk the skipped rows. |
| Cursor pagination | `?limit=10` returns a `next_cursor` that points at the last row you saw. The next call asks for rows after that id. | Feeds, chat, “my orders” while new orders arrive. The page stays stable. | The product needs “go to page 5” with no cursor. Also a poor fit if the sort key is not unique. |
| Session row | Server stores the login. The client sends a session id. Logout deletes the row. | You must revoke access immediately. | Every request now reads that store. Fine at moderate QPS. |
| JWT | The token carries user id, role, and expiry, signed by the server. Any app server can check the signature. | Many app servers, and you do not want a session lookup on the hot path. | You need logout to work before `exp`. A stolen token stays valid until it expires. |
| API key | A long secret that names a program, not a person. | Another service you run, or a third-party developer. | A human logging in. People should not hold raw keys, and a key has no user expiry story. |
| Idempotency key | The client sends a unique id for one logical POST. The server stores that id with the first response and replays it on retry. | Create booking, place order, charge a card. The network can time out after the write succeeded. | GET, PUT, and DELETE, which are already safe to repeat. A pure read does not need a key. |
| Rate limiting | Cap calls per user, per IP, or per route. Over the cap, respond 429. | Abuse, bots, a hot client. Say it in one sentence. | Designing the token bucket here. That lab is [questions/rate-limiter](../../questions/rate-limiter/). |

Realtime (chat, live scores) is a different contract: WebSocket when both sides send, server-sent events when only the server pushes. Name it and move on. It is not a REST resource.

## How a REST call is shaped

Three places to put input:

- **Path** when the value is required to name the thing: `/accounts/42/orders`.
- **Query** when the filter is optional: `/orders?status=open`.
- **Body** for the document you are creating or replacing. Do not put a card number in the query string. URLs get logged.

List endpoints paginate from the first version, with a max page size. A client that sends `limit=100000` is asking your database to load the table.

Status codes worth saying: 200 ok, 201 created, 202 accepted (the work is queued; the one-time-password generate path did this), 400 bad input, 401 who are you, 403 you are not allowed, 404 missing, 409 conflict (same idempotency key, different body), 429 slow down, 500 we failed, 503 try later (dependency down). 4xx is the caller. 5xx is you.

Errors share one shape on every route: a stable `code` the client can branch on, and a `message` a human can read. `SEAT_TAKEN` can change its sentence later. The code stays.

## Interview default

1. Say REST unless they asked for flexible field selection or for an internal high-QPS call.
2. Name four or five routes as plural nouns. Nest when the parent is required (`/accounts/{id}/orders`). Filter with a query when it is optional.
3. Paginate every list. Offset if they want page numbers. Cursor if rows arrive while someone is scrolling.
4. On a create that charges or reserves something, say the idempotency key in the same breath as POST.
5. Say which routes need a logged-in user. JWT when any app server should verify the token. A session row when logout must stick immediately. An API key only for another program.
6. Stop. Do not version the URL, do not list every 4xx, do not design RBAC matrices, unless they ask. Adding a JSON field is safe. Renaming or removing one is `/v2` later.

## After the happy URLs

These are the probes once the routes exist.

**The create timed out.** The client posted an order. The TCP connection died. The client cannot tell whether the row was committed, so it sends the same request again. The idempotency key does not stop that send. It makes the second send return the first order.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | The second POST inserts a second order | The operation is harmless to repeat, or the user can see the duplicate and delete it |
| Idempotency-Key header | First call stores the key and the response. The retry with the same key returns that response and does not insert again | Place order, book a seat, charge a card |
| Put the order id in the body and use PUT | `PUT /orders/{id}` with a client-generated id. A second PUT replaces the same row | The client can mint the id (the unique-id chapter). The URL names the resource already |

For this study set, a place-order POST carries an idempotency key. Same key and same body returns the first order. Same key and a different body is 409, so a bug cannot reuse the key for a new purchase. Keep the stored response for about a day. Longer than that, a retry is a new order.

**Someone scrolls “my orders” while a new order is placed.**

| Option | What happens | When it wins |
| --- | --- | --- |
| Offset | Page 2 is “skip 20.” An insert at the top shifts every later row. The user sees one order twice or misses one. `OFFSET 100000` is a slow scan | A short admin list that nobody inserts into during the browse |
| Cursor | Page 2 is “ids older than the last id I showed you.” An insert newer than the cursor does not move the rows already returned | “My orders,” a feed, chat history |

Both styles miss the brand-new order on page 2. It was inserted at the top, which the user already passed. A reload of page 1 shows it. Cursor page 2 does not repeat the last row of page 1. Offset page 2 does: the insert shifts every later row down by one.

Cursor for the order list. Offset if they explicitly want a page number on a quiet table.

**Account 7 asks for account 42’s orders.** Authentication succeeded. Authorization did not.

| Option | What happens | When it wins |
| --- | --- | --- |
| Any logged-in user can read any account | One route, no check | A public directory. Orders are not that |
| The path account must equal the token’s account | 403 otherwise. Admins are a separate role you name only if the product has them | “My orders.” The token says who you are. The path says whose rows you want |

The check is in the API, and again in the query (`WHERE account_id = token.account_id`). Hiding the button is not the check.

**An old phone app is still installed.**

| Option | What happens | When it wins |
| --- | --- | --- |
| Add a field | Old clients ignore it | The usual change |
| New URL `/v2` | Old clients stay on `/v1` until you turn it off | You renamed or removed a field, or you changed what a field means |
| Header version | The URL stays clean. The client must send the version | You already operate that way. Harder to try in a browser, so it is not the interview default |

Say `/v1` only if they ask how you ship a breaking change. Do not put a version on every box in the diagram by habit.

**The list is huge, or one client is loud.** Cap `limit` (for example 100). A page that would scan the world is a 400. A client over its budget gets 429. The algorithm for that budget is the rate-limiter question, not this chapter.

**They ask for GraphQL because the phone wants less data.** One query can load every order and then one query per account (N+1) unless you batch. HTTP caches understand `GET /accounts/42/orders`. They do not understand a single POST that contains an arbitrary query. Stay on REST unless two clients truly need different graphs and you are willing to talk about that batching.

## Pitfalls

- Spending the interview on URLs. Four routes, then the data path.
- Verbs in the path (`/createOrder`, `/getUserBookings`). The noun is the resource. The method is the verb.
- POST for a read, or GET for a charge. GET is cached and retried by clients and proxies.
- Returning 200 with `{ "ok": false }` for a failure. The status code is the class of the outcome. The body is the detail.
- A list with no page size. The first demo has 50 rows. Production has millions.
- Treating a retry of POST as the caller’s bug. The server has to make the retry safe when the create matters.
- JWT as “we have auth.” Say what the token is for, and say the 403 when the token’s account is not the path’s account.
- An API key for a human login.
- GraphQL as the default because it sounds modern.
- Designing the rate-limit algorithm inside the API minute.

## Local demo

The page at `http://localhost:8000` is a React and TypeScript app. GraphQL uses Apollo. REST uses `fetch`. The interview default is still one public REST API. The page shows the variants side by side.

| Control | What you see |
| --- | --- |
| REST query | `GET /v1/events?city=NYC&status=upcoming&sort=date`. The response includes `received_query`, so you can see the filters the API got. |
| GraphQL query | Apollo sends `POST /graphql`. The page lists the call chain. The query asks for `id` and `name` only. |
| GraphQL mutation | The same `POST /graphql` runs `bookSeat`. Strawberry calls `book_seat` and writes a booking for account 42. A second click replays that booking. |
| gRPC | Book a seat with REST. The result prints `POST /v1/events/1/bookings?mode=jwt&server=a` and the JSON body. The API calls inventory with `CheckSeats`. |
| JWT | Login returns a signed token. Any server can read it. Logout does not erase it. |
| Memory session | Login on server A. Server A accepts the session id. Server B returns 401. The two servers are two dicts in one process. |
| Redis session | Login writes `session:{id}` in Redis. Server A and server B both read it. Logout deletes the key. |
| Idempotency key | The same key returns the first booking. A different quantity with that key is 409 `KEY_REUSED`. |
| Error shape | A failure body is `{ "error": { "code", "message" } }`. Nine seats returns `SEATS_UNAVAILABLE`. |
| Version | `/v1/events` uses `name`. `/v2/events` uses `title`. |

**Cut vs production:** no API gateway, no real load balancer, and no Postgres. The event rows live in memory. The idempotency table lives in memory. Rate limiting stays a pointer to the rate-limiter question. Cursor pages stay in the notes above. This page does not page the list.

## How to run

```bash
cd core-concepts/api-design
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

### 2026-10-03

**Q: Learn API design as a stepping stone before more system-design questions.**  
A: The interview spends a few minutes on the contract, then moves on. Default is REST, plural nouns, path for required ids, query for optional filters, pagination on every list, an idempotency key on place-order, and a token check that the caller owns the account. RPC is for internal calls. GraphQL is for two clients that need different shapes. Cursor pagination when rows arrive during the scroll. Offset when someone needs a page number on a quiet list. JWT when any server can verify the signature. A session row when logout must work now. An API key names a program. A timeout after a successful create is the server’s problem: store the key and replay the first response. Adding a JSON field does not need `/v2`. Renaming one does.

**Q: Public REST, then the frontend calls the backend with GraphQL, and backend services use gRPC. Idempotency key so the same request is not sent again. If a new order arrives between pages, do we miss it?**  
A: One public contract for this orders page: REST, which the browser calls directly. gRPC is the right name when a second service of ours is on the other side (payment, inventory). GraphQL as a required middle hop adds a translation layer and the N+1 query problem, and this design has one screen. The client still sends the place-order call again after a timeout. The key is stored with the first response, so the retry returns that order and does not insert another. A new key would create a second order. On page 2, both cursor and offset miss the order that was inserted at the top. Reload page 1 to see it. Cursor page 2 does not repeat the last row of page 1. Offset page 2 does, because the insert shifts the window.

**Q: Make the lab show REST filters, GraphQL, gRPC, JWT, a Redis session, idempotency, errors, and versions. Cover that breadth on later topics too.**  
A: The lab now runs each of those options. REST puts `city`, `status`, and `sort` in the query string and echoes them. GraphQL returns only the fields in the query. A booking calls inventory with gRPC. A JWT needs no store, and logout does not erase it. A memory session works only on the server that created it. A Redis session works on both servers, and logout deletes the key. The same idempotency key replays the first booking. Errors use one `code` and one `message`. `/v2` renames `name` to `title`. The interview default is still one REST API. Later labs must show the important variants side by side (`16-show-the-variants.mdc`).

**Q: Where do city, status, and sort go in FastAPI? Which GraphQL framework do we use? Do v1 and v2 hit the same service?**  
A: The page builds the query string. FastAPI puts each query name into the matching argument of `list_events`. That function calls `filter_events` in `catalog.py`. GraphQL uses Strawberry on the server. The page POSTs the query text to `/graphql` on the same app. `/v1/events` and `/v2/events` enter one function. `for_version` renames `name` to `title` for v2. Both paths read the same event list in this process.

**Q: Where does a JSON payload get parsed? Can the page be React, TypeScript, and Apollo?**  
A: A Pydantic model argument is the body. `LoginBody` and `BookBody` are that parse. Query args stay on the URL. Headers use `Header()`. The page is now React and TypeScript. Apollo sends the GraphQL POST. `fetch` still sends REST, including the JSON body. The server library stays Strawberry.

**Q: Do query parameters and a JSON body both become function arguments? Can one request have both?**  
A: Yes. FastAPI fills each argument from a different part of the same request. `POST /v1/events/1/bookings?mode=jwt&server=a` with body `{"quantity": 1}` is that case. `event_id` comes from the path. `mode` and `server` come from the query string. `body.quantity` comes from the JSON. `Idempotency-Key` comes from a header. A list call can stay query-only. A login call can stay body-only.

**Q: Show that booking URL in the UI. Can GET and POST each use a query string, a body, or both?**  
A: The booking result now prints `method`, the full `url` with `mode` and `server`, and the JSON `payload`. A POST may use a query string, a JSON body, or both. A GET in this lab uses the query string. A body on GET has no defined meaning in HTTP, and caches may drop it, so this lab keeps GET bodies out.

**Q: In production, does a GET have no body?**  
A: Yes. A production GET carries the query string and no body. A cache stores the response under the URL, so a hidden body would not change the cache key. A large filter document belongs on a POST. A few search APIs have sent a GET body, and proxies may drop it. This lab and the interview default leave the GET body out.

**Q: Where is the Apollo client, and how does it talk to the backend?**  
A: The client is `frontend/src/apollo.ts`. `HttpLink` uses `POST /graphql`. `main.tsx` passes that client to `ApolloProvider`. The GraphQL panel runs `useLazyQuery` with variables `city` and `status`, and it asks for `id` and `name`. Strawberry in `src/graphql_api.py` runs `Query.events_query` on the same FastAPI process. The response is `{ data: { eventsQuery } }`. Apollo is the browser library. The server library is Strawberry.

**Q: How does the Python server read the fields and the variables? How does that compare with a Ruby schema that has queries and mutations?**  
A: The server reads field arguments, not the `$` variable names. `eventsQuery(city: $city, status: $status)` plus `variables: { city: "NYC", status: "upcoming" }` becomes `Query.events_query(city="NYC", status="upcoming")`. `Event` exports `id`, `name`, `city`, and `status`. The selection `{ id name }` keeps those two. A query is the read root. A mutation is the write root. A Ruby `field` plus `argument` plus a method is the same shape as this Python method.

**Q: What is the call chain from Apollo to Python? How do the two sides agree? Can GraphQL also write?**  
A: The page lists the chain after each click. Apollo Client in `frontend/src/apollo.ts` sends `POST /graphql`. FastAPI accepts that route. Strawberry exports `Query.events_query` as `eventsQuery` and `Mutation.book_seat` as `bookSeat`. Variable values become the Python arguments. The selection set chooses the JSON fields. The agreement is the schema: the same field names on both sides. The browser does not import the Python file. The mutation writes a booking for account 42. The REST booking remains on the page too.

**Q: Where is the code that sends POST /graphql?**  
A: `frontend/src/apollo.ts` only sets `uri: "/graphql"`. The method `POST` is the default in Apollo Client `HttpLink`, in `selectHttpOptionsAndBody.js` (`method: "POST"`). `createHttpLink.js` calls `fetch` with that method and the JSON body. This lab does not set `useGETForQueries`, so a query uses POST too.

**Q: Where is `/graphql` defined? Is it an endpoint?**  
A: Yes. An endpoint is a path the server accepts. `GraphQLRouter` in `src/graphql_api.py` has no path of its own. `main.py` mounts it with `prefix="/graphql"`. The client repeats that path in `uri: "/graphql"`. The browser calls `http://localhost:8000/graphql`. The name is a shared string. Both files must use the same path.

**Q: Does `eventsQuery` match `events_query`, and does `bookSeat` match `book_seat`?**  
A: Yes. `useLazyQuery(EVENTS)` sends the document. The field `eventsQuery` matches `Query.events_query`. The field `bookSeat` matches `Mutation.book_seat`. Strawberry builds the camelCase name from the Python snake_case name. `Upcoming` and `BookSeat` are operation names and have no Python method. The page table lists each pair. A one-word name such as `city` stays `city`.

**Q: What do strawberry.type, strawberry.field, and strawberry.mutation mean? Which other backend libraries exist?**  
A: `type` makes a class into a GraphQL type. `field` makes a method into a resolver, such as `events_query`. `mutation` marks a write. In Strawberry that function calls `field()`, and `Schema(mutation=Mutation)` places the class on the write root. graphql-ruby is the Ruby match for this shape. Graphene is the older Python code-first library. Ariadne keeps the schema as text and attaches resolvers. Apollo Server is a Node server, and it is a different package from Apollo Client. This lab stays on Strawberry. The page lists this note under the GraphQL section.

Session closed 2026-10-04. No further questions.
