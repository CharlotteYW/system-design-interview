import base64
import binascii
import hashlib
import json

from fastapi import HTTPException

PAGE_SIZE = 20


def read_cursor(token, scope):
    if token is None:
        return None
    try:
        value = json.loads(base64.urlsafe_b64decode(token))
        if not isinstance(value, list) or len(value) != 3 or value[0] != scope:
            raise ValueError
        return value[1], value[2]
    except (ValueError, TypeError, binascii.Error):
        raise HTTPException(400, "INVALID_CURSOR") from None


def cursor_scope(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:20]


def page(rows, scope, sort_key, id_key):
    next_cursor = None
    if len(rows) > PAGE_SIZE:
        last = rows[PAGE_SIZE - 1]
        raw = json.dumps([scope, last[sort_key], str(last[id_key])], default=str).encode()
        next_cursor = base64.urlsafe_b64encode(raw).decode()
    return rows[:PAGE_SIZE], next_cursor


def like_literal(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
