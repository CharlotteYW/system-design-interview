# Real-time updates

**Source:** [Hello Interview: Real-time Updates](https://www.hellointerview.com/learn/system-design/patterns/realtime-updates). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **real-time update** is a change the server sends toward the user, instead of waiting for the user to ask. This pattern has two hops. Hop 1 is server to client. Hop 2 is the place the event happened to the server that holds the client connection.

## The problem

Lee sends Kim a chat message. Kim is online. Kim should see the message in about a second, without tapping refresh. The same shape is a live comment, a cursor in a shared document, a chess move, and the tokens of a model reply.

Plain HTTP closes after the response. The server cannot speak first. If every client asks every 100 ms, the ask rate becomes the product of users and the poll rate. That load is mostly empty answers.

## Hop 1: server to client

- **Option A: The client polls.** The client asks on a timer. Cost: most answers are empty, and the delay is the timer. Wins for a rare event, such as "is the video ready?" once every few seconds.
- **Option B: Server-sent events.** The client opens one HTTP response and the server writes events down that response. The channel is one way. Cost: one long connection per client. Wins for a live feed the user does not send back, such as a dashboard or a notification.
- **Option C: A WebSocket.** The connection stays open and both sides write. Cost: the server must remember each connection, and a load balancer must not break it. Wins for chat, docs, and a game, because the user also sends.

We pick A until the empty polls cost more than the feature. We pick C for chat. We pick B when the user only listens.

## Hop 2: event to the right server

Kim's socket is on server B. Lee's send lands on server A.

- **Option A: Pub/sub.** Server A publishes on a channel such as `user:kim`. Server B subscribes and writes to Kim's socket. Redis pub/sub does this. Cost: a message can be missed if server B is down at that instant. The stored message is still there for the next read. Wins for a small event, such as a chat message id.
- **Option B: A sticky server.** All of one document, or one game, lives on one server. Consistent hashing picks it. Cost: that server is a hot spot, and a crash drops the room until clients reconnect. Wins when the event is heavy to apply, such as merging a document edit.

The chat lab in this repo uses Option C on hop 1 and Option A on hop 2.

## What an interviewer probes

- The socket can drop. The client must reconnect and ask for what it missed. In chat, that is "messages after seq N."
- A pub/sub message is not the store. The database write happens first. The push is a hint. A missed hint is repaired by the read.
- One viral live post can put every viewer on the comment channel. That is a hot key on hop 2. Split the channel, or fall back to a short poll for that post.

## Questions

| Question | What moves in real time |
| --- | --- |
| [Chat system](../questions/chat-system/) | A message. WebSocket, then Redis pub/sub. This is the worked example |
| [Live comments](../questions/live-comments/) | A comment on one post. The post can be hot |
| [Google Docs](../questions/google-docs/) | An edit. Heavy enough that one document stays on one server |
| [Online chess](../questions/online-chess/) | A move. Two clients, one board |
| [ChatGPT](../questions/chatgpt/) | Tokens of a reply. The server streams, the user mostly listens |

| Question | How it also pushes |
| --- | --- |
| [Notification system](../questions/notification-system/) | The phone push is the last hop, after a worker sends |
| [YouTube](../questions/youtube/) | Upload progress. A poll is enough |
| [Uber](../questions/uber/) | The car moving on the map |
| [Nearby friends](../questions/nearby-friends/) | A friend entering the area |
| [Tinder](../questions/tinder/) | "You matched" |
| [Ticketmaster](../questions/ticketmaster/) | A seat that someone else just took |
| [Flash sale](../questions/flash-sale/) | The stock count falling |
| [Online auction](../questions/online-auction/) | The current bid |
| [Stock exchange](../questions/stock-exchange/) | The last trade |
| [Robinhood](../questions/robinhood/) | An order filling |
| [Metrics monitoring](../questions/metrics-monitoring/) | A live chart. Server-sent events fit |
| [Strava](../questions/strava/) | A live segment attempt |
| [Price tracking](../questions/price-tracking/) | The alert that a price crossed a line |
