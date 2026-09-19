# Streams

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `stream-processing`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| Queue vs stream | TBD — consume-and-delete vs retain and replay |
| Event sourcing | TBD — state = replay of events |
| Partitions + key | TBD — ordering within a key |
| Consumer groups | TBD — independent readers |
| Windowing | TBD — aggregates over time |
| Kafka / Kinesis / Flink | TBD — interview names |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

Redis stream or Kafka in Docker: two consumer groups on the same topic (dashboard vs archive).

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/stream-processing
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Streams` to fill this folder.
