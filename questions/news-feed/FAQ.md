# FAQ — News Feed

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: A user creates a post with text and an optional image or video. A user follows an account in one direction. A user views posts from the people they follow, newest first, and pages that feed with a cursor. A user likes a post and comments on it. A repost stays out.

**Q: What scale numbers would you use, and why?**  
A: 1 million daily active users. About 10 percent publish, and each of those users writes 2 posts, so the day has about 200,000 posts. Each user opens home about 10 times, so the normal peak is about 200 reads per second. 5,000 reads per second is rush hour, not the steady rate. 5 million posts per day assumes every user publishes 5 times.

**Q: What if the product becomes popular and the day has 5 million posts?**  
A: That is a follow-up, not the first design. 5 million posts is 25 times the locked rate of 200,000. We draw the happy path first. Then we say what breaks, and what we add, at the higher rate.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Search, a chat thread, analytics, a ranking model, a repost, and video transcoding. Likes, comments, and the original media file are in. We added them back after a text-only pass. Transcoding belongs to the YouTube question.

## 2. High-level design

**Q: Walk through each functional requirement at a high level.**  
A: Create a post: upload the file to S3, then insert one post row. Follow: insert one pair. Home: load the follow list, load those posts, sort newest first. Page: send the cursor from the last post, and return older posts. Like: insert one user-and-post pair, and bump the count when the pair is new. Comment: insert one row under the post. The home feed does not copy that comment.

**Q: Which choices does step 2 lock, and which wait for the deep dive?**  
A: Step 2 locks S3 plus a link, a follow pair in Postgres, fan-out on read, and a cursor. The hot like count, the hybrid inbox at 5,000 reads per second, and a shard for 5 million posts stay in step 4.

**Q: Why these major boxes and not fewer?**  
A: The load balancer spreads traffic. The API servers hold no feed state. Postgres is the source of truth for posts, follows, likes, and comments. Object storage holds the image and video bytes. A queue is not on the happy path, because fan-out on read does the work at read time. A cache can wait until the home query or a like count is hot.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: Postgres stores users, follows, posts, the like pair, and comments. S3 stores the file bytes. The post and the comment store link lists. The follow table is required, because the home query is "posts by these accounts." A like count with no user id cannot stop a second tap. The count column sits on the post for the card. DynamoDB, or Redis in the lab, is the later home for one hot count.

**Q: Where is the bottleneck as traffic grows?**  
A: The home query grows when one user follows thousands of accounts, or when home reads hit 5,000 per second. One viral post makes `like_count` a hot row. The comment list stays on that post and does not fan out.

## 4. Component questions and special situations

**Q: What fails if this component dies, and how do you recover?**  
A: If Redis dies, the like pairs are still in Postgres. Rebuild the count from those pairs. If the inbox worker lags, a normal post shows up a few seconds late, and a famous account is still merged on read. If the Postgres primary dies, promote the replica. If S3 is slow, the card still shows the text and the link.

**Q: What would you change for 10x traffic or rush hour?**  
A: At 5,000 home reads per second, use hybrid. A normal publish copies one inbox row to each follower before the peak. Each inbox keeps the newest 200 post ids. A page older than that window uses fan-out on read for normal accounts. A famous account, above 10,000 followers, stays one post row. The home read loads the reader's inbox and merges the famous posts by time. The same hybrid covers about 2,000 reads per second. A Redis page per user only helps a refresh within about 10 seconds.

**Q: How do you handle a hot key or a single hot partition?**  
A: One post with about 1,700 likes per second makes `like_count` the hot row. Insert the like pair in Postgres. Increment Redis. Write the number back to Postgres once a second. Five million posts a day stay on one posts table. Shard the inbox by reader id first. Shard posts by author id only after that, because an author shard splits the fan-out-on-read merge.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: The inbox worker can lag, so a normal post shows up a few seconds late. Redis can die before the like count is written back. One viral post is still read from Postgres. A year of posts can fill one disk.

**Q: What would you add with more time?**  
A: A replicated Post Cache for one hot post row. A rank step. A CDN for the files. A shard of the inbox by reader id.

## Session questions

**Q: Can we add likes, comments, and image or video after the four-line feed?** (2026-10-09)  
A: Yes. The feed, the follow, and the page stay as they were. A like is one unique pair of user and post. A comment is a separate list under the post, with its own cursor. The file bytes go to object storage. The post row stores the link. A repost and video transcoding stay out.

**Q: Can the like be only a DynamoDB count on the post?** (2026-10-09)  
A: The count can move to DynamoDB when one post is hot. The pair stays in Postgres. A count alone accepts two taps from the same user. The follow table is also required. User, post, and comment rows do not record who you follow. Comment rows include the author id. Image and video links on a comment use the same S3 pattern as the post.

