# Components — YouTube

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client app | Phone, browser, or TV app | Cuts the file into parts, sends them to S3, resumes after a drop. Plays video by reading manifests and segments |
| Load balancer | Front door for API calls | Spreads small API requests over gateway hosts. Video bytes do not pass through it |
| API gateway | Auth and routing | Checks the user, then routes to the upload service or the video service |
| Upload service | Owns uploads | Creates the `videos` row and the S3 multipart upload, signs part URLs, lists parts for resume, completes the upload, and puts a processing job on the queue |
| Video service | Owns video reads | Returns metadata and the manifest URL. Reads Redis first, then Postgres |
| Postgres | Metadata store | `videos` (id, owner, title, status, manifest key) and `uploads` (upload id, part size, state) |
| Redis | Cache | Hot video metadata, so a viral video does not hit Postgres on every view |
| S3 originals | Object store | The creator's raw file. Kept forever as the source for rebuilds |
| S3 renditions | Object store | Segments and manifests for every rendition. Rebuildable from the original |
| Job queue | Work buffer | One job per completed upload. Lets processing lag without failing uploads |
| Processing workers | Compute fleet | Split the original into segments, transcode each into several renditions, write manifests, set status `ready` |
| CDN | Edge cache near viewers | Serves manifests and segments. Fetches from S3 only on a miss |

## Why these pieces

- Bytes skip our servers in both directions. At about 1 Tbps watched and 500 TB uploaded a day, any server in the byte path becomes the bottleneck.
- The queue separates "upload finished" from "video ready." An upload never fails because transcoding is busy.
- Originals and renditions are separate buckets because their value differs. An original must never be lost. A rendition can be rebuilt.
- Postgres is enough for metadata: about 12 writes and 3,500 reads a second at peak. Redis absorbs one viral video.
