# Blob Storage

**Status:** Stub  
**Kind:** Key technology  
**Sources:** [Hello Interview — Key technologies](https://www.hellointerview.com/learn/system-design/in-a-hurry/key-technologies)  
**Slug:** `blob-storage`

This folder is a **concept lab**, not a product interview. The README must explain the idea in your own words (options, when each wins, pitfalls). Prompt this topic by name to fill the notes and, when it helps, a small local demo.

Keep notes original. Link to Hello Interview; cite Alex Xu. Do not paste write-ups.

## What this is

TBD — one or two sentences: what problem this concept solves in a system design interview.

## Variants to know

Fill a row for **each** option below when this topic is practiced. That comparison is the point of the folder.

| Variant | Fill in: what it is, when it wins, when to skip |
| --- | --- |
| S3 / GCS / Azure Blob | TBD — interview default: S3 |
| MinIO (local) | TBD — S3 API without a cloud account |
| Metadata in a DB | TBD — never query the blob store as your catalog |
| Presigned URL | TBD — client upload/download without proxying bytes |
| Multipart / chunking | TBD — large video/file resume |
| CDN in front | TBD — origin + edge; see cdn |

## Interview default

TBD — what you say first, and when you switch.

## Pitfalls

- TBD

## Local demo

MinIO in Docker: upload, get URL, metadata row in Postgres. Optional presigned PUT.

**Cut vs production:** TBD after implement.

## How to run

Not implemented yet. After this topic is prompted:

```bash
cd key-technologies/blob-storage
./scripts/setup.sh
./scripts/run-scenarios.sh
./scripts/run-functional.sh
./scripts/stop.sh
```

## Session notes

None yet. Prompt `Blob Storage` to fill this folder.