**Q: For a hot like count, a 5,000-read peak, and 5 million posts, what do we add?** (2026-10-10)  
A: Redis holds the hot like count and writes it back to Postgres about once a second. The like pair is inserted first. At 5,000 home reads per second, a normal post is copied into each follower's inbox. Each inbox keeps the newest 200 ids. A page past that window uses fan-out on read. A famous post stays one row and is merged at read time. Five million posts a day is about 58 writes per second, so the posts stay on one machine. Split that table by month when the disk reaches about 2 TB in a year. Shard the inbox by reader id when the inbox machine fills. Shard posts by author id only after the inbox already serves the home read.

**Q: At 5,000 reads, does the follower list include the celebrity?** (2026-10-10)  
A: The inbox holds posts from normal accounts. The read adds the celebrity's posts, then sorts the combined list by time. The celebrity is not copied into the inbox.

**Q: Why did step 2 skip a clear path for post, follow, the home feed, and the page?** (2026-10-10)  
A: The first write of step 2 named the boxes and the fan-out table. It did not list the steps for each requirement. The process rule now requires one heading per functional requirement, with the steps, the options, and the choice. A hot like and a huge post stay in the deep dive.

**Q: On fan-out on write, does each reader have a queue of post ids?** (2026-10-10)  
A: One shared message queue holds a job: the post id and the author id. A worker loads the followers and writes that post id into each follower's inbox. The inbox is the per-user list. A second design puts one job per follower on that same shared queue. A private queue per user is a third design, and this session does not use it. All three still copy the post when the author publishes, so all three are fan-out on write.

**Q: Why does each flow chart stop at a service and skip the database?** (2026-10-10)  
A: It should not. Each feature chart runs client, load balancer, gateway, the named service, then the named database. `FLOW.md` and `final-design-flow.md` both follow that rule. The same rule applies to every question.

**Q: Why not one Feed API for post, follow, like, comment, and home?** (2026-10-10)  
A: One process can serve about 200 home reads per second. The picture still splits five services, because each feature has its own table and its own call. Hello Interview splits the post write from the feed read for that reason. Like and comment are in this session, so they are services too. Feed calls Follow, then Post, to build a page. The comment list is a separate call.

**Q: Where is the end-to-end picture of services and databases?** (2026-10-10)  
A: `final-design-flow.md`. The client reaches a load balancer, then an API gateway, then one Feed API. Postgres holds the rows. S3 holds the files. Redis, one shared queue, a worker, and the inbox table turn on for a shock. `FLOW.md` keeps the interview sequences.

**Q: Is Lee's inbox a database, a Redis record, or a key-value record?** (2026-10-10)  
A: The inbox is a list of post ids for one reader. This session stores it as Postgres rows, keyed by Lee's user id. Redis is a key-value store, and a Redis sorted set is the other common inbox. DynamoDB is also key-value, one item per reader. The happy path has no inbox. The inbox appears at 5,000 home reads per second. The post text stays in the posts table.

**Q: Is a private queue per user the same as fan-out on read?** (2026-10-10)  
A: A private queue is still fan-out on write. Kim's publish would push post 42 onto Lee's queue. Fan-out on read stores the post once. Lee's open loads the accounts Lee follows and merges their posts. Lee has no line of post ids before that open.

**Q: Can the top of the page show each database, so each action shows what it adds?** (2026-10-10)  
A: Yes. The header lists Postgres users, follows, posts, likes, comments, and the inbox. It also lists Redis keys and the S3 links. A new or changed row is highlighted after the next action. The first paint is the baseline, so it does not mark every row.

**Q: Is the read path fan-out on read at low traffic, an inbox at high traffic, a skip for a famous account, Redis for that account's recent ids, and a replicated Post Cache later?** (2026-10-10)  
A: Yes. Low traffic loads the accounts Lee follows, then their posts, and sorts. High traffic writes a normal account into an inbox table and keeps the newest 200 ids. A famous account skips the queue. The home read merges the inbox with Redis key `recent:{author_id}`. A Post Cache of the post text comes later, on several nodes that may each store the same hot post.

**Q: Why is the Redis key `recent:{author_id}` and not `celebrity:{author_id}`?** (2026-10-10)  
A: The key names the value. The value is that author's recent post ids. The famous rule decides whether Feed service writes the key. An author with more than 10,000 followers gets the key. The word celebrity is not used in this session. The account mark is `users.famous`. A key named `celebrity` would be wrong after the follower count drops below the line, while the list of recent ids would still be the same list.

**Q: In this interview, does Redis store the famous account id and the post id, or only the post id?** (2026-10-10)  
A: The famous list stores both. The key is `recent:{author_id}`. The value is that account's recent post ids. The post text stays in Postgres. A second key, `like_count:{post_id}`, stores only a count for one post id. The Post Cache key `post:{post_id}` would store the text, and it stays off.

