"""v25 migration: traffic_ledger + settings_kv, with the one-time backfill."""

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


def _tables(db) -> set[str]:
    return set(inspect(db.bind).get_table_names())


def test_fresh_database_stamps_25_with_new_tables(session):
    assert migrations.migrate(session) == SCHEMA_VERSION == 25
    assert {"traffic_ledger", "settings_kv"} <= _tables(session)
    assert migrations.current_version(session) == 25
    assert migrations.verify_schema(session) == []


def test_backfill_matches_daily_from_stamped_16(session):
    """A checked-in db stamped 16 must migrate 17-25 and backfill exactly."""
    migrations.migrate(session)
    rows = [(1, "2030-01-01", 100), (1, "2030-01-02", 200), (2, "2030-01-01", 50)]
    for user_id, day, size in rows:
        session.execute(
            text("INSERT INTO user_traffic_daily (user_id, day, bytes) VALUES (:u, :d, :b)"),
            {"u": user_id, "d": day, "b": size},
        )
    session.execute(text("DROP TABLE traffic_ledger"))
    session.execute(text("DROP TABLE settings_kv"))
    session.execute(text("DELETE FROM schema_version"))
    session.execute(text("INSERT INTO schema_version (version, applied_at, note) VALUES (16, 0, 'stamped-16 fixture')"))
    session.commit()

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
        assert row[0] == session.execute(text("SELECT CAST(strftime('%s', :d) AS REAL)"), {"d": day}).scalar()
        assert row[1] == size
        assert row[2] is None


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
