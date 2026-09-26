"""Read-only health surface for the panel.

Two views:

- ``/overview`` (owner only): a plain-English checklist covering the panel
  process, the SQLite database, node reachability (read from the in-memory
  live snapshot — no fan-out), TLS, disk space, and backups.
- ``/setup`` (owner or admin): first-run counters. Admins only see their own
  users, matching the rest of the panel's tenancy rules.

Every check runs defensively: a failure inside one check becomes an
``"error"`` entry in that check's result, never a 500 for the whole endpoint.
"""

import os
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from fastapi import APIRouter, Depends
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.auth.authz import require_owner
from backend.config import config
from backend.data_paths import DATA_DIR
from backend.db.engine import get_db
from backend.db.models import Node, User
from backend.operations.live import get_node_online, last_poll_ts
from backend.routers.tls import _cert_path, _classify_issuer, _key_path, _load_certificate
from backend.schema import ResponseModel
from backend.version import __version__

router = APIRouter(prefix="/health", tags=["Health"])

DB_PATH = DATA_DIR / "ovmanager.db"
BACKUP_DIR = DATA_DIR / "backups"

_STARTED_AT = time.time()

_SEVEN_DAYS = 7 * 24 * 60 * 60


def _entry(check_id: str, status: str, summary: str, hint: str = "", detail: dict | None = None) -> dict:
    """Build one checklist row. ``hint`` is only kept for warn/error."""
    return {
        "id": check_id,
        "status": status,
        "summary": summary,
        "hint": hint if status != "ok" else "",
        "detail": detail or {},
    }


def _fmt_gb(num_bytes: float) -> str:
    return f"{num_bytes / (1024**3):.1f} GB"


def _fmt_age(seconds: float) -> str:
    """Human-friendly age string ("5 minutes", "3 hours", "2 days")."""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{int(seconds)} seconds"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} minutes"
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours)} hours"
    return f"{int(hours / 24)} days"


def _check_panel(db: Session) -> dict:
    uptime = int(time.time() - _STARTED_AT)
    detail = {
        "version": __version__,
        "uptime_seconds": uptime,
        "port": config.PORT,
        "host": config.HOST,
    }
    return _entry(
        "panel",
        "ok",
        f"Panel version {__version__} has been running for {_fmt_age(uptime)} on port {config.PORT}.",
        detail=detail,
    )


def _check_database(db: Session) -> dict:
    if not DB_PATH.exists():
        return _entry(
            "database",
            "error",
            f"The database file was not found at {DB_PATH}.",
            "Restore a backup from the Maintenance page, or restart the panel so it can recreate the file.",
            detail={"path": str(DB_PATH), "size_bytes": None, "quick_check": None},
        )

    size = DB_PATH.stat().st_size
    result = db.execute(text("PRAGMA quick_check")).scalar()
    result_text = "ok" if result is None else str(result)
    detail = {"path": str(DB_PATH), "size_bytes": size, "quick_check": result_text}

    if result_text.lower() == "ok":
        return _entry(
            "database",
            "ok",
            f"The database file is {_fmt_gb(size)} and SQLite reports it as ok.",
            detail=detail,
        )
    return _entry(
        "database",
        "error",
        f"The database file is {_fmt_gb(size)} but SQLite reported a problem: {result_text}",
        "The database may be damaged. Restore the newest backup from the Maintenance page, then restart the panel.",
        detail=detail,
    )


def _check_nodes(db: Session) -> dict:
    nodes = db.query(Node).order_by(Node.id).all()
    total = len(nodes)
    online = get_node_online()

    node_list = []
    reachable = 0
    for node in nodes:
        is_up = bool(online.get(node.name, False))
        if is_up:
            reachable += 1
        node_list.append(
            {
                "name": node.name,
                "reachable": is_up,
                "latency_ms": None,
                "version": None,
            }
        )

    poll_ts = last_poll_ts()
    detail = {
        "total": total,
        "reachable": reachable,
        "last_poll_ts": poll_ts or None,
        "nodes": node_list,
    }

    if total == 0:
        return _entry(
            "nodes",
            "warn",
            "No nodes are configured yet.",
            "Add your first node on the Nodes page so users can connect.",
            detail=detail,
        )
    if reachable == 0:
        return _entry(
            "nodes",
            "warn",
            f"None of the {total} configured nodes answered the latest check.",
            "Open the Nodes page and test each node. Make sure the node service is running "
            "and that its address and API key are correct.",
            detail=detail,
        )
    if reachable < total:
        return _entry(
            "nodes",
            "warn",
            f"{reachable} of {total} nodes answered the latest check.",
            "One or more nodes are offline. Open the Nodes page and test the failing node.",
            detail=detail,
        )
    return _entry(
        "nodes",
        "ok",
        f"All {total} nodes answered the latest check.",
        detail=detail,
    )


