import threading
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from backend.data_paths import DATA_DIR

BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = f"sqlite:///{DATA_DIR / 'ovmanager.db'}"

restore_lock = threading.Event()

# Resolved once per process, at import — the connect hook below runs while a
# connection is being established and must not open another reader: a nested
# SQLAlchemy session deadlocks against the write migrate() holds (seen as a
# suite hang), and a bare sqlite3 handle was the same bet pointed elsewhere.
# The flag is a startup setting, like the worker's triggers: flipping it in
# the panel applies on the next restart, when this is read again.
_low_resource = False


def load_low_resource_flag() -> bool:
    """Read ``perf.low_resource`` once through the normal session and store it.

    The startup read every process shares (web, worker, CLI): env override
    first, then settings_kv, through ``config.low_resource_enabled`` — one
    code path for the parse, and no table yet just reads as the default.
    """
    global _low_resource
    try:
        from backend.config import low_resource_enabled

        _low_resource = bool(low_resource_enabled())
    except Exception:  # no database / no table yet: the default stands
        _low_resource = False
    return _low_resource


def _low_resource_cache_size() -> int:
    """Page cache: 32MiB normally, 8MiB on a 1GB box (perf.low_resource)."""
    return -8192 if _low_resource else -32768


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


# Startup read: import is the one point every process has in common, and it
# happens after SessionLocal/Base exist, so the read can use the normal stack.
load_low_resource_flag()
