# FAQ — YouTube

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?** (2026-10-18)  
A: Upload a video and watch a video. Hello Interview uses the same two. Upload hides very large files and resumable transfer. Watch hides smooth playback on slow networks.

**Q: What scale numbers would you use, and why?** (2026-10-18)  
A: About 1 million uploads and 100 million views a day, from Hello Interview. That is about 12 uploads and 1,160 view starts a second, with about three times that at peak (this session's choice). Bytes matter more than requests. At an assumed 5 minutes and 3 Mbps per view, viewers pull about 11 PB a day, about 1 Tbps on average and about 3 Tbps at peak. Uploads add about 500 TB of raw files a day at an assumed 500 MB each. A file can be tens of GB.

**Q: What does "low latency, even on slow networks" mean?** (2026-10-18)  
A: Playback starts before the file finishes, and quality adapts to the network. The video is cut into segments of a few seconds at several bitrates. The player reads a manifest, fetches one segment at a time, and picks a lower bitrate when the network slows. This session's target is the first frame in about 2 seconds, with rare rebuffering.

**Q: What must never be lost?** (2026-10-18)  
A: The original file after "upload complete," and the video metadata. The renditions can be rebuilt from the original. A half-finished upload may be lost, because the client resumes it.

**Q: Availability or consistency?** (2026-10-18)  
A: Availability. Watching must stay up. A new video can take minutes to appear while it is processed. The uploader sees `processing` until it is ready.

**Q: What would you explicitly cut from a 45-minute interview?** (2026-10-18)  
A: Hello Interview's list: video info and view counts, search, comments, recommendations, channels, subscriptions, bad-content protection, bot and fake-account protection, and monitoring. This session also cuts live streaming, ads, DRM, captions, offline downloads, likes, and playlists.

## 2. High-level design

**Q: Walk through an upload.** (2026-10-21)  
A: The client sends the title and the file size to the upload service. The service inserts a `videos` row (status `uploading`), starts an S3 multipart upload, and returns presigned URLs for 50 MB parts. The client sends each part straight to S3 and keeps the ETags. After a drop, it asks which parts arrived (S3 `ListParts`) and sends only the rest. On complete, the service finishes the multipart upload, sets status `processing`, and queues a job. Workers make segments and renditions, write manifests, and set `ready`.

**Q: Walk through watching a video.** (2026-10-21)  
A: The player asks the video service for the video. The service reads Redis, then Postgres, and returns the manifest URL on the CDN. The player reads the primary manifest, picks a rendition, reads its segment list, and fetches segments of about 4 seconds from the CDN. It changes rendition when the network changes. The CDN goes to S3 only on a miss.

**Q: Why not return a presigned S3 URL for the video?** (2026-10-21)  
A: That gives one file at one quality, from one S3 region. Adaptive playback needs a manifest and many segments, and about 1 Tbps must come from edge servers near viewers. Public videos use plain CDN URLs. Private or unlisted videos use short-lived signed URLs or signed cookies at the CDN.

**Q: Postgres or Cassandra for video metadata?** (2026-10-21)  
A: Hello Interview picks Cassandra by `videoId`, because every read is a point lookup and rows grow by about 365 million a year. This session picks Postgres. That is about 365 GB a year at about 1 KB a row, 12 writes a second, and about 3,500 reads a second at peak, which one primary plus replicas handle. Shard by `video_id`, or move to Cassandra, when the rows outgrow one machine or writes must work in many regions.

**Q: What are a manifest, a rendition, and a segment? Give a simple example.** (2026-10-23)  
A: Take one 12-second cat video, id `abc123`.

- **Rendition.** The same video encoded at one quality. Example: 240p at 0.4 Mbps, 720p at 2.5 Mbps, 1080p at 5 Mbps. Same picture, different sharpness and size.
- **Segment.** A small file holding about 4 seconds of one rendition. 12 seconds makes 3 segments per rendition. Every rendition is cut at the same time points, 0 to 4 s, 4 to 8 s, and 8 to 12 s, so segment 1 is the same moment in every quality.
- **Rendition manifest.** A small text file that lists one rendition's segments in order.
- **Primary manifest.** A small text file that lists the renditions and the bandwidth each needs. The player reads it first.

The files in S3 (HLS layout):

```
v/abc123/master.m3u8          primary manifest
v/abc123/240p/index.m3u8      rendition manifest
v/abc123/240p/seg_00000.ts    0-4 s, about 0.2 MB
v/abc123/240p/seg_00001.ts    4-8 s
v/abc123/240p/seg_00002.ts    8-12 s
v/abc123/720p/index.m3u8
v/abc123/720p/seg_00000.ts    0-4 s, about 1.25 MB
...
v/abc123/1080p/...            0-4 s, about 2.5 MB each
```

`master.m3u8`:

```
#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=400000,RESOLUTION=426x240
240p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720
720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080
1080p/index.m3u8
```

`720p/index.m3u8`:

```
#EXTM3U
#EXT-X-TARGETDURATION:4
#EXTINF:4.0,
seg_00000.ts
#EXTINF:4.0,
seg_00001.ts
#EXTINF:4.0,
seg_00002.ts
#EXT-X-ENDLIST
```

Kim watches on a train at 3 Mbps:

1. The player gets `master.m3u8` (under 1 KB). 720p needs 2.5 Mbps, and Kim has 3, so the player picks 720p.
2. It gets `720p/index.m3u8` and learns the three segment names.
3. It gets `720p/seg_00000.ts` and plays seconds 0 to 4.
4. The train enters a tunnel, and the speed falls to 1 Mbps. For the next 4 seconds the player gets `240p/seg_00001.ts`. That is the same moment of the video in a smaller file, so playback continues without a pause, only blurrier.
5. Out of the tunnel, it gets `720p/seg_00002.ts`.

The size math: segment size = bitrate × 4 s. 2.5 Mbps × 4 s = 10 Mb = 1.25 MB. A 1-hour video has 900 segments per rendition. With 4 renditions, that is 3,600 segment files plus 5 manifests. HLS (`.m3u8`, from Apple) and DASH (`.mpd`, an XML standard) are the two common formats. Both use the same idea.

**Q: Why these major boxes and not fewer/more?** (2026-10-21)  
A: Bytes skip our servers in both directions. S3 takes uploads, and the CDN serves views. The queue separates "upload finished" from "video ready," so busy transcoding never fails an upload. Originals and renditions are in separate buckets, because an original must never be lost and a rendition can be rebuilt.

## 3. Low-level design and deep dive

**Q: What is in the data model?** (2026-10-23)  
A: `videos` holds the id, uploader, title, status, visibility, `original_key`, `manifest_key`, duration, times, and an error. `renditions` holds one row per version (codec, size, bitrate, manifest key, segment count). `uploads` holds the S3 multipart upload id, the part size, and the state. Store S3 keys, not URLs, so the CDN domain can change and signed URLs stay fresh. Do not store a row per segment. A 1-hour video has 3,600 segments, so a row each would add billions of rows a day. The manifest is the segment index, and the key pattern `v/{id}/{rendition}/seg_{n}.ts` names every segment.

**Q: If there is no row per segment, where is the segment information?** (2026-10-23)  
A: In three places, and none of them is one row per segment:

- The database row for a rendition holds `manifest_key` (where its list is) and `segment_count` (how many segments). The count is a summary. The pipeline uses it to check that fan-in is complete.
- The rendition manifest in S3, `v/abc123/720p/index.m3u8`, is the real list: each segment's file name and exact duration, in order. The last segment can be shorter, and only the manifest knows that.
- The key pattern `v/{videoId}/{rendition}/seg_{n:05}.ts` makes each name predictable.

The player never asks the database about segments. It reads the manifest from the CDN.

**Q: How does the processing DAG work, and what if a worker dies?** (2026-10-23)  
A: Probe, then split at keyframes, then fan out one transcode task per chunk per rendition (3,600 for one hour at 4 renditions), plus audio and thumbnails. Then fan in to write each rendition manifest and the primary manifest, and set `ready` last. A chunk must start at a keyframe, a full picture, or it cannot be decoded alone. At an assumed 10 s per task, 3,600 tasks take 10 hours on one core and about 72 seconds on 500 cores.

A dead worker misses its heartbeat, and its task goes to another worker. That worker writes the same output key. An S3 PUT is all or nothing, and the manifest comes only after every segment, so viewers never see the retry. Three failures mark the video `failed`, and the original stays for a re-run.

**Q: Airflow for the DAG?** (2026-10-23)  
A: The idea is right, and the tool is a poor fit at this scale. About 600 tasks a video times 1 million videos a day is about 7,000 tasks a second. Airflow adds seconds of scheduler overhead per task and a metadata row each. A durable workflow engine, Temporal (Hello Interview's choice) or Step Functions, is built for millions of runs, with fan-out, retries, and heartbeats. A plain queue plus a job-table counter is the simple version, and the lab will use it.

**Q: How do we know each upload part arrived undamaged, and which parts arrived?** (2026-10-23)  
A: The client sends a checksum for each part (MD5 or CRC32C) in a header that the presigned URL requires. S3 checks the bytes and rejects a mismatch with `BadDigest`, and the client resends that part. So a stored part is always whole. To resume, trust `ListParts`: S3 already records every stored part with its number, size, and ETag. Hello Interview keeps a chunk list in the metadata as well. That gives progress on any device, at the cost of one more write per part and a second copy that can disagree.

**Q: What is an ETag?** (2026-10-24)  
A: An HTTP header, short for "entity tag," that a server returns as a fingerprint of an object's content. For an S3 upload part, the ETag is normally the MD5 of that part's bytes. The client keeps each `(partNumber, ETag)` pair and sends the full list in `complete`. S3 then knows exactly which bytes to join. If part 241 was sent twice, the ETag says which copy to use. The ETag of the finished multipart object is not the MD5 of the whole file. It looks like `"9b2cf...-400"`, a hash of the part hashes plus the part count. Browsers and CDNs use ETags too: `If-None-Match: <etag>` gets a `304 Not Modified` when nothing changed.

**Q: Is the ETag only between the client and S3? Is it saved in our tables?** (2026-10-24)  
A: Mostly between the client and S3, with our upload service as the relay at the end. S3 returns an ETag for each part. The client keeps it. On `complete`, the client sends all the pairs to the upload service, and the service passes them to S3 `CompleteMultipartUpload`.

We do not save part ETags in Postgres. S3 already keeps them. If the app forgets them after a restart or on another device, `GET /v1/videos/{id}/upload` calls `ListParts` and returns every part with its ETag. Hello Interview's chunk list is the option that does store them. One optional column is the finished object's ETag and size on `videos` (`original_etag`). A later job can then check that the original in S3 is still the same file.

**Q: Show every call between the client, the upload service, and S3.** (2026-10-24)  
A: See the table "Every call in one upload" in `FLOW.md`. In short: create (Postgres row, S3 `CreateMultipartUpload`, `uploads` row). Then signed part URLs, made locally with no S3 call. Then the client sends `PUT` parts to S3 and keeps the ETags. Resume runs through the service calling `ListParts`. Complete runs `CompleteMultipartUpload`, then one Postgres transaction, then the queue. The client is the only one that moves bytes.

**Q: How do we show upload progress, and what is `original_etag` for?** (2026-10-24)  
A: They answer different questions.

Progress needs no new table. `ListParts` already returns every stored part with its size, so `uploadedBytes / fileSizeBytes` is the progress on any device: 240 of 400 parts is 60%. Add an `upload_parts` table, primary key `(video_id, part_number)` with ETag, size, and time, only if you need:

- progress without calling S3, for example a dashboard that refreshes often;
- a history of each part;
- a check that the client reported every part.

The cost is one more write per part, and a copy that can disagree with S3.

`original_etag` is an integrity check. The upload service saves the finished object's ETag (`9b2cf...-400`) and size at `complete`. A later job runs `HEAD originals/abc123/source.mp4` and compares them. A mismatch means the original changed or was replaced, so alert and restore from the replica in the second region. For a stronger check, also store a full-file checksum, such as SHA-256 or S3's full-object checksum.

**Q: Should we store the final ETag and a checksum? Does our system do it?** (2026-10-24)  
A: Store both, because they catch different problems.

| Check | Saved when | Proves | Catches |
| --- | --- | --- | --- |
| Part checksum | Every `PUT`, checked by S3 | Each part arrived whole | A part damaged in transit (`BadDigest`) |
| `original_etag` | At `complete`, from S3's answer | The object has not changed since then | Later replacement or change in S3 (`HEAD` and compare) |
| `original_sha256` | Sent by the client at create, rechecked by the probe step | The joined file equals the file on Lee's device | A wrong part list, a missing part, or a client bug that the part checks miss |

The client hashes the file once while it reads the parts. The worker reads the whole original anyway, so it hashes while it reads. Our design now has both columns and `sha256` in `POST /v1/videos`. The YouTube lab is not built yet. It will compute and check both.

**Q: When is the SHA-256 checked, and what are all the uses of an ETag?** (2026-10-24)  
A: The SHA-256 is checked once, at the start of processing. Before the worker transcodes, it confirms that it holds the creator's exact file, so no renditions are built from a broken original. The same hash can also spot a duplicate upload: the same SHA-256 means the same file.

The ETag has five uses:

1. **A receipt for each part** during multipart upload. `complete` lists them.
2. **A cheap integrity check over time.** `HEAD` the original and compare it with `original_etag`, with no download.
3. **A guarded read.** The worker reads the original with `If-Match: <original_etag>`. S3 returns `412 Precondition Failed` if the object changed, so the guard costs nothing extra.
4. **A guarded write.** S3 supports conditional writes. Writing the original with `If-None-Match: *` fails if an object already exists at that key, so a bug cannot overwrite an original.
5. **HTTP cache revalidation.** A CDN or browser sends `If-None-Match: <etag>` and gets `304 Not Modified` when nothing changed.

A multipart ETag depends on the part size. Compare an ETag only with the ETag of the same object, never with a hash you computed yourself.

**Q: Progress on all devices: do we store each part's ETag? Do transcoded files need ETags?** (2026-10-24)  
A: Progress needs no ETags. It is `bytes stored / file size`.

- **Option A:** the uploading device counts its own parts. This is the usual detailed bar.
- **Option B (pick, with A):** another device calls `GET /upload`, and the service sums the sizes from `ListParts`.
- **Option C:** a stored counter (`parts_done`, `bytes_done`) for dashboards that poll often. It stores two numbers, not 400 ETags.

Only the original's ETag is stored and used, for `HEAD` checks, `If-Match` reads, and an `If-None-Match: *` first write. Segments have ETags automatically, and CDNs and browsers use them for revalidation. We do not store them: segments are rebuildable, there are billions, and a retry must overwrite them. A manifest rewrite can use `If-Match`, so two jobs cannot erase each other's change.

**Q: Why delete the cache key when a video becomes ready?** (2026-10-24)  
A: Without it, the cache keeps the old status. At 10:00 Kim opens Lee's link. The cache misses, Postgres says `processing`, and Redis keeps that for 10 minutes. At 10:02 the worker sets `ready`. Kim refreshes at 10:03 and still sees "processing" until 10:10.

- **Option A: Short TTL only.** It is simple, but the status is stale for up to the TTL, and the database load is higher.
- **Option B: Delete the key after the database commit (cache-aside invalidation).** The next read loads `ready`.
- **Option C: Write the new value into the cache (write-through).** There are two writes to keep in step.
- **Option D: Cache only `ready` videos.** A ready row rarely changes, so its cache is almost never wrong.

We pick D plus B, and keep the in-process cache TTL at 5 seconds, because a key cannot be deleted from every host's memory.

Two traps:

- **Deleting before the commit.** A reader can reload the old row in between.
- **A lagging replica.** A reader after the delete can reload `processing` from a replica that is behind. Read from the primary on a miss for rows changed in the last minute, or check `updated_at`.

**Q: What is an origin shield? Is it part of S3?** (2026-10-24)  
A: It is a CDN feature, not S3. You turn it on in the CDN settings. You choose one shield location near the origin, the S3 region, and every edge's miss goes through that one cache. CloudFront calls it Origin Shield. Fastly calls it shielding. Cloudflare calls it Tiered Cache. Akamai calls it tiered distribution.

Without it, a new viral video makes 1,000 edges miss at once, and S3 gets 1,000 requests for each segment. With it, the shield gets those 1,000 requests, fetches each segment from S3 once, and answers the edges from its cache.

**Q: When is an abandoned upload cleaned up?** (2026-10-23)  
A: Parts of an open multipart upload are billed, but they are hidden from normal listings. An S3 lifecycle rule, `AbortIncompleteMultipartUpload`, deletes them a set number of whole days after the upload started. We use 7 days, not 24 hours, so a 20 GB upload paused over a weekend survives. A sweep job marks the Postgres rows `failed`, because S3 does not know about them.

**Q: Where is the bottleneck as traffic grows?** (2026-10-23)  
A: The processing workers and the CDN. The upload service and the video service are stateless and light (about 350 and 3,500 requests a second at peak).

- **Workers:** about 600 million tasks a day at an assumed 10 s each, about 69,000 cores all day. Autoscale on queue depth, use spot instances, encode low renditions first, and use hardware encoders.
- **CDN:** about 3 Tbps at peak. An origin shield stops a viral video's misses from hitting S3 from 1,000 edges at once.
- **Postgres:** replicas, then shard by `video_id`, with the cache key deleted on each status change.
- **S3:** the bottleneck is cost, not speed: about 365 PB a year, so use colder storage classes for old originals.

## 4. Component questions and special situations

**Q: The workers fall 2 hours behind. What then?** (2026-10-24)  
A: Autoscale, but new cores take minutes, and a surge needs about 280,000 extra core-hours, so priority matters more than raw scale:

- **Low renditions first.** The video plays at 720p within minutes.
- **Short videos first.**
- **Fair share per uploader.**
- **A separate pool for an event you know is coming.** This is a bulkhead, so the surge cannot slow regular uploads.

Creators see `processing` with an estimate from the queue depth, and a notice when the video is ready.

**Q: A 50-million-subscriber creator uploads. What happens?** (2026-10-24)  
A: 1 million viewers at 3 Mbps is about 3 Tbps, the platform's whole normal peak. Each edge collapses its own misses. The origin shield collapses the edges, so S3 sees each segment about once. Metadata uses the in-process cache and Redis with coalesced misses. The `ready` moment is the risky one, because every viewer misses at once. Pre-warm the shield and the edges for a premiere. The CDN needs the headroom, through several CDNs or caches inside ISPs.

**Q: The S3 region with the originals goes down.** (2026-10-24)  
A: It depends on what was prepared. With one region, uploads fail and every CDN miss fails. Prepare these in advance:

- S3 cross-region replication for the originals.
- A CDN origin group with the replica as the backup.
- A Postgres replica in the second region.
- An upload service that can start uploads in the second bucket (`original_key` records the bucket).

Uploads from the last few minutes may lag in the replica, but they are not lost. The data is still in the first region.

**Q: The CDN fails in one region.** (2026-10-24)  
A: Never send about 600 Gbps straight to S3. It is far from the viewers, egress is costly, and S3 returns 503 while it scales. First, route to the same CDN's other regions. Then, steer DNS to a second CDN, with the origin shield ready for its cold misses. When capacity is short, cap the manifest at 480p. That is about 1 Mbps instead of 3, so about three times fewer bytes.

**Q: What would you change for 10x traffic?** (2026-10-24)  
A: In this order:

1. **The CDN,** from 3 to 30 Tbps: caches inside ISPs, several CDNs, and newer codecs.
2. **The processing fleet,** from 69,000 to 690,000 cores: hardware encoders, spot instances, and skipping high renditions nobody watches.
3. **Storage,** from 365 PB to 3.6 EB a year: storage classes, and rebuilding cold renditions on demand.
4. **Postgres:** shard by `video_id` at 3.6 billion rows a year.

The upload and video services only need more hosts, because they are stateless and the bytes skip them.

**Q: For a big upload, do we pre-warm the CDN and then set `ready`?** (2026-10-24)  
A: Almost. Keep two steps apart: `ready` means processed, and publish means visible. For a premiere:

1. Processing sets `status = ready` while `visibility = scheduled`.
2. A warm-up job fetches the manifests and the first segments (about 30 s of the likely renditions) through the CDN in each big region, so the shield and the edges cache them.
3. At `publish_at`, the video becomes `public`, and its metadata cache key is deleted.

Pre-warm only uploads predicted to be big, such as big creators or scheduled premieres. Every other video is pulled on demand.

**Q: How do we add processing workers? Do we ask AWS for more?** (2026-10-24)  
A: Partly. Do these four things:

- **Autoscale on the backlog.** The workers run in an EC2 Auto Scaling group, or on Kubernetes with Karpenter or the cluster autoscaler. The target is waiting tasks per worker, so a longer queue adds machines.
- **Buy capacity in layers.** The steady base on Savings Plans or reserved capacity, cheaper and guaranteed. The burst on spot instances, much cheaper and safe here because tasks are short and idempotent. Use many instance types, so spot capacity can be found.
- **Plan quotas ahead.** AWS limits vCPUs per region by default, so request higher limits weeks ahead, and run workers in several regions near the originals.
- **Use hardware encoders.** AWS has video transcoding instances (EC2 VT1). Google built its own chips for YouTube.

At about 690,000 cores, capacity is planned months ahead, not requested on the day.

**Q: How do you handle a hot key or a single hot partition?** (2026-10-24)  
A: The hot key is one viral video. For metadata: an in-process cache with a 5-second TTL, then Redis, with misses coalesced, so Postgres sees one read. For bytes: edge collapsing plus the origin shield, so S3 sees one read per segment.

## 5. Summary and future improvements

**Q: Summarize the design in a few sentences.** (2026-10-24)  
A: Uploads skip our servers. The client sends presigned multipart parts straight to S3, with per-part checksums and resume through `ListParts`. An S3 event starts a workflow that probes, checks the SHA-256, splits at keyframes, transcodes chunk by rendition in parallel (low renditions first), writes manifests, and sets `ready`. Watching reads metadata from the caches and Postgres, then manifests and 4-second segments from the CDN. S3 serves only misses, through an origin shield.

**Q: Why the S3 event and not the client calling complete?** (2026-10-24)  
A: Not because the client waits. `complete` returns 202 at once either way. A multipart upload is finished only when someone calls `CompleteMultipartUpload`, so the client still calls our `complete`, and our service still calls S3. The event matters after that. With the event, the file itself starts processing, so a crash between "S3 finished" and "job queued" cannot leave an unprocessed file. The job start must be idempotent per `videoId`, because an event can arrive twice.

**Q: What are the biggest risks in this design?** (2026-10-24)  
A:

1. Processing cost and backlog: about 69,000 cores.
2. CDN capacity and cost: about 3 Tbps more for one viral video, plus regional outages.
3. About 365 PB of new storage a year.
4. Replication lag in a region loss.
5. Malicious files against the decoder: sandbox the workers.
6. Stale cached status after `ready`.
7. One Postgres primary until sharding.

**Q: What would you add with more time?** (2026-10-24)  
A: Hello Interview's list: pipelining processing during upload, resuming playback, and view counts. Then likes and comments (news-feed patterns), captions, live streaming, per-title encoding, multi-CDN steering, and storage tiering for cold renditions.

**Q: How does the player pick a quality from my internet speed, and how often does it check?** (2026-10-24)  
A: The server does not measure anything. The player does, on every segment.

1. **Start with a guess.** hls.js assumes about 500 kbps (`abrEwmaDefaultEstimate`), or it starts at a set level. The lab sets `startLevel: 0`, so 240p.
2. **Measure each download.** Speed = segment bytes / download time. A 180 KB segment in 1.8 s is about 0.8 Mbps.
3. **Smooth the measurements.** It keeps two moving averages, a fast one (half-life about 3 s) and a slow one (about 9 s), and uses the lower one. One lucky or unlucky segment does not swing the choice.
4. **Pick the next segment's rendition, with a safety margin.** It moves up only if the estimate × 0.7 covers the higher rendition's bitrate (`abrBandWidthUpFactor`). It stays if the estimate × 0.95 covers the current one (`abrBandWidthFactor`).
5. **Watch the buffer.** If a segment is downloading too slowly to finish before the buffer runs out, it aborts that download and fetches a lower rendition, without waiting for the next segment.
6. **Repeat for every segment,** about every 4 s of video. Switches happen at segment boundaries, which is why every rendition is cut at the same time points.

In the lab: on the fast edge, the first 240p segment came in at about 190 Mbps, so the player jumped to 720p. On the slow edge, about 0.8 Mbps × 0.7 is about 0.56 Mbps, below 480p's 0.96 Mbps, so it stayed at 240p.

Other players use other rules. Buffer-based rules (BBA, and BOLA in dash.js) choose by how full the buffer is. Hybrids use both, and large platforms tune their own.

**Q: So the client decides which rendition to pull for each 4 seconds?** (2026-10-24)  
A: Yes. The player chooses each segment's rendition, and it updates its estimate after every download. The server only sets the menu: the manifest lists the renditions the player may choose. The server can still steer by changing the menu. During an incident it can serve a manifest capped at 480p (step 4, option D). A private video can also list fewer renditions. Each segment request is a plain GET to the CDN, so the servers never track any viewer's quality.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?** (2026-10-24)  
A:

- Signing a part URL is local math. The browser talks to S3 directly, so S3's CORS must expose `ETag`, or the client cannot keep its receipts.
- A per-part SHA-256 must be signed into the URL. S3 then rejects one flipped byte, and the client resends that part.
- MinIO sends bucket events wrapped in a JSON array. The consumer must start the job idempotently, because a replayed event arrives again.
- Chunk × rendition fan-out needs a lock for fan-in. Two workers can finish a rendition's last chunks at once, and only one may write the manifest.
- Low renditions first makes a video playable before 720p exists. That also means the master manifest changes, so it cannot be cached for a long time until it is final.
- Re-encoding audio per chunk leaves small overlaps at the joins. Real pipelines encode audio once.
- The shield's effect shows in one number: 20 viewers on two edges made 1 origin fetch with the shield and 2 without it. With 1,000 edges, that gap is 1 against 1,000.
