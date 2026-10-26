# Dealing with contention

**Source:** [Hello Interview: Dealing with Contention](https://www.hellointerview.com/learn/system-design/patterns/dealing-with-contention). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

**Contention** means many callers want the same row at the same moment. This pattern makes that row change once, in one order, so two callers cannot both win. A **race** is the bug where both callers read the old value and both write a win.

## The problem

One seat is left at a concert. Ada and Kim both tap Buy. Both read "1 seat left." Both write "sold to me." The venue now owes two seats.

The same shape is the last item in a flash sale, the high bid, a wallet balance, two riders grabbing one driver, and a one-time code used twice.

A database is good at this while the row lives on one machine. The moment you split that row across machines, you take the problem back from the database. Do that late.

## Options

- **Option A: One transaction on one database.** Lock the row, or use a conditional write: "update where seats = 1." Exactly one caller changes the row. The other gets a conflict and retries or fails. Cost: the lock waits. Wins when the hot row fits one database. This is the interview default.
- **Option B: Optimistic concurrency.** Read a version number. Write only if the version is unchanged. Cost: under a heavy fight, most writes fail and retry. Wins when conflicts are rare, such as two people editing one profile.
- **Option C: Serialize through one queue.** All buys for that event go to one worker, which applies them in order. Cost: the wait is the queue, and that worker is the ceiling. Wins when the fight is so hot that locks thrash. A flash sale can do this for one item.
- **Option D: A distributed lock or two-phase commit.** Several databases agree before the write. Cost: more round trips, and a crash in the middle needs a repair. Wins only when the row truly cannot live on one machine. Say this last.

We pick A. The conditional write in the crawler (`attribute_not_exists`) is the same idea for "insert this URL once." A wallet debit is "update where balance >= amount."

## What an interviewer probes

- Ada's request times out after the seat was sold to Ada. She retries. The second call must not sell a second seat, and it must not tell her she lost. Store the result under her request id and return it. That is an **idempotency key**.
- A lock held by a crashed server stays held. Give the lock a timeout.
- "Just shard the seats" makes the race worse if one seat's row is the hot key. Sharding does not remove contention on one row. It removes contention across different rows.

## Questions

| Question | The row they fight over |
| --- | --- |
| [Ticketmaster](../questions/ticketmaster/) | One seat. Hello Interview uses this example |
| [Flash sale](../questions/flash-sale/) | The last unit of one item |
| [Hotel reservation](../questions/hotel-reservation/) | One room on one night |
| [Online auction](../questions/online-auction/) | The current high bid |
| [Digital wallet](../questions/digital-wallet/) | One balance. Debit only if the balance covers it |
| [Stock exchange](../questions/stock-exchange/) | One price level in the book |
| [Rate limiter](../questions/rate-limiter/) | One counter. Two requests must not both pass the last token |
| [One-time password](../questions/one-time-password/) | One code. The second submit must fail |

| Question | How it also fights for a row |
| --- | --- |
| [Unique ID generator](../questions/unique-id-generator/) | The design exists to avoid one counter |
| [Web crawler](../questions/web-crawler/) | "Insert this URL only if it is absent" |
| [Payment system](../questions/payment-system/) | Charge this card once for this order |
| [Uber](../questions/uber/) | Two riders must not get the same driver |
| [Google Docs](../questions/google-docs/) | Two edits of the same character |
| [Online chess](../questions/online-chess/) | Two moves at the same ply |
| [Google Drive](../questions/google-drive/) | Two devices write the same file |
| [Local delivery](../questions/local-delivery/) | Two orders must not take the same courier |
