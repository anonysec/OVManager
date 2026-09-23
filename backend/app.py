# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

import asyncio
import mimetypes
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import config
from backend.data_paths import DATA_DIR
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
# Monotonic deadline while a clean (rc=0 = disabled, no token / toggled off)
# bot exit suppresses restart attempts. Prevents a per-minute fork+WARNING
# loop on installs without a bot token; real crashes (rc!=0) still restart.
_bot_disabled_until: float | None = None
_BOT_DISABLED_RETRY_SECONDS = 3600


# ── Security Headers Middleware ───────────────────────────────────
# CSP: strict-by-default. The SPA loads only same-origin scripts/styles;
# images may come from data: URIs (QR codes, inline flag SVGs). Fonts are
# self-hosted under /fonts/ (no third-party origin needed anymore). Inline
# styles are needed for React style props. The single inline boot script in
# index.html (theme/dir pre-paint, no network access) is allowlisted by hash;
# everything else must be same-origin (the subscription page's script was
# extracted to /sub/static/subscription.js).
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

        # During a database restore the file on disk is being swapped: reject
        # writes (503) so in-flight sessions cannot commit to the unlinked old
        # file. Reads stay available for the UI's progress polling.
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

        # HSTS is meaningful only on HTTPS. Trust the forwarded proto only when
        # the deployment explicitly trusts its reverse proxy — and only the
        # rightmost hop (the one the proxy appended; earlier ones are spoofable).
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


# ── Simple CSRF Protection ────────────────────────────────────────
# For state-changing endpoints (POST/PUT/DELETE/PATCH) that use cookie auth.
# Since this panel uses Bearer tokens in Authorization header, CSRF risk is low,
# but we add a middleware that requires a custom header for non-GET requests
# to defend against accidental cross-origin form submissions.
class AssetCacheMiddleware:
    """Immutable caching + pre-compressed responses for build assets.

    ``/assets/*`` filenames carry a content hash and ``/fonts/*.woff2`` are
    frozen upstream releases, so both may be cached forever. Vite writes a
    ``.gz`` sibling next to every compressible file; when the client accepts
    gzip the sibling is served directly (Content-Encoding set), roughly
    halving first-load bytes with no runtime compression cost.

    Plain ASGI like the other middlewares — this only inspects the request
    path and rewrites response headers, no body copying.
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

        rel = path[len("/assets/"):] if path.startswith("/assets/") else path[len("/fonts/"):]
        if not rel or ".." in rel:
            await self.app(scope, receive, send)
            return
        base = os.path.join(self.frontend_dir, "assets" if path.startswith("/assets/") else "fonts")
        cand = os.path.join(base, rel)

        is_fonts_css = path.startswith("/fonts/") and rel.endswith(".css")
        if (
            accept
            and "gzip" in accept.lower()
            and os.path.splitext(cand)[1] in self._TEXT_EXTS
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

    _TEXT_EXTS = _TEXT_EXTS = {".js", ".css", ".svg", ".html", ".json", ".map"}


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
        # Create the operations-owned tables once at startup: the traffic
        # collector must never run DDL (and its implicit commit) in the middle
        # of a billing transaction.
        from backend.operations.metrics import ensure_metrics_tables
        from backend.operations.usage_history import ensure_daily_table

        ensure_daily_table(_db)
        ensure_metrics_tables(_db)
    finally:
        _db.close()
    # Candidate verification runs with the update marker present. Migrations
    # above are intentional and covered by the safety backup, but background
    # jobs and the bot must not race writes into a database that may be rolled
    # back moments later.
    if not (DATA_DIR / "update-maintenance").is_file():
        start_scheduler()
        start_bot()
    else:
        logger.info("Update verification mode: scheduler and bot are paused")
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
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


# ── Health check (always at /health — hidden by middleware when URLPATH set) ─
@api.get("/health", tags=["Health"])
async def health_check(request: Request):
    # Browser navigation to /health (F5, bookmark, open-in-new-tab on the
    # sidebar link) must see the SPA Health page, not this JSON: the SPA
    # routes /health to the Health center. Browsers send Sec-Fetch-Mode:
    # navigate; uptime monitors, curl, installers and the Docker healthcheck
    # never do, so they keep getting the JSON probe.
    if request.headers.get("sec-fetch-mode") == "navigate" and "text/html" in request.headers.get("accept", ""):
        from fastapi.responses import HTMLResponse

        html = _read_index_html()
        if html is not None:
            return HTMLResponse(html)
    # The version is only reported to loopback callers (installer, Docker
    # healthcheck, `install.sh status`). Unauthenticated internet scanners get
    # a plain "ok" without a version fingerprint.
    client = request.client.host if request.client else ""
    data: dict = {"status": "ok"}
    if client in ("127.0.0.1", "::1", "localhost"):
        data["version"] = __version__
    return data


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

# Self-hosted fonts (see frontend/public/fonts). Root-level like the PWA
# files so the public subscription page can use them without the prefix.
_fonts_path = os.path.join(frontend_build_path, "fonts")
if os.path.isdir(_fonts_path):
    api.mount("/fonts", StaticFiles(directory=_fonts_path), name="fonts")

# PWA files: manifest + icons + service worker. They live at well-known
# root paths so the browser can find them regardless of the panel prefix;
# the URLPATH middleware whitelists them too.
_icons_path = os.path.join(frontend_build_path, "icons")
if os.path.isdir(_icons_path):
    api.mount("/icons", StaticFiles(directory=_icons_path), name="icons")


@api.get("/manifest.webmanifest", include_in_schema=False)
async def pwa_manifest():
    path = os.path.join(frontend_build_path, "manifest.webmanifest")
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return FileResponse(
        path,
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@api.get("/sw.js", include_in_schema=False)
async def pwa_service_worker():
    """Served with no-cache so a new build's service worker is picked up."""
    path = os.path.join(frontend_build_path, "sw.js")
    if not os.path.isfile(path):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )


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


