"""A small fake web. One server answers for many sites, chosen by the Host header.

kim.test     robots Disallow /private/ (Allow /private/open), a PDF, a page over the size limit
mirror.test  the same text as kim.test pages, with different scripts and comments (content dedupe)
wiki.test    200 linked articles and Crawl-delay: 1 (the huge domain)
trap.test    an endless calendar with session ids and utm params (crawler trap)
flaky.test   503 twice per page, then 200; /slow never answers in time
dead.test    503 forever (dead-letter queue)
closed.test  robots.txt answers 500 (disallow all)
"""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse

app = FastAPI()

hits: dict[str, list[float]] = defaultdict(list)
min_gap: dict[str, float] = {}
attempts: dict[str, int] = defaultdict(int)

KIM_PAGES = {c: f"Kim writes about topic {c.upper()}. " + " ".join(
    f"Sentence {i} about {c} and distributed systems." for i in range(6)) for c in "abcdefghij"}


def page(title: str, body: str, links: list[str], noise: bool = False) -> HTMLResponse:
    extra = ""
    if noise:
        extra = (f"<script>var ad={random.randint(1, 10**9)};</script><!-- served {time.time()} -->"
                 f"<style>.x{{color:#{random.randint(0, 0xffffff):06x}}}</style>")
    anchors = "".join(f'<li><a href="{h}">{h}</a></li>' for h in links)
    return HTMLResponse(f"<html><head><title>{title}</title>{extra}</head>"
                        f"<body data-t='{time.time()}'><h1>{title}</h1><p>{body}</p><ul>{anchors}</ul></body></html>")


@app.get("/__lab/stats")
def stats():
    return {h: {"requests": len(t), "minGapMs": round(min_gap[h] * 1000) if h in min_gap else None}
            for h, t in hits.items()}


@app.post("/__lab/reset")
def reset():
    hits.clear()
    min_gap.clear()
    attempts.clear()
    return {"ok": True}


@app.api_route("/{path:path}", methods=["GET", "HEAD"])
async def serve(path: str, request: Request):
    host = (request.headers.get("host") or "").split(":")[0].lower()
    path = "/" + path
    now = time.time()
    if hits[host]:
        gap = now - hits[host][-1]
        min_gap[host] = min(gap, min_gap.get(host, gap))
    hits[host].append(now)
    site = SITES.get(host)
    if not site:
        return PlainTextResponse("unknown site", status_code=404)
    return await site(path, request)


async def kim(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("User-agent: *\nDisallow: /private/\nAllow: /private/open\n")
    if path == "/":
        return page("Kim's blog", "Welcome to Kim's blog about systems.",
                    [f"/{c}" for c in "abcdefghij"] + ["/private/secret", "/private/open", "/files/report.pdf",
                                                        "/huge", "http://mirror.test/", "http://wiki.test/",
                                                        "http://trap.test/", "http://flaky.test/",
                                                        "http://dead.test/", "http://closed.test/",
                                                        "/a#comments", "/b?utm_source=feed"])
    if path.lstrip("/") in KIM_PAGES:
        c = path.lstrip("/")
        return page(f"Topic {c.upper()}", KIM_PAGES[c], ["/", "/" + chr(((ord(c) - 96) % 10) + 97)])
    if path == "/private/secret":
        return page("Secret", "This page is disallowed by robots.txt.", [])
    if path == "/private/open":
        return page("Open note", "Allow /private/open is longer than Disallow /private/, so this page is allowed.", [])
    if path == "/files/report.pdf":
        return Response(b"%PDF-1.4 fake", media_type="application/pdf")
    if path == "/huge":
        async def chunks():
            yield b"<html><body><p>"
            for _ in range(2000):
                yield b"x" * 1024
            yield b"</p></body></html>"
        return StreamingResponse(chunks(), media_type="text/html")
    return PlainTextResponse("not found", status_code=404)


async def mirror(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("not found", status_code=404)
    if path == "/":
        return page("Mirror of Kim", "A site that copies Kim's posts.", [f"/{c}" for c in "abcdefghij"])
    c = path.lstrip("/")
    if c in KIM_PAGES:
        return page(f"Topic {c.upper()}", KIM_PAGES[c], ["/", "/" + chr(((ord(c) - 96) % 10) + 97)], noise=True)
    return PlainTextResponse("not found", status_code=404)


async def wiki(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("User-agent: *\nCrawl-delay: 1\nDisallow: /w/edit\n")
    if path == "/":
        return page("Wiki", "The wiki home page.", [f"/wiki/{i}" for i in range(1, 61)] + ["/w/edit?page=1"])
    if path.startswith("/wiki/"):
        try:
            n = int(path.rsplit("/", 1)[1])
        except ValueError:
            return PlainTextResponse("not found", status_code=404)
        links = [f"/wiki/{(n * k) % 200 + 1}" for k in (3, 7, 11)]
        return page(f"Article {n}", f"Article number {n} explains subject {n} in depth.", links)
    return PlainTextResponse("not found", status_code=404)


async def trap(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("not found", status_code=404)
    if path == "/":
        return page("Calendar", "An events calendar.", ["/calendar/2026/10/25"])
    if path.startswith("/calendar/"):
        try:
            y, m, d = (int(x) for x in path.split("/")[2:5])
        except ValueError:
            return PlainTextResponse("not found", status_code=404)
        nxt = f"/calendar/{y}/{m}/{d + 1}"
        sid = random.randint(1, 10**9)
        return page(f"{y}-{m}-{d}", f"No events on day {d} of month {m}.",
                    [nxt, f"{nxt}?sid={sid}", f"{nxt}?utm_campaign=x{sid}"])
    return PlainTextResponse("not found", status_code=404)


async def flaky(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("User-agent: *\nAllow: /\n")
    if path == "/slow":
        await asyncio.sleep(5)
        return page("Slow", "Too late.", [])
    attempts[path] += 1
    if attempts[path] <= 2:
        return PlainTextResponse("busy", status_code=503)
    if path == "/":
        return page("Flaky", "A site that fails twice before it answers.", ["/p1", "/p2", "/slow"])
    if path in ("/p1", "/p2"):
        return page(f"Flaky {path}", f"Flaky page {path} finally loaded.", ["/"])
    return PlainTextResponse("not found", status_code=404)


async def dead(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("not found", status_code=404)
    return PlainTextResponse("down", status_code=503)


async def closed(path: str, request: Request):
    if path == "/robots.txt":
        return PlainTextResponse("error", status_code=500)
    return page("Closed", "You should not see this.", [])


SITES = {"kim.test": kim, "mirror.test": mirror, "wiki.test": wiki, "trap.test": trap,
         "flaky.test": flaky, "dead.test": dead, "closed.test": closed}


@app.exception_handler(Exception)
async def boom(request: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=500)
