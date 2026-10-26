# Long-running tasks

**Source:** [Hello Interview: Managing Long-Running Tasks](https://www.hellointerview.com/learn/system-design/patterns/long-running-tasks). One of the [seven patterns](https://www.hellointerview.com/blog/patterns).

A **long-running task** takes longer than the caller should wait. This pattern accepts the work now and finishes it later, on a worker. A **queue** holds the work until a worker takes it. A **dead-letter queue** holds a job that failed too many times.

## The problem

Ada uploads a 20 GB video. Encoding takes minutes. The HTTP call cannot stay open that long. The web server also cannot spend those minutes on one user, or it stops serving everyone else.

The same shape is a crawl of 10 billion pages, a judge that compiles code, a mail send to a million people, and a workflow of CI jobs.

Do not use this pattern for a short write. A short write that goes through a queue is harder to explain, and the user waits anyway. A chat message save is short. Keep it in the request.

## Options

- **Option A: Do the work in the request.** The caller gets the result in the same call. Cost: the caller waits, and a slow job blocks a server. Wins under a few hundred milliseconds.
- **Option B: Accept, queue, and return an id.** The API checks the request, writes a job, and returns `202` with the id. A worker does the job. The caller polls the id, or gets a push when it finishes. Cost: two states to store, and a job can sit in the queue. Wins when the work is seconds or longer.
- **Option C: Pick the queue for the failure you care about.** Redis is a simple list. SQS retries one message and has a dead-letter queue. Kafka keeps the log so you can replay it. Cost rises with the features. The crawler picks SQS because one URL must wait without blocking the next URL.

We pick A for a short call. We pick B when the work outlives the request. The status row is the source of truth. The queue message is only a wake-up.

## What an interviewer probes

- The worker dies mid-job. The message must come back. In the crawler, a message that was not deleted returns after the visibility timeout.
- A bad job fails forever and blocks the queue. After N tries, move it to the dead-letter queue. Do not retry a permanent error, such as a 404.
- The web tier and the worker tier scale on different limits. Add workers when the queue grows. Do not add web servers for a CPU job.
- A job that calls a third party can be slow and flaky. Bound the concurrency, or you will open too many calls at once.

## Questions

| Question | What runs later |
| --- | --- |
| [Web crawler](../questions/web-crawler/) | Fetch, then parse. The frontier is the queue. This is the worked example |
| [Notification system](../questions/notification-system/) | Accept the notice, then a worker sends the push, email, or SMS |
| [Distributed message queue](../questions/distributed-message-queue/) | This question builds the queue the other questions use |
| [Job scheduler](../questions/job-scheduler/) | Run a job at a time. The scheduler is the delayed queue |
| [GitHub Actions](../questions/github-actions/) | A pipeline of jobs. Each step is one queued task |
| [Distributed email](../questions/distributed-email/) | Accept the mail, then deliver to each mailbox |
| [News aggregator](../questions/news-aggregator/) | Fetch sources on a timer |
| [Price tracking](../questions/price-tracking/) | Check a page on a timer |
| [LeetCode](../questions/leetcode/) | Compile and run the submission |

| Question | How it also defers work |
| --- | --- |
| [YouTube](../questions/youtube/) | Transcode runs on workers after the upload |
| [YouTube Top K](../questions/youtube-top-k/) | The heavy count can be a batch job |
| [Ad click aggregation](../questions/ad-click-aggregation/) | Workers roll the click log |
| [Metrics monitoring](../questions/metrics-monitoring/) | Ingest workers write the series |
| [ChatGPT](../questions/chatgpt/) | A long generation should not hold the web worker |
| [One-time password](../questions/one-time-password/) | The send of the code can be a worker. The check stays in the request |