async def auto_daily_alerts_job():
    """Push the daily expiring/out-of-traffic summary to the owner once a day."""
    from backend.operations.notifier import run_daily_alerts

    # Sync job: run off the event loop so the blocking HTTPS call cannot
    # stall request handling (same pattern as the audit prune below).
    await asyncio.to_thread(run_daily_alerts)


async def auto_prune_audit_job():
    from backend.operations.audit import prune_audit_logs
    from backend.operations.usage_history import prune_daily

    db = SessionLocal()
    try:
        removed = await asyncio.to_thread(prune_audit_logs, db)
        if removed:
            logger.info("Pruned %s audit log row(s) older than 90 days", removed)
        removed_daily = await asyncio.to_thread(prune_daily, db)
        if removed_daily:
            logger.info("Pruned %s daily usage row(s) older than 90 days", removed_daily)
    finally:
        db.close()


async def auto_backup_job():
    """Run the scheduled panel database backup when enabled in settings.

    Best-effort by design: every outcome is audited and logged, and nothing
    is ever raised — a failed backup must not kill the scheduler.
    """
    from backend.operations.audit import log_event
    from backend.routers.maintenance import create_panel_backup

    try:
        from backend.db.models import Settings

        db = SessionLocal()
        try:
            settings = db.query(Settings).first()
            enabled = bool(getattr(settings, "auto_backup_enabled", False))
            keep = int(getattr(settings, "auto_backup_keep", 50) or 50)
            offsite_target = getattr(settings, "offsite_backup_target", None) or ""
            telegram_backup_enabled = bool(getattr(settings, "telegram_backup_enabled", False))
        finally:
            db.close()

        if not enabled:
            return

        try:
            backup_path = await asyncio.to_thread(create_panel_backup, keep)
        except Exception as exc:
            logger.exception("Scheduled auto backup failed")
            log_event(None, "maintenance.backup", actor="auto", detail=f"Scheduled backup failed: {exc}")
            return

        if backup_path is None:
            logger.warning("Scheduled auto backup skipped: database file not found")
            log_event(None, "maintenance.backup", actor="auto", detail="Scheduled backup skipped: database file not found")
            return

        logger.info("Scheduled auto backup created: %s", backup_path.name)
        log_event(None, "maintenance.backup", actor="auto", detail=f"Backup created: {backup_path.name}")

        # Optional offsite copy of the fresh backup (rsync, fallback scp).
        if offsite_target.strip():
            from backend.operations.offsite_backup import push_offsite

            pushed = await asyncio.to_thread(push_offsite, backup_path, offsite_target)
            if pushed:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy pushed: {backup_path.name}")
            else:
                log_event(None, "maintenance.offsite_backup", actor="auto", detail=f"Offsite copy failed for {backup_path.name}")

        # Telegram is a separate opt-in destination. The bundle is encrypted
        # locally with a key unrelated to the bot token before upload.
        if telegram_backup_enabled:
            from backend.config import config as panel_config
            from backend.db import crud
            from backend.operations.telegram_backup import send_backup_document

            db = SessionLocal()
            try:
                settings = crud.get_settings(db)
                key = panel_config.BACKUP_ENCRYPT_KEY or ""
                result = await asyncio.to_thread(send_backup_document, backup_path, settings, key)
            finally:
                db.close()
            if result.ok:
                log_event(
                    None,
                    "maintenance.telegram_backup",
                    actor="auto",
                    detail=f"Encrypted Telegram copy delivered: {backup_path.name} message={result.message_id}",
                )
            else:
                log_event(
                    None,
                    "maintenance.telegram_backup",
                    actor="auto",
                    detail=f"Encrypted Telegram copy failed for {backup_path.name}: {result.error}",
                )
    except Exception:
        logger.exception("Scheduled auto backup job crashed")


