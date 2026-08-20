# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.data_paths import DATA_DIR

BASE_DIR = Path(__file__).resolve().parent

DATABASE_URL = f"sqlite:///{DATA_DIR / 'ovmanager.db'}"

# OVManager uses SQLite by default. The panel performs scheduled writes while
# admins may also be using the UI, so the default SQLite settings can raise
# transient "database is locked" errors under normal concurrent activity.
#
# WAL allows readers and one writer to coexist, and busy_timeout makes SQLite
# wait briefly for a writer instead of immediately failing the request/job.
engine = create_engine(
    url=DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


Base = declarative_base()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
