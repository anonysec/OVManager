"""Dynamic URL path prefix manager for OVManager.

Reads the current URLPATH from the DB Settings table with a short cache TTL.
When URLPATH is changed via the web UI, the new value takes effect within
the cache TTL (default 5 seconds) without any restart.

Usage:
    from backend.urlpath import get_urlpath, set_urlpath, URLPathMiddleware

    # Get current prefix (cached)
    prefix = get_urlpath()   # "" or e.g. "mysecret"

    # Update at runtime (immediately cached)
    set_urlpath("newpath")
"""

import time
import threading

from backend.db.engine import SessionLocal

# Thread-safe cache for the current URLPATH
_lock = threading.Lock()
_cache_value: str = ""
_cache_ts: float = 0.0
_CACHE_TTL: float = 5.0  # seconds


def _load_from_db() -> str:
    """Read urlpath from the Settings table. Returns "" if not set or table missing."""
    db = SessionLocal()
    try:
        from backend.db import crud
        s = crud.get_settings(db)
        return (getattr(s, "urlpath", "") or "").strip("/")
    except Exception:
        return ""
    finally:
        db.close()


def get_urlpath() -> str:
    """Return the current URLPATH prefix (without leading/trailing slashes).

    Empty string means the panel is served at root.
    Cached for _CACHE_TTL seconds to avoid a DB query on every request.
    """
    global _cache_value, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL:
        return _cache_value
    with _lock:
        # Double-check after acquiring lock
        if now - _cache_ts < _CACHE_TTL:
            return _cache_value
        _cache_value = _load_from_db()
        _cache_ts = now
    return _cache_value


def set_urlpath(value: str) -> str:
    """Update URLPATH in DB and invalidate cache.

    Returns the normalized value that was stored.
    If DB is unavailable (e.g., tests), still updates the in-memory cache.
    """
    global _cache_value, _cache_ts
    value = (value or "").strip("/")
    # Persist to DB (best effort — may fail in test environments)
    try:
        db = SessionLocal()
        try:
            from backend.db import crud
            s = crud.get_settings(db)
            s.urlpath = value
            db.commit()
        finally:
            db.close()
    except Exception:
        pass  # DB not available (e.g., tables not yet created in tests)
    # Always update cache regardless of DB success
    with _lock:
        _cache_value = value
        _cache_ts = time.monotonic()
    return value


def invalidate_cache() -> None:
    """Force the next get_urlpath() to read from DB."""
    global _cache_ts
    with _lock:
        _cache_ts = 0.0


class URLPathMiddleware:
    """ASGI middleware that enforces the dynamic URLPATH prefix.

    Behavior:
    - If URLPATH is empty: all requests pass through unchanged.
    - If URLPATH is set (e.g. "mysecret"):
      - Requests to /mysecret/... → strip prefix, pass to app as /...
      - Requests to /mysecret (exact) → strip prefix, pass as /
      - Any other request → return empty 200 response (no 404, no redirect)
        This hides the panel from scanners and unauthorized visitors.

    This is an ASGI middleware (not Starlette BaseHTTPMiddleware) because it
    needs to modify the request scope before routing, and must short-circuit
    non-matching paths before they reach the app.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            # Let non-HTTP (lifespan, etc.) pass through
            await self.app(scope, receive, send)
            return

        urlpath = get_urlpath()
        path = scope.get("path", "")

        if not urlpath:
            # No prefix configured — serve everything at root
            await self.app(scope, receive, send)
            return

        # Always allow these paths through regardless of URLPATH
        path = scope.get("path", "")
        _ALWAYS_ALLOWED_PREFIXES = ("/assets/", "/sub/", "/health", "/doc", "/openapi.json")
        if any(path == p.rstrip("/") or path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
            await self.app(scope, receive, send)
            return

        prefix = f"/{urlpath}"

        if path == prefix:
            # Exact match: /mysecret → /
            scope = dict(scope)
            scope["path"] = "/"
            await self.app(scope, receive, send)
            return

        if path.startswith(prefix + "/"):
            # Strip prefix: /mysecret/api/users → /api/users
            scope = dict(scope)
            scope["path"] = path[len(prefix):]
            await self.app(scope, receive, send)
            return

        # Path doesn't match the prefix → return empty response (security)
        # No 404, no redirect, no headers that reveal the server exists.
        await self._send_empty(send)

    @staticmethod
    async def _send_empty(send):
        """Send a minimal empty response that reveals nothing."""
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"],
                [b"content-length", b"0"],
            ],
        })
        await send({
            "type": "http.response.body",
            "body": b"",
        })
