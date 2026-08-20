# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import mimetypes
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.config import config
from backend.db.engine import SessionLocal
from backend.db.exceptions import ConflictError, NotFoundError
from backend.logger import logger
from backend.node.task import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.operations.daily_checks import check_user_used_traffic, enforce_user_limits
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # HSTS is meaningful only on HTTPS. Trust forwarded proto only when
        # the deployment explicitly trusts its reverse proxy.
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "").lower()
        is_https = request.url.scheme == "https" or (config.TRUSTED_PROXY and forwarded_proto == "https")
        if is_https:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # Other hardening headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Content-Security-Policy"] = CSP_POLICY
        return response


# ── Simple CSRF Protection ────────────────────────────────────────
# For state-changing endpoints (POST/PUT/DELETE/PATCH) that use cookie auth.
# Since this panel uses Bearer tokens in Authorization header, CSRF risk is low,
# but we add a middleware that requires a custom header for non-GET requests
# to defend against accidental cross-origin form submissions.
class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            # Skip for API endpoints that use Bearer token auth (they have Authorization header)
            auth = request.headers.get("Authorization")
            # Allow public endpoints (login, subscription) and API key auth
            path = request.url.path
            # Strip URLPATH prefix so CSRF check works for both
            # /api/login and /<urlpath>/api/login
            _up = _get_urlpath()
            if _up and path.startswith(f"/{_up}/"):
                path = path[len(f"/{_up}"):]
            if auth and auth.startswith("Bearer "):
                return await call_next(request)
            if path.startswith("/api/sub/") or path in ("/api/login", "/api/logout", "/api/refresh"):
                return await call_next(request)
            # Require custom header for browser-based form submissions
            if not request.headers.get("X-Requested-With"):
                return Response(
                    content="CSRF check failed: missing X-Requested-With header",
                    status_code=403,
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        return await call_next(request)


def _run_migrations():
    from sqlalchemy import text as _text

    from backend.db.engine import Base

    db = SessionLocal()
    try:
        Base.metadata.create_all(bind=db.get_bind())
        _ALLOWED_TABLES = {"users", "settings", "nodes", "admins"}
        _ALLOWED_COLUMNS = {
            ("users", "last_online", "DATETIME"),
            ("settings", "timezone", "VARCHAR NOT NULL DEFAULT 'UTC'"),
            ("settings", "subscription_url_prefix", "VARCHAR"),
            ("settings", "subscription_path", "VARCHAR NOT NULL DEFAULT 'sub'"),
            ("settings", "urlpath", "VARCHAR NOT NULL DEFAULT ''"),
            ("nodes", "use_tls", "BOOLEAN DEFAULT 0"),
        }
        for table, column, coltype in _ALLOWED_COLUMNS:
            if table not in _ALLOWED_TABLES:
                continue
            existing = {
                r[1] for r in db.execute(_text(f"PRAGMA table_info({table})")).fetchall()
            }
            if column not in existing:
                db.execute(_text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
        # Seed initial URLPATH from config if Settings row exists and urlpath is empty.
        # On a fresh DB, the settings table is empty — use INSERT OR IGNORE to create
        # the row first so the URLPATH from .env gets seeded.
        try:
            initial_urlpath = (config.URLPATH or "").strip("/")
            db.execute(_text(
                "INSERT OR IGNORE INTO settings (port, protocol, urlpath) "
                "VALUES (1194, 'tcp', '')"
            ))
            db.execute(
                _text("UPDATE settings SET urlpath = :v WHERE (urlpath IS NULL OR urlpath = '')"),
                {"v": initial_urlpath},
            )
        except Exception:
            pass
        db.commit()
    finally:
        db.close()


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
async def _serve_react() -> FileResponse | JSONResponse:
    from fastapi.responses import HTMLResponse
    index_path = os.path.join(frontend_build_path, "index.html")
    if not os.path.isfile(index_path):
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)
    with open(index_path, encoding="utf-8") as f:
        html = f.read()
    urlpath = _get_urlpath()
    # <base href="/dashboard/"> under a prefix, <base href="/"> at root.
    # It must be the first element in <head> so all relative URLs resolve
    # against it (script/asset tags are absolute and unaffected).
    base_href = f"/{urlpath}/" if urlpath else "/"
    if "<base " not in html:
        html = html.replace("<head>", f"<head>\n    <base href=\"{base_href}\" />", 1)
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
