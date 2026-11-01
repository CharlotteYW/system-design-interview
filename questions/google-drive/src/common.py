"""Local provider adapter and lab primitives; not a GCS emulator."""
import base64
import hashlib
import hmac
import json
import os
import time

import google_crc32c
import httpx
import redis
from fastapi import HTTPException

CA = os.getenv("TLS_CA", "/certs/ca.crt")
INTERNAL = os.getenv("INTERNAL_KEY", "local-study-internal-key")
SIGNING = os.getenv("SIGNING_KEY", "local-study-signing-key").encode()
R = redis.Redis.from_url(os.environ["REDIS_URL"], decode_responses=True,
                        ssl_ca_certs=CA, ssl_cert_reqs="required")


def now():
    return time.time() + float(R.get("lab:offset") or 0)


def fault(name):
    return R.hget("lab:faults", name) == "1"


def metric(name, amount=1):
    R.hincrby("lab:metrics", name, amount)


def crc(data):
    return base64.b64encode(google_crc32c.value(data).to_bytes(4, "big")).decode()


def seal(payload):
    raw = base64.urlsafe_b64encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(SIGNING, raw.encode(), hashlib.sha256).hexdigest()
    return raw + "." + sig


def unseal(ticket, audience):
    try:
        raw, sig = ticket.rsplit(".", 1)
        if not hmac.compare_digest(sig, hmac.new(SIGNING, raw.encode(), hashlib.sha256).hexdigest()):
            raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if data.get("aud") != audience or data.get("exp", 0) < now():
            raise ValueError()
        return data
    except Exception:
        raise HTTPException(403, detail={"code": "invalid_or_expired_permission"})


def internal(key):
    if not hmac.compare_digest(key or "", INTERNAL):
        raise HTTPException(403, detail={"code": "service_access_denied"})


def http():
    return httpx.Client(verify=CA, timeout=30, headers={"X-Internal-Key": INTERNAL})
