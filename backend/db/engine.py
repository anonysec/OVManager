import os
import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from backend.data_paths import DATA_DIR

BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = f"sqlite:///{DATA_DIR / 'ovmanager.db'}"

restore_lock = threading.Event()

_TRUTHY = ("1", "true", "yes", "on")


def _low_resource_cache_size() -> int:
    """Page cache: 32MiB normally, 8MiB on a 1GB box (perf.low_resource).

    Read with a bare sqlite3 connection and never with SessionLocal: this runs
    inside the connect event, where a second SQLAlchemy connection deadlocks
    against the one being established (migrate() holds its first write, the
    nested reader waits on it, and the connect never finishes). Same key and
    truthy parse as ``backend.config.low_resource_enabled``; a miss, a missing
    table or a busy database all read as the default — the pragma must never
    stop a connection from opening.
    """
    import sqlite3

    env = os.getenv("OVMANAGER_LOW_RESOURCE", "").strip().lower()
    if env:
        return -8192 if env in _TRUTHY else -32768
    try:
        conn = sqlite3.connect(str(DATA_DIR / "ovmanager.db"), timeout=1.0)
        try:
            row = conn.execute("SELECT value FROM settings_kv WHERE key = 'perf.low_resource'").fetchone()
        finally:
            conn.close()
    except Exception:
        return -32768
    if row is None:
        return -32768
    return -8192 if str(row[0]).strip().lower() in _TRUTHY else -32768


engine = create_engine(
    url=DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    poolclass=NullPool,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute(f"PRAGMA cache_size={_low_resource_cache_size()}")
    cursor.execute("PRAGMA mmap_size=268435456")
    cursor.close()


Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
