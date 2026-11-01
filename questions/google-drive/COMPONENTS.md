# Components — Google Drive

Steps 1 and 2, 2026-10-30. One logical Drive service contains the named application functions. The table describes production roles; section 14 of final-design-flow.md maps their local containers.

**Implementation update, 2026-11-01:** The local full-stack lab is now implemented and tested. Earlier dated sections describe the design sequence. [final-design-flow.md](final-design-flow.md) section 14 maps the applied schema, local services, and deliberate limits. README section 6 has setup and tests.

| Component | Definition | Role in this design |
| --- | --- | --- |
| Client | Browser, mobile app, or desktop app | Request transfer permission; send and receive bytes directly |
| Sync agent | Client code that watches and transfers changes | Keep pending work; chunk original content locally; select identity or gzip per chunk; use one bounded device scheduler; discover remote changes; validate stored bytes, decode with output limits, and install content |
| Load balancer | Router across application instances | Distribute control requests |
| API gateway | Entry point for application calls | Validate sessions and route requests |
| Drive upload function | Handler for transfer setup and completion | Stage a pending upload; verify storage; publish ready metadata |
| Drive download function | Handler for content authorization | Create a pinned download session; check current access; return only that session's manifest and version-bound URLs |
| Drive sharing function | Handler for grants and file lists | Check ownership; write access rows; list files by owner or recipient |
| Drive sync function | Handler for change discovery and hints | Read a durable cursor stream; emit SSE hints |
| Fan-out worker, large-recipient path | Background processor with a recoverable lease | Materialize per-user changes in batches; atomically save rows and progress; retry safely |
| Redis cache, cache-enabled variant | Bounded store of reusable read payloads | Cache immutable manifest pages after authoritative access checks; not upload or permission authority |
| Database connection pool | Bounded SQL connection manager | Prevent additional Drive instances and workers from exhausting database connections |
| Admission control | Capacity boundary at gateway or handler | Reject unsafe excess work with retry guidance while retaining durable accepted work |
| PostgreSQL | Relational database | Own files, upload attempts, access grants, and durable changes |
| GCS | Google Cloud Storage | Store content outside the application servers; validate supported checksums; encrypt storage and decrypt authorized direct reads |
| CDN edge, repeated-read variant | Delivery node with a private content cache | Validate signed delivery permission on hits and misses; fetch misses from the protected origin |
| TLS endpoints | Connection endpoints with verified certificates | Encrypt each applicable transport hop; service endpoints still see application bytes |
| Provider key infrastructure | Protected Google-managed encryption keys | Support default GCS storage encryption without exposing plaintext keys to Drive or clients |
| Cloud KMS, optional variant | Customer-controlled key operations | Control key permissions and lifecycle for CMEK; not required for the default route |
| SSE connection | Server-sent event stream | Wake a connected device; carry no file content |
| Identity provider | Existing account and session system | Supply validated identity; profile management stays excluded |
| Receipt verifier | Checker of provider metadata | Compare planned destination, length, provider checksum, and generation; persist ordinary transfer receipts |
| Optional SHA-256 worker | Stronger content-identity checker | Read bytes only when a trusted SHA-256 claim is required; separate verification flag and storage-I/O cost |
| Retention cleanup | Worker for expired internal state | Respect current manifests, live download leases, pending uploads, and safe deletion rules |
| Recovery function | Retry logic for pending publication | Run the same verified finalizer after interruption; implementation follows step 5 |
| MinIO | Local storage stand-in | Planned lab store with an S3-compatible protocol; not a GCS API emulator |

## Database responsibilities

