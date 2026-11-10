const byId = (id) => document.getElementById(id);
const centers = new Map([["sf-ca", [37.762, -122.423]]]);
const keys = new Map();
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(path, store, options = {}) {
  const {method = "GET", headers = {}, body} = options;
  const response = await fetch(path, {method, headers, body: body && JSON.stringify(body)});
  const raw = await response.text();
  let result;
  try { result = JSON.parse(raw); } catch { result = raw; }
  const details = document.createElement("details");
  details.open = true;
  const summary = document.createElement("summary");
  summary.textContent = `${method} ${path} · ${response.status} · ${store}`;
  const pre = document.createElement("pre");
  pre.textContent = JSON.stringify({
    request: {method, path, headers, body: body ?? null},
    response: {status: response.status, cache: response.headers.get("X-Study-Cache"), body: result},
  }, null, 2);
  details.append(summary, pre);
  const log = byId("http-log");
  if (log.firstElementChild) log.firstElementChild.open = false;
  log.prepend(details);
  if (log.children.length > 12) log.lastElementChild.remove();
  if (!response.ok) {
    const error = new Error(result?.errorCode || `HTTP ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return {result, cache: response.headers.get("X-Study-Cache")};
}

function list(target, rows, draw, next) {
  const ul = document.createElement("ul");
  for (const row of rows) {
    const li = document.createElement("li");
    draw(li, row);
    ul.append(li);
  }
  target.replaceChildren();
  if (rows.length) target.append(ul);
  else target.textContent = "No matches.";
  if (next) {
    const button = document.createElement("button");
    button.textContent = "Next page";
    button.onclick = next;
    target.append(button);
  }
}

async function findPlace() {
  const name = byId("place-name").value.trim();
  if (!name) return;
  const {result} = await request(`/v1/places?${new URLSearchParams({name})}`, "PostgreSQL places");
  const select = byId("place");
  select.replaceChildren();
  for (const place of result.places) {
    centers.set(place.placeId, [place.centerLat, place.centerLon]);
    select.add(new Option(`${place.name} · ${place.region}`, place.placeId));
  }
  byId("place-status").textContent = result.places.length ? "Select a place to search." : "No matching places.";
}

async function search(mode, previous = null) {
  const target = byId(`${mode}-results`);
  try {
    const placeId = byId("place").value;
    if (!placeId && !previous) throw new Error("Select a place first.");
    const params = previous || new URLSearchParams({
      name: byId("name").value.trim(), category: byId("category").value,
      nameMode: byId("name-mode").value, cacheMode: byId("cache-mode").value,
    });
    if (!previous && mode === "radius") {
      const [lat, lon] = centers.get(placeId);
      params.set("lat", lat);
      params.set("lon", lon);
      params.set("radiusM", byId("radius").value);
    } else if (!previous) {
      params.set("placeId", placeId);
      params.set("areaMode", mode);
    }
    const store = mode === "membership" ? "PostgreSQL business_places" : "PostgreSQL + PostGIS";
    const {result, cache} = await request(`/v1/businesses/search?${params}`, store);
    const next = result.nextCursor && new URLSearchParams(params);
    if (next) next.set("cursor", result.nextCursor);
    list(target, result.businesses, (li, business) => {
      const button = document.createElement("button");
      button.className = "link";
      button.textContent = business.name;
      button.onclick = () => {
        byId("business-id").value = business.businessId;
        openBusiness();
      };
      const rating = business.averageRating == null ? "No ratings" : `${business.averageRating.toFixed(1)} ★`;
      li.append(button, ` · ${Math.round(business.distanceM)} m · ${rating} (${business.reviewCount})`);
    }, next && (() => search(mode, next)));
    if (cache && cache !== "off") target.append(`Cache: ${cache}`);
  } catch (error) { target.textContent = error.message; }
}

function drawReview(li, review) {
  li.textContent = `${review.businessName ? review.businessName + " · " : ""}${review.rating} ★ · ${review.text || "Rating only"}`;
}

async function loadReviews(path, target, headers, cursor = null) {
  try {
    const query = cursor ? `?${new URLSearchParams({cursor})}` : "";
    const {result} = await request(path + query, "PostgreSQL reviews", {headers});
    list(target, result.reviews, drawReview, result.nextCursor && (() => loadReviews(path, target, headers, result.nextCursor)));
  } catch (error) { target.textContent = error.message; }
}

async function openBusiness() {
  const path = `/v1/businesses/${encodeURIComponent(byId("business-id").value.trim())}`;
  await Promise.all([
    request(path, "PostgreSQL businesses").then(({result}) => {
      byId("profile").textContent = `${result.name} · ${result.address}`;
    }).catch((error) => { byId("profile").textContent = error.message; }),
    loadReviews(path + "/reviews", byId("public-reviews"), {}),
  ]);
}

async function submit(button) {
  const variant = button.dataset.submit;
  const mode = variant === "queued" && byId("batch-rating").checked ? "queued-batch" : variant;
  const status = byId(`${variant}-status`);
  const user = byId("user").value;
  const business = byId("business-id").value.trim();
  const body = {rating: Number(byId("rating").value), text: byId("review-text").value || null};
  const signature = JSON.stringify([user, business, mode, body]);
  if (!keys.has(signature)) keys.set(signature, crypto.randomUUID());
  const headers = {"X-Demo-User": user, "Idempotency-Key": keys.get(signature), "Content-Type": "application/json"};
  button.disabled = true;
  status.textContent = "";
  try {
    const path = `/v1/businesses/${encodeURIComponent(business)}/reviews?mode=${mode}`;
    const {result} = await request(path, mode === "direct" ? "PostgreSQL reviews + rating totals" : "PostgreSQL review_submissions",
                                   {method: "POST", headers, body});
    if (result.submissionId) {
      status.textContent = `Pending · ${result.submissionId}`;
      for (let attempt = 0; attempt < 12; attempt++) {
        await sleep(650);
        let job;
        try {
          ({result: job} = await request(`/v1/review-submissions/${result.submissionId}`,
                                        "PostgreSQL review_submissions", {headers: {"X-Demo-User": user}}));
        } catch (error) {
          if (error.status !== 503) throw error;
          status.textContent = `Status temporarily unavailable · ${result.submissionId}`;
          continue;
        }
        status.textContent = `Pending · ${result.submissionId}`;
        if (job.status !== "pending") {
          status.textContent = job.status === "saved" ? `Saved · ${job.reviewId}` : `Failed · ${job.errorCode}`;
          return;
        }
      }
      status.textContent = `Still pending · ${result.submissionId}. Select Queue review again to check with the same key.`;
    } else {
      status.textContent = `Saved · ${result.reviewId}`;
    }
  } catch (error) {
    status.textContent += ` ${error.message}`;
  } finally {
    button.disabled = false;
  }
}

byId("find-place").onclick = () => findPlace().catch((error) => { byId("place-status").textContent = error.message; });
byId("open-business").onclick = openBusiness;
byId("my-reviews").onclick = () => loadReviews("/v1/me/reviews", byId("own-reviews"), {"X-Demo-User": byId("user").value});
document.querySelectorAll("[data-search]").forEach((button) => { button.onclick = () => search(button.dataset.search); });
document.querySelectorAll("[data-submit]").forEach((button) => { button.onclick = () => submit(button); });
