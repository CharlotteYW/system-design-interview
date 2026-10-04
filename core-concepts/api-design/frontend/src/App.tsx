import { gql, useLazyQuery, useMutation } from "@apollo/client";
import { useState } from "react";

const EVENTS = gql`
  query Upcoming($city: String, $status: String) {
    eventsQuery(city: $city, status: $status) {
      id
      name
    }
  }
`;

const BOOK_SEAT = gql`
  mutation BookSeat($eventId: Int!, $quantity: Int!, $idempotencyKey: String!) {
    bookSeat(eventId: $eventId, quantity: $quantity, idempotencyKey: $idempotencyKey) {
      code
      replayed
      bookingId
      quantity
    }
  }
`;

type Auth = { mode: string; token: string; session: string };

const emptyAuth: Auth = { mode: "", token: "", session: "" };

function authHeaders(auth: Auth): Record<string, string> {
  const headers: Record<string, string> = {};
  if (auth.mode === "jwt" && auth.token) headers.Authorization = `Bearer ${auth.token}`;
  if (auth.session) headers["X-Session"] = auth.session;
  return headers;
}

export function App() {
  const [auth, setAuth] = useState<Auth>(emptyAuth);

  return (
    <>
      <h1>API design</h1>
      <p>
        The interview default is one public REST API. This page also runs the other options.
        You are account 42. The page is React and TypeScript. GraphQL uses Apollo.
        REST uses fetch.
      </p>
      <RestQuery />
      <GraphqlEvents />
      <LoginPanel auth={auth} setAuth={setAuth} />
      <BookingPanel auth={auth} />
      <VersionPanel />
    </>
  );
}

function RestQuery() {
  const [city, setCity] = useState("NYC");
  const [status, setStatus] = useState("upcoming");
  const [sort, setSort] = useState("date");
  const [out, setOut] = useState("Ready.");

  async function load() {
    const params = new URLSearchParams();
    if (city) params.set("city", city);
    if (status) params.set("status", status);
    params.set("sort", sort);
    const url = `/v1/events?${params.toString()}`;
    const body = await (await fetch(url)).json();
    setOut(JSON.stringify({ url, body }, null, 2));
  }

  return (
    <section>
      <h2>REST query</h2>
      <p>The browser puts filters in the query string. This call has no JSON body.</p>
      <label>
        City
        <select value={city} onChange={(event) => setCity(event.target.value)}>
          <option value="">any</option>
          <option value="NYC">NYC</option>
          <option value="SF">SF</option>
        </select>
      </label>
      <label>
        Status
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="">any</option>
          <option value="upcoming">upcoming</option>
          <option value="past">past</option>
        </select>
      </label>
      <label>
        Sort
        <select value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="date">date</option>
          <option value="-date">-date</option>
        </select>
      </label>
      <button id="rest" type="button" onClick={() => void load()}>
        GET /v1/events
      </button>
      <pre>{out}</pre>
    </section>
  );
}

