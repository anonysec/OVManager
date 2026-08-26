# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import config
from backend.db.engine import SessionLocal
from backend.db.exceptions import ConflictError, NotFoundError, ValidationError
from backend.db.migrations import migrate
from backend.logger import logger
from backend.node.task import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.operations.daily_checks import check_user_used_traffic, enforce_user_limits
from backend.operations.live import POLL_SECONDS, collect_live_snapshot
from backend.operations.metrics import collect_metrics
from backend.routers import all_routers
from backend.routers.sub import router as subscription_router
from backend.tls_config import TLSConfig
from backend.urlpath import URLPathMiddleware
from backend.urlpath import get_urlpath as _get_urlpath
from backend.version import __version__

_scheduler = None
_bot_process = None


# ── Security Headers Middleware ───────────────────────────────────
# CSP: strict-by-default. The SPA loads only same-origin scripts/styles;
# images may come from data: URIs (QR codes, inline flag SVGs). The panel and
# the subscription page load Google Fonts (Manrope/Space Grotesk) and the
# subscription page uses a jsdelivr-hosted Arad font, so those two origins are
# explicitly allowed for fonts + the Google Fonts stylesheet. Inline styles
# are needed for React style props. No inline <script> is used anywhere (the
# subscription page's script was extracted to /sub/static/subscription.js) —
# `'unsafe-inline'` for script-src is intentionally NOT granted.
CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "img-src 'self' data:; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)


# Header names the middleware owns: any value set further down the stack is
# replaced rather than duplicated.
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

    Written as a plain ASGI middleware instead of Starlette's
    ``BaseHTTPMiddleware``: that helper runs each request through a task group
    that copies the response body through a queue, which costs a task and a
    buffer per request and adds latency to streaming responses — notably the
    SSE live stream. Rewriting headers on the ``http.response.start`` message
    does the same job with no per-request allocation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # HSTS is meaningful only on HTTPS. Trust the forwarded proto only when
        # the deployment explicitly trusts its reverse proxy.
        is_https = scope.get("scheme") == "https"
        if not is_https and config.TRUSTED_PROXY:
            for key, value in scope.get("headers") or ():
                if key == b"x-forwarded-proto":
                    is_https = value.lower() == b"https"
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


# ── Simple CSRF Protection ────────────────────────────────────────
# For state-changing endpoints (POST/PUT/DELETE/PATCH) that use cookie auth.
# Since this panel uses Bearer tokens in Authorization header, CSRF risk is low,
# but we add a middleware that requires a custom header for non-GET requests
# to defend against accidental cross-origin form submissions.
class CSRFProtectionMiddleware:
    """Reject state-changing requests that look like a cross-origin form post.

    Plain ASGI for the same reason as :class:`SecurityHeadersMiddleware`: the
    check only inspects the request, so wrapping the response buys nothing.
    """

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

        # Bearer-token callers (the SPA, nodes, the bot) are not browser forms.
        if auth.startswith(b"Bearer "):
            await self.app(scope, receive, send)
            return

        # Public endpoints: login and the user-facing subscription routes.
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


def _run_migrations():
    """Bring the database up to the current schema version.

    All migration logic lives in :mod:`backend.db.migrations`; this is only the
    startup hook. It raises on failure so a half-migrated database stops the
    panel instead of serving requests against a broken schema.
    """
    migrate()


