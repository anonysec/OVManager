from datetime import datetime
from pathlib import Path
from shutil import copy2
import os
import sqlite3
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db.engine import BASE_DIR, engine, get_db
from backend.node.task import clean_global_mlogin_registry, clean_stale_sessions_all_nodes, login_diagnostics, login_health_summary, sync_all_user_limits
from backend.operations.audit import log_event
from backend.schema.output import ResponseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

DB_DIR = BASE_DIR.parent.parent / "data"
DB_PATH = DB_DIR / "ov-panel.db"
BACKUP_DIR = DB_DIR / "backups"


@router.get("/backup", response_model=ResponseModel)
async def backup_database(user: dict = Depends(get_current_user)):
    """Create a backup of the panel database.

    Exports a SQLite copy + config snapshot. Downloadable as .db file.
    Only main_admin can access this.
    """
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)

    if not DB_PATH.exists():
        return ResponseModel(success=False, msg="Database file not found", data=None)

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"ovpanel_backup_{ts}.db"
        # SQLite doesn't like being copied while open; use WAL checkpoint
        with engine.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE, full=1)")
            conn.commit()
        copy2(str(DB_PATH), str(backup_path))
        log_event(
            None,
            "maintenance.backup",
            actor=user.get("username"),
            detail=f"Backup created: {backup_path.name}",
        )
        return ResponseModel(
            success=True,
            msg="Backup created successfully",
            data={"filename": backup_path.name, "path": str(backup_path)},
        )
    except Exception as e:
        return ResponseModel(success=False, msg=f"Backup failed: {e}", data=None)


@router.get("/backup/download", response_class=FileResponse)
async def download_backup(user: dict = Depends(get_current_user)):
    """Download the latest backup as a .db file."""
    if user["type"] != "main_admin":
        raise HTTPException(status_code=403, detail="Unauthorized")

    if not BACKUP_DIR.exists():
        raise HTTPException(status_code=404, detail="No backups found")

    backups = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        raise HTTPException(status_code=404, detail="No backups found")

    latest = backups[0]
    return FileResponse(
        path=str(latest),
        filename=latest.name,
        media_type="application/octet-stream",
    )


@router.get("/backup/list", response_model=ResponseModel)
async def list_backups(user: dict = Depends(get_current_user)):
    """List all available backups."""
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)

    if not BACKUP_DIR.exists():
        return ResponseModel(success=True, msg="No backups", data=[])

    backups = sorted(BACKUP_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    files = []
    for b in backups:
        files.append({
            "name": b.name,
            "size": b.stat().st_size,
            "modified": datetime.fromtimestamp(b.stat().st_mtime).isoformat(),
        })
    return ResponseModel(success=True, msg="Backups listed", data=files)


def _atomic_db_restore(src_path: Path, user: dict, detail: str) -> ResponseModel:
    """Atomically restore DB from src_path to DB_PATH using os.replace.

    Creates a backup of current DB first, then atomically swaps.
    """
    # Validate it's a SQLite DB
    try:
        conn = sqlite3.connect(str(src_path))
        conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        conn.close()
    except Exception as e:
        return ResponseModel(success=False, msg=f"Invalid SQLite database: {e}", data=None)

    # Create backup of current DB before restore (in case restore fails or needs rollback)
    pre_restore_backup = None
    if DB_PATH.exists():
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        pre_restore_backup = BACKUP_DIR / f"pre_restore_backup_{ts}.db"
        try:
            # Checkpoint WAL first
            with engine.connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE, full=1)")
                conn.commit()
            copy2(str(DB_PATH), str(pre_restore_backup))
        except Exception as e:
            logger.warning(f"Failed to create pre-restore backup: {e}")

    # Close all connections and dispose engine
    engine.dispose()

    try:
        # Atomic replace: write to temp file next to target, then os.replace
        # This is atomic on POSIX (single filesystem rename)
        tmp_path = DB_PATH.with_suffix(".db.tmp")
        copy2(str(src_path), str(tmp_path))
        # Atomic swap
        os.replace(str(tmp_path), str(DB_PATH))

        log_event(
            None,
            "maintenance.restore",
            actor=user.get("username"),
            detail=detail,
        )
        return ResponseModel(success=True, msg="Database restored successfully", data=None)
    except Exception as e:
        # Try to restore pre-restore backup if it exists
        if pre_restore_backup and pre_restore_backup.exists():
            try:
                os.replace(str(pre_restore_backup), str(DB_PATH))
            except Exception:
                pass
        return ResponseModel(success=False, msg=f"Restore failed: {e}", data=None)


@router.post("/backup/restore", response_model=ResponseModel)
async def restore_backup(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    restore_from_server: str = None,
):
    """Restore the database from a backup file.

    The panel will be stopped during restore. The backup file must be a valid SQLite DB.
    Only main_admin can access this.

    If `restore_from_server` is provided (as a form field), the backup is read
    from the server's backup directory instead of the uploaded file.
    """
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)

    try:
        if restore_from_server:
            # Restore from a backup file already on the server
            src_path = BACKUP_DIR / restore_from_server
            if not src_path.exists() or not src_path.is_file():
                return ResponseModel(success=False, msg=f"Backup file '{restore_from_server}' not found", data=None)
            if not restore_from_server.endswith(".db"):
                return ResponseModel(success=False, msg="Backup file must be a .db file", data=None)
            return _atomic_db_restore(src_path, user, f"Restored from server backup: {restore_from_server}")

        # Original path: restore from uploaded file
        if not file.filename.endswith(".db"):
            return ResponseModel(success=False, msg="Backup file must be a .db file", data=None)

        # Save uploaded file temporarily
        tmp_path = BACKUP_DIR / f"restore_{file.filename}"
        content = await file.read()
        tmp_path.write_bytes(content)

        result = _atomic_db_restore(tmp_path, user, f"Restored from: {file.filename}")

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)
        return result
    except Exception as e:
        return ResponseModel(success=False, msg=f"Restore failed: {e}", data=None)


@router.get("/login-health", response_model=ResponseModel)
async def login_health(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    data = await login_health_summary(db, hours=hours)
    return ResponseModel(success=True, msg="Login health", data=data)


@router.post("/sync-limits", response_model=ResponseModel)
async def sync_limits(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)
    data = await sync_all_user_limits(db)
    log_event(db, "maintenance.sync_limits", actor=user.get("username"), detail=f"{data.get('success')}/{data.get('total')} synced")
    return ResponseModel(success=True, msg="Login limits synced", data=data)


@router.post("/clean-stale", response_model=ResponseModel)
async def clean_stale(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)
    data = await clean_stale_sessions_all_nodes(db)
    log_event(db, "maintenance.clean_stale", actor=user.get("username"), detail=f"removed={data.get('removed_total')}")
    return ResponseModel(success=True, msg="Stale sessions cleaned", data=data)


@router.post("/clean-global-registry", response_model=ResponseModel)
async def clean_global_registry(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    if user["type"] != "main_admin":
        return ResponseModel(success=False, msg="Unauthorized", data=None)
    data = await clean_global_mlogin_registry(db)
    log_event(db, "maintenance.clean_global_registry", actor=user.get("username"), detail=f"removed={len(data.get('removed') or [])}")
    return ResponseModel(success=True, msg="Global login registry cleaned", data=data)


@router.get("/login-diagnostics/{username}", response_model=ResponseModel)
async def user_login_diagnostics(username: str, hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    data = await login_diagnostics(username, db, hours=hours)
    return ResponseModel(success=True, msg="Login diagnostics", data=data)