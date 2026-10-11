# Components — News Feed

Each row is a piece you would name on the whiteboard. Fill definition and responsibility; drop unused rows.

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | The app on the phone or the browser | Publishes, follows, likes, comments, and opens the home screen |
| Load balancer | A front door that spreads connections | Sends each call to one healthy API server |
| API gateway | The session check in front of the services | Checks the login. Routes a post, a follow, a like, a comment, or a home read to the service that owns it. |
| Post service | Stateless writer for posts | Inserts one post row. Owns `posts`. Enqueues an inbox job on the 5,000-read path. |
| Follow service | Stateless writer for follows | Inserts one follow pair. Owns `follows`. Returns the followee list to Feed service. |
| Like service | Stateless writer for likes | Inserts one like pair. Owns `likes`. Updates the count on the post. |
| Comment service | Stateless writer for comments | Inserts one comment. Owns `comments`. Pages that list. |
| Feed service | Stateless reader for the home page | Calls Follow service and Post service. Sorts newest first. Owns `inbox` on the 5,000-read path. |
| Primary database | Postgres, the source of truth | Stores users, follows, posts, the like pair, the like count, and comments |
| Object store | S3, or the same idea | Stores image and video bytes. The post row and the comment row keep the links. |
| Cache | Redis | On the shock path. It holds a hot like count and each author's recent posts. The like count is written back to Postgres about once a second. |
| Message queue | An async buffer | On the 5,000-read path. Publish returns after the post insert. The queue carries inbox copies for normal accounts. |
| Worker | A background processor | Writes the inbox, keeps the newest 200 rows per reader, and writes the like count back. Transcoding is out of this interview. |
| CDN | An edge cache for media | A later step for a far user. The card still works with the object-store link. |

## Why these pieces

- The load balancer, the gateway, the five services, Postgres, and the object store carry the happy path.
- The login check sits in the gateway. This interview does not design passwords.
- Post, Follow, Like, Comment, and Feed are separate services. They share one Postgres database. Each service owns its tables.
- Redis, a queue, and a worker carry the hot like count and the 5,000-read hybrid. A CDN shows up when a far user loads the same file.
