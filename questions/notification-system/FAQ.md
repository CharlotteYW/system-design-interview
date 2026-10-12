# FAQ — Notification System

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: Does notification priority belong in the functional requirements?** (2026-10-10)  
A: No. The three core actions stay send, campaign, and preferences. Priority means a worker sends a login code before a campaign notice. That choice is a deep dive. One shared queue lets the campaign occupy the workers. Two lanes, or a priority on the job, let the login code go first. This session keeps two lanes in the deep dive. The functional list does not gain a new action.

**Q: What are the must-have functional requirements?**  
A: Save email, phone number, and device token. Channels are phone app notification, email, and SMS. Let the user turn a channel off and set quiet hours. An upstream service sends one notice to one user, now or later. The same service can send one campaign to many users. The system stores sent or failed.

**Q: What scale numbers would you use, and why?**  
A: 2 million daily users and about 1 million notices a day. That average is about 12 notices per second. Hello Interview designs for a campaign surge of 5,000 notices per second, because a blast does not spread over the day. This session uses that peak. The caller returns after the notice is saved. A single notice arrives within 2 minutes. A high notice should reach the vendor within 5 seconds during a blast. Accepted work is stored first, so a crash does not drop it. Intake stays up when a vendor is down. Delivery is at least once. A retry must not look like a new notice.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: Hello Interview puts four items below the line. A template editor and rich content. Delivery charts such as open rate and click-through. An in-app notice list and badge counts. A cap across notice types. This session also cuts user onboarding. The phone vendor and the email vendor stay outside. We call them.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: The dashboard writes a contact and a preference into the key-value store under the user id. An upstream service posts one notice. Notification service stores the notice, the send record, and a schedule row in one Postgres commit, then returns. The API does not call Kafka. The scheduler publishes the notice id. A worker loads the contact and the preference, calls the vendor, and marks the send record sent or failed. A campaign stores one row. The expander writes one schedule row per user. The scheduler publishes those ids.

**Q: Why these major boxes and not fewer/more?**  
A: The load balancer and the gateway sit in front. Notification service accepts the call. Kafka keeps the vendor call off the request. Workers talk to Twilio, an email vendor, Apple, and Google. The key-value store holds contact and preference. Postgres holds the notice, the schedule, the campaign, and the send record, because those need a time lookup or a notice id. One queue is enough here. Two lanes wait for the priority deep dive.

**Q: How does a campaign work if the API must not loop over every user?** (2026-10-10)  
A: The API writes one campaign row and returns. An expander then writes one notice and one Kafka job per user. A future campaign stays in the schedule table until the scheduler starts that expand. The workers are the same workers as a one-user send.

**Q: Should creating a campaign return 202?** (2026-10-11)  
A: Yes. 202 Accepted means the campaign row is stored and the expander has not finished. The body is `{ id, status }` and status is accepted. `GET /v1/campaigns/{id}` returns the later status. A one-user notice also returns 202, because the vendor call is still ahead. Contact and preference writes stay 200. Those writes finish inside the call.

**Q: For a campaign, who writes the many send-record rows?** (2026-10-11)  
A: The expander inserts one `send_records` row per user when it writes that user's notice. The status is accepted. The worker later sets sent or failed after the vendor call. A crash after the insert still leaves a row to retry. The worker does not create the row.

**Q: Is Kafka only a notice id, with notices, campaigns, campaign users, and send records in Postgres?** (2026-10-11)  
A: Yes. Each Kafka message is one notice id. Postgres holds `notices`, `campaigns`, `campaign_users`, `send_records`, and a schedule row when the time is in the future. The key-value store holds the contact and the preference, under the user id. The worker reads the notice from Postgres, the text from the notice or the campaign, and the contact from the key-value store.

**Q: What is the expander, where does it load user ids, and what is in the Kafka message?** (2026-10-10)  
A: The expander is a worker this system runs. The API stores the user ids in Postgres on the campaign, then returns. The expander reads that list, one page at a time. It writes one notice per user. That notice points at the campaign. The Kafka message is only the notice id. The text stays on the campaign row. The worker loads the notice, then the campaign text, then the contact.

**Q: Does a campaign put every user's message on Kafka?** (2026-10-10)  
A: Yes, one job per user, after the API has returned. Each Kafka message is only the notice id. That is the same message a one-user send uses. The text stays once on the campaign row. The notice row points at that campaign. The expander writes a schedule row per user. The scheduler publishes. The API does not. One Kafka message that lists every user would stick the whole blast on one worker.

## 3. Low-level design and deep dive

**Q: Is the scheduler a service, an Airflow task, or a cron job?** (2026-10-11)  
A: It is a long-running service this system runs. The process sleeps about one second, reads due `schedule` rows, and publishes notice ids or starts the expander. It sets queued only after Kafka accepts the id. It does not call the vendor. A second copy can publish the same id if the first dies after the publish. The worker claim stops a second vendor call. Airflow is a batch runner. A one-second poll does not need it. A single machine cron works at about 12 notices a second and stops if that machine dies.

