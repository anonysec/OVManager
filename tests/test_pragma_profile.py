"""The SQLite pragma profile applied to every new connection."""

from backend.config import low_resource_enabled
from backend.db.engine import engine


def test_pragma_profile_on_fresh_connection():
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1  # NORMAL
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1

        assert conn.exec_driver_sql("PRAGMA temp_store").scalar() == 2  # memory
        cache_size = conn.exec_driver_sql("PRAGMA cache_size").scalar()
        if low_resource_enabled():  # perf.low_resource: 8MiB instead of 32MiB
            assert cache_size == -8192, f"low mode should trim the cache to 8MiB, got {cache_size}"
        else:
            assert cache_size <= -32768, f"cache_size should be at least 32MiB (negative = KiB), got {cache_size}"
        mmap_size = conn.exec_driver_sql("PRAGMA mmap_size").scalar()
        assert mmap_size >= 268435456, f"mmap_size should be at least 256MiB, got {mmap_size}"
