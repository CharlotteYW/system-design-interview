# FAQ — Key-Value Store

Practice these out loud. Add questions you actually got stuck on. Same five steps as the README.

## 1. Requirements and design scope

**Q: What are the must-have functional requirements?**  
A: TBD

**Q: What scale numbers would you use, and why?**  
A: TBD

**Q: What would you explicitly cut from a 45-minute interview?**  
A: TBD

## 2. High-level design

**Q: Walk through a write and a read at a high level.**  
A: TBD

**Q: Why these major boxes and not fewer/more?**  
A: TBD

## 3. Low-level design and deep dive

**Q: On a put, do we write memory first, and do we delete the WAL once two servers acknowledge?**  
A: No. Each replica appends its own write-ahead log and updates its memtable, and it acknowledges only after that log is on disk. The coordinator’s “2 of 3” does not delete anyone’s log. A replica deletes a log segment only after the memtable that held those keys has been flushed to an SSTable on that same replica. Until then the log is the only durable copy of data that still lives in RAM.

**Q: Ack after the WAL, delete the WAL only after the SSTable flush, so a successful reply is never lost? And a disagreement returns the later version?**  
A: Yes. A replica’s own success means the key, value, and version are in its write-ahead log on disk, so a process crash replays them. The log segment is removed only after those keys are in an SSTable on that replica. The client’s success still requires two replicas to have reached that point. If two copies differ, get returns the one with the later version.

**Q: What actually stores the key, value, and version? An LSM tree, or Postgres?**  
A: An LSM tree on each of the three replicas. The memtable and the SSTables are the store, sorted by key. Postgres is not sitting behind them. A single cluster-wide Postgres was the option we passed on at 20,000 puts/s.

**Q: Why not Postgres, and what does Alex Xu use?**  
A: Alex Xu Vol 1 Ch 6 follows the Dynamo / Cassandra write path: a commit log, an in-memory table, then an SSTable. That is an LSM. Postgres on each node could hold a few thousand simple writes per second, and it is still a B-tree leaf update per put. This interview stays with the book’s path.

