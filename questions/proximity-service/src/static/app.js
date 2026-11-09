"use strict";

const $ = (selector) => document.querySelector(selector);
const postgis = ["postgis", "PostGIS", "PostgreSQL · GiST spatial index", "Prune candidates with the spatial index, then check the radius."];
const variants = document.body.dataset.page === "advanced" ? [
  postgis,
  ["quadtree", "Quadtree", "Search Service memory · four-way splits", "Build a tree from the catalog. Open only branches that can overlap the search."],
  ["kd-tree", "k-d tree", "Search Service memory · two-way splits", "Split points at the median along one axis at a time. Prune by branch bounds."],
  ["s2", "Google S2", "PostgreSQL · business_cell_keys", "Cover the circle with spherical cells and look up ranges of finer cell IDs."],
  ["h3", "H3", "PostgreSQL · business_cell_keys", "Look up every overlapping hexagonal cell at the stored resolution."],
] : [
  postgis,
  ["full-scan", "Full scan", "PostgreSQL · business rows", "Measure distance for every location. This is the reference result."],
  ["geohash", "Geohash", "PostgreSQL · cell key index", "Look up cells covering the circle, then check the exact distance."],
];

async function callApi(path, trace, {method = "GET", headers = {}, body} = {}) {
  const sent = {...headers};
  if (body !== undefined) sent["Content-Type"] = "application/json";
  const requestText = method + " " + path + "\n"
    + Object.entries(sent).map(([key, value]) => key + ": " + value + "\n").join("")
    + "Body: " + (body === undefined ? "none" : JSON.stringify(body, null, 2));
  trace.textContent = requestText + "\n\nWaiting for response…";
  const start = performance.now();
  try {
    const response = await fetch(path, {method, headers: sent, body: JSON.stringify(body)});
    const raw = await response.text();
    const json = response.headers.get("Content-Type")?.includes("application/json");
    const data = json ? JSON.parse(raw) : raw;
    trace.textContent = requestText + "\n\nHTTP " + response.status + " "
      + response.statusText + "\n" + (json ? JSON.stringify(data, null, 2) : raw);
    return {ok: response.ok, status: response.status, data, headers: response.headers,
      elapsed: Math.round(performance.now() - start)};
  } catch (error) {
    trace.textContent = requestText + "\n\nRequest failed: " + error.message;
    return {ok: false, status: 0};
  }
}

let profileVersion = 0;
async function showProfile(id) {
  const version = ++profileVersion;
  $("#profile").scrollIntoView({block: "nearest"});
  $("#profile-result").textContent = "Loading profile…";
  const reply = await callApi("/v1/businesses/" + encodeURIComponent(id), $("#profile-trace"));
  if (version !== profileVersion) return;
  if (reply.ok) {
    const {name, category, address} = reply.data;
    $("#profile-result").textContent = name + " · " + category + " · " + address;
  } else {
    $("#profile-result").textContent = "Profile request failed. See the API trace.";
    $("#profile-details").open = true;
  }
}

const cards = variants.map(([mode, title, store, description]) => {
  const card = $("#variant-template").content.firstElementChild.cloneNode(true);
  const next = card.querySelector(".next");
  card.dataset.mode = mode;
  card.querySelector("h3").textContent = title;
  card.querySelector(".badge").hidden = mode !== "postgis";
  card.querySelector(".store").textContent = store;
  card.querySelector(".description").textContent = description;
  $("#variants").append(card);
  let query;
  let cursor;
  let busy = false;

  async function run(params, continuation) {
    busy = true;
    next.disabled = true;
    const path = new URLSearchParams(params);
    if (continuation) path.set("cursor", continuation);
    card.querySelector(".metrics").textContent = "Searching…";
    const reply = await callApi("/v1/nearby?" + path, card.querySelector(".trace"), {
      headers: {"X-Lab-Search-Mode": mode},
    });
    const list = card.querySelector(".results");
    list.replaceChildren();
    query = params;
    cursor = reply.ok ? reply.data.nextCursor : null;
    if (reply.ok) {
      const cells = reply.headers.get("X-Lab-Cell-Count");
      const diagnostics = reply.data.diagnostics;
      const cellLabel = mode === "s2" ? " cell ranges" : " cell keys";
      card.querySelector(".metrics").textContent = reply.data.businesses.length + " matches on this page · "
        + reply.elapsed + " ms" + (cells ? " · " + cells + cellLabel : "");
      if (diagnostics?.nodesVisited !== undefined) {
        const {pointsLoaded, nodesVisited, candidateCount} = diagnostics;
        card.querySelector(".metrics").textContent += " · " + nodesVisited + " nodes visited · "
          + candidateCount + " candidates from " + pointsLoaded + " points loaded";
      }
      if (diagnostics?.fallback) {
        card.querySelector(".metrics").textContent += " · Fallback: " + diagnostics.fallback;
      }
      for (const business of reply.data.businesses) {
        const row = document.createElement("li");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "result-link";
        button.textContent = business.name;
        button.addEventListener("click", () => showProfile(business.businessId));
        const distance = document.createElement("span");
        distance.textContent = Math.round(business.distanceMeters) + " m";
        row.append(button, distance);
        list.append(row);
      }
    } else {
      card.querySelector(".metrics").textContent = "Search failed. See the API trace.";
      card.querySelector("details").open = true;
    }
    busy = false;
    next.disabled = !cursor;
  }

  next.addEventListener("click", () => {
    if (!busy && cursor) run(query, cursor);
  });
  return {run, get busy() { return busy; }};
});

