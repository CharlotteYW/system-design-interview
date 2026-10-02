# FAQ — One-Time Password

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: Generate a 6-digit code, send it by SMS or email, accept it once within 10 minutes, then refuse it. A new code for the same destination and purpose replaces the old one. One generate per destination per 60 seconds. About 10 generates per IP per minute. Five wrong checks kill the code.

**Q: What scale numbers would you use, and why?**  
A: 1,000 sends/s and 1,000 verifies/s, from this session. Live codes ≈ 600,000 and about 60 MB, so the database size is not the hard part. The hard part is SMS cost and delay: 1,000 SMS/s is tens of millions of messages a day. Verify is a single-key read and should stay under 50 ms. The generate API returns after the store write, under 100 ms, and the carrier sends afterward.

**Q: What would you explicitly cut from a 45-minute interview?**  
A: The user table, registration, the session cookie, the payment ledger, and a fraud model. The security of the code stays in: expiry, single use, guess cap, store a hash, same error for a wrong code and an unknown phone. Cutting that security leaves a 6-digit number an attacker can scan.

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: Generate hits the load balancer and the OTP API, writes a hash to Redis under destination plus purpose, enqueues the plaintext for SMS or email, and returns 202. A worker sends it. Verify reads that same key, compares the hash, deletes the key on success, and returns `ok: true` or `ok: false`.

**Q: Why these major boxes and not fewer/more?**  
A: One API is enough at 1,000/s. A separate gateway only repeats routing. Redis holds the live code because it expires on its own. A queue keeps the carrier’s seconds off the request. Postgres with a `used` flag also works at this size if verify is one transaction and something deletes old rows. User id and session id are the caller’s data. Our key is the phone or email plus the purpose.

**Q: Why Redis for the live code, and does Postgres still have a job? (2026-10-01)**  
A: At 1,000 sends/s the live set is about 600,000 codes and 60 MB. Postgres can hold that if verify is one transaction and a job deletes expired rows. Redis wins here because the TTL is the expiry and a successful check is a delete. A Postgres audit table is for “a code was issued / delivered / verified,” written asynchronously, with no digits and no code hash. Verify does not read it. This interview uses Redis only. Twilio Verify and Auth0 keep the live code inside their own service. Twilio’s public limit is 5 checks and a 10-minute verification. Auth0’s default is 3 checks and 3 minutes. An AWS messaging sample stores the live code in DynamoDB and deletes it on success.

**Q: What does HTTP 202 mean on generate, and when is the hash stored? (2026-10-01)**  
A: `202 Accepted` means the code is live and the send job is queued. The SMS may still be in flight. The API hashes the 6 digits, writes Redis with a 10-minute TTL, enqueues the plaintext, then returns `202` with `expires_in: 600`. The worker only delivers.

Hashing in the worker is safe only until the first successful verify. Queues deliver a job more than once. A second consume does `SET` again after verify already deleted the key, so the same code works twice. The same `SET` also puts the five guesses back. `SET NX` still resurrects a deleted key. A tombstone key can close that hole, and it is extra machinery. The API write happens once, and a redelivery only resends the SMS.

## 3. Low-level design and deep dive

**Q: Why this storage model over the alternative?**  
A: One key holds the hash and the wrong-guess count. Verify is one Lua script: match deletes the key, a mismatch increments `attempts`, and the fifth mismatch deletes the key. There is no `used` field to set. Splitting the counter onto its own key, or doing `GET` then `DEL` from the API, lets two overlapping checks both succeed. `WATCH`/`MULTI` also serializes them, with a retry when the key changed. Lua does it in one round trip.

**Q: How does Redis enforce 5 attempts and a single success? (2026-10-01)**  
A: See the script story in the README deep dive. Redis runs one client’s script to completion before the next command on that key. Two correct submits: the first deletes the key and wins; the second finds nothing. Two wrong submits at `attempts = 4`: each script sees the current count, so you cannot sneak a sixth guess by racing.

**Q: After a successful delete, does verify return 202? (2026-10-01)**  
A: The delete happens first, inside the Lua script. Then the API returns **200** `{ "ok": true }`. `202` is only the generate response: the code is stored and the SMS is still queued. Verify is finished when the script returns, so success is `200` and failure is `400` `{ "ok": false }`. We do not answer `ok: true` and delete afterward.