def reschedule_auto_backup():
    """Re-register the daily auto-backup job from the current settings.

    Removes any existing ``auto_backup`` job, then adds it back with the
    configured time when auto backup is enabled. A no-op when the scheduler
    is not running. Called at startup and after a settings update.
    """
    scheduler = _scheduler
    if scheduler is None:
        return
    try:
        scheduler.remove_job("auto_backup")
    except Exception:
        # JobLookupError (nothing registered) is the common case; a stopped
        # scheduler is equally harmless here.
        pass

    try:
        from backend.db.models import Settings

        db = SessionLocal()
        try:
            settings = db.query(Settings).first()
            enabled = bool(getattr(settings, "auto_backup_enabled", False))
            raw_time = str(getattr(settings, "auto_backup_time", "") or "")
        finally:
            db.close()
    except Exception:
        logger.exception("Could not read auto backup settings")
        return

    if not enabled:
        return

    try:
        hour, minute = (int(part) for part in raw_time.split(":"))
    except (TypeError, ValueError):
        logger.warning("Auto backup not scheduled: invalid auto_backup_time %r", raw_time)
        return

    try:
        scheduler.add_job(
            auto_backup_job,
            CronTrigger(hour=hour, minute=minute),
            id="auto_backup",
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception:
        logger.exception("Could not register the auto backup job for %r", raw_time)
        return
    logger.info("Automatic backup scheduled daily at %02d:%02d", hour, minute)


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
        auto_prune_audit_job,
        CronTrigger(hour="*/6"),
        id="prune_audit_logs",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        auto_daily_alerts_job,
        CronTrigger(hour=9, minute=15),
        id="daily_alerts",
        replace_existing=True,
        misfire_grace_time=3600,
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
    # Auto backup is OFF by default; only registered when enabled in settings.
    reschedule_auto_backup()
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
    global _bot_process, _bot_disabled_until
    if _bot_process is None:
        return  # Bot was never started (no bot.main.py)
    rc = _bot_process.poll()
    if rc is None:
        _bot_disabled_until = None
        return
    if rc == 0:
        # Clean exit = disabled (no token or turned off in Settings).
        # Don't hot-loop: retry at most once per hour, at INFO level.
        import time

        now = time.monotonic()
        if _bot_disabled_until is not None and now < _bot_disabled_until:
            return
        _bot_disabled_until = now + _BOT_DISABLED_RETRY_SECONDS
        logger.info("Telegram bot disabled (no token or turned off) — will retry in 1h")
        return
    _bot_disabled_until = None
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
api.add_middleware(AssetCacheMiddleware, frontend_dir=frontend_build_path)

# ── URLPathMiddleware (MUST be added last — it wraps everything) ──
# This is the outermost middleware: it runs first on every request.
# When URLPATH is set, it strips /{urlpath}/ prefix and hides non-matching paths.
api.add_middleware(URLPathMiddleware)
