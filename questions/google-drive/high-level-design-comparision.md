# High-level design comparison — Google Drive / Dropbox

Session: 2026-10-30. Steps 1 and 2 are recorded. Deep-dive choices remain pending. Original notes only.

**Verification limit:** The official ByteByteGo page for Alex Xu's chapter redirects to sign-in. The full chapter was not available in this session. The Alex Xu column therefore marks unverified details. This does not mean the chapter omits them. Do not replace those cells with invented store choices.

## 1. Database choice

| Data | Hello Interview: Dropbox | Alex Xu: Vol 1 Ch 15 | This session | Production: public Dropbox sources |
| --- | --- | --- | --- | --- |
| Account identity | Existing users | Not verified | Existing identity provider; demo accounts locally | Metadata service includes account information |
| File descriptions | DynamoDB example; PostgreSQL also acceptable | Not verified | PostgreSQL files | MySQL-backed, sharded metadata service |
| Content bytes | S3 | Not verified | GCS; MinIO locally | Encrypted blocks in content-addressable storage |
| Upload attempts | Pending file and chunk status | Not verified | PostgreSQL uploads plus expected upload_chunks and verified receipts | Internal upload-attempt schema not specified in cited public sources |
| Access grants | Separate user/file table | Not verified | PostgreSQL access, keyed by user and file | Exact grant schema not specified in cited public sources |
| Change discovery | Change queries and push hints | Not verified | PostgreSQL changes plus client cursors | Journal and cursors in the 2014 engineering description |
| Stream position allocation | Not specified in that source | Not verified | PostgreSQL user_streams transactional counter and row lock | Allocation policy not specified in the cited sources |
| Piece order | Chunk data discussed | Not verified | PostgreSQL delta manifests with ordered references and lengths; client content-defined boundaries | Blocklist in the 2014 journal description |
| Client progress | Client tracks uploads | Not verified | Pending local work and applied revision; exact format pending | Clients track their journal position |
| CDN cache | CDN for downloads | Not verified | Later performance option | The cited production documents do not specify this path |

Production means the published Dropbox design, not a claim about Google's internal implementation. The engineering journal article dates from 2014. Its details are historical evidence. Do not assume every detail remains current.

## 2. High-level design choice

| Source | Main boxes and byte path | Immediate work versus queued work |
| --- | --- | --- |
| Hello Interview | File service, metadata store, S3, CDN | Storage completion publishes metadata; sync notifications follow |
| Alex Xu | Not verified from the chapter in this session | Not verified |
| This session | Gateway, Drive service, PostgreSQL, direct GCS transfers | Create intent now; transfer bytes; verify completion; commit file and change; send hints afterward |
| Dropbox production | Metadata servers, block servers, block storage, notification service | Public documents separate content transfer, committed metadata, and notification hints; exact current queue topology is not specified |

Our PostgreSQL transaction covers metadata publication and durable change recording. It does not cover GCS. Client completion is a request for verification. It is not proof that the bytes exist.

## 3. Upload a file

| Source | Steps and stores |
| --- | --- |
| Hello Interview | Request transfer permission; upload to S3; publish verified metadata |
| Alex Xu | Not verified from the chapter in this session |
| This session | Gateway → Drive → PostgreSQL intent; client → GCS; verified completion → PostgreSQL file and change |
| Dropbox production | Client transfers blocks through block infrastructure. Metadata represents committed content. The historical article describes a blocklist commit |

**This session keeps:** Direct transfer. A single application service does not relay 50 GB of bytes. Resumability and piece reuse await step 3.

## 4. Download a file

| Source | Steps and stores |
| --- | --- |
| Hello Interview | Authorized transfer URL; CDN reads content from S3 |
| Alex Xu | Not verified from the chapter in this session |
| This session | Gateway → Drive → PostgreSQL permission and pinned download session; client → version-bound GCS URL |
| Dropbox production | Clients receive content through block servers. Block storage retains encrypted content |

**This session keeps:** Direct GCS reads initially. No geographic reuse or cache hit rate is specified. A CDN remains a performance deep dive.

## 5. Share and list files