**Q: The key was deleted and the 200 never reached the client. What happens? (2026-10-01)**  
A: The business action has not happened, because the login or payment service only continues after it sees `200`. The code is already consumed. A retry of the same digits gets `ok: false`. The user asks for a new code after the 60-second cooldown. An idempotency key on the verify request can store “this retry already succeeded” for a minute, so the same retry gets `200` again. A second click with a new key still fails. This interview does not add that receipt.

**Q: What is the full story of two overlapping verifies? (2026-10-01)**  
A: The user double-submits `482913`. Two API processes both `GET` the hash, both see a match, both `DEL`, and both return `ok: true`. A payment or a login can run twice. The live key has no `used` flag. Success deletes it. Putting that read, compare, and delete inside one Lua script makes the second request observe an empty key and return `ok: false`. `WATCH`/`MULTI` also works, with a retry when the key changed between the read and the delete.

**Q: Where is the bottleneck as traffic grows?**  
A: Redis at 1,000 checks/s is a point read plus one script. The bound is the SMS provider: seconds of delay and on the order of 86 million messages a day at 1,000 sends/s. A dead worker after the `202` retries the same plaintext. It does not mint a new hash. The user can verify until the 10-minute TTL, or request a replacement after the 60-second cooldown.

## 4. Component questions and special situations

**Q: What fails if this component dies, and how do you recover?**  
A: Redis down: generate and verify return 503, and we do not send SMS. `ok: false` would mean a wrong guess. When Redis is back, lost codes stay lost and the user asks again. SMS provider down: the API rejects `channel=sms`, the UI hides it, email still works. Queued SMS jobs retry until the code’s expiry, then drop. They do not write a new hash.

**Q: What would you change for 10x traffic or rush hour?**  
A: 10,000 sends/s and 10,000 checks/s. Add API servers and workers. One Redis still holds about 6 million keys and ~600 MB. The SMS quota is the real ceiling. If the queue cannot drain before the 10-minute TTL, stop accepting generates (503) rather than texting a dead code.

**Q: How do you handle a hot key or a single hot partition?**  
A: One destination is already one generate per minute, so the code key is not hot. A 24-hour ban after a single SMS would block a normal second login. Cap at 10 codes per destination per 24 hours with `otp:day:{destination}`. A code already sent can still be verified. The per-IP cap stays at about 10 generates per minute.

## 5. Summary and future improvements

**Q: What are the biggest risks in this design?**  
A: A dropped `200` consumes a correct code and the caller, having never seen success, does not log the user in. One SMS provider and one region. Redis loss returns 503 and drops in-flight codes.

**Q: What would you add with more time?**  
A: An idempotency key on verify, a second SMS provider, and a Postgres audit that records the outcome without the digits. Shedding generates when SMS cannot keep up with 10× is already the step-4 choice.

## Session questions

Questions you asked at the end of a practice session. Append new ones with a date. Do not delete old entries unless a later design change superseded them.

### 2026-10-01

**Q: When verify succeeds, what does the code actually do?**  
A: `otp.verify` hashes the guess and runs `VERIFY_LUA`. On a match the script deletes `otp:{purpose}:{destination}` and returns `ok`. `main.verify` then returns `200` `{ "ok": true }`. This process does not create a session, confirm a payment, or write the inbox. The caller does that after it sees the `200`.

**Q: Does the success path finish inside the Redis script, and does Redis have transactions? (2026-10-01)**  
A: The hash compare and the `DEL` finish inside `VERIFY_LUA`. Redis runs that script to the end before any other command. The HTTP `200` is afterward, in `main.verify`. `MULTI`/`EXEC` is a Redis transaction: queued commands run with no other client in between, and they cannot branch on a `GET` result. `WATCH` plus `MULTI` can retry when the key changed. The script is the transaction we use because it can `GET`, branch, and `DEL` in one atomic run.

**Q: Is the Lua script atomic, and is that why we chose it? (2026-10-01)**  
A: Yes. Redis runs `VERIFY_LUA` to the end before any other command. The match and the `DEL` are one step, so two verifies cannot both succeed. `MULTI`/`EXEC` is also atomic, and it cannot branch on the hash. The script is the atomic operation that can still say “delete only on a match.”

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: The `202` body is only `expires_in`. The 6 digits show up in the inbox after the worker runs. Verify’s `200` comes back only for the first matching submit. The lab uses one process and a Redis list as the queue, and the inbox stands in for the carrier.
