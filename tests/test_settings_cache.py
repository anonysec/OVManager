"""Process-local settings cache: read-through + explicit refresh."""

import pytest
from sqlalchemy import event, text

from backend.config import settings_cache
from backend.db.crud.settings import get_cached_settings, refresh_settings, update_setting_timezone
from backend.db.engine import SessionLocal, engine


@pytest.fixture(autouse=True)
def _clean_cache():
    settings_cache.clear()
    yield
    settings_cache.clear()


@pytest.fixture()
def select_counter():
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "settings" in statement.lower():
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    yield statements
    event.remove(engine, "before_cursor_execute", _record)


def test_two_reads_share_one_select(select_counter):
    db = SessionLocal()
    try:
        first = get_cached_settings(db)
        second = get_cached_settings(db)

        assert first is second
        assert len(select_counter) == 1, f"expected one SELECT, saw {len(select_counter)}"
    finally:
        db.close()


def test_writes_and_refresh_show_new_values():
    db = SessionLocal()
    try:
        get_cached_settings(db)
        update_setting_timezone(db, "Asia/Tokyo")
        assert get_cached_settings(db).timezone == "Asia/Tokyo"

        db.execute(text("UPDATE settings SET timezone = 'Europe/Berlin'"))
        db.commit()
        refresh_settings(db)
        assert get_cached_settings(db).timezone == "Europe/Berlin"
    finally:
        db.execute(text("UPDATE settings SET timezone = 'UTC'"))
        db.commit()
        db.close()


def test_set_urlpath_refreshes_settings_cache():
    from backend.urlpath import set_urlpath

    db = SessionLocal()
    try:
        get_cached_settings(db)  # populate from this session
        original = db.execute(text("SELECT urlpath FROM settings")).scalar() or ""
        try:
            set_urlpath("gate6probe")
            assert get_cached_settings(db).urlpath == "gate6probe", "set_urlpath must invalidate the settings cache"
        finally:
            set_urlpath(original)
    finally:
        settings_cache.clear()
        db.close()