# ── TLS Configuration ─────────────────────────────────────────────
tls_config = TLSConfig.get_ssl_config()
ssl_keyfile = tls_config.get("key_file") or None
ssl_certfile = tls_config.get("cert_file") or None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown via the modern lifespan API."""
    # ── Startup ──────────────────────────────────────────────────────
    _run_migrations()
    from backend.db.engine import SessionLocal as _SL
    from backend.operations.audit import ensure_audit_table

    _db = _SL()
    try:
        ensure_audit_table(_db)
    finally:
        _db.close()
    start_scheduler()
    start_bot()
    yield
    # ── Shutdown ─────────────────────────────────────────────────────
    global _scheduler, _bot_process
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
    if _bot_process and _bot_process.poll() is None:
        _bot_process.terminate()
        try:
            _bot_process.wait(timeout=5)
        except Exception:
            _bot_process.kill()
    _bot_process = None


# ── FastAPI app (routes registered at root — URLPathMiddleware handles prefix) ─
# All routes are at /api/..., /doc, /health, etc.
# The URLPathMiddleware strips /{urlpath}/ prefix before routing.
api = FastAPI(
    title="OVManager API",
    description="API for managing OVManager",
    version=__version__,
    docs_url="/doc" if config.DOC else None,
    openapi_url="/openapi.json" if config.DOC else None,
    lifespan=lifespan,
)


# ── Exception handlers (domain → HTTP) ────────────────────────────
@api.exception_handler(NotFoundError)
async def not_found_handler(request, exc: NotFoundError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=404, content={"detail": str(exc)})


@api.exception_handler(ConflictError)
async def conflict_handler(request, exc: ConflictError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": str(exc)})


@api.exception_handler(ValidationError)
async def validation_handler(request, exc: ValidationError):
    from fastapi.responses import JSONResponse

    # 422 to match FastAPI's own request-validation status.
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ── CORS ──────────────────────────────────────────────────────────
# never allow "*" with allow_credentials=True — browsers reject it and
# it defeats the same-origin boundary. Default to no cross-origin access
# (same-origin only). Set CORS_ORIGINS to an explicit comma-separated
# allowlist (e.g. https://panel.example.com,https://sub.example.com) when
# the frontend is served from a different origin than the API.
_allow_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
api.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Refresh-Token"],
)


# ── Health check (always at /health — hidden by middleware when URLPATH set) ─
@api.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": __version__}


# ── Frontend static assets ────────────────────────────────────────
frontend_build_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_path = os.path.join(frontend_build_path, "assets")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

if os.path.isdir(assets_path):
    api.mount("/assets", StaticFiles(directory=assets_path), name="assets")


# ── Background jobs ───────────────────────────────────────────────
async def auto_sync_limits_job():
    db = SessionLocal()
    try:
        await sync_all_user_limits(db)
    finally:
        db.close()


async def auto_clean_stale_job():
    db = SessionLocal()
    try:
        await clean_stale_sessions_all_nodes(db)
    finally:
        db.close()


def start_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(
        check_user_used_traffic,
        CronTrigger(minute="*/5"),
        id="check_user_used_traffic",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        enforce_user_limits,
        CronTrigger(minute="*/10"),
        id="enforce_user_limits",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        collect_metrics,
        CronTrigger(minute="*/5"),
        id="collect_metrics",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        auto_sync_limits_job,
        CronTrigger(minute="*/30"),
        id="auto_sync_limits",
        replace_existing=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        auto_clean_stale_job,
        CronTrigger(minute="*/15"),
        id="auto_clean_stale",
        replace_existing=True,
        misfire_grace_time=60,
    )
    # Live collector: single poller for all nodes. Request handlers and SSE
    # subscribers use its in-memory snapshot instead of fanning out to nodes.
    # First run is immediate so the cache is warm before the first page load.
    scheduler.add_job(
        collect_live_snapshot,
        IntervalTrigger(seconds=POLL_SECONDS),
        id="live_snapshot",
        replace_existing=True,
        next_run_time=datetime.now(tz=UTC),
        misfire_grace_time=30,
    )
    scheduler.add_job(
        _watchdog_bot,
        CronTrigger(minute="*/1"),
        id="watchdog_bot",
        replace_existing=True,
        misfire_grace_time=30,
    )
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def start_bot():
    """Start one supervised Telegram bot subprocess from the app root."""
    global _bot_process
    import subprocess
    import sys

    app_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bot_path = os.path.join(app_root, "bot", "main.py")
    if not os.path.exists(bot_path):
        return None
    if _bot_process and _bot_process.poll() is None:
        return _bot_process
    try:
        _bot_process = subprocess.Popen(
            [sys.executable, "-m", "bot.main"],
            cwd=app_root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=False,
        )
        logger.info("Telegram bot process started (pid=%s)", _bot_process.pid)
        return _bot_process
    except OSError as exc:
        logger.error("Could not start Telegram bot: %s", exc)
        return None


def _watchdog_bot():
    """Restart the bot process if it has died. Called by scheduler every minute."""
    global _bot_process
    if _bot_process is None:
        return  # Bot was never started (no bot.main.py)
    rc = _bot_process.poll()
    if rc is not None:
        logger.warning("Telegram bot exited (rc=%s) — restarting", rc)
        start_bot()


# Startup/shutdown are now managed by the lifespan context manager above.


# ── Register API routers (no prefix — URLPathMiddleware handles it) ─
for router in all_routers:
    api.include_router(prefix="/api", router=router)

# Subscription router (public, also goes through middleware)
api.include_router(subscription_router)


# ── SPA catch-all (serve React index.html for unknown paths) ──────
# The frontend is fully prefix-agnostic: it reads its base path from a
# <base href> tag, so we inject the CURRENT urlpath here on every request
# (a runtime prefix change is reflected on the next page load). The response
# is never cached — otherwise a browser/proxy could keep serving a stale
# <base href> and break API calls.
#
# The file *contents* are cached, though: this catch-all serves every route in
# the SPA, so re-reading and decoding index.html from disk on each navigation
# was pure overhead. A single os.stat() per request replaces the read, and the
# cache is invalidated by mtime+size so a redeploy is picked up immediately.
_index_cache: tuple[int, int, str] | None = None


def _read_index_html() -> str | None:
    """Return the built index.html, or None when the frontend is not built."""
    global _index_cache
    index_path = os.path.join(frontend_build_path, "index.html")
    try:
        stat = os.stat(index_path)
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    if _index_cache is not None and (_index_cache[0], _index_cache[1]) == key:
        return _index_cache[2]
    try:
        with open(index_path, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return None
    _index_cache = (key[0], key[1], html)
    return html


async def _serve_react() -> FileResponse | JSONResponse:
    from fastapi.responses import HTMLResponse

    html = _read_index_html()
    if html is None:
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)
    urlpath = _get_urlpath()
    # <base href="/dashboard/"> under a prefix, <base href="/"> at root.
    # It must be the first element in <head> so all relative URLs resolve
    # against it (script/asset tags are absolute and unaffected).
    base_href = f"/{urlpath}/" if urlpath else "/"
    if "<base " not in html:
        html = html.replace("<head>", f'<head>\n    <base href="{base_href}" />', 1)
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Catch-all for SPA — must be registered LAST to not shadow API routes
@api.get("/")
async def spa_root():
    return await _serve_react()


@api.get("/{path:path}", include_in_schema=False)
async def spa_catchall(path: str):
    # Don't catch API, doc, health, asset, or subscription paths
    if path.startswith(("api/", "doc", "openapi.json", "health", "assets/", "sub/")):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await _serve_react()


# ── Security middleware (added before URLPathMiddleware so headers
#    are applied to all responses including SPA catch-all) ──────
api.add_middleware(SecurityHeadersMiddleware)
api.add_middleware(CSRFProtectionMiddleware)

# ── URLPathMiddleware (MUST be added last — it wraps everything) ──
# This is the outermost middleware: it runs first on every request.
# When URLPATH is set, it strips /{urlpath}/ prefix and hides non-matching paths.
api.add_middleware(URLPathMiddleware)
