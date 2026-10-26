# High-level design comparison — Search Autocomplete

For the next study pass. The interview path stays in [README.md](README.md). Hello Interview has no problem breakdown for this question, so that column is empty on purpose.

## Database choice

| Data | Hello Interview | Alex Xu Vol 1 Ch 13 | This session | Production |
| --- | --- | --- | --- | --- |
| Finished search | not in that source | A frequency table built from query logs | Postgres `searches`, one row per Enter | not in that source. Facebook's typeahead indexes people and pages, not past search strings |
| Counts | not in that source | Aggregated frequency, then a rebuild | The daily builder computes frequency from `searches` | The global leaf ranks pages by recent interaction, not by a search log |
| Prefix to top results | not in that source | An in-memory trie. Each node keeps the top results | Postgres `suggestions`, loaded into memory on the query service | Leaf indexes. The global leaf caches answers in memcached |

## High-level design choice

| | Hello Interview | Alex Xu Vol 1 Ch 13 | This session | Production |
| --- | --- | --- | --- | --- |
| Boxes | not in that source | Data gathering, and a query service | Client, load balancer, gateway, query service, daily builder, Postgres | Browser, load balancer, web tier, a stateless aggregator, leaf services |
| When the count changes the list | not in that source | The first sketch updates as queries arrive. The chapter then rebuilds offline, because a live update does not scale | Enter appends a row now. The list changes at the next daily load | Leaf indexes are their own pipeline. The request does not write them |

## Return the top suggestions

| | Steps | Store |
| --- | --- | --- |
| Hello Interview | not in that source | not in that source |
| Alex Xu Vol 1 Ch 13 | The query service finds the prefix in the trie and returns the top results stored on that node | In-memory trie |
| This session | Gateway to query service. Memory lookup of `ki`. Return the first 5 of 10 stored strings | In-memory copy of `suggestions` |
| Production | Aggregator asks leaf services. The global leaf can answer from memcached. The browser already holds the user's friends | Leaf index, memcached, browser cache |

Source: [The Life of a Typeahead Query](https://engineering.fb.com/2010/05/17/web/the-life-of-a-typeahead-query/), Engineering at Meta, 17 May 2010. That system searches people and pages. It is the closest public post. It is not a search-query autocomplete.

## Record a finished search

| | Steps | Store |
| --- | --- | --- |
| Hello Interview | not in that source | not in that source |
| Alex Xu Vol 1 Ch 13 | Gathering aggregates query logs. A later build refreshes the trie | Query logs, then the trie |
| This session | Gateway inserts one `searches` row and returns 202. The daily builder replaces `suggestions` | Postgres |
| Production | not the same product. A search-string log is not described in the 2010 post | not in that source |

## What this session keeps

The peak read is about 48,000 requests a second. The list must return in about 100 ms. Enter traffic is about 2,300 rows a second at the peak. The happy path is a daily snapshot in memory, with the log in Postgres. That is closest to the chapter's offline trie. The chapter rebuilds weekly. This session rebuilds daily. The trie shape itself is step 3. Here the snapshot is a prefix and a stored top 10.

## Sources

- Alex Xu, *System Design Interview*, Volume 1, chapter 13. Cited, not copied.
- Hello Interview has no problem breakdown for search autocomplete.
- Keith Adams, "The Life of a Typeahead Query," Engineering at Meta, 17 May 2010. https://engineering.fb.com/2010/05/17/web/the-life-of-a-typeahead-query/