**Q: Who decides the high topic or the low topic, and where is that stored?** (2026-10-11)  
A: The caller sets `priority` on `POST /v1/notices`. `high` or `low`. The default is `low`. Notification service stores it on `notices.priority`. The scheduler reads that column when it publishes. The API does not pick a topic. A campaign does not choose. Those notice ids go to `notices-low`.

**Q: Does send-now go straight to Kafka, and does a later notice go schedule, then notices, then Kafka?** (2026-10-11)  
A: Superseded the same day. See the dual-write question below. Send-now no longer publishes from the API.

**Q: How do we prevent a duplicate message?** (2026-10-11)  
A: Three checks. The caller sends `idempotencyKey` on the notice or the campaign. The unique column returns the first row, so a timed-out POST does not create a second one. The worker sets `send_records` from accepted to sending once, so a second Kafka copy of that notice id does not call the vendor. The vendor call also sends the notice id when the vendor stores an idempotency key. A crash after the vendor accepts and before `sent` is saved can still deliver twice. A campaign user is unique on `(campaign_id, user_id)`, so a restarted expander skips that user. Two real login codes use two keys. Matching on the text would drop the second code, and that cap stays below the line.

**Q: Is the provider budget a token rate limiter on Twilio?** (2026-10-11)  
A: Yes. It is a token bucket. The bucket refills at the vendor's contract rate. One send spends one token. An empty bucket waits. Twilio has two buckets, high and low. The email vendor, Apple, and Google each have their own pair. One shared bucket would let the campaign spend the login-code reserve.

**Q: How do we keep Twilio from slowing a login code during a campaign?** (2026-10-11)  
A: Separate topics keep the high workers free. They do not add a second Twilio cap. Each vendor has a contract rate R per second. This session reserves 100 per second for high and leaves R minus 100 for low. Tokens live in the key-value store, one pair of keys per vendor. The worker takes a token before the call. High may borrow a low token. Low may not take a high token. No token delays the notice and does not count as a vendor failure. A second vendor account would isolate the cap and would waste unused campaign room. Hello Interview's high bar during a blast is 5 seconds. This session uses that bar.

**Q: Does Hello Interview return accepted when the queue accepts the message?** (2026-10-11)  
A: Yes. The API returns 202 after the broker has stored the message. The worker has not called the vendor yet. If the publish fails, the API does not return accepted, and the caller retries. This session returns 202 after the Postgres commit. The scheduler publishes after that.

**Q: Why does Hello Interview accept a notice with only a queue publish?** (2026-10-11)  
A: The accept call has one fact: please deliver this. A durable queue already stores that fact, so a notice row would be a second copy. Two copies can split if the process dies between them. An outbox matters when the same call must change another fact, such as mark an order paid and tell the warehouse. A notice accept does not change the contact or the preference. Those rows already exist. Sent or failed can be written later by the worker, as one write, after the vendor answers. A future send stays one publish when the queue can hold the message until that time. This session still writes the row, because the Kafka message is only the notice id and the caller can read that id.

**Q: If we insert `send_records` and then publish, what happens when the queue step fails?** (2026-10-11)  
A: That gap is a dual write. Postgres and Kafka do not share a commit. A crash after the insert and before the publish leaves an accepted row and no message. A client retry that only returns the first id does not publish either. The fix is one Postgres transaction for the notice, the send record, and a `schedule` row. The API returns 202 and does not call Kafka. The scheduler publishes that notice id, then sets the schedule row to queued. A crash before the commit leaves nothing, so the client retry inserts again. A crash after the publish and before queued can publish the id twice. The worker claim from accepted to sending stops the second vendor call. Hello Interview can skip the row when the queue message is the whole notice. This design cannot. The message is only the notice id, and the idempotency key lives on the row. The expander uses the same schedule row. It does not publish.

**Q: How does a scheduled notice or a scheduled campaign leave the schedule table?** (2026-10-11)  
A: The API inserts a `schedule` row as waiting and does not touch Kafka. A one-user notice also inserts `notices` and `send_records` in that same commit. A campaign inserts `campaigns` and `campaign_users`, and no notice rows yet. About once a second the scheduler reads due waiting rows, publishes, then sets queued. A notice id goes to `notices-high` or `notices-low`. A campaign starts the expander. The expander writes one notice, one send record, and one schedule row per user. The scheduler publishes those ids to `notices-low`. The workers call the vendor and set each send record to sent or failed.

**Q: Does this system accept an OTP?** (2026-10-11)  
A: Yes. An OTP is a login code. The auth service creates the digits and calls `POST /v1/notices` with `priority` high. The body text is the code. This system does not create the code and does not check it. There is no OTP table. The notice goes to `notices-high`. A high notice skips quiet hours. A channel the user turned off still skips the send. A high notice retries once, then fails, because the code dies in about a minute. A low notice still gets five tries.

