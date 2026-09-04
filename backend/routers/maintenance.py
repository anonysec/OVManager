# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import text as _text
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename

from backend.auth.authz import require_owner
from backend.data_paths import DATA_DIR
from backend.db.engine import engine, get_db
from backend.node.task import (
    clean_global_mlogin_registry,
    clean_stale_sessions_all_nodes,
    login_diagnostics,
    login_health_summary,
    sync_all_user_limits,
)
from backend.operations.audit import log_event
from backend.schema.output import ResponseModel

logger = logging.getLogger(__name__)

MAX_BACKUP_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

DB_DIR = DATA_DIR
DB_PATH = DB_DIR / "ovmanager.db"
BACKUP_DIR = DB_DIR / "backups"
_MAX_BACKUPS = 50  # keep at most N backups to prevent unbounded growth


@router.get("/backup", response_model=ResponseModel)
@router.post("/backup", response_model=ResponseModel)
async def backup_database(user: dict = Depends(require_owner)):
    """Create a backup of the panel database.

    Exports a SQLite copy + config snapshot. Downloadable as .db file.
    Only owner can access this.

    Supports both GET (legacy panel builds) and POST (REST-correct create).
    """

    if not DB_PATH.exists():
        return ResponseModel(success=False, msg="Database file not found", data=None)

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"ovmanager_backup_{ts}.db"
        # Checkpoint WAL so the backup sees a consistent snapshot, then use
        # the SQLite online-backup API instead of a raw file copy (safe
        # while writers are active).
        with engine.connect() as conn:
            conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
            conn.commit()
        _sqlite_backup(str(DB_PATH), str(backup_path))
        # Prune old backups — keep only the most recent _MAX_BACKUPS
        all_backups = sorted(
            BACKUP_DIR.glob("ovmanager_backup_*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in all_backups[_MAX_BACKUPS:]:
            try:
                old.unlink()
            except OSError:
                pass
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
async def download_backup(user: dict = Depends(require_owner)):
    """Download the latest backup as a .db file."""

    if not BACKUP_DIR.exists():
        raise HTTPException(status_code=404, detail="No backups found")

    backups = sorted(
        (p for p in BACKUP_DIR.iterdir() if p.is_file() and p.suffix == ".db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not backups:
        raise HTTPException(status_code=404, detail="No backups found")

    latest = backups[0]
    return FileResponse(
        path=str(latest),
        filename=latest.name,
        media_type="application/octet-stream",
    )


@router.get("/backup/list", response_model=ResponseModel)
async def list_backups(user: dict = Depends(require_owner)):
    """List all available backups."""

    if not BACKUP_DIR.exists():
        return ResponseModel(success=True, msg="No backups", data=[])

    backups = sorted(
        (p for p in BACKUP_DIR.iterdir() if p.is_file() and p.suffix == ".db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    files = []
    for b in backups:
        files.append(
            {
                "name": b.name,
                "size": b.stat().st_size,
                "modified": datetime.fromtimestamp(b.stat().st_mtime, tz=UTC).isoformat(),
            }
        )
    return ResponseModel(success=True, msg="Backups listed", data=files)


def _sqlite_backup(src: str, dst: str) -> None:
    """Online backup via the SQLite backup API (consistent under writers)."""
    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
    try:
        dst_conn = sqlite3.connect(dst, timeout=30)
        try:
            src_conn.backup(dst_conn)
            dst_conn.commit()
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


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
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        pre_restore_backup = BACKUP_DIR / f"pre_restore_backup_{ts}.db"
        try:
            # Checkpoint WAL first
            with engine.connect() as conn:
                conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
                conn.commit()
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            _sqlite_backup(str(DB_PATH), str(pre_restore_backup))
        except Exception as e:
            logger.warning("Failed to create pre-restore backup: %s", e)

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
    file: UploadFile | None = File(default=None),
    user: dict = Depends(require_owner),
    restore_from_server: str | None = Form(default=None),
):
    """Restore the database from a backup file.

    The panel will be stopped during restore. The backup file must be a valid SQLite DB.
    Only owner can access this.

    If `restore_from_server` is provided (as a form field), the backup is read
    from the server's backup directory instead of the uploaded file.
    """

    try:
        if restore_from_server:
            # Restore from a backup file already on the server
            # Security: resolve and verify the path stays within BACKUP_DIR
            src_path = (BACKUP_DIR / restore_from_server).resolve()
            backup_dir_resolved = BACKUP_DIR.resolve()
            if not src_path.is_relative_to(backup_dir_resolved):
                return ResponseModel(success=False, msg="Invalid backup path", data=None)
            if not src_path.exists() or not src_path.is_file():
                return ResponseModel(success=False, msg=f"Backup file '{restore_from_server}' not found", data=None)
            if not restore_from_server.endswith(".db"):
                return ResponseModel(success=False, msg="Backup file must be a .db file", data=None)
            return _atomic_db_restore(src_path, user, f"Restored from server backup: {restore_from_server}")

        # Original path: restore from uploaded file
        if file is None or not file.filename or not file.filename.endswith(".db"):
            return ResponseModel(success=False, msg="Backup file must be a .db file", data=None)

        # Sanitize filename to prevent path traversal
        safe_name = secure_filename(file.filename)
        if not safe_name:
            return ResponseModel(success=False, msg="Invalid filename", data=None)

        # Stream to disk with an enforced size cap — never buffer the whole
        # upload in memory (previous code did await file.read() first).
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = BACKUP_DIR / f"restore_{safe_name}.part"
        # Ensure tmp_path stays inside BACKUP_DIR
        try:
            tmp_path.resolve().relative_to(BACKUP_DIR.resolve())
        except ValueError:
            return ResponseModel(success=False, msg="Invalid backup path", data=None)

        total = 0
        try:
            with open(tmp_path, "wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)  # 1 MB
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_BACKUP_FILE_SIZE:
                        out.close()
                        tmp_path.unlink(missing_ok=True)
                        return ResponseModel(
                            success=False,
                            msg=f"File too large (max {MAX_BACKUP_FILE_SIZE} bytes)",
                            data=None,
                        )
                    out.write(chunk)
                out.flush()
                try:
                    os.fsync(out.fileno())
                except OSError:
                    pass
        except Exception as e:
            tmp_path.unlink(missing_ok=True)
            return ResponseModel(success=False, msg=f"Upload failed: {e}", data=None)

        final_tmp = BACKUP_DIR / f"restore_{safe_name}"
        try:
            final_tmp.resolve().relative_to(BACKUP_DIR.resolve())
        except ValueError:
            tmp_path.unlink(missing_ok=True)
            return ResponseModel(success=False, msg="Invalid backup path", data=None)
        os.replace(str(tmp_path), str(final_tmp))
        tmp_path = final_tmp

        result = _atomic_db_restore(tmp_path, user, f"Restored from: {file.filename}")

        # Clean up temp file
        tmp_path.unlink(missing_ok=True)
        return result
    except Exception as e:
        return ResponseModel(success=False, msg=f"Restore failed: {e}", data=None)


@router.get("/login-health", response_model=ResponseModel)
async def login_health(hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await login_health_summary(db, hours=hours)
    return ResponseModel(success=True, msg="Login health", data=data)


@router.post("/sync-limits", response_model=ResponseModel)
async def sync_limits(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await sync_all_user_limits(db)
    log_event(
        db,
        "maintenance.sync_limits",
        actor=user.get("username"),
        detail=f"{data.get('success')}/{data.get('total')} synced",
    )
    return ResponseModel(success=True, msg="Login limits synced", data=data)


@router.post("/clean-stale", response_model=ResponseModel)
async def clean_stale(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await clean_stale_sessions_all_nodes(db)
    log_event(db, "maintenance.clean_stale", actor=user.get("username"), detail=f"removed={data.get('removed_total')}")
    return ResponseModel(success=True, msg="Stale sessions cleaned", data=data)


@router.post("/clean-global-registry", response_model=ResponseModel)
async def clean_global_registry(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await clean_global_mlogin_registry(db)
    log_event(
        db,
        "maintenance.clean_global_registry",
        actor=user.get("username"),
        detail=f"removed={len(data.get('removed') or [])}",
    )
    return ResponseModel(success=True, msg="Global login registry cleaned", data=data)


@router.get("/login-diagnostics/{username}", response_model=ResponseModel)
async def user_login_diagnostics(
    username: str, hours: int = 8, db: Session = Depends(get_db), user: dict = Depends(require_owner)
):
    data = await login_diagnostics(username, db, hours=hours)
    return ResponseModel(success=True, msg="Login diagnostics", data=data)
