"""HTTP middlewares: security headers, asset caching, CSRF guard.

Plain ASGI, not Starlette ``BaseHTTPMiddleware``: these only inspect the request
or rewrite response headers, so routing the body through a task group would add
a task, a buffer and latency per request — notably on the SSE live stream.
"""

from __future__ import annotations

import mimetypes
import os

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'sha256-DfXw4dmojGxppeSGQd3gY5VwJccQpen/20YT8l+VMDQ='; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


_OVERRIDDEN_HEADERS = frozenset(
    {
        b"x-content-type-options",
        b"x-frame-options",
        b"referrer-policy",
        b"permissions-policy",
        b"content-security-policy",
        b"strict-transport-security",
    }
)


class SecurityHeadersMiddleware:
    """Add hardening headers to every response.

    Also enforces the restore/update write lock: a state-changing request while
    a restore or update is verifying gets a 503 rather than racing the database.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from backend.data_paths import DATA_DIR
        from backend.db.engine import restore_lock

        maintenance_marker = DATA_DIR / "update-maintenance"
        writes_blocked = restore_lock.is_set() or maintenance_marker.is_file()
        if writes_blocked and scope.get("method", "GET") not in ("GET", "HEAD", "OPTIONS"):
            reason = b"Database restore in progress" if restore_lock.is_set() else b"Update verification in progress"
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        [b"content-type", b"application/json"],
                        [b"retry-after", b"5"],
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b'{"success":false,"msg":"' + reason + b'"}'})
            return

        from backend.config import config

        is_https = scope.get("scheme") == "https"
        if not is_https and config.TRUSTED_PROXY:
            for key, value in scope.get("headers") or ():
                if key == b"x-forwarded-proto":
                    is_https = value.split(b",")[-1].strip().lower() == b"https"
                    break

        extra: list[list[bytes]] = [
            [b"x-content-type-options", b"nosniff"],
            [b"x-frame-options", b"DENY"],
            [b"referrer-policy", b"strict-origin-when-cross-origin"],
            [b"permissions-policy", b"geolocation=(), microphone=(), camera=()"],
            [b"content-security-policy", CSP_POLICY.encode("latin-1")],
        ]
        if is_https:
            extra.append([b"strict-transport-security", b"max-age=31536000; includeSubDomains; preload"])

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                kept = [h for h in (message.get("headers") or ()) if h[0].lower() not in _OVERRIDDEN_HEADERS]
                message["headers"] = kept + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)


class AssetCacheMiddleware:
    """Immutable caching + pre-compressed responses for build assets.

    ``/assets/*`` filenames carry a content hash and ``/fonts/*.woff2`` are
    frozen upstream releases, so both may be cached forever. Vite writes a
    ``.gz`` sibling next to every compressible file; when the client accepts
    gzip the sibling is served directly, roughly halving first-load bytes with
    no runtime compression cost.
    """

    _IMMUTABLE = "public, max-age=31536000, immutable"
    _TEXT_EXTS = {".js", ".css", ".svg", ".html", ".json", ".map"}

    def __init__(self, app, frontend_dir: str):
        self.app = app
        self.frontend_dir = frontend_dir

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not (path.startswith("/assets/") or path.startswith("/fonts/")):
            await self.app(scope, receive, send)
            return

        accept = ""
        for key, value in scope.get("headers") or ():
            if key == b"accept-encoding":
                accept = value.decode("latin-1")
                break

        rel = path[len("/assets/") :] if path.startswith("/assets/") else path[len("/fonts/") :]
        if not rel or ".." in rel:
            await self.app(scope, receive, send)
            return
        base = os.path.join(self.frontend_dir, "assets" if path.startswith("/assets/") else "fonts")
        # A leading slash survives as scope["path"] (/assets//etc/passwd), and
        # os.path.join(base, "/etc/passwd") DISCARDS base — so the ".." test
        # above was not the boundary, it was decoration. Confine by real path:
        # anything resolving outside the base (including via a symlink) falls
        # through to the app, which 404s.
        real_base = os.path.realpath(base)

        def _inside(candidate: str) -> bool:
            resolved = os.path.realpath(candidate)
            return resolved == real_base or resolved.startswith(real_base + os.sep)

        cand = os.path.join(base, rel.lstrip("/"))
        if not _inside(cand):
            await self.app(scope, receive, send)
            return

        is_fonts_css = path.startswith("/fonts/") and rel.endswith(".css")
        if (
            accept
            and "gzip" in accept.lower()
            and os.path.splitext(cand)[1] in self._TEXT_EXTS
            and _inside(cand + ".gz")
            and os.path.isfile(cand + ".gz")
            and (path.startswith("/assets/") or is_fonts_css)
        ):
            media = mimetypes.guess_type(cand)[0] or "application/octet-stream"
            headers = [
                [b"content-encoding", b"gzip"],
                [b"vary", b"Accept-Encoding"],
                [b"cache-control", self._IMMUTABLE.encode() if path.startswith("/assets/") else b"public, max-age=3600"],
            ]
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": headers + [[b"content-type", media.encode()]],
                }
            )
            with open(cand + ".gz", "rb") as fh:
                body = fh.read()
            await send({"type": "http.response.body", "body": body})
            return

        cache = self._IMMUTABLE if path.startswith("/assets/") else "public, max-age=3600"

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append([b"cache-control", cache.encode()])
            await send(message)

        await self.app(scope, receive, send_with_cache)


class CSRFProtectionMiddleware:
    """Reject state-changing requests that look like a cross-origin form post."""

    _MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})
    _EXEMPT_PATHS = frozenset({"/api/login", "/api/logout", "/api/refresh"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in self._MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        auth = b""
        requested_with = False
        for key, value in scope.get("headers") or ():
            if key == b"authorization":
                auth = value
            elif key == b"x-requested-with":
                requested_with = True

        if auth.startswith(b"Bearer "):
            await self.app(scope, receive, send)
            return

        from backend.urlpath import get_urlpath as _get_urlpath

        path = scope.get("path", "")
        _up = _get_urlpath()
        if _up and path.startswith(f"/{_up}/"):
            path = path[len(f"/{_up}") :]
        if path.startswith("/api/sub/") or path in self._EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        if not requested_with:
            await _send_csrf_failure(send)
            return

        await self.app(scope, receive, send)


async def _send_csrf_failure(send) -> None:
    body = b"CSRF check failed: missing X-Requested-With header"
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                [b"content-type", b"text/plain; charset=utf-8"],
                [b"content-length", str(len(body)).encode("ascii")],
                [b"x-content-type-options", b"nosniff"],
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
