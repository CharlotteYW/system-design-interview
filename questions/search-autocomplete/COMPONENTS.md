# Components — Search Autocomplete

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Kim's browser | Waits 0.5 s after the last key. Skips `GET` when the cached shorter prefix still has 5 matches. Calls `POST /v1/searches` on Enter |
| Load balancer | Spreads calls across gateway machines | A suggestion call can land on any machine. No session stickiness |
| API gateway | The HTTP front | Routes `GET` to the query service. Appends `POST` to `searches` |
| Query service | The read path | Loads `suggestions` and builds a trie from the same rows. A request can use the map or the trie. Either way it returns a stored list and does not sort |
| Daily builder | The write path for the snapshot | Once a day, counts `searches` and publishes a new `suggestions` set |
| Postgres `searches` | The durable log | One row per finished search. About 2,300 inserts a second at the peak |
| Postgres `suggestions` | The published snapshot | Prefix, position, text, frequency. Query machines load it. A `GET` does not read it |

## Why these pieces

- The read is about 48,000 requests a second. The sort cannot run on that path.
- The log is about 2,300 rows a second at the peak. One table can append them.
- A failed build leaves yesterday's snapshot in place, so the dropdown stays up.
- A queue is not on this path. The log is the buffer. The builder reads it once a day.
- Redis, a trie layout, and a last-hour weight are later. The builder is where the weight would be added.