- `files`: identity, owner, name, committed content pointer, internal revision, server update time, and deleted_at for logical deletion. The delta variant uses `current_manifest_id`. Fresh publication and download checks reject a deleted target.
- `manifests` and `manifest_chunks`: proposed delta metadata with ordered chunk references, logical and stored lengths, encoding, stored checksum, generation, and chunking policy, stored in PostgreSQL.
- `uploads`: uploadId, owner, fileId, mode, expected size, base revision, idempotency key, canonical creation parameters, expiry, state, and committed result references. Enforce UNIQUE(owner_id, idempotency_key) for initial creation. Retain results for the documented retry window.
- `upload_chunks`: primary key `(upload_id, ordinal)`; logical length, expected stored length and CRC32C, encoding, optional declared stored-byte SHA-256, opaque chunkId, destination, observed generation and size, observed CRC32C, verification method, optional verified SHA-256, sha256_verified flag, state, and verification time. Pending reconciliation and verification work must survive a worker restart.
- `download_sessions`: downloadId, ownerId, fileId, selectedRevision, manifestId or whole-object identity, createdAt, leaseExpiresAt, and status. Retain the selected state for a bounded active session.
- `access`: one grant per `(user_id, file_id)`; reader is the initial shared role.
- `changes`: journal keyed by `(user_id, seq)`, with `file_id, revision, type, source_event_id`; unique `(user_id, source_event_id)` prevents duplicate delivery. Here `user_id` identifies the affected user, not necessarily the editing actor.
- `chunk_objects`: chunk_id, bucket, object_key, object_generation, state, created_at, unreferenced_since, delete_token, delete_started_at, and deleted_at. Coordinate reference acquisition with chunk retirement.
- `outbox`: event_id, file_id, revision, event_type, state, last_recipient_id, lease_owner, lease_until, lease_epoch, and created_at. Durable work for the large-recipient path.
- `user_streams`: one transactional counter per user, with `user_id` and `last_seq`.

The replay follow-up chooses a stream-row lock and transactional counter for journal-append commit order within each user's stream. In asynchronous fan-out, this need not match original source-publication order across different files. Large-recipient fan-out uses the outbox and worker described below. The consolidated design schemas now appear in [final-design-flow.md](final-design-flow.md). They are not applied migrations.

All publication paths use one finalizer. The synchronous mode commits file state, recipient journal entries, counters, and upload result together. The large-recipient mode commits file state, owner journal and counter, upload result, and one outbox event together. Later batch transactions create recipient replay. An omitted statement is a code defect, not an eventual-consistency feature. PostgreSQL commits related metadata changes together. It cannot include a GCS upload in that transaction. New bytes must be verified before file publication.

## Temporary storage permission

Signed URLs authorize limited storage operations. GCS native resumable transfers use a session URI after initiation. Both credentials require protection. An active signed URL can be used by anyone who possesses it.

## Main path and later options

| Decision | Main path | Later comparison |
| --- | --- | --- |
| Byte transfer | Client directly to GCS | Proxy path for a small lab comparison |
| Metadata | PostgreSQL | Compare keyed NoSQL modeling in the notes |
| Sharing | Access table | Embedded recipient list |
| Discovery | SSE hints plus durable replay | Polling-only mode beside it |
| Content updates | Stage the full replacement content | Delta variant uses variable manifests and content-defined boundaries; fixed boundaries remain a comparison |
| CDN | Direct GCS stays the ordinary path | Private signed CDN variant for measured repeated reads across edge locations |
| Durable fan-out work | PostgreSQL outbox for large-recipient discovery | External broker relay is optional; storage-event recovery is a separate use case |

