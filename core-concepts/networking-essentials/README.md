# Networking Essentials

**Status:** Implemented  
**Kind:** Core concept  
**Sources:** [Hello Interview — Networking Essentials](https://www.hellointerview.com/learn/system-design/core-concepts/networking-essentials) · Alex Xu does not give this topic its own chapter. The latency numbers sit in [numbers to know](../numbers-to-know/).  
**Slug:** `networking-essentials`

This folder is a **concept lab**, not a product interview. Original notes from the 2026-10-04 session.

Keep notes original. Link to Hello Interview. Cite Alex Xu. Do not paste write-ups.

## What this is

A client has to reach a server. The connection decides who can talk, and how long the socket stays open. In an interview you name that choice in one or two sentences. Then you move on.

## Variants to know

| Variant | What it is | When it wins | When to skip |
| --- | --- | --- | --- |
| HTTP over TCP | HTTP is the request and the response. TCP carries the bytes in order and sends a lost packet again. | The interview default for a normal API call. | The server must push many events, or both sides must talk at once. |
| HTTPS / TLS | TLS is a handshake that checks the server and encrypts the bytes. The HTTP message stays the same shape inside that tunnel. | Every public API. | A private link you already trust, and only when the interviewer agrees. |
| Long polling | The client sends one HTTP request and waits. The server answers on an event, or on a timeout. The client then sends the next request. | A live update when the client cannot hold a stream. | You expect many events per second. Each event costs a new request. |
| Server-Sent Events | One HTTP response stays open. The server writes text events. The browser reads them. | A live score, a feed, or a job status. Only the server sends. | The client must send data on the same connection. |
| REST | A resource has a path. The HTTP method is the verb. | A public API with a few resources. | The client must choose fields, or the call is internal and very hot. |
| GraphQL | The client names the fields in one query. | Two screens need different shapes of the same data. | The interview has one screen. The API design lab shows the larger case. |
| WebSocket | The call starts as HTTP. Both sides then send frames on one socket. | Chat, a game, or a cursor that both sides move. | A normal read or create call. The socket is stateful. |
| WebRTC | Peers try to send media directly. UDP carries the audio. TURN relays it when the direct path fails. | A call or a video meeting. | A normal API, or a document that already has a central server. |
| HLS | The player reads a media playlist, then fetches short segments in order. | One video quality, often on Apple clients. | You need several qualities in one manifest. |
| DASH | The player reads a manifest that lists qualities, then fetches segments for one quality. | A video with 360 and 720 choices. | A two-second clip that fits in one file. |
| gRPC | A function call between your services. HTTP/2 carries it. Protobuf is the body. | Service to service, as in the API design lab. | A browser. A browser does not speak gRPC by itself. |
| Client-side balancer | The client keeps a server list and picks the next server. | You own the clients, as with an internal gRPC client. DNS is the slow public version. | You have many browsers, and the server list must change in seconds. |
| L4 balancer | A dedicated balancer sees the IP and the port. It forwards the TCP connection. | The bytes are encrypted, or the socket must stay on one server. | You must route `/api` and `/ws` to different pools. |
| L7 balancer | A dedicated balancer reads the HTTP method and the path. It can choose a pool from the path. | A public HTTP API with more than one service behind one host. | You only forward TCP, and you do not need the path. |
| Timeout and backoff | A timeout stops a slow call. The next try waits longer. Jitter is a small random extra wait. | A call fails for a moment, then works. | The dependency is down for minutes. Retries then add load. |
| Idempotency key | The server stores the first result for a key and returns it on a retry. | A charge, a booking, or any write that must happen once. | A pure read. GET is already safe to repeat. |
| Circuit breaker | After several failures the client stops calling. One later trial checks recovery. | A dependency is down, and retries would keep it down. | A single rare error. A timeout is enough. |
| Round trip | A round trip is the wait for a packet to go and come back. A new HTTPS connection spends one round trip on TCP and one on TLS. | The user is far from the server, or you explain a CDN. | The call stays in one data center. The wait is under 1 ms. |

## Interview default

1. Say HTTPS for a normal API. That is HTTP on TCP, plus TLS.
2. Say Server-Sent Events when only the server pushes.
3. Say WebSocket when both sides send.
4. Say gRPC for a call between your own services.
5. Say an L7 balancer when the path picks the service. Say an L4 balancer when the socket stays open or the bytes stay encrypted. Say a client-side balancer when you own the clients and they can keep the server list.
6. Say the round trip when the user is far away. Same city is about 1 ms. Across a country is about 40 ms. Across an ocean is about 150 ms.
7. Say a timeout plus a longer wait between tries for a short failure. Say an idempotency key when the write must happen once. Say a circuit breaker when the dependency stays down.

## When to use each application protocol

For a normal API, say HTTPS with REST. Say Server-Sent Events when only the server pushes. Say WebSocket when both sides send. Say gRPC between your services. Say HLS or DASH for stored video. Say WebRTC for a live call.

| Protocol | Usual job | Use it when |
| --- | --- | --- |
| REST | A path names a resource. The method is the verb. | The usual public API. Start here. |
| GraphQL | The client names the fields. | A client that changes often and wants only some fields. |
| gRPC | One service calls a function on another service. | A hot call between your own services. |
| Server-Sent Events | The server writes text events on one open response. | Push a live update, such as an auction price. |
| WebSocket | Both sides send frames on one socket. | A game or a chat where both sides send often. |
| WebRTC | Peers send audio or video. | A video call or an audio call. |
| Long polling | One HTTP request waits for one event. | One live update when the client cannot hold a stream. |
| HLS | The player reads one playlist, then short segments. | Play a stored video from one playlist. |
| DASH | The player reads a manifest that lists qualities. | Play a stored video and pick 360 or 720. |

Each button on the page prints the call. You see the request, then the response. gRPC on this page shows the HTTP/2 call as fields. The lab result under it is JSON, because `get_video_rpc` runs in this process.

## After the happy connection

These are the probes once the connection type is chosen.

**TLS ends at the balancer.** The balancer decrypts the bytes. It can read the path, so it can act as L7. The app then receives plain HTTP from the balancer.

| Option | What happens | When it wins |
| --- | --- | --- |
| End TLS at the app | The balancer sees encrypted bytes. It can only use the IP and the port. | You do not trust the network between the balancer and the app. |
| End TLS at the balancer | The balancer reads the host and the path. The app skips the handshake. | A normal public API. Path routing matters. |
| Do nothing extra | One app owns the certificate. There is no second pool. | The system is still one service. |

For this lab, the page does not run a real certificate. The round-trip panel adds the extra TLS wait as a number. In an interview, end TLS at the L7 balancer for a public HTTP API.

**The WebSocket drops and comes back on another server.** Server A holds the old socket. Server B accepts the new one. Server B has no memory of the chat on A.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | The user sends again. Each message is complete. | A demo echo, or a message that carries its own state. |
| Pin the client | The balancer sends that client to the same server. A dead server still drops the pin. | One room fits on one server. |
| Share the messages | Both servers read a bus or a store. Any server can take the next socket. | The chat must survive a server restart. |

For this lab, the echo stays on the socket that accepted it. In an interview, name the pin first. Name the shared bus when a dropped server must not erase the room.

**The user is across an ocean.** A new connection waits about 150 ms for TCP. TLS waits about 150 ms more. The HTTP response waits again.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | The user pays two or three round trips on a cold connection. | The call is rare, and the data must stay in one region. |
| Keep the connection | Later calls skip the handshake. HTTP/2 can put many requests on that socket. | The same user sends a burst of API calls. |
| Put a copy near the user | A CDN stores the static file in a close city. The round trip shrinks. | Images, scripts, and other bytes that can be stale for a short time. |

For this lab, the three region buttons sleep 1 ms, 40 ms, and 150 ms. They also report a second wait of the same size for TLS. The real certificate is out of the lab.

**Ten thousand clients hold a stream.** The cost is open sockets, not queries per second. Each long poll, event stream, or WebSocket holds one socket until it ends.

| Option | What happens | When it wins |
| --- | --- | --- |
| Do nothing | One server can hold many idle sockets. A chatty stream still fills the CPU. | The count stays in the tens of thousands, and events are rare. |
| Add servers | The balancer spreads new connections. An open socket stays where it landed. | The socket count or the CPU climbs. |
| Fall back to HTTP | The client asks on a timer. The server stores no waiting socket. | Updates can wait a few seconds, and the client count is huge. |

For this interview, say Server-Sent Events for a one-way feed. Say how you add a second server when the socket count grows. Do not design the feed product here.

## Pitfalls

- A WebSocket is HTTP only for the opening upgrade. Later frames are not HTTP requests.
- Long polling ends on each answer. It is not one open stream.
- "Encrypted" does not say where TLS ends. The balancer can read the path only after it decrypts.
- An L7 rule does nothing while the bytes are still encrypted.
- A held connection costs a socket. A quiet client still occupies that socket.

## Local demo

The page at `http://localhost:8000` follows one stack, from the application layer down to IP. The interview default on the page is HTTPS.

Read it in this order:

1. The application box: REST, GraphQL, gRPC, then Server-Sent Events, WebSocket, WebRTC. Long polling, HLS, and DASH use the REST path.
2. HTTP or HTTP/2.
3. TLS on TCP, or DTLS on UDP.
4. TCP or UDP.
5. IP.
6. A balancer beside one of those layers, then the failure tools.

| Control | What you see |
| --- | --- |
| The stack | Wrap REST, gRPC, or WebRTC. The page lists the layers from the application down to IP and marks those boxes. |
| REST, GraphQL, gRPC | REST reads `/api/videos/1`. GraphQL asks for `title` only. gRPC runs `Video.Get` in this process. |
| Server-Sent Events | One response stays open and writes `connected`, then later text. |
| WebSocket | The browser sends text. The server sends that text back on the same socket. |
| WebRTC | The buttons walk signal, STUN, a direct UDP path, and a TURN relay. No real peer socket opens. |
| HLS and DASH | HLS reads a playlist, then three segments. DASH reads a manifest with 360 and 720, then three 720 segments. |
| Long polling | The request waits. Publish completes it. A quiet request returns `timeout`. |
| HTTP / HTTP/2 | `GET /api/http` returns one JSON body. The transport field says TCP. |
| TLS / DTLS and round trip | Same city waits about 1 ms. Across a country waits about 40 ms. Across an ocean waits about 150 ms. The body adds the same number again for TLS. |
| Client-side balancer | The page reads the registry and picks the next server. The work call names that server. |
| L4 and L7 | L4 sends both paths for `alice` to one server. L7 sends `/api/http` to the api pool and `/ws` to the realtime pool. |
| Timeout and backoff | The first two calls are slow. The page aborts them, waits longer, and the third call succeeds. |
| Idempotency | Key `pay-1` returns the same receipt on the second click. Key `pay-2` is a new charge. |
| Circuit breaker | Three failures open the breaker. The next call does not touch the dependency. After a short wait, one success closes it. |

**Cut vs production:** no real certificate, no second machine, and no real video file. gRPC here is the function `get_video_rpc` in this process. The [API design](../api-design/) lab runs gRPC on a second process. WebRTC walks the steps and does not open a peer socket. The delays are `sleep`, not a real cable.

## How to run

```bash
cd core-concepts/networking-essentials
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

**Q: What is each connection, and which one do you name first?**  
A: HTTP is the L7 message and TCP is the L4 byte stream. That pair is the common case. HTTPS adds TLS around those bytes. Long polling is one waiting HTTP call, then another call. Server-Sent Events keep one response open so the server can write text. A WebSocket lets both sides send. gRPC is a service call on HTTP/2. The interview default is HTTPS. Switch to Server-Sent Events for a one-way feed, to a WebSocket when both sides send, and to gRPC between your services.

**Q: What is an L4 balancer versus an L7 balancer? What is a round trip?**  
A: An L4 balancer forwards a TCP connection from the IP and the port. An L7 balancer reads the HTTP path and can pick a pool. A round trip is the wait for a packet to go and come back. A new HTTPS connection spends one round trip on TCP and one on TLS. Same city is about 1 ms. Across an ocean is about 150 ms.

**Q: Show each application protocol, HLS and DASH, a client-side balancer, and the failure tools.**  
A: The page now runs TCP, UDP, HTTP, REST, GraphQL, gRPC, long polling, Server-Sent Events, WebSocket, WebRTC, HLS, and DASH. The client-side balancer picks from a registry. The dedicated balancer still shows L4 and L7. A slow call times out and retries with a longer wait. The same charge key returns the first receipt. Three failures open a circuit breaker, and one later trial can close it. Each panel names the function in `src/main.py`.

**Q: Order the page like the stack, with the application layer on top and IP on the bottom.**  
A: The page now starts with that box. REST, GraphQL, and gRPC are the first row. Server-Sent Events, WebSocket, and WebRTC are the second row. Under them come HTTP or HTTP/2, TLS or DTLS, TCP or UDP, and IP. Wrap a REST call to see HTTP, TLS, and TCP. Wrap a gRPC call to see HTTP/2. Wrap a WebRTC call to see DTLS and UDP. Balancers and failure tools stay after the stack, because they sit beside a layer.

**Q: For each application protocol, what is the usual job, and what does the call look like?**  
A: REST is the public resource API. GraphQL is the client-chosen field list. gRPC is the internal function call. Server-Sent Events is a one-way text feed. A WebSocket is two-way frames. WebRTC is a live call. Long polling is one waiting HTTP request. HLS is one video playlist. DASH is a manifest with several qualities. Each button prints the request and the response. The gRPC button prints an HTTP/2 call with fields, then the JSON from this process.

**Q: Show DNS, service discovery, a health check, and the other ways the client fills its memory.**  
A: The page walks six ways, one step at a time. A static file is copied at start and stays old. DNS stores the lookup for the TTL, so a dead address remains until the TTL ends. A registry poll copies the new list on the next poll. A registry push sends the new list without a poll. A health check probes known addresses and skips a silent one. It cannot find a new server. MOVED is the answer from the wrong server, and the client stores the owner for that key.

**Q: Where does a client-side balancer keep the server list, on a laptop and on a phone?**  
A: A config file holds a seed, which is the address of the registry. The program fetches the server list and keeps it in memory. This page does that with `clientCursor`. A phone browser for a public site caches a DNS answer for the TTL, then talks to a dedicated balancer. A phone app you ship can keep the list in app memory and refresh it from the registry.

**Q: Put the most common use on each panel.**  
A: Each panel now starts with "Most common use." REST is the public API you start with. GraphQL is a client that changes often. gRPC is a hot internal call. Server-Sent Events push a live update, such as an auction price. A WebSocket is a game or a chat. WebRTC is a video or audio call. HLS and DASH play a stored video. TCP is the default transport. UDP is live audio, a game, or DNS. An L7 balancer routes public HTTP. An L4 balancer keeps a WebSocket. A short failure gets a retry with exponential backoff and jitter. A payment uses an idempotency key. A dependency that stays down gets a circuit breaker.
