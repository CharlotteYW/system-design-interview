# Message Queue

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `message-queue`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Synchronous no queue | TBD — when p99 must stay tiny |
| Queue as buffer | TBD — absorb a spike |
| Competing consumers | TBD — scale workers independently |
| FIFO vs priority | TBD — ordering |
| Retries + DLQ | TBD — poison messages |
| Backpressure | TBD — queue is not infinite capacity |
| SQS vs Kafka-as-queue | TBD — pick one you can defend |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Redis list or RabbitMQ: producer HTTP, worker container, retry + poison message. Kafka only if the topic needs a log.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/message-queue
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Message Queue` to fill this folder.