def _check_tls(db: Session) -> dict:
    cert_file = (config.SSL_CERTFILE or "").strip()
    key_file = (config.SSL_KEYFILE or "").strip()
    detail = {
        "mode": None,
        "cert_file": cert_file or None,
        "key_file": key_file or None,
        "expires_in_days": None,
        "expires_at": None,
    }

    if not cert_file and not key_file:
        detail["mode"] = "disabled"
        return _entry(
            "tls",
            "warn",
            "TLS is turned off, so the panel is served over plain HTTP.",
            "Set SSL_CERTFILE and SSL_KEYFILE in the panel settings and restart to serve the panel over HTTPS.",
            detail=detail,
        )

    if not cert_file or not key_file:
        detail["mode"] = "misconfigured"
        missing = "SSL_CERTFILE" if not cert_file else "SSL_KEYFILE"
        return _entry(
            "tls",
            "error",
            f"TLS is only half configured: {missing} is missing.",
            "Set both SSL_CERTFILE and SSL_KEYFILE together, or clear both to run the panel without TLS.",
            detail=detail,
        )

    detail["mode"] = "files"
    missing_paths = [p for p in (cert_file, key_file) if not os.path.isfile(p)]
    if missing_paths:
        return _entry(
            "tls",
            "error",
            f"The TLS file was not found: {missing_paths[0]}",
            "The configured certificate or key file does not exist. Check the path, or re-run "
            "the installer to create new certificate files, then restart the panel.",
            detail=detail,
        )

    try:
        with open(cert_file, "rb") as fh:
            cert = x509.load_pem_x509_certificate(fh.read())
        expires = cert.not_valid_after_utc
    except Exception as exc:
        return _entry(
            "tls",
            "error",
            f"The TLS certificate could not be read: {exc}",
            "The certificate file is not a valid PEM certificate. Replace it with a valid certificate and restart the panel.",
            detail=detail,
        )

    days = (expires - datetime.now(UTC)).days
    detail["expires_in_days"] = days
    detail["expires_at"] = expires.isoformat()

    if days < 0:
        return _entry(
            "tls",
            "error",
            f"The TLS certificate expired {_fmt_age(-days * 86400)} ago.",
            "Renew the certificate (for example with certbot) and restart the panel.",
            detail=detail,
        )
    if days <= 14:
        return _entry(
            "tls",
            "warn",
            f"The TLS certificate expires in {days} days.",
            "Renew the certificate soon so browsers keep trusting the panel.",
            detail=detail,
        )
    return _entry(
        "tls",
        "ok",
        f"TLS is using {cert_file}; the certificate expires in {days} days.",
        detail=detail,
    )


def _check_disk(db: Session) -> dict:
    usage = shutil.disk_usage(str(DATA_DIR))
    free_gb = usage.free / (1024**3)
    total_gb = usage.total / (1024**3)
    percent_free = (usage.free / usage.total * 100) if usage.total else 0.0
    detail = {
        "path": str(DATA_DIR),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "free_percent": round(percent_free, 1),
    }

    if percent_free < 10:
        return _entry(
            "disk",
            "warn",
            f"Only {free_gb:.1f} GB of {total_gb:.1f} GB is free on the data disk.",
            "Less than 10 percent of the disk is free. Delete old backups or free up space so the panel can keep writing data.",
            detail=detail,
        )
    return _entry(
        "disk",
        "ok",
        f"{free_gb:.1f} GB free of {total_gb:.1f} GB on the data disk.",
        detail=detail,
    )


def _check_backups(db: Session) -> dict:
    detail = {"path": str(BACKUP_DIR), "newest": None, "age_seconds": None, "size_bytes": None}

    files = []
    if BACKUP_DIR.is_dir():
        files = [p for p in BACKUP_DIR.iterdir() if p.is_file() and (p.suffix == ".db" or p.name.endswith(".ovmbak"))]
    if not files:
        return _entry(
            "backups",
            "warn",
            "No database backup has been created yet.",
            "Create a backup from the Maintenance page to protect your data.",
            detail=detail,
        )

    newest = max(files, key=lambda p: p.stat().st_mtime)
    age = max(0.0, time.time() - newest.stat().st_mtime)
    detail["newest"] = newest.name
    detail["age_seconds"] = int(age)
    detail["size_bytes"] = newest.stat().st_size

    if age > _SEVEN_DAYS:
        return _entry(
            "backups",
            "warn",
            f"The newest backup ({newest.name}) is {_fmt_age(age)} old.",
            "Backups older than a week may be out of date. Create a fresh backup from the Maintenance page.",
            detail=detail,
        )
    return _entry(
        "backups",
        "ok",
        f"The newest backup is {newest.name}, created {_fmt_age(age)} ago.",
        detail=detail,
    )


