import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from backend.operations.daily_checks import enforce_user_limits, check_user_used_traffic
from backend.operations.metrics import collect_metrics
from backend.node.task import clean_stale_sessions_all_nodes, sync_all_user_limits
from backend.db.engine import SessionLocal
from backend.config import config
from backend.routers import all_routers
from backend.routers.sub import router as subscription_router
from backend.version import __version__
from backend.tls_config import TLSConfig


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
        db.commit()
    finally:
        db.close()


URLPATH = (config.URLPATH or "").strip("/")
API_PREFIX = f"/{URLPATH}/api" if URLPATH else "/api"
DOC_PREFIX = f"/{URLPATH}" if URLPATH else ""

# TLS Configuration - Load from environment, support Let's Encrypt via imkoris.info
try:
    tls_config = TLSConfig.get_ssl_config()
except Exception:
    tls_config = {"cert_file": "", "key_file": "", "acme_enabled": False}

ssl_keyfile = tls_config.get("key_file") or None
ssl_certfile = tls_config.get("cert_file") or None

api = FastAPI(
    title="OVPanel API",
    description="API for managing OVPanel",
    version=__version__,
    docs_url=f"{DOC_PREFIX}/doc" if config.DOC else None,
    openapi_url=f"{DOC_PREFIX}/openapi.json" if config.DOC else None,
)

api.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@api.get(f"{API_PREFIX}/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "version": __version__}


@api.get("/health", include_in_schema=False)
async def health_check_public():
    return {"status": "ok", "version": __version__}


frontend_build_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_path = os.path.join(frontend_build_path, "assets")
if os.path.isdir(assets_path):
    api.mount(
        f"/{URLPATH}/assets" if URLPATH else "/assets",
        StaticFiles(directory=assets_path),
        name="assets",
    )


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


@api.on_event("startup")
async def startup_event():
    try:
        _run_migrations()
    except Exception as e:
        print("migration warning:", e)
    start_scheduler()


for router in all_routers:
    api.include_router(prefix=API_PREFIX, router=router)

api.include_router(subscription_router, prefix=f"/{URLPATH}" if URLPATH else "")


async def _serve_react():
    index_path = os.path.join(frontend_build_path, "index.html")
    return FileResponse(
        index_path,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


if URLPATH:
    @api.get(f"/{URLPATH}")
    @api.get(f"/{URLPATH}/{{path:path}}")
    async def serve_react_path():
        return await _serve_react()

    @api.get("/")
    async def root_redirect():
        return RedirectResponse(url=f"/{URLPATH}")
else:
    @api.get("/")
    @api.get("/{path:path}")
    async def serve_react_root(path: str = ""):
        return await _serve_react()
