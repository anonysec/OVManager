import logging
import os
import sqlite3
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from sqlalchemy import create_engine
from sqlalchemy import text as _text
from sqlalchemy.orm import Session, sessionmaker

from backend.auth.authz import require_owner
from backend.data_paths import DATA_DIR
from backend.db.engine import engine, get_db
from backend.node.task import (
    clean_stale_sessions_all_nodes,
    sync_all_user_limits,
)
from backend.operations.audit import log_event
from backend.operations.backup_bundle import (
    BUNDLE_SUFFIX,
    BackupBundleError,
    create_bundle,
    extract_database,
    verify_bundle,
)
from backend.schema import ResponseModel

logger = logging.getLogger(__name__)

MAX_BACKUP_FILE_SIZE = 100 * 1024 * 1024  # 100 MB

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])

DB_DIR = DATA_DIR
DB_PATH = DB_DIR / "ovmanager.db"
BACKUP_DIR = DB_DIR / "backups"
_MAX_BACKUPS = 50  # keep at most N backups to prevent unbounded growth
_maintenance_lock = threading.RLock()


def create_panel_backup(keep: int | None = None, *, label: str = "backup") -> Path | None:
    """Serialize backup creation with restore/update-sensitive data work."""
    with _maintenance_lock:
        return _create_panel_backup_unlocked(keep, label=label)


