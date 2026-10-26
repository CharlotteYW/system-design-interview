# Proximity

**Source:** [Hello Interview: Common Patterns](https://www.hellointerview.com/learn/system-design/in-a-hurry/patterns) (section "Proximity-Based Services") and the deep dive [Proximity Search](https://www.hellointerview.com/learn/system-design/deep-dives/proximity-search). This is the eighth pattern on that page. The [blog list of seven](https://www.hellointerview.com/blog/patterns) does not include it.

**Proximity** means "which items are near this point." A normal index cannot answer that well. A B-tree sorts one column. Sort by latitude and you get a horizontal strip of the earth, not a circle around the rider.

## The problem

Kim requests a ride at one street corner. The service must find drivers within about 2 km. A scan of every driver on earth is too slow. A scan of 1,000 drivers in one city is fine.

The same shape is "friends near me," "restaurants in this neighborhood," and "which map tile is this."

Most queries are local. Kim does not search the whole planet. She searches around herself.

## Options

- **Option A: Scan the candidates you already narrowed.** Load the drivers in one city and compute the distance. Cost: the city must stay small. Hello Interview puts the break at about 1,000 items. Wins for a lab and for a small city.
- **Option B: Encode each point as one sortable key.** A **geohash** turns latitude and longitude into one string. Nearby points usually share a prefix. Redis GEO stores that key and returns a candidate box. You then drop the points outside the real circle. Cost: the box is square, so you over-fetch, and a point on a cell edge can sit next to a point with a different prefix. Wins for points that move, such as drivers and phones.
- **Option C: A spatial tree.** PostGIS and Elasticsearch keep a tree that understands shapes. Cost: more machinery, and a moving driver rewrites the tree often. Wins for polygons, roads, and delivery zones. A restaurant is a point. A delivery zone is a polygon.

We pick A under about 1,000 items. We pick B for drivers and phones. We pick C when the query is "inside this zone" or "along this road." The index returns candidates. The exact distance check is always a second pass.

## What an interviewer probes

- Drivers move. Writing a new location every second for a million drivers is a write problem as well as a geo problem. Keep the latest point in Redis. Do not update a Postgres row every second.
- The cell edge. Two drivers 10 m apart can fall in different geohash cells. Search the neighbor cells too, then filter by real distance.
- "Near me" is not "best." Yelp still has to rank the candidates by rating and by the word the user typed. The geo index only builds the candidate set.

## Questions

| Question | What is near the user |
| --- | --- |
| [Proximity service](../questions/proximity-service/) | The index itself. Volume 2 starts here |
| [Uber](../questions/uber/) | A driver near the rider. Points that move, so Option B |
| [Nearby friends](../questions/nearby-friends/) | A friend inside a radius |
| [Yelp](../questions/yelp/) | A business in the neighborhood, then a text rank |
| [Tinder](../questions/tinder/) | A person within a chosen distance |
| [Google Maps](../questions/google-maps/) | Tiles and roads. Shapes, so Option C is in play |
| [Local delivery](../questions/local-delivery/) | A courier near the pickup, inside a zone |
| [Strava](../questions/strava/) | A segment near the athlete |

| Question | How it also uses a location |
| --- | --- |
| [Food review](../questions/food-review/) | Reviews of a place. The place is the Yelp problem |
