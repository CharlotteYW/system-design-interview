# Components — Key-Value Store

Pieces we actually name. A cluster-wide primary database, a queue, and a CDN are outside this design. A cache sits on the get path only for a hot key. It is not the durable copy.

| Component | Definition | Functionality in this design |
| --- | --- | --- |
| Client | Caller of put, get, delete | Sends the key. Does not choose the three replicas or the coordinator |
| Load balancer | Round-robin across healthy servers | Picks who accepts the HTTP call. Does not hash the key |
| Coordinator | The server that accepted this call | Hashes the key, writes and reads 2 of 3, returns the newer version. Any server can do this |
| L1 cache | A map inside each server that accepts calls | Hot-key gets. A hit returns from this process. A miss reads two replicas and fills this map. A put sets the new version on the coordinator and on each replica that applied the write. Other servers keep the old entry until the TTL |
| Replica | One server on the preference list | Appends a write-ahead log, keeps a memtable, flushes SSTables. Holds its own slice plus copies of its neighbors |
| Ring | Consistent hash of keys and servers | Preference list is the owner and the next two clockwise. Adding a server moves one arc |
| Tombstone | A replicated delete record | Newer than the value it removes. Stops a late replica from restoring the key |
| Shared cache | One Redis | Optional at about 40,000 gets/s of one key. One box, so it does not cover 400,000 gets/s |

## Why these pieces

- The coordinator is whoever accepted the call. Losing one does not lose keys, and the next call is hashed again on whichever server receives it.
- The durable copy is the write-ahead log on two replicas, not the memtable.
- Repair after a new server joins is a stream of the moved arc, then a background compare of what both sides have.
- The cache is a copy of one hot key. Losing it sends gets back to the three replicas. It does not replace a missing region.
