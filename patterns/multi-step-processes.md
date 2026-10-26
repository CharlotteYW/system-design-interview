# Multi-step processes

**Source:** [Hello Interview: Multi-step Processes](https://www.hellointerview.com/learn/system-design/patterns/multi-step-processes). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **multi-step process** is work that visits more than one service, and a crash can land between the steps. This pattern keeps the process moving, or undoes the steps that already happened. A **saga** is a sequence of steps with a defined undo for each step. A **workflow engine** stores the step list and resumes it after a crash.

## The problem

Kim pays for a ride. The charge succeeds. The trip row update fails. Kim was charged and the trip still says "unpaid." A retry charges Kim again.

The same shape is an order (charge, reserve, ship, email), a video (upload, probe, transcode, publish), and a broker order (submit, match, settle).

One database transaction covers steps that share one database. It does not cover a card network, a blob store, and an email service. Those are separate failures.

## Options

- **Option A: One database transaction.** All of the rows change, or none do. Cost: it cannot include a call outside that database. Wins when every step is a row in one database. A hotel hold plus the room row can be this.
- **Option B: A saga with an undo.** Step 1 charges. Step 2 reserves the seat. If step 2 fails, refund the charge. Cost: you write the undo, and the user can see the middle state. Wins when the steps are few and each undo is clear.
- **Option C: A workflow engine.** The engine stores "step 2 is next" and retries that step after a crash. Temporal and Step Functions are examples. Cost: another system to run. Wins when the chain is long, slow, or easy to get wrong by hand. A video pipeline and an agent pipeline fit.
- **Option D: Events.** Each step writes an event. The next service reacts. Cost: the order of events and the replay rules become the design. Wins when many consumers care about the same fact.

We pick A when it fits. We pick B for a payment plus one local write. We name C when the chain has human waits or more than a few fragile steps. Do not start at C.

Every step that can be retried must be safe to run twice. The charge uses an idempotency key. The second call returns the first charge.

## What an interviewer probes

- Name the crash point. "The charge returned 200. The process then died." Say which step runs again, and why the card is not charged twice.
- The undo can also fail. A refund that fails must be retried, not forgotten. The saga is not finished until the undo finishes.
- A step that waits for a person, such as a courier pickup, cannot hold a database transaction open. Store the state and wait for an event.

## Questions

| Question | The steps |
| --- | --- |
| [Payment system](../questions/payment-system/) | Authorize, capture, record. The idempotency key is the whole point |
| [Donations](../questions/donations/) | Charge, then add to the public total. Both must agree |
| [Robinhood](../questions/robinhood/) | Submit, match at the exchange, settle into the wallet |

| Question | How it also spans steps |
| --- | --- |
| [YouTube](../questions/youtube/) | Upload, probe, transcode each rendition, write the manifest |
| [Uber](../questions/uber/) | Request, match, start, end, pay |
| [Hotel reservation](../questions/hotel-reservation/) | Hold the room, charge, confirm. Release the hold if the charge fails |
| [Ticketmaster](../questions/ticketmaster/) | Hold the seat for a few minutes, then pay or release |
| [Local delivery](../questions/local-delivery/) | Accept, assign, pick up, drop off |
| [Digital wallet](../questions/digital-wallet/) | Debit one account, credit the other. Undo the debit if the credit fails |
| [GitHub Actions](../questions/github-actions/) | Steps in a pipeline. A later step runs only after the earlier one passes |
| [Web crawler](../questions/web-crawler/) | Fetch, then parse. The HTML in storage lets the parse retry without a second fetch |
| [Notification system](../questions/notification-system/) | Store the notice, then send on each channel |
| [Distributed email](../questions/distributed-email/) | Accept, store, deliver. A delivery failure retries that recipient only |
| [ChatGPT](../questions/chatgpt/) | A tool call, then the model, then another tool call. A long chain of fragile steps |
