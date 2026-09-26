"""OVManager FastAPI composition root.

Thin by design: middlewares live in :mod:`backend.middlewares`, background
jobs in :mod:`backend.scheduler`, bot supervision in
:mod:`backend.bot_supervisor`. This module wires them together (lifespan,
routes, static assets, SPA fallback) and re-exports the names the test
suite and routers import from here.
"""

from __future__ import annotations

import mimetypes
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.bot_supervisor import start_bot
from backend.config import config
from backend.data_paths import DATA_DIR
from backend.db.exceptions import ConflictError, NotFoundError, ValidationError
from backend.db.migrations import migrate
from backend.logger import logger
from backend.middlewares import (
    CSP_POLICY,  # noqa: F401  (re-exported: tests pin the hash via backend.app)
    AssetCacheMiddleware,
    CSRFProtectionMiddleware,
    SecurityHeadersMiddleware,
)
from backend.routers import all_routers
from backend.routers.sub import router as subscription_router
from backend.scheduler import (
    auto_backup_job,  # noqa: F401  (re-exported for tests/callers)
    reschedule_auto_backup,  # noqa: F401  (re-exported: setting router, tests)
    start_scheduler,
)
from backend.tls_config import TLSConfig
from backend.urlpath import URLPathMiddleware
from backend.urlpath import get_urlpath as _get_urlpath
from backend.version import __version__

__all__ = [
    "api",
    "health_check",
    "reschedule_auto_backup",
    "auto_backup_job",
    "start_scheduler",
    "start_bot",
    "AssetCacheMiddleware",
    "SecurityHeadersMiddleware",
    "CSRFProtectionMiddleware",
    "CSP_POLICY",
    "frontend_build_path",
    "_run_migrations",
    "_read_index_html",
]


def _run_migrations():
    """Bring the database up to the current schema version.

    All migration logic lives in :mod:`backend.db.migrations`; this is only the
    startup hook. It raises on failure so a half-migrated database stops the
    panel instead of serving requests against a broken schema.
    """
    migrate()


tls_config = TLSConfig.get_ssl_config()
ssl_keyfile = tls_config.get("key_file") or None
ssl_certfile = tls_config.get("cert_file") or None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown via the modern lifespan API."""
    _run_migrations()
    from backend.db.engine import SessionLocal as _SL
    from backend.operations.audit import ensure_audit_table

    _db = _SL()
    try:
        ensure_audit_table(_db)
        from backend.operations.metrics import ensure_metrics_tables
        from backend.operations.usage_history import ensure_daily_table

        ensure_daily_table(_db)
        ensure_metrics_tables(_db)
    finally:
        _db.close()
    if not (DATA_DIR / "update-maintenance").is_file():
        start_scheduler()
        start_bot()
    else:
        logger.info("Update verification mode: scheduler and bot are paused")
    yield
    import backend.bot_supervisor as _bot_mod
    import backend.scheduler as _sched_mod

    if _sched_mod._scheduler and _sched_mod._scheduler.running:
        _sched_mod._scheduler.shutdown(wait=False)
    _sched_mod._scheduler = None
    if _bot_mod._bot_process and _bot_mod._bot_process.poll() is None:
        _bot_mod._bot_process.terminate()
        try:
            _bot_mod._bot_process.wait(timeout=5)
        except Exception:
            _bot_mod._bot_process.kill()
    _bot_mod._bot_process = None


api = FastAPI(
    title="OVManager API",
    description="API for managing OVManager",
    version=__version__,
    docs_url="/doc" if config.DOC else None,
    openapi_url="/openapi.json" if config.DOC else None,
    lifespan=lifespan,
)


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

    return JSONResponse(status_code=422, content={"detail": str(exc)})


_allow_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
api.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)


@api.get("/health", tags=["Health"])
async def health_check(request: Request):
    if request.headers.get("sec-fetch-mode") == "navigate" and "text/html" in request.headers.get("accept", ""):
        from fastapi.responses import HTMLResponse

        html = _read_index_html()
        if html is not None:
            return HTMLResponse(html)
    client = request.client.host if request.client else ""
    data: dict = {"status": "ok"}
    if client in ("127.0.0.1", "::1", "localhost"):
        data["version"] = __version__
    return data


frontend_build_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_path = os.path.join(frontend_build_path, "assets")

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")

if os.path.isdir(assets_path):
    api.mount("/assets", StaticFiles(directory=assets_path), name="assets")

_fonts_path = os.path.join(frontend_build_path, "fonts")
if os.path.isdir(_fonts_path):
    api.mount("/fonts", StaticFiles(directory=_fonts_path), name="fonts")

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


for router in all_routers:
    api.include_router(prefix="/api", router=router)

api.include_router(subscription_router)


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
    base_href = f"/{urlpath}/" if urlpath else "/"
    if "<base " not in html:
        html = html.replace("<head>", f'<head>\n    <base href="{base_href}" />', 1)
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@api.get("/")
async def spa_root():
    return await _serve_react()


@api.get("/{path:path}", include_in_schema=False)
async def spa_catchall(path: str):
    if path.startswith(("api/", "doc", "openapi.json", "health", "assets/", "sub/")):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await _serve_react()


api.add_middleware(SecurityHeadersMiddleware)
api.add_middleware(CSRFProtectionMiddleware)
api.add_middleware(AssetCacheMiddleware, frontend_dir=frontend_build_path)

api.add_middleware(URLPathMiddleware)
