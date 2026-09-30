"""Dynamic URL path prefix manager for OVManager.

Reads the current URLPATH from the DB Settings table with a short cache TTL, so
a change made in the web UI takes effect without a restart.
"""

import logging
import threading
import time

from backend.db.engine import SessionLocal

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache_value: str = ""
_cache_ts: float = 0.0
_CACHE_TTL: float = 5.0  # seconds
_reserved_cache: frozenset | None = None


def _load_from_db() -> str:
    """Read urlpath from the Settings table. Returns "" if not set or table missing."""
    db = SessionLocal()
    try:
        from backend.db import crud

        s = crud.get_settings(db)
        return (getattr(s, "urlpath", "") or "").strip("/")
    except Exception as exc:
        logger.error("Could not read URLPATH from database: %s", exc)
        raise
    finally:
        db.close()


def get_urlpath() -> str:
    """Return the current URLPATH prefix (without leading/trailing slashes).

    Empty string means the panel is served at root. Cached for _CACHE_TTL
    seconds to keep a DB query off every request.
    """
    global _cache_value, _cache_ts
    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL:
        return _cache_value
    with _lock:
        if now - _cache_ts < _CACHE_TTL:
            return _cache_value
        try:
            _cache_value = _load_from_db()
        except Exception:
            if _cache_ts > 0:
                return _cache_value
            try:
                from backend.config import config

                _cache_value = (config.URLPATH or "").strip("/")
            except Exception:
                _cache_value = ""
        _cache_ts = now
    return _cache_value


def set_urlpath(value: str) -> str:
    """Update URLPATH in DB and invalidate cache.

    Returns the normalized value that was persisted; raises when persistence
    fails, so no caller reports a security-sensitive path change that would be
    lost on restart. Reserved prefixes raise here too — the settings router
    validates user input, but the CLI path must not be able to shadow live
    routes and lock the operator out.
    """
    global _cache_value, _cache_ts
    value = (value or "").strip("/")
    if value and value.lower() in reserved_prefixes():
        raise ValueError(f"URLPATH {value!r} is reserved (it would shadow a panel route) — choose another path")
    try:
        db = SessionLocal()
        try:
            from backend.db import crud

            s = crud.get_settings(db)
            s.urlpath = value
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        if "no such table" in str(exc).lower():
            logger.warning("URLPATH table is not ready; using in-memory value until migration")
            with _lock:
                _cache_value = value
                _cache_ts = time.monotonic()
            return value
        logger.error("Could not persist URLPATH: %s", exc)
        raise RuntimeError("URLPATH could not be persisted") from exc
    with _lock:
        _cache_value = value
        _cache_ts = time.monotonic()
    return value


def invalidate_cache() -> None:
    """Force the next get_urlpath() to read from DB."""
    global _cache_ts
    with _lock:
        _cache_ts = 0.0


def reserved_prefixes() -> set[str]:
    """First path segments the panel itself owns — never usable as URLPATH.

    Derived from the live route table so it cannot drift as routers are added
    or removed, plus the middleware-level exemptions that must stay reachable
    whatever the routes look like.
    """
    global _reserved_cache
    with _lock:
        if _reserved_cache is not None:
            return set(_reserved_cache)

    reserved = {"api", "assets", "health", "static", "doc", "openapi.json"}
    try:
        from backend.config import config

        reserved.add((config.SUBSCRIPTION_PATH or "sub").strip("/").lower())
    except Exception:
        pass
    try:
        from backend.app import api

        for route in api.routes:
            seg = (getattr(route, "path", "") or "").strip("/").split("/", 1)[0].lower()
            if seg and not seg.startswith("{"):  # skip the SPA catch-all
                reserved.add(seg)
    except Exception as exc:
        logger.error("Could not derive reserved URL paths from routes: %s", exc)

    with _lock:
        _reserved_cache = frozenset(reserved)
    return set(reserved)


def reset_urlpath() -> bool:
    """Emergency recovery for an operator locked out by a forgotten prefix.

    Backs ``main.py --reset-urlpath``. The settings row is auto-created if
    missing, so failure means the database itself is unreachable.
    """
    global _cache_value, _cache_ts
    try:
        db = SessionLocal()
        try:
            from backend.db import crud

            settings = crud.get_settings(db)
            settings.urlpath = ""
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.error("Could not reset URLPATH: %s", exc)
        return False
    with _lock:
        _cache_value = ""
        _cache_ts = time.monotonic()
    return True


class URLPathMiddleware:
    """ASGI middleware that enforces the dynamic URLPATH prefix.

    With URLPATH unset every request passes through. When it is set, requests
    under the prefix are rewritten to the bare path and anything else gets an
    empty 404 — no redirect, so the panel stays hidden from scanners.

    Written as raw ASGI rather than BaseHTTPMiddleware because it must modify
    the request scope before routing and short-circuit non-matching paths.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        urlpath = get_urlpath()
        path = scope.get("path", "")

        if not urlpath:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        try:
            from backend.config import config as _panel_config

            _sub_prefix = f"/{_panel_config.SUBSCRIPTION_PATH.strip('/')}/"
        except Exception:
            _sub_prefix = "/sub/"
        _ALWAYS_ALLOWED_PREFIXES = (
            "/assets/",
            "/fonts/",
            _sub_prefix,
            "/health",
            "/manifest.webmanifest",
            "/sw.js",
            "/icons/",
        )
        if any(path == p.rstrip("/") or path.startswith(p) for p in _ALWAYS_ALLOWED_PREFIXES):
            await self.app(scope, receive, send)
            return

        prefix = f"/{urlpath}"

        if path == prefix:
            scope = dict(scope)
            scope["path"] = "/"
            await self.app(scope, receive, send)
            return

        if path.startswith(prefix + "/"):
            scope = dict(scope)
            scope["path"] = path[len(prefix) :]
            await self.app(scope, receive, send)
            return

        await self._send_empty(send)

    @staticmethod
    async def _send_empty(send):
        """An empty body with a real 404 status: content-free, but not mistakable
        for a 200 from a server that is up."""
        await send(
            {
                "type": "http.response.start",
                "status": 404,
                "headers": [
                    [b"content-type", b"text/plain"],
                    [b"content-length", b"0"],
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b"",
            }
        )
