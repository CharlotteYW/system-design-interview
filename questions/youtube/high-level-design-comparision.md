# High-level design comparison — YouTube

Read this file on the next pass. It compares the stores, the high-level path, and each feature. It does not replace [README.md](README.md).

The columns are Hello Interview (YouTube), Alex Xu volume 1 chapter 14 (Design YouTube), this session, and production. Production cites only public sources, and a store that no public source names stays "not in a cited source."

## Database choice

| Data | Hello Interview | Alex Xu, chapter 14 | This session | Production |
| --- | --- | --- | --- | --- |
| Video metadata | Cassandra, partitioned by `videoId` | A metadata database with a metadata cache | Postgres `videos`, Redis cache for hot rows | YouTube: MySQL scaled with Vitess, which began at YouTube |
| Upload session | S3 multipart upload state | Not named as its own table | Postgres `uploads` holding the S3 `uploadId` | YouTube Data API: a resumable upload session URL |
| Original file | S3, through presigned multipart upload | Original storage, a blob store | S3 originals bucket | Not in a cited source |
| Segments and renditions | S3, one object per segment per format | Transcoded storage, a blob store | S3 renditions bucket | Not in a cited source |
| Manifests | S3, made during processing | Not named as its own store | S3 renditions bucket | Not in a cited source |
| Edge copies | CDN, in the scale deep dive | CDN for popular videos, own video servers for the rest | CDN in front of S3 renditions | Netflix: Open Connect appliances inside ISPs |
| Processing jobs | S3 event to a processing service | A completion queue and handler, with a DAG scheduler | A job queue after `complete` | Not in a cited source |

## High-level design choice

| Source | Boxes on the happy path | What upload does before it returns |
| --- | --- | --- |
| Hello Interview | Client, video service, Cassandra, S3 with presigned multipart, S3 event, processing pipeline, CDN | Returns presigned URLs. The client sends parts to S3. An S3 event starts processing |
| Alex Xu, chapter 14 | API servers, metadata DB and cache, original storage, transcoding servers, transcoded storage, completion queue, CDN | Returns a presigned URL. Processing runs through a DAG of tasks |
| This session | Load balancer, gateway, upload service, video service, Postgres, Redis, S3 originals, S3 renditions, job queue, workers, CDN | Returns presigned part URLs. `complete` finishes the multipart upload, sets `processing`, and returns 202. The S3 event starts the workflow |
| Production | Not in a cited source as one diagram | YouTube Data API: a resumable session the client resumes after a drop |

## Upload a video

1. The client registers the video and gets upload targets.
2. The bytes go straight to the object store.
3. Processing makes playable versions.

| Source | Steps that differ | Store |
| --- | --- | --- |
| Hello Interview | `POST /presigned_url` with metadata only. Multipart to S3. S3 event notification starts the pipeline | Cassandra, S3 |
| Alex Xu, chapter 14 | A presigned URL. Original storage, then transcoding servers, a DAG of tasks, and a completion queue | Metadata DB, blob stores |
| This session | 50 MB parts with checksums, `ListParts` to resume, the client calls `complete`, an S3 event starts the workflow | Postgres, S3 |

## Watch a video

1. The player gets metadata with a manifest URL.
2. It reads the manifest and picks a rendition.
3. It streams segments and adapts to the network.

| Source | Steps that differ | Store |
| --- | --- | --- |
| Hello Interview | Adaptive bitrate from the manifest, with segments in several formats | Cassandra, S3, CDN |
| Alex Xu, chapter 14 | Streaming protocols. Popular videos from the CDN, the long tail from own video servers to save cost | Metadata cache, CDN, video servers |
| This session | HLS-style primary and rendition manifests on the CDN, segments of about 4 seconds | Redis, Postgres, CDN, S3 |

## What this session keeps

- About 1 million uploads and 100 million views a day (Hello Interview), with a peak of three times the average (this session).
- Bytes never pass through our servers. S3 takes uploads, and the CDN serves views, at about 1 Tbps on average and 3 Tbps at peak.
- Postgres for metadata, not Cassandra: about 12 writes and 3,500 reads a second at peak.
- The client calls our `complete`, and our service calls `CompleteMultipartUpload`. The S3 `ObjectCreated` event starts processing, as in Hello Interview. Step 2 first used a service-written queue job, and step 5 switched to the event to close the crash gap.
- The happy path is closest to Hello Interview. The CDN cost split (popular on the CDN, long tail elsewhere) comes from Alex Xu, and it is kept for step 4.

## Sources

- Hello Interview, "Design YouTube": https://www.hellointerview.com/learn/system-design/problem-breakdowns/youtube
- Alex Xu, *System Design Interview* volume 1, chapter 14, "Design YouTube."
- Vitess history (began at YouTube to scale MySQL): https://vitess.io/docs/overview/history/
- YouTube Data API, resumable uploads: https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol
- Netflix Open Connect: https://openconnect.netflix.com/