**Q: When Twilio fails, how does the retry work?** (2026-10-11)  
A: The API has already returned 202. The worker claims the send record from accepted to sending, then calls Twilio. A bad phone number sets failed and the Kafka offset commits. A timeout, a 500, or a 429 sets the row back to accepted, adds one attempt, and inserts a schedule row for the next time. The scheduler publishes the same notice id. A low notice gets five tries, then failed. A high notice gets two tries, then failed. The notice id is the vendor idempotency key when Twilio stores one. The caller's idempotency key is different. That key stops a second POST from creating a second notice. A sleep in the worker would block the partition. Leaving the Kafka offset open would retry at once and hammer Twilio.

**Q: How does a login code get a worker while a campaign fills Kafka?** (2026-10-11)  
A: Two topics. The login code goes to `notices-high`. The campaign goes to `notices-low`. A small worker group reads only the high topic. Those workers stay free while the campaign workers call the vendor. One topic with a priority tag does not help. Kafka keeps partition order. It does not jump a tagged message ahead of a million earlier campaign jobs. The high workers can still wait if the campaign uses up the vendor's rate limit. See the provider budget question.

**Q: Why this storage model over the alternative?**  
A: Postgres holds `notices`, `campaigns`, `campaign_users`, `send_records`, and `schedule`, because those rows are found by notice id, by campaign page, or by due time. One key-value store holds `contact:{user_id}` and `preference:{user_id}`. A second database for preferences adds a lookup and no new query. A future campaign points the schedule row at `campaign_id`, because notice rows do not exist yet. The Kafka message stays the notice id.

**Q: Where is the bottleneck as traffic grows?**  
A: The vendor contract. Kafka can hold a 50,000-per-second backlog. More workers cannot send faster than the token bucket. Pay to raise R before you add a second vendor.

## 4. Component questions and special situations

**Q: What if the scheduler dies, or Twilio is down for 10 minutes?** (2026-10-11)  
A: Two scheduler copies run all the time. They lock due rows, publish, then set queued. Intake still returns 202. Due rows wait only when every copy is dead. A Twilio outage opens a circuit. Workers stop calling, and attempt_count stays put. Low rows resume after a probe succeeds. A high notice older than about a minute is failed. Do not clear the user's SMS preference. Upstream services would still send, and a later login code would be blocked.

**Q: What would you change for 10x traffic or rush hour?** (2026-10-11)  
A: 50,000 notices a second lands in Kafka and in schedule rows. More workers help only until the buckets are empty. Pay Twilio for a higher R. Add a second SMS vendor only when one contract cannot drain the campaign in time. High tokens stay on the first vendor. The 9 a.m. blast at 5,000 per second is already the design point.

**Q: How do you handle a hot key or a single hot partition?** (2026-10-11)  
A: `budget:twilio:low` is one key. Five thousand takes a second can stay on that key. Fifty thousand makes every worker wait on it. Each worker leases 20 tokens in one call and spends them in memory. The key then sees tens of calls a second. The lease stays small so the extra spend cannot jump the contract by a wide margin.

**Q: What if the workers in one region disappear?** (2026-10-11)  
A: Workers and one scheduler run in each region and share the Kafka topics. The live region takes the partitions. Delivery lags, then it catches up. At least one high worker stays in each region. Postgres stays one primary. A dead primary stops intake. That is a bigger shock than dead workers.

## 5. Summary and future improvements

**Q: Session close** (2026-10-11)  
A: The lab page was tested. Topic counts are the number of notice ids still in each queue. No further questions. The stack was stopped.

**Q: Do the topic counts control high-priority traffic?** (2026-10-11)  
A: No. The count is how many notice ids are still waiting in that queue. The control is the topic name. `notices-high` has its own workers, so a campaign on `notices-low` cannot occupy them. Twilio tokens are a second control. They limit how many calls each priority may make this second. A count of 0 means the worker already took the ids.

**Q: What do Topics and Twilio tokens on the lab page mean?** (2026-10-11)  
A: Topics are the two queues. `notices-high` holds login-code ids that a worker has not taken yet. `notices-low` holds campaign ids in the same way. A 0 means the worker already took the id. Twilio tokens are the sends still allowed this second. High keeps 100. Low keeps 900. The page refills both every second. `down` false means the mock Twilio is accepting calls.

**Q: What did we design, and what risk remains?** (2026-10-11)  
A: A login code commits a notice, a send record, and a schedule row, then returns 202. The scheduler publishes the id to `notices-high`. A campaign returns 202 after one campaign row. The expander writes one schedule row per user onto `notices-low`. The risk that remains is a second vendor call. The worker can die after the vendor accepts and before `sent` is saved. The notice id is the vendor idempotency key when the vendor stores one. A vendor that does not store it can still deliver two texts. At least once stays the promise.

**Q: How would a campaign cancel stop in the middle?** (2026-10-11)  
A: `POST /v1/campaigns/{id}/cancel` sets `campaigns.status` to `cancelled`. The expander stops before the next page, so it writes no more notices. A low worker that already has a notice id loads the campaign, sees `cancelled`, and does not call the vendor. That send record becomes `cancelled`. A record already `sent` stays sent. Deleting Kafka messages is a weak cancel, because a worker may have read the id already. Turning off every user's SMS preference would also block login codes.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: TBD (fill after `./scripts/run-scenarios.sh` and `./scripts/run-functional.sh` pass)