**Q: Does the Hello Interview Post Cache mean several nodes can each store the same hot post?** (2026-10-10)  
A: Yes. That cache sits in front of the posts table. Posts change rarely, so an entry can live for a long time, and a full cache drops the least recently used rows. The nodes are copies, not shards. Every node may store any post, including the same viral post. A load balancer sends each read to one node. A sharded cache would keep that post on one node. The first miss on each node can read Postgres once, so N nodes can cause N database reads. This interview leaves the Post Cache off at 5,000 home reads per second.

**Q: Can Redis hold Bea's recent ids and also the post content, with the Post Cache added later?** (2026-10-10)  
A: Yes. `recent:{author_id}` is in this design. It holds post ids. The Post Cache is a second Redis key, `post:{post_id}`, with the text and the links. This interview does not turn that key on. Add it when one post row is read harder than one Postgres primary can serve. At 5,000 home reads per second, Feed service still loads the post row from Postgres. The file bytes stay in S3.

**Q: A famous account is fan-out on read, so many people still read the same posts. Do we handle that database load in this interview?** (2026-10-10)  
A: Yes for the post ids. Followers share one Redis list, `recent:{author_id}`, so a million home opens do not each query that author's posts. Feed service then loads the post row by id. This interview does not add a second cache of the post body. That cache is the next step when one post row is read harder than one Postgres primary can serve. The hot like count on that post already uses Redis.

**Q: For a famous account, do we skip the queue, then merge precomputed ids with that account's recent posts?** (2026-10-10)  
A: Yes, on the 5,000-read path. Post service inserts the famous post and does not put a job on the queue. The home read loads the reader's precomputed inbox ids, then the recent posts of famous accounts that reader follows. Feed service merges those lists by time. `FLOW.md` and `final-design-flow.md` both show that publish and that read.

**Q: Hello Interview skips precompute per account. Do we skip it based on how many feed reads?** (2026-10-10)  
A: The skip is per account in both designs. The test is how many followers that author has. This session uses more than 10,000 followers. Hello Interview puts a flag on the follow row. This session puts `famous` on the user row, so every follower of that author is skipped together. The 5,000 home reads per second only decide when precompute turns on. The 200 ids only limit one reader's inbox. Lee still sees both: Kim's post comes from the inbox, and Bea's post is merged at read time.

**Q: The top picture has no queue and no worker. Did the design miss them?** (2026-10-10)  
A: The design includes both. They are off on a normal day, so the first drawing left them out of the boxes. The final picture now draws Queue and Worker and marks them shock. Post service inserts the post, then puts one job on the shared queue. The worker writes inbox rows for a normal account. Feed service reads the inbox. It does not own the queue. The lab still writes those inbox rows inside the publish call. It does not run a separate queue process.

**Q: Is the happy path no inbox, and rush hour fan-out on write except for a popular account?** (2026-10-10)  
A: Yes. A normal day is about 200 home reads per second. That path is fan-out on read. There is no inbox, no queue, and no worker. Rush hour is about 5,000 home reads per second. That path is hybrid. A normal account uses fan-out on write: one shared queue, one job per post, and a worker that writes inbox rows. Each inbox keeps the newest 200 ids. A page older than those 200 ids uses fan-out on read for normal accounts. A famous account has more than 10,000 followers. That author's posts stay on fan-out on read for every page.

**Q: Does the Postgres inbox keep only 200 posts per reader, then fall back to fan-out on read?** (2026-10-10)  
A: The first lock did not cap the inbox. Hello Interview keeps about 200 post ids per reader on the later path. This session now does the same on the 5,000-read path. The worker writes the new id, then drops rows older than those 200. Recent pages read that list. A page older than the oldest inbox row loads normal accounts with fan-out on read. A famous account is separate: an author with more than 10,000 followers never gets an inbox copy, and every page merges that author's posts. The lab still keeps every inbox row.

**Q: When I am Bea, why is there no way to follow Lee?** (2026-10-10)  
A: The first page had three fixed buttons: Follow Kim, Follow Ada, and Follow Bea. Those match the seed, where Lee follows those accounts. The Follow service stores any pair except a user who follows themselves. The page now builds one button for every other user. Bea can store the pair (4, 1). That row is one direction. Lee's home feed does not gain Bea's posts from it.

**Q: Where do Hello Interview, Alex Xu, and production sit next to our design?** (2026-10-10)  
A: The study file is `high-level-design-comparision.md`. It compares the database, the high-level path, and every feature: post, follow, like, comment, and home feed. This session keeps those rows in Postgres and the files in S3. Hello Interview uses DynamoDB for the post and the follow, and leaves the like and the comment out. Chapter 11 uses a graph database for friends and a cache of post ids. Facebook's 2015 post gathers recent actions from memory leaves. Twitter's public notes split FlockDB, a timeline cache, and a blob store.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: The three home columns use the same posts. Fan-out on read queries authors. Fan-out on write reads the inbox. Hybrid reads the inbox and then Bea's posts. A second like returns the first count. The comment stays off the home card.