$("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (cards.some((card) => card.busy)) return;
  const form = new FormData(event.currentTarget);
  $("#compare").disabled = true;
  try {
    await Promise.all(cards.map((card) => card.run(form)));
  } finally {
    $("#compare").disabled = false;
  }
});

function bindRegistration(businessForm) {
  const storageKey = "proximity-study-submission";
  let submission;
  let sending = false;
  try {
    submission = JSON.parse(localStorage.getItem(storageKey));
  } catch {
    submission = null;
  }

  function refreshKey() {
    $("#active-key").textContent = submission?.key ?? "Generated on submit";
    $("#retry").disabled = sending || !submission;
  }
  if (submission?.body) {
    for (const [key, value] of Object.entries(submission.body)) {
      const field = businessForm.elements.namedItem(key);
      if (field) field.value = value;
    }
  }
  refreshKey();

  async function sendBusiness(body, simulateLoss = false) {
    if (sending) return;
    if (!submission) {
      submission = {key: crypto.randomUUID(), body};
      localStorage.setItem(storageKey, JSON.stringify(submission));
    }
    sending = true;
    businessForm.querySelector("[type=submit]").disabled = true;
    $("#new-key").disabled = true;
    refreshKey();
    const headers = {"Authorization": "Bearer lab-owner-lee", "Idempotency-Key": submission.key};
    if (simulateLoss) headers["X-Lab-Lose-Response"] = "true";
    try {
      const reply = await callApi("/v1/businesses", $("#business-trace"), {method: "POST", headers, body});
      $("#business-details").open = true;
      $("#business-status").textContent = reply.ok
        ? "Saved business " + reply.data.businessId
        : "Registration returned " + (reply.status || "a network error") + ". See the API trace.";
    } finally {
      sending = false;
      businessForm.querySelector("[type=submit]").disabled = false;
      $("#new-key").disabled = false;
      refreshKey();
    }
  }

  businessForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(businessForm));
    body.latitude = Number(body.latitude);
    body.longitude = Number(body.longitude);
    const simulateLoss = $("#simulate-loss").checked;
    $("#simulate-loss").checked = false;
    sendBusiness(body, simulateLoss);
  });
  $("#retry").addEventListener("click", () => sendBusiness(submission.body));
  $("#new-key").addEventListener("click", () => {
    submission = null;
    localStorage.removeItem(storageKey);
    $("#business-status").textContent = "The next registration will get a new key.";
    refreshKey();
  });
}

const businessForm = $("#business-form");
if (businessForm) bindRegistration(businessForm);

async function fixtures(method) {
  const buttons = [$("#load-fixtures"), $("#reset-fixtures")];
  buttons.forEach((button) => { button.disabled = true; });
  const reply = await callApi("/lab/fixtures", $("#fixture-trace"), {method});
  $("#fixture-status").textContent = reply.ok
    ? (method === "POST" ? "Examples added: " + reply.data.inserted : "Examples removed: " + reply.data.removed)
    : "Could not change example data. See the API trace.";
  buttons.forEach((button) => { button.disabled = false; });
}
$("#load-fixtures").addEventListener("click", () => fixtures("POST"));
$("#reset-fixtures").addEventListener("click", () => fixtures("DELETE"));

function renderRows(container, rows, keyFor, labelFor) {
  const prior = new Map(Array.from(container.children, (row) => [row.dataset.key, row]));
  for (const record of rows) {
    const key = keyFor(record);
    const existing = prior.get(key);
    const row = existing ?? document.createElement("details");
    row.dataset.key = key;
    row.classList.toggle("fresh", !existing);
    if (!existing) row.append(document.createElement("summary"), document.createElement("pre"));
    row.querySelector("summary").textContent = labelFor(record);
    row.querySelector("pre").textContent = JSON.stringify(record, null, 2);
    container.append(row);
    prior.delete(key);
  }
  prior.forEach((row) => row.remove());
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "No rows";
    container.replaceChildren(empty);
  }
}

$("#inspect")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  const reply = await callApi("/lab/state", $("#store-trace"));
  if (reply.ok) {
    renderRows($("#catalog-rows"), reply.data.businesses, (row) => row.business_id, (row) => row.name);
    renderRows($("#request-rows"), reply.data.creation_requests,
      (row) => row.owner_id + ":" + row.idempotency_key, (row) => row.owner_id + " · " + row.idempotency_key);
  }
  button.disabled = false;
});

$("#inspect-cells")?.addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    const reply = await callApi("/lab/cells", $("#cell-trace"));
    if (!reply.ok) {
      $("#cell-status").textContent = "Could not load the cell table. See the API trace.";
      return;
    }
    $("#cell-status").textContent = reply.data.totals.map(({method, total}) =>
      method.toUpperCase() + ": " + total + " keys"
    ).join(" · ") || "No indexed businesses yet.";
    renderRows($("#s2-rows"), reply.data.rows.filter((row) => row.method === "s2"),
      (row) => row.business_id, (row) => row.name + " · " + row.cell_id);
    renderRows($("#h3-rows"), reply.data.rows.filter((row) => row.method === "h3"),
      (row) => row.business_id, (row) => row.name + " · " + row.cell_id);
  } finally {
    button.disabled = false;
  }
});