Source: [Hello Interview — Dropbox](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox). Provider details: [GCS signed URLs](https://docs.cloud.google.com/storage/docs/access-control/signed-urls).

## Proposed delta representation

Each manifest entry records a chunk identity and length. Upload new chunks before publishing the manifest. Reuse unchanged chunks. A changed chunk can alter total file length without moving later stored chunks. The selected study CDC policy uses a 64-byte rolling window, a 1 MiB minimum, a nominal 4 MiB target, and an 8 MiB maximum. Record algorithm version and parameters; keep them stable for reuse. These values are not vendor defaults. Garbage collection must protect all live references and active readers.

## Transaction boundary clarification, 2026-10-31

GCS does not join the SQL publication transaction. Client code creates chunks; GCS retains their immutable bytes. PostgreSQL stores the proposed delta manifest and file pointer. Upload and verify first. Publish references second. A failed publication can leave unused content for later recovery or safe cleanup. A SQL rollback does not undo a GCS upload.

## Manifest read clarification, 2026-10-31

The selected delta manifest lives in PostgreSQL tables. Drive returns it through an authorized API. The client uses ordered chunk identities and lengths to reconstruct the file. It obtains temporary read URLs for chunks belonging to that file revision. Never treat possession of a raw chunk ID as authorization. An immutable GCS manifest object is a documented alternative, not a second required copy.

## Upload recovery clarification, 2026-10-31

API instances stay stateless. PostgreSQL retains the upload plan, pending work, and receipts. GCS retains the independently uploaded objects. Reconcile expected destinations rather than trusting names or client byte counters. Retry with immutable identities and conditional creation.

The ordinary receipt verifier trusts provider-side CRC32C validation and reads authoritative size, checksum, and generation. It does not download chunk bytes. An optional worker can establish a trusted SHA-256 identity. ETag alone does not prove expected size or content. A completion request returns 202 while verification remains pending. The finalizer returns ready only after the shared SQL publication commits.

## Integrity clarification, 2026-10-31

Freeze the client-declared plan separately from storage receipts. Supported GCS checksum validation compares received bytes with the upload checksum. Only the optional stronger mode hashes the actual pinned chunk version. The ordinary receipt does not claim SHA-256 verification and does not trust a client-set SHA-256 metadata label.

Per-chunk verification plus the complete ordered plan is the required publication check. A whole-file digest is optional. A manifestHash is not that digest. ETags support HTTP validation; GCS generations support object-version conditions. A raw 412 is not proof of matching content. Reconciliation establishes that proof.

## Current verification policy, 2026-10-31

The learner's provider-validation optimization supersedes mandatory SHA-256 rereads. Ordinary GCS uploads use a supported expected CRC32C field, provider computation, and Drive metadata comparison. Store verification_method=provider_crc32c and sha256_verified=false unless an additional trusted path validated H17.

Use an opaque chunkId tied to an authorized key and protected generation. Do not use an unverified declared hash as a trusted global deduplication identity. The client receives a validated checksum for downloads. The ordinary path does not require all of CRC32C, SHA-256, and ETag.

The optional sha256_verified flag is algorithm-specific. False means SHA-256 has not been established; it does not invalidate a successful provider_crc32c receipt. GCS custom metadata named sha256 is an uploader declaration, not provider-computed plaintext SHA-256.

## Download recovery policy, 2026-10-31

The phone retains one session, revision, manifest, and durable verified-chunk set. It finishes revision 7 before installing the queued newer state. Generation-bound URLs and per-chunk checks prevent mixed content. A completed cached chunk may be reused only when the selected manifest references that same protected content.

The study session lasts at most 24 hours; URLs last at most five minutes and cannot outlive the session. These are configurable choices, not vendor limits. A URL can expire while the retained revision remains available. Refresh URLs for that same session. If the retained state expires, stop the job and offer an explicit restart.

A server completion report is a client acknowledgment, not independent proof of device bytes. The client must validate and durably install content before changing its applied revision. Missing protected content during a live session is a failure to recover, not permission to substitute the latest revision.

## Parallel-transfer policy, 2026-10-31

A device-wide scheduler starts with two requests and adapts within a study cap of eight. Memory and CPU budgets can lower that cap. Measure useful newly accepted bytes, not repeated retry traffic. Keep a change only when measured gain justifies it. Back off on throttling and repeated timeouts.

All requests share the user's connection. More workers cannot turn a 100 Mb/s uplink into 2 Gb/s. Bound bytes in flight, preparation buffers, and work queues. Fetch URLs for near-term batches. Sequential and fixed-concurrency modes remain lab comparisons. No benchmark is implemented yet.

## Chunk size and compression policy, 2026-10-31

The delta variant uses bounded content-defined chunks. Fixed 1 MB and 100 MB modes remain lab comparisons. Network and device conditions first change concurrency and buffer budgets. Do not mutate the frozen plan during retry.

The client chunks original content, then chooses identity or gzip per new chunk. Keep gzip only when measured size savings and estimated total time justify CPU work. A ten-percent size threshold is a study starting point. Cache prepared bytes or reproduce and validate the exact planned representation for retry. Unchanged references retain their existing encoding.

PostgreSQL records logicalSizeBytes, storedSizeBytes, encoding, and storedCrc32c for each planned and committed entry. GCS stores the encoded bytes. The metadata verifier compares GCS size and CRC32C with the stored-byte expectations. It does not verify decoded semantics. Downloaders verify stored bytes, decode with bounded output, and check logical length before installation. Optional SHA-256 fields in this representation contract refer to stored bytes.

For gzip objects, use Content-Type: application/gzip and omit HTTP Content-Encoding. The manifest controls decoding. This avoids GCS automatic decompression altering the verified representation. The first whole-object Range baseline stays identity-encoded.

Progress reports distinguish totalSizeBytes (logical), totalStoredSizeBytes, storedBytes (unique observed object bytes), verifiedStoredBytes, and verifiedLogicalBytes (logical lengths of verified entries). In-flight traffic and retries are separate metrics. Provider receipts establish stored integrity, not independent proof of decoded logical length.

## Private CDN policy, 2026-10-31

The global CDN provider supplies edge locations. Cache copies fill on demand. Nearby repeated reads improve reuse; cold one-off files may not justify the extra route. Compare direct and cached delivery in the lab.

Drive validates the caller's identity, file grant, download lease, and pinned chunk membership before signing. CDN signed credentials differ from GCS signed credentials. The CDN validates them even on cache hits. Keep origin private, configure the delivery identity, and block unsigned bypasses. Signing alone is not a complete Cloud CDN private-origin configuration.

Use immutable destination and generation as content identity. Preserve stored encoding. Shared content reuse must never bypass access enforcement. Ordinary signed URLs are bearer credentials with a study maximum of five minutes. They do not independently require Kim's login at each GET. Cache retention and grant validity remain separate. Stronger user-bound delivery is an alternative for stricter requirements.

## Revocation policy, 2026-10-31

The sharing function authorizes the owner and removes the access row with the required change record in one PostgreSQL transaction. The download function denies newly authorized URLs after it observes the committed removal. A retained download session is not an access grant.

Issued URLs remain scoped bearer permissions until expiry. The selected study policy validates each request at admission and permits admitted responses to finish. Five minutes is not a hard cutoff for bytes in flight. A stricter design adds current authorization on each request; a strict active-stream cutoff also needs cancellation or repeated enforcement.

The sync agent can stop on an access-removal hint or a denied refresh. Hints are not enforcement. The client never installs incomplete content. It cannot guarantee erasure of bytes the recipient already saved. Shared content and unrelated signing credentials remain available for other users.

## Encryption policy, 2026-10-31

Choose TLS on each applicable production hop and standard Google-managed GCS encryption at rest. Provider infrastructure owns default keys. GCS decrypts content for authorized reads, including valid signed URLs. Separate key authority protects raw encrypted storage; it does not replace file authorization.

The current PostgreSQL manifest keeps its existing logical/stored sizes, encoding, checksum, and object generation. Provider disk encryption is transparent to these fields. The application checksum covers uploaded representation bytes. Client-held encryption would add a different representation and key-recovery protocol; it remains an alternative.

The CDN terminates transport encryption and can cache application bytes. Its origin link and storage need their own policies. PostgreSQL, backups, and local temporary files also need separate protection. Local TLS and encrypted storage must be verified during implementation; no cloud accounts or real Google KMS resources are planned.

## Concurrent-edit policy, 2026-10-31

The upload finalizer checks the frozen baseRevision when it publishes. Use an atomic conditional update or equivalent checked row lock. A separate read followed by an unchecked update is insufficient. Keep publication, change rows, counters, and result in one transaction.

A stale candidate returns 409 and retains verified references until the attempt expiry. The sync agent preserves dirty local content. An explicit conflict-copy action creates a new private file and repeats safely from the recorded result. GCS content need not be uploaded again.

Extend uploads with conflicted state, conflict_current_revision, resolution_kind, result_file_id, and result_revision. A copy uses the same finalizer infrastructure and a separate file identity. It does not change provider checksum validation or require user-visible version history.

Server-order last-write-wins remains a comparison mode. It preserves convergence while accepting loss of an overwritten edit. Generic automatic merge remains a notes alternative.

## Large-recipient recovery, 2026-10-31

One file publication can require 100000 small recipient rows. The selected outbox path keeps that expansion outside the publication transaction. The worker claims jobs with recoverable leases and fencing. A batch transaction appends recipient changes, updates counters, and advances its checkpoint together.

A stable source_event_id and unique (user_id, source_event_id) make repeated work safe. Preserve per-file event order and use a reverse access index on (file_id, user_id). Check current access for disclosure and delivery. A new grant supplies its own initial-state event.

A five-minute URL, a durable change journal, and an outbox protect different things. The outbox retains unfinished discovery work. The journal retains completed replay rows. Signed URLs delegate byte access. Queueing does not eliminate recipient-write cost or guarantee the two-second discovery target.

## Recipient stream clarification, 2026-10-31

The fan-out worker primarily writes PostgreSQL rows. user_id in changes is the recipient, not the actor. A plan-file update can appear at Lee's seq 41, Kim's seq 73, and Ada's seq 9. Each client queries its own authenticated stream. A live hint is separate and optional.

An offline Kim still needs the kim row for the selected replay protocol. A design that instead scans current file revisions can avoid recipient copies, but pays repeated metadata reads. The 100000-recipient outbox requirement follows from our selected per-user feed, not from every possible file-sync architecture.

## Database outage and operation identity, 2026-10-31

The finalizer returns retryable 503 while required metadata publication is unconfirmed. The client retains uploadId and prepared content. After recovery, read the attempt from the authoritative database. Return a completed result before attempting publication again. Reuse receipts or reconcile storage metadata for a pending attempt.

Serialize duplicate completion on the upload row. Commit result_file_id, result_revision, result_manifest_id, result_event_id, result_updated_at, and completion kind with file state, required owner replay, and outbox. Make source_upload_id unique for content-publication events. A later file update must not cause an older completed attempt to publish again.

Keep initial request keys unique by owner and reject changed canonical parameters. File names, chunk existence, CRC32C, and unverified client digests are not operation identities. A new file with identical content can reuse authorized chunks but remains a new logical request. Retry-result retention and cleanup must agree.

## Upload session and key scope, 2026-11-01

The client generates a random UUID for one initial upload intent and persists it before the request. K1 is a label for that value. Drive stores the key and normalized creation parameters on uploads. A database uniqueness constraint handles duplicate creation across instances. Reusing a key with changed parameters fails.

Upload state belongs to uploads; per-chunk state belongs to upload_chunks. Later endpoints identify the attempt by uploadId. Completion locks that attempt and replays its stored result after success. The API creation receipt, current upload status, published file state, and outbox progress have different meanings.

A generic idempotency_requests table is an alternative for many API operation types. It is not required for this selected upload schema. Retention must cover the supported retry window. Client resume state does not replace PostgreSQL authority.

## Equal-content files and reuse policy, 2026-11-01

Distinct names create distinct logical files and operation identities. The selected reuse path allows owned, already verified source chunks in another manifest. The manifest PUT accepts reuseFrom with source file, selected manifest, and ordinal. Drive validates ownership, derives authoritative metadata, and pins the reference for the new attempt. Reused entries return uploadRequired=false; new entries still transfer bytes.

The resulting files keep independent names, revisions, grants, and manifests. Immutable chunks can serve both. Updates use new chunks and switch only the edited file's pointer. Deleting one file does not remove chunks protected by another file, upload, or download lease.

Keep separate stored copies as a lab comparison. Automatic global hash deduplication remains an unselected alternative. This does not require new SHA validation for ordinary uploads and does not treat CRC32C as a global content identity.

## Safe cleanup policy, 2026-11-01

The collector traces current nondeleted files, active upload plans, protected download manifests, and retention guards. The small lab uses these roots rather than an unchecked reference counter. Keep the copy's A/C/D/X, and retain B while the old download lease remains protected. Offline acknowledgments do not extend retention forever.

The chunk_objects row is the coordination point. Cleanup discovers unreachable candidates, applies grace, then locks and rechecks before marking deleting. All new file, upload, reuse, and download protections lock the same chunk rows in a consistent order and reject deleting or deleted content. Old unrooted manifest metadata is not permanent protection.

The storage DELETE occurs after the mark commits, outside SQL, and selects the intended object version. Record completion afterward. Retry durable deletion intents after a crash. Do not collect based on bucket listings while PostgreSQL is unavailable. Never reopen retired identities for a new valid upload; reconcile late orphan generations separately.

Acquiring a new protection resets unreferenced_since. Renewing a lease across expiry also follows the registry admission rule. An expired lease cannot restore protection after cleanup wins the deleting transition.

Logical deletion, client sync, and physical reclamation have separate timing. Protect issued credentials and retained sessions according to server policy. Provider holds or soft delete can delay physical space recovery.

## Tenfold-traffic capacity policy, 2026-11-01

Scale Drive instances for control traffic and SSE endpoints for connections. GCS and CDN carry ordinary file bytes. Count plans, chunk PUTs/GETs, metadata verification, leases, publication, journal expansion, and retries separately from transfer starts.

The cache-enabled variant uses Redis for immutable manifest pages after current authorization. Current grants, upload results, stream counters, registry state, and outbox progress remain authoritative in SQL. Coalesce hot fills and bound fallback on cache failure. The cache-disabled variant stays available.

Bound database pools, application queues, verification workers, and fan-out work. Transaction pooling must preserve multi-statement transactions; statement pooling is unsuitable. A best-effort hint backplane can connect workers to SSE instances without becoming durable replay storage.

Longer private CDN retention helps reused immutable bytes; it does not extend five-minute permission or remove all authorization queries. Capacity and hit rate need measurement. Read replicas do not scale primary writes and cannot silently weaken new-permission checks.

Production partitioning/sharding is a later capacity path with explicit local transaction boundaries and asynchronous recipient projections. The local lab uses one PostgreSQL instance and must label the production capacity model as unmeasured.

## Regional durability and failover, 2026-11-01

For the production single-region-loss target, require the publication transaction's log to be durable on an eligible remote-region standby before ready. Replica placement and synchronous acknowledgment settings must meet that failure domain. Apply the policy to operation results, canonical grants, retention state, and source outbox as well as file pointers.

The failover controller selects a candidate with the acknowledged history, completes log replay, prevents the old primary from remaining writable, and promotes one new authority. Retrying u123 returns its existing result. An asynchronous stale replica cannot redefine an already confirmed upload as failed.

Content must independently survive the same failure under its storage acknowledgment contract. A single-region local database and MinIO mock do not prove regional durability. Synchronous replication adds latency and can block new acknowledgments when required replicas are unavailable.