| Source | Steps and stores |
| --- | --- |
| Hello Interview | Separate user/file mapping supports recipient queries |
| Alex Xu | Not verified from the chapter in this session |
| This session | Drive verifies owner; PostgreSQL commits access row and recipient change; recipient list queries access plus files |
| Dropbox production | Metadata services support shared access. Exact grant keys and shared-list queries are not specified in these sources |

**This session keeps:** A composite grant key, `(user_id, file_id)`. One user can receive many files. Add the reverse index when listing file recipients.

## 6. Automatically sync devices

| Source | Steps and stores |
| --- | --- |
| Hello Interview | Local watcher uploads; push plus change queries discovers remote updates |
| Alex Xu | Not verified from the chapter in this session |
| This session | Local agent stages content; verified publication commits a change; SSE hint or timer triggers cursor replay; client downloads and installs |
| Dropbox production | Notification hints cause metadata sync. The historical design uses journal cursors and blocklists |

**This session keeps:** Durable changes provide truth. SSE supplies one-way hints. Polling remains a safety check and a comparison mode. A file timestamp does not identify changed bytes. Delta sync needs piece identity and order.

## 7. What this session keeps

- 10 million daily active users and a fivefold peak are planning assumptions.
- Peak transfer starts are about 1,160 uploads/s and 2,900 downloads/s.
- The maximum file size is 50 GB. Average incoming content is about 200 TB/day under the stated assumptions.
- PostgreSQL handles metadata and grants. This is not a measured capacity guarantee.
- GCS handles bytes. MinIO is the planned local stand-in.
- Main-path downloads use GCS. A CDN remains a performance option.
- Sync uses one-way hints plus durable replay. The normal change-discovery target is two seconds.
- Changed-part transfer and detailed conflict recovery await step 3.

The direct-storage path is closest to Hello Interview's direct-transfer approach. This session differs in its PostgreSQL choice, initial origin downloads, and explicit verified completion. The Alex Xu comparison remains unverified until the chapter text is available.

## Production evidence for manifest location

Checked 2026-10-31. These sources establish examples, not an industry-wide majority.

| System | Manifest equivalent and location | Evidence limit |
| --- | --- | --- |
| Dropbox, 2014 engineering description | Blocklist in the Server File Journal metadata database | Historical source; exact current schema not established |
| Dropbox, currently available architecture overview | MySQL-backed file metadata, with separate block storage | Broad architecture; not a complete current blocklist schema |
| Google Drive | Not verified from official sources reviewed here | Public file metadata APIs do not identify internal manifest storage |
| restic | Ordered references in tree metadata blobs stored in repository pack files; S3 is a supported repository backend | Backup software, not a claim about interactive Drive storage |

The Dropbox source supports a metadata-database default for our interview. It does not require PostgreSQL. Our exact schema and GCS content store remain session choices.

Do not identify all Dropbox file metadata with Edgestore merely because its broader metadata platform uses that name. Do not claim the 2014 fixed-size block description proves a current content-defined chunking implementation.

A storage-object manifest is also a real architecture, illustrated by restic. Its tree metadata blobs are packed in repository files. They are not necessarily one standalone JSON file per uploaded user file.

