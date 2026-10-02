"""OTP API. Generate returns 202 after the hash is stored. Verify returns 200 only after the delete."""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src import otp

app = FastAPI(title="One-time password")


class GenerateIn(BaseModel):
    destination: str
    channel: str
    purpose: str


class VerifyIn(BaseModel):
    destination: str
    purpose: str
    code: str


class FlagIn(BaseModel):
    down: bool


class DestinationIn(BaseModel):
    destination: str


@app.on_event("startup")
def startup() -> None:
    otp.start_worker()


@app.get("/healthz")
def healthz() -> dict:
    otp.STORE.client().ping()
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


def _ip(request: Request) -> str:
    return request.headers.get("x-client-ip") or (request.client.host if request.client else "unknown")


@app.post("/v1/otps")
def generate(body: GenerateIn, request: Request) -> JSONResponse:
    try:
        payload = otp.generate(body.destination.strip(), body.channel, body.purpose, _ip(request))
    except otp.Unavailable:
        return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
    except otp.Rejected as exc:
        body_out = {"ok": False, "error": exc.error}
        if exc.retry_after is not None:
            body_out["retry_after"] = exc.retry_after
        status = 400 if exc.error == "bad_request" else 429
        return JSONResponse(body_out, status_code=status)
    return JSONResponse(payload, status_code=202)


@app.post("/v1/otps/verify")
def verify(body: VerifyIn) -> JSONResponse:
    try:
        ok = otp.verify(body.destination.strip(), body.purpose, body.code.strip())
    except otp.Unavailable:
        return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
    if ok:
        return JSONResponse({"ok": True}, status_code=200)
    return JSONResponse({"ok": False}, status_code=400)


@app.get("/api/inbox")
def inbox(destination: str) -> JSONResponse:
    try:
        rows = otp.inbox(destination.strip())
    except otp.Unavailable:
        return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503)
    return JSONResponse({"messages": rows})


@app.get("/api/status")
def status() -> dict:
    return otp.status()


@app.post("/api/situations/redis")
def redis_flag(body: FlagIn) -> dict:
    otp.STORE.redis_down = body.down
    return otp.status()


@app.post("/api/situations/sms")
def sms_flag(body: FlagIn) -> dict:
    otp.STORE.sms_down = body.down
    return otp.status()


@app.post("/api/situations/daily-full")
def daily_full(body: DestinationIn) -> dict:
    otp.fill_daily(body.destination.strip())
    return {"daily_cap": otp.DAILY_CAP}


@app.post("/api/reset")
def reset() -> dict:
    otp.reset()
    return otp.status()
