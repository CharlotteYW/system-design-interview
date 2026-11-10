from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from psycopg import OperationalError
from psycopg_pool import PoolTimeout

from . import reviews, search
from .db import pool


@asynccontextmanager
async def lifespan(app):
    pool.open(wait=True)
    try:
        yield
    finally:
        pool.close()


app = FastAPI(title="Yelp study lab", lifespan=lifespan)
app.include_router(search.router)
app.include_router(reviews.router)


@app.exception_handler(HTTPException)
async def api_error(request: Request, exc: HTTPException):
    return JSONResponse({"errorCode": exc.detail}, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeout)
async def database_error(request: Request, exc: Exception):
    return JSONResponse({"errorCode": "DATABASE_UNAVAILABLE"}, status_code=503)


@app.get("/healthz")
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1 FROM businesses LIMIT 1")
    return {"status": "ok"}