function GraphqlEvents() {
  const [runQuery, { loading: queryLoading }] = useLazyQuery(EVENTS);
  const [runBook, { loading: bookLoading }] = useMutation(BOOK_SEAT);
  const [steps, setSteps] = useState<string[]>([]);
  const [out, setOut] = useState("Click a button. The call chain appears above the result.");

  async function runRead() {
    const variables = { city: "NYC", status: "upcoming" };
    const result = await runQuery({ variables });
    setSteps([
      "The React button calls useLazyQuery in App.tsx.",
      "frontend/src/apollo.ts sets uri to /graphql. HttpLink defaults the method to POST.",
      `The JSON body carries the query text and variables ${JSON.stringify(variables)}.`,
      "FastAPI accepts that POST on the /graphql route.",
      "Strawberry exports Query.events_query as the GraphQL field eventsQuery.",
      'Strawberry calls events_query(city="NYC", status="upcoming").',
      "Event exports id, name, city, and status. The selection keeps id and name.",
    ]);
    setOut(JSON.stringify({ operation: "query", data: result.data }, null, 2));
  }

  async function runWrite() {
    const variables = { eventId: 1, quantity: 1, idempotencyKey: "gql-click-1" };
    const result = await runBook({ variables });
    setSteps([
      "The React button calls useMutation in App.tsx.",
      "HttpLink sends POST /graphql again. The method is the library default, and the URI comes from apollo.ts.",
      `The document starts with mutation. Variables are ${JSON.stringify(variables)}.`,
      "FastAPI accepts that POST on the /graphql route.",
      "Strawberry exports Mutation.book_seat as the GraphQL field bookSeat.",
      'Strawberry calls book_seat(event_id=1, quantity=1, idempotency_key="gql-click-1").',
      "The method writes through bookings.book for account 42.",
      "The selection keeps code, replayed, bookingId, and quantity.",
    ]);
    setOut(JSON.stringify({ operation: "mutation", data: result.data }, null, 2));
  }

  return (
    <section>
      <h2>GraphQL call chain</h2>
      <p>Apollo Client is the browser program. FastAPI and Strawberry are the server program. This is client-server.</p>
      <p>The two sides agree on the GraphQL schema. Strawberry builds that schema from the Python classes. Apollo sends the field names in the document. The server checks those names. A matching name runs the Python method. A wrong name returns an error.</p>
      <p>A query reads. A mutation writes. Both calls use POST /graphql.</p>
      <p>Strawberry turns a Python snake_case name into a GraphQL camelCase name. The document must use the camelCase name.</p>
      <table>
        <thead>
          <tr>
            <th>GraphQL name in App.tsx</th>
            <th>Python name in graphql_api.py</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>eventsQuery</td>
            <td>events_query</td>
          </tr>
          <tr>
            <td>city, status, id, name</td>
            <td>city, status, id, name</td>
          </tr>
          <tr>
            <td>bookSeat</td>
            <td>book_seat</td>
          </tr>
          <tr>
            <td>eventId</td>
            <td>event_id</td>
          </tr>
          <tr>
            <td>idempotencyKey</td>
            <td>idempotency_key</td>
          </tr>
          <tr>
            <td>bookingId</td>
            <td>booking_id</td>
          </tr>
          <tr>
            <td>code, replayed, quantity</td>
            <td>code, replayed, quantity</td>
          </tr>
          <tr>
            <td>Upcoming, BookSeat</td>
            <td>Operation names. No Python method.</td>
          </tr>
        </tbody>
      </table>
      <button id="gql" type="button" onClick={() => void runRead()}>
        Run the query
      </button>
      <button id="gql-write" type="button" onClick={() => void runWrite()}>
        Run the mutation
      </button>
      <ol>
        {steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <pre>{queryLoading || bookLoading ? "Loading." : out}</pre>
      <h3>Strawberry note</h3>
      <p>These three names build the schema. The class Query is the read root. The class Mutation is the write root.</p>
      <ul>
        <li>strawberry.type makes a class into a GraphQL type. Event, Query, Mutation, and BookingResult are types. A type is a named group of fields.</li>
        <li>strawberry.field makes a method into a field. events_query is a field on Query. The client calls it as eventsQuery.</li>
        <li>strawberry.mutation marks a write field. In this library the function calls field(). Schema(mutation=Mutation) places that class on the write root. book_seat is that write.</li>
      </ul>
      <p>Other backend libraries publish the same schema idea.</p>
      <ul>
        <li>graphql-ruby is the Ruby library. A field block and an argument match type and field here.</li>
        <li>Graphene is an older Python library. Classes become the schema, as they do in Strawberry.</li>
        <li>Ariadne is a Python library. You write the schema as text, then attach a Python resolver to each field.</li>
        <li>Apollo Server is a Node server. Apollo Client is the browser library. They are different packages.</li>
      </ul>
      <p>This lab uses Strawberry. The Python class is the schema.</p>
    </section>
  );
}

function LoginPanel({ auth, setAuth }: { auth: Auth; setAuth: (auth: Auth) => void }) {
  const [out, setOut] = useState("Not logged in.");

  async function login(mode: string) {
    const payload = { account_id: 42, mode, server: "a" };
    const response = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();
    setAuth({ mode, token: body.token || "", session: body.session_id || "" });
    setOut(JSON.stringify({ payload, body }, null, 2));
  }

  async function who(server: string) {
    const params = new URLSearchParams({ mode: auth.mode || "jwt", server });
    const response = await fetch(`/api/me?${params.toString()}`, { headers: authHeaders(auth) });
    setOut(JSON.stringify({ server, status: response.status, body: await response.json() }, null, 2));
  }

  async function logout() {
    const params = new URLSearchParams({ mode: auth.mode || "jwt", server: "a" });
    const response = await fetch(`/api/logout?${params.toString()}`, {
      method: "POST",
      headers: authHeaders(auth),
    });
    setOut(JSON.stringify(await response.json(), null, 2));
  }

  return (
    <section>
      <h2>Login</h2>
      <p>The login payload is JSON. FastAPI parses it into LoginBody. JWT needs no store. A memory session stays on server A. A Redis session works on server A and server B.</p>
      <button id="login-jwt" type="button" onClick={() => void login("jwt")}>Login with JWT</button>
      <button id="login-memory" type="button" onClick={() => void login("memory")}>Login on server A memory</button>
      <button id="login-redis" type="button" onClick={() => void login("redis")}>Login with Redis</button>
      <button type="button" onClick={() => void who("a")}>Who am I on A</button>
      <button type="button" onClick={() => void who("b")}>Who am I on B</button>
      <button type="button" onClick={() => void logout()}>Logout</button>
      <pre>{out}</pre>
    </section>
  );
}

function BookingPanel({ auth }: { auth: Auth }) {
  const [quantity, setQuantity] = useState("1");
  const [key, setKey] = useState("click-1");
  const [out, setOut] = useState("Ready.");

  async function book(count: number, idempotencyKey: string) {
    const payload = { quantity: count };
    const params = new URLSearchParams({ mode: auth.mode || "jwt", server: "a" });
    const url = `/v1/events/1/bookings?${params.toString()}`;
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
        ...authHeaders(auth),
      },
      body: JSON.stringify(payload),
    });
    setOut(
      JSON.stringify(
        {
          method: "POST",
          url,
          payload,
          header: { "Idempotency-Key": idempotencyKey },
          status: response.status,
          body: await response.json(),
        },
        null,
        2,
      ),
    );
  }

  return (
    <section>
      <h2>Book a seat</h2>
      <p>This POST has a query string and a JSON body. The result prints the full URL, then the body. FastAPI parses the body into BookBody. The API calls inventory with gRPC.</p>
      <label>
        Quantity <input value={quantity} onChange={(event) => setQuantity(event.target.value)} />
      </label>
      <label>
        Key <input value={key} onChange={(event) => setKey(event.target.value)} />
      </label>
      <button id="book" type="button" onClick={() => void book(Number(quantity || "1"), key)}>
        POST /v1/events/1/bookings
      </button>
      <button type="button" onClick={() => void book(9, "click-too-many")}>
        Ask for 9 seats
      </button>
      <pre>{out}</pre>
    </section>
  );
}

function VersionPanel() {
  const [out, setOut] = useState("Ready.");

  async function load(path: string) {
    const body = await (await fetch(`${path}?city=NYC&status=upcoming&sort=date`)).json();
    setOut(JSON.stringify({ url: path, event: body.events[0] }, null, 2));
  }

  return (
    <section>
      <h2>Version</h2>
      <p>v1 uses name. v2 uses title. Both calls enter the same API process.</p>
      <button type="button" onClick={() => void load("/v1/events")}>GET /v1/events</button>
      <button id="v2" type="button" onClick={() => void load("/v2/events")}>GET /v2/events</button>
      <pre>{out}</pre>
    </section>
  );
}
