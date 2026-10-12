"""v25 migration: traffic_ledger + settings_kv, with the one-time backfill."""

import datetime as dt
import os
import time

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from backend.db import migrations
from backend.db.migrations import SCHEMA_VERSION


@pytest.fixture()
def session(tmp_path):
    """Session bound to an isolated SQLite file."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    maker = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def non_utc_tz():
    """Run the test in a far-from-UTC timezone, restore the process TZ after."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Pacific/Auckland"
    time.tzset()
    yield
    if previous is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = previous
    time.tzset()


def _tables(db) -> set[str]:
    return set(inspect(db.bind).get_table_names())


def _rewind_to_stamped_16(db, rows) -> None:
    """Migrate at HEAD, plant daily rows, then rewind to the stamped-16 fixture."""
    migrations.migrate(db)
    for user_id, day, size in rows:
        db.execute(
            text("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (:u, :d, :b)"),
            {"u": user_id, "d": day, "b": size},
        )
    db.execute(text("DROP TABLE traffic_ledger"))
    db.execute(text("DROP TABLE settings_kv"))
    db.execute(text("DELETE FROM schema_version"))
    db.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (16, 0, 'stamped-16 fixture')"))
    db.commit()


def test_fresh_database_stamps_25_with_new_tables(session):
    assert migrations.migrate(session) == SCHEMA_VERSION == 25
    assert {"traffic_ledger", "settings_kv"} <= _tables(session)
    assert migrations.current_version(session) == 25
    assert migrations.verify_schema(session) == []


def test_backfill_matches_daily_from_stamped_16(session):
    """A checked-in db stamped 16 must migrate 17-25 and backfill exactly."""
    rows = [(1, "2030-01-01", 100), (1, "2030-01-02", 200), (2, "2030-01-01", 50)]
    _rewind_to_stamped_16(session, rows)

    assert migrations.migrate(session) == SCHEMA_VERSION

    daily = session.execute(text("SELECT COUNT(*) FROM user_traffic_daily")).scalar()
    backfilled = session.execute(text("SELECT COUNT(*) FROM traffic_ledger WHERE kind = 'backfill'")).scalar()
    assert daily == backfilled == len(rows)
    assert migrations.verify_schema(session) == []

    for user_id, day, size in rows:
        row = session.execute(
            text(
                "SELECT ts, delta_bytes, node_id FROM traffic_ledger "
                "WHERE user_id = :u AND kind = 'backfill' AND delta_bytes = :b"
            ),
            {"u": user_id, "b": size},
        ).fetchone()
        assert row is not None, f"missing backfill row for user {user_id} day {day}"
        utc_midnight = dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.UTC).timestamp()
        assert row[0] == utc_midnight, f"backfill ts must be UTC midnight of {day}, got {row[0]}"
        assert row[1] == size
        assert row[2] == ""


def test_backfill_ts_is_utc_midnight_under_non_utc_tz(session, non_utc_tz):
    """The day key is a UTC day; its ledger ts must be that day's UTC midnight.

    Live rows carry ``time.time()`` instants, so a backfilled row that lands on
    local midnight would sit 13 hours off the poll that recorded it for an
    Auckland operator (any non-UTC TZ, worst at the date boundary).
    """
    rows = [(1, "2030-01-01", 100)]
    _rewind_to_stamped_16(session, rows)

    migrations.migrate(session)

    ts = session.execute(text("SELECT ts FROM traffic_ledger WHERE kind = 'backfill'")).scalar()
    utc_midnight = dt.datetime(2030, 1, 1, tzinfo=dt.UTC).timestamp()
    local_midnight = time.mktime(time.strptime("2030-01-01", "%Y-%m-%d"))
    assert local_midnight != utc_midnight, "TZ fixture failed: local midnight equals UTC midnight"
    assert ts == utc_midnight, f"want UTC midnight {utc_midnight}, got {ts}"


def test_null_node_id_is_rejected(session):
    """NULL node_id would defeat the UNIQUE key — NULLs are distinct in SQLite."""
    migrations.migrate(session)
    null_insert = text(
        "INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes) VALUES (1, 1700000000.0, NULL, 'poll', 10)"
    )
    with pytest.raises(IntegrityError):
        session.execute(null_insert)
        session.commit()
    session.rollback()

    bare = text("INSERT INTO traffic_ledger (user_id, ts, kind, delta_bytes) VALUES (1, 1700000000.0, 'poll', 10)")
    session.execute(bare)  # omitted node_id → default sentinel ''
    session.commit()
    with pytest.raises(IntegrityError):
        session.execute(bare)  # same (user, ts, kind, sentinel) must collide
        session.commit()
    session.rollback()

    assert session.execute(text("SELECT COUNT(*) FROM traffic_ledger")).scalar() == 1


def test_backfill_rows_carry_sentinel_and_reject_duplicates(session):
    rows = [(1, "2030-01-01", 100)]
    _rewind_to_stamped_16(session, rows)
    migrations.migrate(session)

    user_id, ts, node_id = session.execute(
        text("SELECT user_id, ts, node_id FROM traffic_ledger WHERE kind = 'backfill'")
    ).fetchone()
    assert node_id == "", f"backfill rows must use the '' sentinel, got {node_id!r}"

    with pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes) VALUES (:u, :t, '', 'backfill', 100)"),
            {"u": user_id, "t": ts},
        )
        session.commit()
    session.rollback()


def test_unique_rejects_duplicate_key(session):
    migrations.migrate(session)
    insert = text(
        "INSERT INTO traffic_ledger (user_id, ts, node_id, kind, delta_bytes) VALUES (1, 1700000000.0, 'node-a', 'poll', 10)"
    )
    session.execute(insert)
    session.commit()

    with pytest.raises(IntegrityError):
        session.execute(insert)
        session.commit()
    session.rollback()

    assert session.execute(text("SELECT COUNT(*) FROM traffic_ledger")).scalar() == 1


def test_settings_kv_roundtrip(session):
    migrations.migrate(session)
    session.execute(
        text("INSERT INTO settings_kv (key, value, updated_at) VALUES ('k', '\"v\"', 1.0)"),
    )
    session.commit()
    assert session.execute(text("SELECT value FROM settings_kv WHERE key = 'k'")).scalar() == '"v"'
    with pytest.raises(IntegrityError):
        session.execute(text("INSERT INTO settings_kv (key, value, updated_at) VALUES ('k', '\"x\"', 2.0)"))
        session.commit()
    session.rollback()
