# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Tests for the versioned migration runner (backend/db/migrations.py).

Each test builds its own throwaway SQLite file so the real panel database is
never touched, and so the three distinct startup paths — fresh database,
adopted legacy database, and refusing a newer one — can each be exercised.
"""

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from backend.db import migrations
from backend.db.engine import Base
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


# ── Fresh database ───────────────────────────────────────────────────────────


def test_fresh_database_is_created_at_head_and_stamped(session):
    assert migrations.current_version(session) == 0

    result = migrations.migrate(session)

    assert result == SCHEMA_VERSION
    assert migrations.current_version(session) == SCHEMA_VERSION

    tables = set(inspect(session.bind).get_table_names())
    for mapped in Base.metadata.sorted_tables:
        assert mapped.name in tables, f"mapped table {mapped.name} was not created"
    # Non-ORM tables owned by the operations modules.
    assert {"audit_logs", "node_health_snapshots", "traffic_snapshots", "security_snapshots"} <= tables
    assert migrations.verify_schema(session) == []


def test_fresh_database_seeds_a_settings_row(session):
    migrations.migrate(session)
    row = session.execute(text("SELECT port, protocol, urlpath FROM settings")).fetchone()
    assert row is not None
    assert row[0] == 1194
    assert row[1] == "tcp"


def test_migrate_is_idempotent(session):
    first = migrations.migrate(session)
    second = migrations.migrate(session)
    third = migrations.migrate(session)
    assert first == second == third == SCHEMA_VERSION
    assert migrations.verify_schema(session) == []


# ── Adopting a database that predates the runner ─────────────────────────────


def test_legacy_database_gains_missing_columns(session):
    """A database from an older release must be repaired, not left broken.

    This is the case ``create_all()`` could never handle: it creates missing
    *tables* but never adds a missing *column* to an existing one.
    """
    session.execute(
        text("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name VARCHAR NOT NULL,
            total BIGINT,
            used BIGINT,
            expiry_date DATE NOT NULL,
            is_active BOOLEAN NOT NULL,
            owner VARCHAR NOT NULL
        )
    """)
    )
    # A pre-existing row that must survive the upgrade.
    session.execute(
        text(
            "INSERT INTO users (name, total, used, expiry_date, is_active, owner) "
            "VALUES ('legacy_user', 0, 0, '2030-01-01', 1, 'owner')"
        )
    )
    session.commit()

    assert migrations.current_version(session) == 0
    migrations.migrate(session)

    columns = {c["name"] for c in inspect(session.bind).get_columns("users")}
    for expected in ("uuid", "node_usage", "max_logins", "last_node_usage", "last_online"):
        assert expected in columns, f"adoption did not add users.{expected}"

    # The pre-existing row survives and picked up the model's defaults.
    row = session.execute(
        text("SELECT name, max_logins, node_usage, last_node_usage FROM users WHERE name = 'legacy_user'")
    ).fetchone()
    assert row is not None
    assert row[1] == 1, "max_logins should default to the model's value (1), not NULL"
    assert row[2] == "{}"
    assert row[3] == 0

    assert migrations.current_version(session) == SCHEMA_VERSION
    assert migrations.verify_schema(session) == []


def test_adoption_preserves_existing_settings_values(session):
    """Adopting must not clobber operator configuration."""
    session.execute(text("CREATE TABLE settings (id INTEGER PRIMARY KEY AUTOINCREMENT, port INTEGER NOT NULL)"))
    session.execute(text("INSERT INTO settings (id, port) VALUES (1, 4433)"))
    session.commit()

    migrations.migrate(session)

    row = session.execute(text("SELECT port, protocol, timezone FROM settings WHERE id = 1")).fetchone()
    assert row[0] == 4433, "an operator's port must not be overwritten"
    assert row[1] == "tcp"
    assert row[2] == "UTC"


# ── Refusing to downgrade ────────────────────────────────────────────────────


def test_newer_database_is_refused(session):
    """A database written by a newer build must stop the panel, not be clobbered."""
    session.execute(
        text("""
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY,
            applied_at REAL NOT NULL,
            note TEXT
        )
    """)
    )
    session.execute(
        text("INSERT INTO schema_version (version, applied_at, note) VALUES (:v, 0, 'from the future')"),
        {"v": SCHEMA_VERSION + 1},
    )
    # One mapped table must exist so the database is not treated as fresh.
    session.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT)"))
    session.commit()

    with pytest.raises(RuntimeError, match="newer than this build supports"):
        migrations.migrate(session)


# ── Schema drift detection ───────────────────────────────────────────────────


def test_verify_schema_reports_missing_column(session):
    session.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name VARCHAR NOT NULL)"))
    session.commit()

    problems = migrations.verify_schema(session)
    assert any("users.uuid" in p for p in problems)
    assert any("missing table" in p for p in problems)


def test_alter_table_sql_quotes_defaults(session):
    """ADD COLUMN defaults must be valid SQL for every mapped column."""
    users = Base.metadata.tables["users"]
    by_name = {c.name: c for c in users.columns}

    sql = migrations._add_column_sql("users", by_name["node_usage"])
    assert "DEFAULT '{}'" in sql, sql
    assert "NOT NULL" in sql

    sql = migrations._add_column_sql("users", by_name["max_logins"])
    # Numeric defaults stay unquoted so SQLite stores an integer, not text.
    assert "DEFAULT 1" in sql, sql

    sql = migrations._add_column_sql("users", by_name["uuid"])
    assert "NOT NULL" not in sql, sql