_CHECK_BUILDERS = (
    ("panel", _check_panel),
    ("database", _check_database),
    ("nodes", _check_nodes),
    ("tls", _check_tls),
    ("disk", _check_disk),
    ("backups", _check_backups),
)


@router.get("/overview")
async def health_overview(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    """Owner-only read-only overview. Never writes to the database."""
    checks = []
    details: dict[str, dict] = {}
    for check_id, builder in _CHECK_BUILDERS:
        try:
            entry = builder(db)
        except Exception as exc:
            entry = _entry(
                check_id,
                "error",
                f"The {check_id} check could not run.",
                f"Try restarting the panel; if the problem continues, check the panel logs. Details: {exc}",
            )
        checks.append({key: entry[key] for key in ("id", "status", "summary", "hint")})
        details[check_id] = entry.get("detail") or {}
    return {"checks": checks, "details": details}


@router.get("/login-health", response_model=ResponseModel)
async def login_health(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    """Aggregate max-login/auth-failure health across users and nodes.

    Read-only aggregate (owner only). Lives in the health router — it is a
    read alongside /overview and /setup, not a maintenance write; it moved
    here from /maintenance/login-health (same response shape).
    """
    from backend.node.diagnostics import login_health_summary

    data = await login_health_summary(db, hours=hours)
    return ResponseModel(success=True, msg="Login health", data=data)


@router.get("/login-diagnostics/{username}", response_model=ResponseModel)
async def user_login_diagnostics(
    username: str, hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(require_owner)
):
    """Per-user drill-down (moved from /maintenance/login-diagnostics)."""
    from backend.node.diagnostics import login_diagnostics

    data = await login_diagnostics(username, db, hours=hours)
    return ResponseModel(success=True, msg="Login diagnostics", data=data)


@router.get("/setup")
async def health_setup(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """First-run checklist counters. Admins only count their own users."""
    node_count = int(db.query(func.count(Node.id)).scalar() or 0)
    active_node_count = int(db.query(func.count(Node.id)).filter(Node.status.is_(True)).scalar() or 0)

    user_query = db.query(func.count(User.id))
    if user.get("type") != "owner":
        user_query = user_query.filter(User.owner == user.get("username"))
    user_count = int(user_query.scalar() or 0)

    return {
        "has_node": node_count > 0,
        "has_user": user_count > 0,
        "has_active_node": active_node_count > 0,
        "node_count": node_count,
        "user_count": user_count,
    }


def _active_cert_path() -> Path | None:
    """The certificate uvicorn actually serves, mirroring ``main.py``.

    Panel-managed files in ``DATA_DIR/tls`` win when both are present; the
    ``SSL_CERTFILE`` / ``SSL_KEYFILE`` environment pair is the fallback.
    """
    if _cert_path().is_file() and _key_path().is_file():
        return _cert_path()
    cert_file = (config.SSL_CERTFILE or "").strip()
    key_file = (config.SSL_KEYFILE or "").strip()
    if cert_file and key_file and os.path.isfile(cert_file):
        return Path(cert_file)
    return None


@router.get("/tls")
async def health_tls(user: dict = Depends(get_current_user)):
    """Classify the panel certificate so the UI can hide the PWA install hint.

    Phones refuse to install over an untrusted (self-signed) certificate, so
    ``install_hint`` is only true for a trusted custom or Let's Encrypt cert.
    Missing or unreadable files answer ``"unknown"`` with the hint off.
    """
    cert_path = _active_cert_path()
    cert = _load_certificate(cert_path) if cert_path is not None else None
    if cert is None:
        return {"issued_by": "unknown", "install_hint": False}

    kind = _classify_issuer(cert)
    issued_by = "lets-encrypt" if kind == "Let's Encrypt" else kind
    if issued_by not in ("self-signed", "lets-encrypt", "custom"):
        issued_by = "unknown"
    return {"issued_by": issued_by, "install_hint": issued_by in ("lets-encrypt", "custom")}