Sources: [Dropbox 2014](https://dropbox.tech/infrastructure/streaming-file-synchronization), [Dropbox overview](https://www.dropbox.com/business/trust/security/architecture), [Drive metadata API](https://developers.google.com/workspace/drive/api/guides/file-metadata), [restic format](https://restic.readthedocs.io/en/stable/100_references.html#trees-and-data), [restic S3 backend](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html#amazon-s3).

## 8. Sources

- [Hello Interview — Dropbox](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox).
- Alex Xu, *System Design Interview — An Insider's Guide*, Vol 1, Ch 15, “Design Google Drive.” [Official chapter entry](https://bytebytego.com/courses/system-design-interview/design-google-drive). Sign-in prevented verification in this session.
- [Dropbox — Architecture overview](https://www.dropbox.com/business/trust/security/architecture). Supports the production metadata, block storage, and notification descriptions.
- [Dropbox engineering — Streaming File Synchronization](https://dropbox.tech/infrastructure/streaming-file-synchronization), July 10, 2014. Historical source for blocklists and journal cursors.
- [Google Cloud — Signed URLs](https://docs.cloud.google.com/storage/docs/access-control/signed-urls).
- [Google Cloud — Resumable uploads](https://docs.cloud.google.com/storage/docs/resumable-uploads).
- [Google Cloud — Pub/Sub notifications](https://docs.cloud.google.com/storage/docs/pubsub-notifications).


- [Google Drive — Manage file metadata](https://developers.google.com/workspace/drive/api/guides/file-metadata). Does not establish an internal storage engine.
- [restic — Trees and Data](https://restic.readthedocs.io/en/stable/100_references.html#trees-and-data).
- [restic — Amazon S3 repositories](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html#amazon-s3).

### Upload recovery addition, 2026-10-31

The independent-chunk variant now uses durable upload plans, conditional retries, and trusted receipts. The initial stronger mode read bytes to validate SHA-256. The learner's later optimization selects provider checksum validation and metadata-only receipt verification for ordinary uploads. Byte hashing remains optional, not an assertion about Dropbox's pipeline. The whole-object baseline remains distinct from persistent chunk manifests.

Provider references: [GCS resume procedure](https://docs.cloud.google.com/storage/docs/performing-resumable-uploads), [GCS preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions), [GCS ETags](https://docs.cloud.google.com/storage/docs/metadata#etags), [GCS data validation](https://docs.cloud.google.com/storage/docs/data-validation).

### Provider validation correction, 2026-10-31

Hello Interview uses S3 multipart part receipts and ListParts. Our GCS example uses independent objects and authoritative metadata. Both can avoid application byte rereads when storage validates the chosen supported checksum. ETag receipt correlation and checksum integrity are separate checks. GCS ETags can differ across XML and JSON APIs.

The ordinary session path verifies expected size, provider CRC32C, and selected generation. It uses opaque chunk identities. A declared SHA-256 remains unverified until a trusted digest-validation path establishes it. No source shows that production must use CRC32C, SHA-256, and ETag together.

Sources: [Hello Interview](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox), [S3 ListParts](https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListParts.html), [S3 UploadPart](https://docs.aws.amazon.com/AmazonS3/latest/API/API_UploadPart.html), [GCS metadata reads](https://docs.cloud.google.com/storage/docs/json_api/v1/objects/get).

### Download recovery addition, 2026-10-31

The session now selects a pinned manifest and bounded download lease. It finishes revision 7 and then syncs revision 8. A lost connection preserves verified local progress. URL expiry refreshes credentials for the same revision. Retention expiry stops the job rather than silently changing content. The 24-hour session and five-minute URLs are study choices; the cited production sources do not establish those values.

### Parallel-transfer addition, 2026-10-31

Parallel requests can improve utilization but do not multiply a shared connection's bandwidth. The session chooses bounded adaptive scheduling, starting with two and capped at eight before resource limits. Those values are not attributed to any vendor or book. The full performance design remains incomplete.

Sources: [S3 performance guidelines](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-guidelines.html), [GCS parallel upload guidance](https://docs.cloud.google.com/storage/docs/parallel-composite-uploads).

### Chunk-size and compression addition, 2026-10-31

Hello Interview discusses content-based boundaries, parallel transfer, and client compression. Restic documents a concrete rolling-fingerprint chunker; its published parameters are not the session's defaults. Our delta variant chooses stable content-defined boundaries, with study bounds of 1–8 MiB and a nominal 4 MiB target. Fixed 1 MB and 100 MB modes remain lab comparisons. Device conditions first change scheduler and buffer limits.

The session adds selective identity/gzip representation per chunk, explicit logical versus stored lengths, and provider checksum verification over stored bytes. A ten-percent savings threshold is a study starting point. These policies and values are not claims about Google Drive or Dropbox internals. The initial lab whole-object baseline remains identity-encoded. CDN, security, and scale-failure probes remain pending.

Sources: [Hello Interview](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox), [restic chunking](https://restic.readthedocs.io/en/stable/100_references.html#backups-and-deduplication), [GCS compression representations](https://docs.cloud.google.com/storage/docs/transcoding).

### CDN addition, 2026-10-31

Hello Interview discusses signed CDN delivery in its performance and security path. The session retains direct GCS delivery for ordinary reads. A private CDN variant serves measured repeated reads. One global provider supplies multiple edge caches; demand fills their copies. Cache locality and reuse, not download QPS alone, determine benefit.

Drive checks identity and grants before signing. The CDN validates its own delivery credential on hits and misses. Private origin configuration prevents bypass. The selected five-minute maximum remains a study choice. It accepts transferable bearer links until expiry. Stronger user-bound delivery and detailed revocation remain pending. These are application choices, not claims about Google Drive or Dropbox internals.

Sources: [Hello Interview](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox), [Cloud CDN](https://docs.cloud.google.com/cdn/docs/overview), [private signed delivery](https://docs.cloud.google.com/cdn/docs/using-signed-urls).

### Revocation addition, 2026-10-31

The learner accepts temporary existing permission after a grant removal. Drive denies new signed permissions after the committed removal governs the check. Existing URLs can admit requests until their expiry. Admitted streams can outlast expiry under the selected lab rule. This is not a strict five-minute byte cutoff.

CloudFront explicitly documents request-time expiry, continued admitted downloads, and rejection of new expired Range requests. This supports the comparison; it does not establish identical behavior for every provider. Stronger request authorization and active cancellation remain alternatives. Already saved bytes cannot be retracted.

Source: [CloudFront signed URL expiry](https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/private-content-signed-urls.html#private-content-check-expiration).

### Encryption addition, 2026-10-31

Hello Interview's file-security topic includes transport encryption, storage encryption, grants, and signed delivery. The session now teaches those areas. The chosen ordinary design uses TLS on applicable hops and standard Google-managed GCS encryption. This keeps direct transfer and metadata-only receipts. GCS decrypts authorized object reads automatically. A valid signed URL can still reveal application content.

Customer-managed KMS keys add customer control of permissions and lifecycle. GCS still decrypts authorized reads while its service agent has key access. Client-held encryption has a different trust boundary: clients must encrypt before upload and manage sharing and recovery. These alternatives are not claims about Google Drive's internal key design.

The lab now uses verified local TLS, AES-GCM content encryption, and a separate encrypted edge cache. PostgreSQL metadata is not encrypted at rest by the lab. Default Google encryption is a provider behavior, not a capability proved by an ordinary local MinIO container.

Sources: [Hello Interview](https://www.hellointerview.com/learn/system-design/problem-breakdowns/dropbox), [GCS standard encryption](https://docs.cloud.google.com/storage/docs/encryption/default-keys), [customer-managed keys](https://docs.cloud.google.com/storage/docs/encryption/customer-managed-keys), [encryption options](https://docs.cloud.google.com/storage/docs/encryption).

### Concurrent edits addition, 2026-10-31

The learner proposed last-write-wins. The session's ordinary path instead checks baseRevision to preserve concurrent work. A stale upload does not replace the current file. An explicit conflict-copy action publishes a new private file from verified candidate chunks. Server-order last-write-wins remains a lab comparison.

Dropbox documents conflicted copies for concurrent and offline edits. That source supports the visible product behavior. It does not establish Dropbox's internal database or our SQL/API contract. The session keeps generic document merging and user-visible revision history outside scope.

Sources: [Dropbox conflicted copies](https://help.dropbox.com/organize/conflicted-copy), [PostgreSQL conditional updates](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED).

### Large-recipient discovery addition, 2026-10-31

The selected 100000-reader path uses a transactional outbox and a leased batch worker. Publication commits one durable event with file state and the owner's change. Recipient rows follow in idempotent batch transactions. This refines the small-list all-recipient publication transaction. A queue moves work; it does not remove 100000 journal writes.

A shared namespace journal is an alternative that changes the client cursor model and avoids per-user event copies. Dropbox's 2014 engineering post documents namespace journals. That historical source does not establish our current per-user outbox architecture or today's exact Dropbox implementation.

Sources: [Transactional outbox](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html), [Dropbox namespace journals](https://dropbox.tech/infrastructure/streaming-file-synchronization).

### Database-failure and retry addition, 2026-10-31

The session confirms that ready requires SQL publication, not merely stored bytes. Transient database failure keeps publication unconfirmed and returns a retryable response. A retry uses the same upload attempt and stored result. Publication commits file state, required owner replay, outbox, and the operation result atomically.

A file fingerprint can support authorized storage reuse. It does not identify whether a particular upload operation completed. Stripe's documented operation-key pattern is an external example of retry identity, not evidence that Drive uses Stripe's exact status or retention policy.

Sources: [Idempotent API requests](https://docs.stripe.com/api/idempotent_requests), [PostgreSQL transactions](https://www.postgresql.org/docs/current/transaction-iso.html).

### Equal-content files addition, 2026-11-01

The session distinguishes logical file creation from physical content reuse. The selected explicit reuse path creates separate file IDs and manifests that reference owned verified chunks. Ordinary new-byte uploads can still create duplicate storage; automatic global fingerprint deduplication is not selected. Separate-copy mode remains a lab comparison.

Dropbox's historical blocklist description and current API content-hash documentation support content references and content comparison. They do not establish all present deduplication boundaries. Google Drive's copy API describes logical behavior without specifying physical allocation for each identical upload.

Sources: [Dropbox blocklists](https://dropbox.tech/infrastructure/streaming-file-synchronization), [Dropbox content hash](https://docs.dropboxapi.com/dropbox-api/docs/technical-reference/content-hash), [Drive copy API](https://developers.google.com/workspace/drive/api/reference/rest/v3/files/copy).

### Cleanup addition, 2026-11-01

The session selects live-root tracing for the small lab. Current files, active attempts, protected download sessions, and retention guards keep chunks alive. Device acknowledgment is not an unbounded retention requirement. A locked registry transition to deleting prevents a new reference from racing physical removal.

Storage deletion selects the recorded GCS generation. PostgreSQL and storage still do not share a transaction, so the registry retains retryable intent. Reference counts and age-based temporary cleanup remain comparisons, with distinct safety limits. Provider retention can delay physical reclamation. This is our collector design, not evidence of Google Drive or Dropbox internals.

Sources: [GCS generation conditions](https://docs.cloud.google.com/storage/docs/request-preconditions), [GCS lifecycle](https://docs.cloud.google.com/storage/docs/lifecycle), [PostgreSQL row locks](https://www.postgresql.org/docs/current/explicit-locking.html).

### Tenfold-traffic addition, 2026-11-01

The session adds bounded control-tier scaling, optional Redis caching for immutable manifest payloads, database connection budgets, worker backpressure, and measured CDN reuse. Cache-disabled and cache-enabled behavior remain lab comparisons. This is an application plan, not evidence that Dropbox or Google Drive uses our exact cache.

Peak starts, chunk operations, and byte throughput are different quantities. The tenfold shock is about 11600 upload starts/s and 29000 download starts/s. No source or local test establishes that one PostgreSQL instance handles the resulting workload. Owner-based production partitioning can keep source publication local and route recipient projections asynchronously; the lab remains one database.

Sources: [PostgreSQL connection resources](https://www.postgresql.org/docs/current/runtime-config-connection.html), [PgBouncer pooling](https://www.pgbouncer.org/features.html), [GCS rate distribution](https://docs.cloud.google.com/storage/docs/request-rate), [Cloud CDN signed delivery](https://docs.cloud.google.com/cdn/docs/using-signed-urls).

### Region-loss addition, 2026-11-01

The session strengthens the previously unspecified production database deployment for a stated one-region-loss target. Ready requires the committed publication and result on durable storage in an eligible remote metadata replica, with appropriate content protection separately. Asynchronous promotion can lose acknowledged metadata and is only a weaker explicit recovery policy.

Safe failover replays received history and prevents two independent writers. Retries use the existing upload result. This is a session durability choice with latency and availability costs, not a documented claim about Google Drive or Dropbox. The local one-database region model does not prove this failure model.

Sources: [PostgreSQL synchronous replication](https://www.postgresql.org/docs/current/warm-standby.html#SYNCHRONOUS-REPLICATION), [commit modes](https://www.postgresql.org/docs/current/runtime-config-wal.html#GUC-SYNCHRONOUS-COMMIT).

### Implemented comparison limits — 2026-11-01

The UI and APIs run the selected local variants. See README section 6. Native GCS resumable uploads and S3 multipart transfers remain documented provider alternatives. The whole-object local baseline is one create-only identity object, not a multipart emulator. Fixed 1 MB and 100 MB production sizing remain a design comparison; the local selector uses 16 KiB through 16 MiB because the lab file cap is 64 MiB. Region behavior is explicitly modeled in one database.
