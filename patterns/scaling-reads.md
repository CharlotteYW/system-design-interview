# Scaling reads

**Source:** [Hello Interview: Scaling Reads](https://www.hellointerview.com/learn/system-design/patterns/scaling-reads). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **read** is a request that does not change stored data. This pattern serves many reads without putting all of them on one database primary. A **primary** is the database that accepts writes.

## The problem

Kim opens the news feed. The app loads 20 posts. Each post needs the author, the text, and the like count. That is about 60 reads. Kim writes one post a day. The read rate is about 100 times the write rate. The same shape appears on a short-link redirect and on a YouTube watch.

One primary has a fixed number of reads per second. Past that number, the feed gets slow, then it fails. More application servers do not help. They all still ask the same primary.

## Options

- **Option A: Make the query cheaper.** Add the index the query uses. Return only the columns the page needs. Store a ready-made feed row so the read is one lookup. Cost: a worse write, or a harder schema. Wins when the primary still has spare CPU.
- **Option B: Add read replicas.** A **replica** is a copy that serves reads and lags the primary by a short time. Cost: a read can miss the newest write. Wins when many users read different rows.
- **Option C: Put a cache in front.** A **cache** keeps a hot value in memory. Redis is the usual choice. A **hot key** is one value that most reads ask for. Cost: you must delete or expire a stale value. A stampede happens when the value expires and every server asks the database at once. Wins when a small set of keys is most of the traffic.
- **Option D: Put a CDN at the edge.** A **CDN** is a cache near the user. It fits bytes that many users can share, such as a video segment or a public image. Cost: a private page must not be cached. Wins for media, not for Kim's own feed.

We pick A first, then B, then C. We add D only for shared bytes. For this repo, the URL shortener and the news feed stop at C. YouTube playback adds D.

## What an interviewer probes

- The like count on one viral post is a hot key. A replica does not fix it. Every replica still serves that one key. A cache does, if you keep one copy and accept a count that lags by a second.
- Kim posts, then refreshes. A replica can hide the post. The fix is to read Kim's own new post from the primary, and to read everyone else from the replica or the cache.
- A cache expiry at the same second sends the full read rate back to the primary. Keep serving the old value while one request refreshes it.

## Questions

**Primary** means this pattern is the main shape of that question.

| Question | What the read is |
| --- | --- |
| [URL shortener](../questions/url-shortener/) | The redirect. A few short links dominate |
| [News feed](../questions/news-feed/) | The home list. About 100 reads per write |
| [Search autocomplete](../questions/search-autocomplete/) | The suggestion list for a prefix. The top prefixes dominate |
| [Instagram](../questions/instagram/) | The photo feed. Hello Interview uses this as the example |
| [Gaming leaderboard](../questions/gaming-leaderboard/) | The top of the board. Everyone reads the same ranks |
| [Post search](../questions/post-search/) | The search result page |
| [Food review](../questions/food-review/) | The review list for a place |

| Question | How it also uses reads |
| --- | --- |
| [YouTube](../questions/youtube/) | Watch traffic. The bytes come from a CDN |
| [Yelp](../questions/yelp/) | The result list, after the geo filter |
| [Strava](../questions/strava/) | The activity feed |
| [Google Maps](../questions/google-maps/) | Map tiles. A tile is a shared read |
| [Metrics monitoring](../questions/metrics-monitoring/) | The dashboard query |
| [Flash sale](../questions/flash-sale/) | The product page, before the buy button |
| [Donations](../questions/donations/) | The public total |
| [Rate limiter](../questions/rate-limiter/) | Every request reads a counter |
| [ChatGPT](../questions/chatgpt/) | The old thread, before the new reply |
