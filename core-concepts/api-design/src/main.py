from pathlib import Path

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import auth, bookings
from src.catalog import filter_events, for_version
from src.errors import ApiError
from src.graphql_api import router as graphql_router

app = FastAPI()
app.include_router(graphql_router, prefix="/graphql")
STATIC = Path(__file__).resolve().parent / "static"


class LoginBody(BaseModel):
    account_id: int
    mode: str
    server: str = "a"


class BookBody(BaseModel):
    quantity: int


@app.exception_handler(ApiError)
def api_error(_request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content=exc.body())


@app.exception_handler(RequestValidationError)
def bad_body(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "BAD_REQUEST", "message": "The request body is not valid"}},
    )


@app.get("/healthz")
def healthz() -> dict:
    auth.client().ping()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/reset")
def reset() -> dict:
    bookings.reset()
    auth.reset()
    return {"ok": True}


@app.get("/{version}/events")
def list_events(
    version: str,
    city: str | None = None,
    status: str | None = None,
    sort: str | None = None,
) -> dict:
    rows = filter_events(city, status, sort)
    return {
        "version": version,
        "received_query": {"city": city, "status": status, "sort": sort},
        "events": [for_version(row, version) for row in rows],
    }


@app.post("/api/login")
def login(body: LoginBody) -> dict:
    return auth.login(body.account_id, body.mode, body.server)


@app.get("/api/me")
def me(
    mode: str,
    server: str = "a",
    authorization: str | None = Header(default=None),
    x_session: str | None = Header(default=None),
) -> dict:
    return auth.who(mode, server, authorization, x_session)


@app.post("/api/logout")
def logout(
    mode: str,
    server: str = "a",
    x_session: str | None = Header(default=None),
) -> dict:
    return auth.logout(mode, server, x_session)


@app.post("/v1/events/{event_id}/bookings")
def create_booking(
    event_id: int,
    body: BookBody,
    mode: str = Query(...),
    server: str = "a",
    authorization: str | None = Header(default=None),
    x_session: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
) -> JSONResponse:
    caller = auth.who(mode, server, authorization, x_session)
    status, payload = bookings.book(caller["account_id"], event_id, body.quantity, idempotency_key or "")
    return JSONResponse(status_code=status, content=payload)


if (STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")
