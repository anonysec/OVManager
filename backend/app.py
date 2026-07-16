import os

from fastapi import FastAPI
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


# Normalize the configured URL path (strip slashes). Empty -> served at root.
URLPATH = (config.URLPATH or "").strip("/")

# Dynamic API prefix support (for URLPATH subpath installs)
# This ensures /dash/api/login, /myapp/api/users etc. work correctly.
API_PREFIX = f"/{URLPATH}/api" if URLPATH else "/api"
DOC_PREFIX = f"/{URLPATH}" if URLPATH else ""

api = FastAPI(
    title="OVPanel API",
    description="API for managing OVPanel",
    version=__version__,
    docs_url=f"{DOC_PREFIX}/doc" if config.DOC else None,
    openapi_url=f"{DOC_PREFIX}/openapi.json" if config.DOC else None,
)

@api.get(f"{API_PREFIX}/health", tags=["Health"])
async def health_check():
    """Simple health check endpoint."""
    return {"status": "ok", "version": __version__}

frontend_build_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
assets_path = os.path.join(frontend_build_path, "assets")
if os.path.isdir(assets_path):
    api.mount(
        f"/{URLPATH}/assets" if URLPATH else "/assets",
        StaticFiles(directory=assets_path),
        name="assets",
    )

api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    """This function starts scheduled maintenance tasks."""
    # Scheduled jobs can perform network I/O against nodes and then write to
    # SQLite. Prevent overlapping copies of the same job from piling up if a
    # node is slow, which reduces write contention and avoids locked database
    # errors during admin UI activity.
    scheduler = AsyncIOScheduler(job_defaults={"coalesce": True, "max_instances": 1})
    scheduler.add_job(
        check_user_used_traffic,
        CronTrigger(minute="*/5"),   # reduced frequency → significantly lower CPU/RAM
        id="check_user_used_traffic",
        replace_existing=True,
        misfire_grace_time=60,
    )

    scheduler.add_job(
        enforce_user_limits,
        CronTrigger(minute="*/10"),  # reduced frequency
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
    # Start serving immediately. Maintenance jobs are scheduled below; running
    # them synchronously during startup can block the panel when a node is
    # powered off or removed by the ISP.
    start_scheduler()


for router in all_routers:
    api.include_router(prefix=API_PREFIX, router=router)

api.include_router(subscription_router, prefix=f"/{URLPATH}" if URLPATH else "")


async def _serve_react():
    index_path = os.path.join(frontend_build_path, "index.html")
    return FileResponse(index_path)


if URLPATH:
    # Serve the SPA under the configured path.
    @api.get(f"/{URLPATH}")
    @api.get(f"/{URLPATH}/{{path:path}}")
    async def serve_react_path():
        return await _serve_react()

    # Redirect the bare root to the panel path so users don't have to know it.
    @api.get("/")
    async def root_redirect():
        return RedirectResponse(url=f"/{URLPATH}")
else:
    # No path configured: serve the SPA directly at the root.
    @api.get("/")
    @api.get("/{path:path}")
    async def serve_react_root(path: str = ""):
        return await _serve_react()
