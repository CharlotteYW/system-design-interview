# Large blobs

**Source:** [Hello Interview: Handling Large Blobs](https://www.hellointerview.com/learn/system-design/patterns/large-blobs). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **blob** is a large file: a video, a photo, or a document. This pattern keeps those bytes out of the application server and out of the database. **Blob storage** is a store built for whole objects, such as S3. A **presigned URL** is a temporary link that lets the client talk to that store directly.

## The problem

Ada uploads a 20 GB video. If the bytes pass through the API server, that server spends its network on one user. The database is a worse place for the file. A large object slows backups, replication, and queries.

The same shape is a Drive file, an Instagram photo, and the raw HTML the crawler keeps. The metadata (who owns it, the status) stays in the database. The bytes do not.

A rule of thumb from the pattern: if the object is large and nobody runs SQL over its bytes, put it in blob storage. The YouTube lab uses about 10 MB as the point where a single put becomes a multipart upload.

## Options

- **Option A: The API receives the file and writes it to storage.** Simple. Cost: the API bandwidth is the ceiling. Wins for a small file, such as an avatar.
- **Option B: The client uploads straight to storage with a presigned URL.** The API records the intent and returns the link. The client puts the bytes to S3. Storage tells the API when the object exists. Cost: the database row and the object can disagree if the client fails halfway. Wins for video and for Drive.
- **Option C: Multipart upload.** Split the file into parts. Each part has its own URL and its own checksum. A failed part is sent again. The other parts stay. Cost: more calls, and you must complete the upload. Wins past one large put. The YouTube lab does this.
- **Option D: A CDN for the download.** Viewers fetch the bytes from an edge cache, not from the API and not from the origin on every view. Cost: a private file needs a signed URL so the cache does not leak it. Wins when many people watch the same bytes.

We pick B, plus C when the file is large, plus D for public playback. The database holds the id, the owner, the status, and the object key. It does not hold the bytes.

## What an interviewer probes

- The client uploaded 18 of 20 parts and then closed the laptop. The parts are still in storage. The client asks for the missing part URLs and continues. Do not start over.
- The database says "uploading" and the object is already complete, or the reverse. An event from storage, such as "object created," is what moves the row to "uploaded." Polling the bucket also works. The event is the better wake-up.
- A deleted database row must not leave the object forever, and a deleted object must not leave a row that points at nothing. Decide which side leads. In YouTube, the row leads, and a cleanup job deletes orphan objects.

## Questions

| Question | What the blob is |
| --- | --- |
| [YouTube](../questions/youtube/) | The original video, then the HLS segments. This is the worked example |
| [Google Drive](../questions/google-drive/) | The file. Dropbox is this same question |
| [Object storage](../questions/object-storage/) | The store itself. The other questions assume it |

| Question | How it also stores bytes |
| --- | --- |
| [Instagram](../questions/instagram/) | Photos and short video. Upload with B. View with D |
| [Web crawler](../questions/web-crawler/) | Raw HTML and extracted text. The crawler is the client, so there is no presigned URL |
| [Distributed email](../questions/distributed-email/) | Attachments. The body can stay in the database if it is small |
| [Google Maps](../questions/google-maps/) | Tiles are blobs, and they are a shared read |
| [Strava](../questions/strava/) | A long GPS trace, when it is too big for a row |
| [ChatGPT](../questions/chatgpt/) | An uploaded document the model reads |
