import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.operations.daily_checks import enforce_user_limits, check_user_used_traffic
from backend.operations.metrics import collect_metrics
from backend.node.task import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.db.engine import SessionLocal
from backend.db.exceptions import NotFoundError, ConflictError
from backend.config import config
from backend.routers import all_routers
from backend.routers.sub import router as subscription_router
from backend.version import __version__
from backend.tls_config import TLSConfig
from backend.urlpath import URLPathMiddleware, get_urlpath as _get_urlpath


# ── Security Headers Middleware ───────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # HSTS: 1 year, include subdomains, preload-ready
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        # Other hardening headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
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
            if auth and auth.startswith("Bearer "):
                return await call_next(request)
            if path.startswith("/api/sub/") or path == "/api/login":
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
        # Seed initial URLPATH from config if Settings row exists and urlpath is empty
        try:
            initial_urlpath = (config.URLPATH or "").strip("/")
            row = db.execute(_text("SELECT urlpath FROM settings LIMIT 1")).fetchone()
            if row is not None and not (row[0] or "").strip():
                db.execute(_text("UPDATE settings SET urlpath = :v"), {"v": initial_urlpath})
        except Exception:
            pass
        db.commit()
    finally:
        db.close()


# ── TLS Configuration ─────────────────────────────────────────────
tls_config = TLSConfig.get_ssl_config()
ssl_keyfile = tls_config.get("key_file") or None
ssl_certfile = tls_config.get("cert_file") or None

# ── FastAPI app (routes registered at root — URLPathMiddleware handles prefix) ─
# All routes are at /api/..., /doc, /health, etc.
# The URLPathMiddleware strips /{urlpath}/ prefix before routing.
api = FastAPI(
    title="OVManager API",
    description="API for managing OVManager",
    version=__version__,
    docs_url="/doc" if config.DOC else None,
    openapi_url="/openapi.json" if config.DOC else None,
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (always at /health — hidden by middleware when URLPATH set) ─
@api.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": __version__}


# ── Frontend static assets ────────────────────────────────────────
frontend_build_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_path = os.path.join(frontend_build_path, "assets")

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
    scheduler.start()


def start_bot():
    """Start the Telegram bot as a subprocess."""
    import subprocess
    import sys

    bot_path = os.path.join(os.path.dirname(__file__), "..", "bot", "main.py")
    if os.path.exists(bot_path):
        subprocess.Popen(
            [sys.executable, "-m", "bot.main"],
            cwd=os.path.dirname(__file__),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


# ── Startup ───────────────────────────────────────────────────────
@api.on_event("startup")
async def startup_event():
    try:
        _run_migrations()
    except Exception as e:
        from backend.logger import logger
        logger.error("migration warning: %s", e)
    start_scheduler()
    start_bot()


# ── Register API routers (no prefix — URLPathMiddleware handles it) ─
for router in all_routers:
    api.include_router(prefix="/api", router=router)

# Subscription router (public, also goes through middleware)
api.include_router(subscription_router)


# ── SPA catch-all (serve React index.html for unknown paths) ──────
# Inject URLPATH into the HTML so the frontend knows its base path
# when served from a sub-path (e.g. /dashboard/). This replaces the
# broken window.__OV_URLPATH__ approach which relied on a template
# that doesn't exist for static files.
def _inject_urlpath(html: str, urlpath: str) -> str:
    if not urlpath:
        return html
    marker = "<div id=\"root\"></div>"
    injection = f'<script>window.__OV_URLPATH__="{urlpath}";</script>'
    return html.replace(marker, marker + injection)


async def _serve_react() -> FileResponse | JSONResponse:
    from fastapi.responses import HTMLResponse
    index_path = os.path.join(frontend_build_path, "index.html")
    if not os.path.isfile(index_path):
        return JSONResponse({"detail": "Frontend not built"}, status_code=404)
    urlpath = _get_urlpath()
    if urlpath:
        # Inject URLPATH into the HTML so the frontend knows its base path
        with open(index_path, "r", encoding="utf-8") as f:
            html = f.read()
        marker = '<div id="root"></div>'
        injection = f'<script>window.__OV_URLPATH__="{urlpath}";</script>'
        html = html.replace(marker, marker + injection)
        return HTMLResponse(content=html)
    return FileResponse(
        index_path,
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