def _create_panel_backup_unlocked(keep: int | None = None, *, label: str = "backup") -> Path | None:
    """Create a timestamped panel database backup and prune old ones.

    Shared by the owner-only POST route and the scheduled auto-backup job.
    Checkpoints the WAL first so the backup sees a consistent snapshot, then
    copies through the SQLite online-backup API (safe while writers are
    active). Returns the new backup path, or ``None`` when the database file
    does not exist; other failures raise to the caller.

    ``keep`` caps how many timestamped backups are retained (defaults to the
    module-wide ``_MAX_BACKUPS``).
    """
    if not DB_PATH.exists():
        return None

    max_backups = _MAX_BACKUPS if keep is None else max(1, int(keep))
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        conn.execute(_text("PRAGMA wal_checkpoint(TRUNCATE)"))
        conn.commit()

    fd, raw_snapshot = tempfile.mkstemp(prefix=".ovmanager-snapshot-", suffix=".db", dir=BACKUP_DIR)
    os.close(fd)
    snapshot = Path(raw_snapshot)
    os.chmod(snapshot, 0o600)
    try:
        _sqlite_backup(str(DB_PATH), str(snapshot))
        backup_path = create_bundle(snapshot, BACKUP_DIR, label=label)
    finally:
        snapshot.unlink(missing_ok=True)

    all_backups = sorted(
        BACKUP_DIR.glob(f"ovmanager-{label}-*{BUNDLE_SUFFIX}"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in all_backups[max_backups:]:
        try:
            old.unlink()
        except OSError:
            pass
    return backup_path


@router.post("/backup", response_model=ResponseModel)
def backup_database(user: dict = Depends(require_owner)):
    """Create a backup of the panel database (POST only).

    Exports a SQLite copy + config snapshot. Downloadable as .db file.
    Only owner can access this. Declared sync on purpose: FastAPI runs it in
    the threadpool, so a large database does not block the event loop.
    """

    try:
        backup_path = create_panel_backup()
        if backup_path is None:
            return ResponseModel(success=False, msg="Database file not found", data=None)
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


def _backup_files() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(
        (
            p
            for p in BACKUP_DIR.iterdir()
            if p.is_file() and (p.name.endswith(BUNDLE_SUFFIX) or p.suffix == ".db") and not p.name.startswith("restore_")
        ),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )


@router.get("/backup/download", response_class=FileResponse)
async def download_backup(user: dict = Depends(require_owner)):
    """Download the latest versioned bundle (or a legacy .db backup)."""

    backups = _backup_files()
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

    backups = _backup_files()
    if not backups:
        return ResponseModel(success=True, msg="No backups", data=[])

    files = []
    for b in backups:
        item = {
            "name": b.name,
            "size": b.stat().st_size,
            "modified": datetime.fromtimestamp(b.stat().st_mtime, tz=UTC).isoformat(),
            "format": "bundle" if b.name.endswith(BUNDLE_SUFFIX) else "legacy-db",
            "verified": None,
        }
        if b.name.endswith(BUNDLE_SUFFIX):
            try:
                manifest = await run_in_threadpool(verify_bundle, b)
                item.update(
                    verified=True,
                    app_version=manifest.get("app_version"),
                    created_at=manifest.get("created_at"),
                    format_version=manifest.get("format_version"),
                )
            except BackupBundleError as exc:
                item.update(verified=False, error=str(exc))
        files.append(item)
    return ResponseModel(success=True, msg="Backups listed", data=files)


@router.post("/backup/verify", response_model=ResponseModel)
async def verify_server_backup(
    filename: str = Form(...),
    user: dict = Depends(require_owner),
):
    """Re-verify a stored bundle without modifying panel state."""

    safe_name = _safe_filename(filename)
    if not safe_name or safe_name != filename or not safe_name.endswith(BUNDLE_SUFFIX):
        return ResponseModel(success=False, msg="Select a valid .ovmbak bundle", data=None)
    path = (BACKUP_DIR / safe_name).resolve()
    if not path.is_relative_to(BACKUP_DIR.resolve()) or not path.is_file():
        return ResponseModel(success=False, msg="Backup file not found", data=None)
    try:
        manifest = await run_in_threadpool(verify_bundle, path)
    except BackupBundleError as exc:
        log_event(None, "maintenance.backup.verify", actor=user.get("username"), detail=f"Verification failed: {safe_name}")
        return ResponseModel(success=False, msg=f"Backup verification failed: {exc}", data=None)
    log_event(None, "maintenance.backup.verify", actor=user.get("username"), detail=f"Verified: {safe_name}")
    return ResponseModel(
        success=True,
        msg="Backup verified",
        data={
            "filename": safe_name,
            "verified": True,
            "app_version": manifest.get("app_version"),
            "created_at": manifest.get("created_at"),
            "format_version": manifest.get("format_version"),
        },
    )


def _safe_filename(name: str | None) -> str:
    """Basename + allowlist sanitizer for backup uploads (no werkzeug).

    Keeps ASCII alphanumerics plus ``._-``; drops directories, backslash
    tricks and NUL bytes; rejects empty/all-dots results. Callers still
    resolve() the final path against BACKUP_DIR as defense in depth.
    """
    if not name:
        return ""
    base = os.path.basename(name.replace("\\", "/")).replace("\x00", "")
    cleaned = "".join(c for c in base if c.isascii() and (c.isalnum() or c in "._-"))
    if not cleaned or set(cleaned) <= {"."}:
        return ""
    return cleaned


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


def _remove_sqlite_sidecars(db_path: Path) -> None:
    """Delete -wal/-shm files so a swapped database cannot replay stale frames."""
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning("Could not remove %s: %s", sidecar, e)


def _apply_migrations_after_restore() -> None:
    """Bring a restored database up to date, or fail loudly.

    Restoring a backup from an older release must not serve requests against
    a schema with missing columns; migrations plus the schema check make that
    impossible (the caller rolls back to the pre-restore copy on failure).
    """
    from backend.db.migrations import migrate, verify_schema

    migrate()
    problems = verify_schema()
    if problems:
        raise RuntimeError("restored database failed schema verification: " + "; ".join(problems))


def _stage_restore_candidate(src_path: Path) -> Path:
    """Copy, migrate, and verify a restore candidate away from the live DB."""
    from backend.db.migrations import migrate, verify_schema

    fd, raw_candidate = tempfile.mkstemp(prefix=".restore-candidate-", suffix=".db", dir=DB_PATH.parent)
    os.close(fd)
    candidate = Path(raw_candidate)
    os.chmod(candidate, 0o600)
    try:
        copy2(src_path, candidate)
        conn = sqlite3.connect(str(candidate))
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                raise RuntimeError(f"candidate database integrity failed: {check[0] if check else 'no result'}")
        finally:
            conn.close()

        candidate_engine = create_engine(f"sqlite:///{candidate}", connect_args={"check_same_thread": False, "timeout": 30})
        maker = sessionmaker(bind=candidate_engine, autoflush=False, expire_on_commit=False)
        session = maker()
        try:
            migrate(session)
            problems = verify_schema(session)
            if problems:
                raise RuntimeError("candidate schema verification failed: " + "; ".join(problems))
        finally:
            session.close()
            candidate_engine.dispose()
        return candidate
    except Exception:
        candidate.unlink(missing_ok=True)
        raise


def _atomic_db_restore(src_path: Path, user: dict, detail: str) -> ResponseModel:
    """Transactionally stage, activate, verify, and roll back a database."""
    from backend.db.engine import restore_lock

    with _maintenance_lock:
        candidate: Path | None = None
        rollback_db: Path | None = None
        safety_bundle: Path | None = None
        activated = False
        try:
            candidate = _stage_restore_candidate(src_path)

            safety_bundle = _create_panel_backup_unlocked(keep=10, label="pre-restore")
            if safety_bundle is None:
                raise RuntimeError("current database is missing; safety backup could not be created")
            verify_bundle(safety_bundle)
            fd, raw_rollback = tempfile.mkstemp(prefix=".restore-rollback-", suffix=".db", dir=DB_DIR)
            os.close(fd)
            rollback_db = Path(raw_rollback)
            extract_database(safety_bundle, rollback_db)

            restore_lock.set()
            engine.dispose()
            os.replace(candidate, DB_PATH)
            candidate = None
            activated = True
            os.chmod(DB_PATH, 0o600)
            _remove_sqlite_sidecars(DB_PATH)

            _apply_migrations_after_restore()
            conn = sqlite3.connect(str(DB_PATH))
            try:
                check = conn.execute("PRAGMA quick_check").fetchone()
                if not check or check[0] != "ok":
                    raise RuntimeError(f"activated database integrity failed: {check[0] if check else 'no result'}")
            finally:
                conn.close()

            actor = user.get("username") if isinstance(user, dict) else str(user)
            log_event(None, "maintenance.restore", actor=actor, detail=f"{detail}; safety={safety_bundle.name}")
            return ResponseModel(
                success=True,
                msg="Database restored and verified successfully",
                data={"safety_backup": safety_bundle.name, "rolled_back": False},
            )
        except Exception as exc:
            logger.exception("Restore failed%s", " after activation; rolling back" if activated else " during staging")
            rolled_back = False
            if activated and rollback_db and rollback_db.exists():
                try:
                    engine.dispose()
                    tmp_path = DB_PATH.with_suffix(".db.rollback")
                    copy2(rollback_db, tmp_path)
                    os.replace(tmp_path, DB_PATH)
                    os.chmod(DB_PATH, 0o600)
                    _remove_sqlite_sidecars(DB_PATH)
                    _apply_migrations_after_restore()
                    rolled_back = True
                except Exception:
                    logger.exception("Rollback to the verified safety backup also failed")
            message = f"Invalid SQLite database: {exc}" if isinstance(exc, sqlite3.DatabaseError) else f"Restore failed: {exc}"
            return ResponseModel(
                success=False,
                msg=message,
                data={
                    "safety_backup": safety_bundle.name if safety_bundle else None,
                    "rolled_back": rolled_back,
                    "data_safe": (not activated) or rolled_back,
                },
            )
        finally:
            if candidate:
                candidate.unlink(missing_ok=True)
            if rollback_db:
                rollback_db.unlink(missing_ok=True)
            engine.dispose()
            restore_lock.clear()


def _restore_artifact(src_path: Path, user: dict, detail: str) -> ResponseModel:
    """Restore a verified bundle or a backward-compatible legacy SQLite file."""

    if src_path.name.endswith(BUNDLE_SUFFIX):
        fd, raw_db = tempfile.mkstemp(prefix=".ovmanager-restore-", suffix=".db", dir=BACKUP_DIR)
        os.close(fd)
        extracted = Path(raw_db)
        try:
            extract_database(src_path, extracted)
            return _atomic_db_restore(extracted, user, detail)
        except BackupBundleError as exc:
            return ResponseModel(success=False, msg=f"Invalid backup bundle: {exc}", data=None)
        finally:
            extracted.unlink(missing_ok=True)
    return _atomic_db_restore(src_path, user, detail)


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
            src_path = (BACKUP_DIR / restore_from_server).resolve()
            backup_dir_resolved = BACKUP_DIR.resolve()
            if not src_path.is_relative_to(backup_dir_resolved):
                return ResponseModel(success=False, msg="Invalid backup path", data=None)
            if not src_path.exists() or not src_path.is_file():
                return ResponseModel(success=False, msg=f"Backup file '{restore_from_server}' not found", data=None)
            if not (restore_from_server.endswith(".db") or restore_from_server.endswith(BUNDLE_SUFFIX)):
                return ResponseModel(success=False, msg="Backup file must be an .ovmbak bundle or legacy .db file", data=None)
            return await run_in_threadpool(
                _restore_artifact, src_path, user, f"Restored from server backup: {restore_from_server}"
            )

        if file is None or not file.filename or not (file.filename.endswith(".db") or file.filename.endswith(BUNDLE_SUFFIX)):
            return ResponseModel(success=False, msg="Backup file must be an .ovmbak bundle or legacy .db file", data=None)

        safe_name = _safe_filename(file.filename)
        if not safe_name:
            return ResponseModel(success=False, msg="Invalid filename", data=None)

        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = BACKUP_DIR / f"restore_{safe_name}.part"
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

        result = await run_in_threadpool(_restore_artifact, tmp_path, user, f"Restored from: {file.filename}")

        tmp_path.unlink(missing_ok=True)
        return result
    except Exception as e:
        return ResponseModel(success=False, msg=f"Restore failed: {e}", data=None)


@router.post("/sync-limits", response_model=ResponseModel)
async def sync_limits(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await sync_all_user_limits(db)
    log_event(
        db,
        "maintenance.sync_limits",
        actor=user.get("username"),
        detail=f"{data.get('success')}/{data.get('total')} synced, {data.get('skipped', 0)} unchanged",
    )
    return ResponseModel(success=True, msg="Login limits synced", data=data)


@router.post("/clean-stale", response_model=ResponseModel)
async def clean_stale(db: Session = Depends(get_db), user: dict = Depends(require_owner)):
    data = await clean_stale_sessions_all_nodes(db)
    log_event(db, "maintenance.clean_stale", actor=user.get("username"), detail=f"removed={data.get('removed_total')}")
    return ResponseModel(success=True, msg="Stale sessions cleaned", data=data)