**Q: Does Hello Interview have this same chapter?**  
A: The guided breakdown is [Distributed Cache](https://www.hellointerview.com/learn/system-design/problem-breakdowns/distributed-cache), a Redis-like store. Same key API and the same ring. Data lives in RAM, expires, and can be evicted. Durability is out of scope there. The durable LSM store is Alex Xu Vol 1 Ch 6. Hello Interview also lists “Design a Key-Value Store” as a reported interview question; that prompt is not the cache chapter.

**Q: Do we pick an LSM because one server must do 20,000 operations per second, which Postgres cannot?**  
A: 20,000 puts/s is the whole cluster, not one box. One Postgres primary would see every put, and that is the design that loses. After the ring, each put is written three times (60,000 replica-writes/s). On about 15 servers that is roughly 4,000 writes/s on one machine, which a tuned Postgres can do. We still use an LSM there: each put is a random key, and the LSM appends a log instead of updating a random B-tree leaf. Alex Xu Vol 1 Ch 6 is that path.

**Q: If each replica used Postgres instead of an LSM, is that three databases and overkill? Would gets be faster?**  
A: The three copies do not change. About 15 servers each run one engine, and each key is stored on three of them. Putting Postgres on every server is a full SQL stack for a single primary-key table: connections, planning, vacuum. A settled get is often one B-tree descent, so it can be cheaper than an LSM read that still checks several SSTables. At about 10,000 gets/s per server both are under the 20 ms budget, and the coordinator already waits for two replicas. This interview keeps the LSM.

**Q: Where is the bottleneck as traffic grows?**  
A: Replica reads. A get touches two owners. At 800,000 gets/s that is about 1.6 million replica reads/s. Coordinators only hash and fan out. The ring servers that store the keys are the limit.

## 4. Component questions and special situations

**Q: What fails if a replica is slow, and how do you recover?**  
A: Send to all three at once and finish when two reply. Timeout the slow one for this call only. Do not drop it from the ring after one miss. A failure detector removes it after repeated timeouts, and the next server on the ring takes its arc. Two timeouts and the call returns an error, because one copy is not a quorum.

**Q: What would you change for 10× gets, with puts unchanged?**  
A: Add ring servers so each box’s read share falls. Coordinator duty rides along, because any server can coordinate. Keep 2-of-3, three copies, and the LSM. A coordinator-only tier does not serve the bytes.

**Q: How do you handle a hot key? Does adding servers spread it?**  
A: No. One key still has one preference list of three. Cache that key on the get path. At 40,000 gets/s, one Redis entry is enough if the put deletes or replaces the entry. At 400,000 gets/s of the same key, copy the value into many app-local caches. One Redis, like one replica, tops out near 100,000 simple ops/s.

**Q: If the whole region is unreachable, does 2-of-3 keep the store up?**  
A: No. The three copies are in that region. The client gets errors for put and get. 2-of-3 is the one-replica failure. A second region is a later design, and a cross-region quorum is too slow for a 20 ms p99.

**Q: Can any server be the coordinator? Do we need a gateway that hashes the key onto the ring? How is the coordinator chosen? Is the hot-key cache an L1 inside each server?**  
A: Any server can coordinate. A load balancer sends the HTTP call to a healthy server round-robin, without looking at the key. That server hashes the key and contacts the three replicas. It does not have to be one of them. A gateway that hashes first and forwards only to the owners piles a hot key onto those three machines. At 400,000 gets/s of one key, each API server keeps a small L1 map of key to value and version. The first get on that process reads two replicas once. Later gets on that process are served from the map. A put drops the map entry. The L1 map is not the LSM memtable.

**Q: On put, does the load balancer pick a coordinator, that server hash the key onto the ring, and the pair get stored on those three servers?**  
A: Yes. The load balancer picks any healthy server and ignores the key. That server hashes the key, finds the owner and the next two clockwise, and sends `(key, value, version)` to those three. Each one appends its own log and replies after the log is on disk. The client gets success when two have replied. The third copy can finish after the response. The coordinator keeps a durable copy only when it is one of those three.

**Q: At high traffic, does the load balancer become a hotspot?**  
A: Not at the rates in this design. It forwards each client call once and does not hash the key or fan out to replicas. 800,000 gets/s of a 1 KB value is about 6.4 Gbps, which fits one 10 Gbps balancer. The L1 cache saves the replicas and still sends every response back through the balancer. Past that bandwidth, DNS round-robin in front of several balancers splits the pipe. A client that already knows the ring can skip the balancer.

**Q: After a put, why do other servers still return the old L1 value, and what do TTL, broadcast, and reading the replicas each do?**  
A: Each server’s L1 is a private copy. A put writes the new version to the replicas. The coordinator sets its own L1 to that new version, and each replica that applied the write does the same in its own process. Any other server keeps the previous L1 until the one-second TTL. A broadcast would clear those too and costs one message per server per put. Reading two replicas on every get returns the newer version and puts the 400,000 gets/s back on those replicas. This design uses the one-second TTL for servers that did not see the write. The quorum on disk remains the durable copy.

**Q: On get, does the coordinator answer from its own L1 without hashing? Do only the three replicas hold that map? On a hit, is there no quorum, so only one server is read?**  
A: The server that accepted the get looks in its own L1. Any server can hold that entry, including one that does not own the key. A hit returns the cached value and version. The ring is not consulted and the other replicas are not read, so this get is one server, the coordinator, until the TTL expires. A miss hashes the key, reads two of the three owners, stores the newer value in this coordinator’s map, and returns it. The L1 exists so the steady gets of a hot key skip that pair of replica reads. A put still always hashes and writes the three owners.

**Q: Do hot-key gets stop at the coordinator, while put and delete always use the ring? On a put, do B, C, and D drop their maps, while coordinator A keeps its old entry until the TTL?**  
A: Steady gets of a hot key stop at whichever coordinator accepted them. That is the hot-key lever. Uniform 10× traffic, every key busier, is more servers on the ring. Put and delete always hash and write the three owners. The coordinator that handled the put updates its own L1 to the new version immediately, including when that coordinator is A. Each of B, C, and D updates its own L1 when it applies the write. A server that neither coordinated nor stored the write keeps the old L1 until the TTL.

**Q: On a put coordinated by A, with owners B, C, and D, do A, B, C, and D update their L1 maps, while E does not?**  
A: Yes. A updates because it coordinated the successful put. B, C, and D update when each applies the write in its own process. The third replica may apply after the client already received success, and its map changes at that moment. E keeps the previous value until the one-second TTL.

## 5. Summary and future improvements

**Q: What did we design, what risk did we leave, and what would you add later?**  
A: Put and delete go load balancer, then coordinator, then the three ring owners, and succeed after two logs. The coordinator and those owners update their L1. A get returns from the coordinator’s L1 on a hit, and otherwise reads two owners and fills that L1. Delete writes a tombstone. The risk called out first is a stale get for about one second on a server that missed the write. A later addition is an optional expiry on the key itself.

Taught: the path is right. Success is two of three owners, and the third can still be applying. Delete is a tombstone with a newer version, so a late replica cannot restore the key by copying an empty value. The one-second stale read is the risk users hit during normal updates. The region outage is the other risk we accepted: every copy is in that one region. A durable per-key expiry is worth adding later. It is replicated like the value. It is a different timer from the L1. This interview leaves it out, because a successful put stays until an explicit delete.

## Local system

**Q: What did the simplified implementation teach you that the diagram did not?**  
A: Five servers live in one process. A put from the page names the coordinator, the three owners, and which L1 maps moved to the new version. A second get on that same server is a hit and reads no replica. A server left out of the put keeps the old value until the one-second TTL. Two owners down returns an error. The third replica lag, a real network, and per-key expiry are not running.

**2026-09-29.** Lab tested in the browser. No further questions. Stack stopped.
