# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Versioned schema migrations for OVManager (SQLite).

Why this module exists
----------------------
OVManager used to ship an Alembic tree that was never wired up: ``env.py``
imported ``Base`` from a module that did not export it and ``alembic.ini``
used a relative ``script_location``, so ``alembic upgrade head`` failed from
every working directory. The real schema was produced by
``Base.metadata.create_all()`` plus a hand-written ``ALTER TABLE`` allowlist.

``create_all()`` only creates *missing tables* — it never adds a missing
column to a table that already exists. The hand-written allowlist covered six
columns, while the models define many more (``users.uuid``, ``users.node_usage``,
``users.max_logins``, ``admins.telegram_id``, ``admins.username_prefix``, the
``settings.bot_*`` family, …). An existing database created by an older release
therefore silently kept running with columns missing until a query touched one.

This module replaces both with a small, explicit, ordered migration runner:

* The mapped models in ``backend/db/models.py`` are the single source of truth
  for the schema. Columns are reconciled from the metadata, so the adoption
  path cannot drift from the models the way a hardcoded list does.
* Every database carries a ``schema_version`` row, so numbered steps run
  exactly once and in order.
* Existing databases are *adopted*: their current shape is inspected, whatever
  is missing is added, and the database is then stamped at HEAD. No manual
  dump/restore is needed to upgrade an existing install.
* ``verify_schema()`` reports drift instead of letting a half-migrated
  database limp along.

SQLite notes
------------
``ALTER TABLE ... ADD COLUMN`` is used rather than table rebuilds. SQLite
allows ``NOT NULL`` on an added column only when a non-null default is
supplied, so a type-appropriate default is synthesised when the model does not
declare one. Existing rows keep working, and no data is copied.
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import inspect, text
from sqlalchemy.dialects import sqlite as sqlite_dialect
from sqlalchemy.orm import Session

# Importing the models registers every mapped table on ``Base.metadata``.
# Without this the metadata is empty unless some other module happened to
# import ``backend.db.models`` first, and ``create_all()`` silently creates
# nothing — so the import is load-bearing, not incidental.
from backend.db import models as _models  # noqa: F401
from backend.db.engine import Base, SessionLocal
from backend.logger import logger

#: Bump this and append a step to :data:`STEPS` for every schema change.
SCHEMA_VERSION = 2

VERSION_TABLE = "schema_version"

_sqlite = sqlite_dialect.dialect()
# SQLAlchemy's own DDL compiler: used so defaults added by ALTER TABLE are
# quoted exactly the way CREATE TABLE would quote them.
_ddl_compiler = _sqlite.ddl_compiler(_sqlite, None)

# DDL for tables that are owned by operations modules rather than the ORM.
# Kept here so one module owns all schema creation and the CREATE statements
# run once per process instead of on every write.
_EXTRA_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        actor TEXT,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_logs_ts ON audit_logs(ts)",
    """
    CREATE TABLE IF NOT EXISTS node_health_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        node_id INTEGER,
        node_name TEXT,
        cpu REAL,
        memory REAL,
        live_count INTEGER,
        latency_ms REAL,
        reachable INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_node_health_ts ON node_health_snapshots(ts)",
    "CREATE INDEX IF NOT EXISTS idx_node_health_node_ts ON node_health_snapshots(node_id, ts)",
    """
    CREATE TABLE IF NOT EXISTS traffic_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        total_used REAL NOT NULL,
        active_connections INTEGER NOT NULL,
        online_users INTEGER NOT NULL,
        active_users INTEGER NOT NULL,
        total_users INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_traffic_snapshots_ts ON traffic_snapshots(ts)",
    """
    CREATE TABLE IF NOT EXISTS security_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        auth_errors INTEGER NOT NULL,
        rejects INTEGER NOT NULL,
        stale_markers INTEGER NOT NULL,
        offline_nodes INTEGER NOT NULL,
        full_users INTEGER NOT NULL,
        inactive_users INTEGER NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_security_snapshots_ts ON security_snapshots(ts)",
    """
    CREATE TABLE IF NOT EXISTS login_attempts (
        key_hash TEXT PRIMARY KEY,
        attempts TEXT NOT NULL DEFAULT '[]',
        updated REAL NOT NULL DEFAULT 0
    )
    """,
)

_lock = threading.Lock()


# ── Introspection helpers ────────────────────────────────────────────────────


def table_names(db: Session) -> set[str]:
    return set(inspect(db.bind).get_table_names())


def column_names(db: Session, table: str) -> set[str]:
    try:
        return {c["name"] for c in inspect(db.bind).get_columns(table)}
    except Exception:
        return set()


def current_version(db: Session) -> int:
    """Return the stamped schema version, or 0 when unstamped."""
    if VERSION_TABLE not in table_names(db):
        return 0
    row = db.execute(text(f"SELECT MAX(version) FROM {VERSION_TABLE}")).fetchone()
    return int(row[0] or 0) if row and row[0] is not None else 0


def _stamp(db: Session, version: int, note: str) -> None:
    db.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL,
                note TEXT
            )
            """
        )
    )

    db.execute(
        text(f"INSERT OR REPLACE INTO {VERSION_TABLE} (version, applied_at, note) VALUES (:v, :ts, :n)"),
        {"v": version, "ts": time.time(), "n": note},
    )


# ── DDL synthesis ────────────────────────────────────────────────────────────


def _sql_type(column) -> str:
    try:
        return column.type.compile(_sqlite) or "TEXT"
    except Exception:
        return "TEXT"


def _quote(value: str) -> str:
    """SQL string literal with embedded quotes doubled."""
    return "'" + str(value).replace("'", "''") + "'"


def _zero_literal(column) -> str:
    """Type-appropriate fallback so NOT NULL columns can be added to SQLite."""
    sql_type = _sql_type(column).upper()
    if any(t in sql_type for t in ("INT", "REAL", "FLOAT", "NUMERIC", "BOOL", "DECIMAL")):
        return "0"
    if "DATE" in sql_type or "TIME" in sql_type:
        return "CURRENT_TIMESTAMP"
    return "''"


def _default_literal(column) -> str | None:
    """SQL literal for a column default, or ``None`` when there is none.

    A declared ``server_default`` is rendered by SQLAlchemy's own DDL compiler
    so quoting matches what ``CREATE TABLE`` would emit. Otherwise a scalar
    Python-side default is used, which keeps ``ALTER TABLE ADD COLUMN``
    consistent with the values the ORM would have written on a fresh database.
    """
    if column.server_default is not None:
        try:
            rendered = _ddl_compiler.get_column_default_string(column)
            if rendered:
                return str(rendered)
        except Exception:
            pass
    default = column.default
    if default is not None and getattr(default, "is_scalar", False):
        value = default.arg
        # bool must be tested before int: bool is a subclass of int.
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, str):
            return _quote(value)
    return None


def _add_column_sql(table: str, column) -> str:
    """Build ``ALTER TABLE ... ADD COLUMN`` for one mapped column.

    SQLite permits ``NOT NULL`` on an added column only when a non-null default
    is supplied, so a default is always synthesised for NOT NULL columns.
    """
    parts = [_sql_type(column)]
    literal = _default_literal(column)
    if literal is None and column.nullable is False:
        literal = _zero_literal(column)
    if literal is not None:
        parts.append(f"DEFAULT {literal}")
    if column.nullable is False:
        parts.append("NOT NULL")
    return f"ALTER TABLE {table} ADD COLUMN {column.name} " + " ".join(parts)


# ── Migration steps ──────────────────────────────────────────────────────────


def _create_mapped_tables(db: Session) -> None:
    """Create every mapped table that does not exist yet."""
    Base.metadata.create_all(bind=db.get_bind())


def _create_extra_tables(db: Session) -> None:
    for ddl in _EXTRA_DDL:
        db.execute(text(ddl))


def ensure_extra_tables(db: Session) -> None:
    """Create the non-ORM tables (audit + metrics) if they are missing.

    Owned here so a single module holds every piece of DDL and the statements
    run once per process instead of on every write or graph query.
    """
    _create_extra_tables(db)
    db.commit()


def _reconcile_columns(db: Session) -> list[str]:
    """Add mapped columns that are missing from existing tables.

    This is the step that ``create_all()`` cannot perform, and the reason an
    existing install needs a real migration path rather than a table creator.
    """
    added: list[str] = []
    existing_tables = table_names(db)
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = column_names(db, table.name)
        for column in table.columns:
            if column.name in present:
                continue
            sql = _add_column_sql(table.name, column)
            db.execute(text(sql))
            added.append(f"{table.name}.{column.name}")
            logger.info("migration: %s", sql)
    return added


def _seed_settings(db: Session) -> None:
    """Ensure a settings row exists and carries the configured URLPATH.

    The row is created through the ORM rather than a raw INSERT: ``create_all()``
    does not emit DEFAULT clauses for Python-side defaults, so ``timezone``,
    ``bot_enabled``, ``default_days`` and friends are NOT NULL with no SQL
    default. A raw partial INSERT therefore violates NOT NULL and — under
    ``INSERT OR IGNORE`` — is discarded silently, leaving a fresh install with
    no settings row and the ``URLPATH`` from ``.env`` unseeded.

    An existing row is never overwritten; the prefix is only filled in when it
    is still empty.
    """
    from backend.config import config
    from backend.db.models import Settings

    initial = (config.URLPATH or "").strip("/")
    settings = db.query(Settings).first()
    if settings is None:
        settings = Settings()
        db.add(settings)
        db.flush()
    if not (settings.urlpath or "").strip("/"):
        settings.urlpath = initial


# Numbered steps. Version N means "after this step the database is at N".
# Existing installations are adopted to HEAD directly (see ``migrate``), so
# these only ever run for databases stamped at an older version.
def _encrypt_node_keys(db: Session) -> None:
    """Encrypt plaintext node API keys at rest (v2).

    Rows already prefixed with ``enc:`` are skipped. When no encryption key
    is configured the step is a no-op so installs without
    NODE/BOT_ENCRYPT_KEY keep working on plaintext (with a warning from crud).
    """
    try:
        from backend.db.crud import _node_fernet, encrypt_node_key
    except Exception:
        return
    if _node_fernet is None:
        logger.info("migrations v2: no node encryption key — leaving keys as-is")
        return
    rows = db.execute(text("SELECT id, key FROM nodes")).fetchall()
    updated = 0
    for row in rows:
        node_id, stored = row[0], row[1]
        if not stored or str(stored).startswith("enc:"):
            continue
        enc = encrypt_node_key(str(stored))
        db.execute(text("UPDATE nodes SET key = :k WHERE id = :i"), {"k": enc, "i": node_id})
        updated += 1
    logger.info("migrations v2: encrypted %s node key(s)", updated)


STEPS: tuple[tuple[int, str, object], ...] = (
    (2, "encrypt node API keys at rest", _encrypt_node_keys),
)


# ── Public API ───────────────────────────────────────────────────────────────


def migrate(db: Session | None = None) -> int:
    """Bring the database up to :data:`SCHEMA_VERSION`. Idempotent.

    Fresh databases are created at HEAD and stamped. Databases that predate
    this runner are adopted: missing columns are added and the result is
    stamped at HEAD. Returns the final schema version.
    """
    own_session = db is None
    session = db or SessionLocal()
    try:
        with _lock:
            before = current_version(session)
            tables = table_names(session)
            fresh = not (tables & {t.name for t in Base.metadata.sorted_tables})

            if fresh:
                _create_mapped_tables(session)
                _create_extra_tables(session)
                _reconcile_columns(session)
                _seed_settings(session)
                _stamp(session, SCHEMA_VERSION, "initial schema")
                session.commit()
                logger.info("migrations: created fresh schema at version %s", SCHEMA_VERSION)
                return SCHEMA_VERSION

            if before == 0:
                # Pre-runner database (created by create_all + ad-hoc ALTERs,
                # or by any older release). Adopt whatever is there.
                _create_mapped_tables(session)
                _create_extra_tables(session)
                added = _reconcile_columns(session)
                _seed_settings(session)
                _stamp(session, SCHEMA_VERSION, f"adopted legacy database (+{len(added)} columns)")
                session.commit()
                # Opportunistically encrypt plaintext node keys on adoption
                # when a key is configured (best-effort, never fails migrate).
                try:
                    _encrypt_node_keys(session)
                    session.commit()
                except Exception as e:
                    logger.warning("migrations: node key encryption on adoption failed: %s", e)
                    session.rollback()
                logger.info(
                    "migrations: adopted legacy database at version %s (added columns: %s)",
                    SCHEMA_VERSION,
                    ", ".join(added) or "none",
                )
                return SCHEMA_VERSION

            if before > SCHEMA_VERSION:
                # Database written by a newer OVManager than this binary.
                # Refuse to run rather than silently downgrading the schema.
                logger.error(
                    "migrations: database is at version %s but this build supports %s — refusing to run",
                    before,
                    SCHEMA_VERSION,
                )
                raise RuntimeError(
                    f"Database schema version {before} is newer than this build supports ({SCHEMA_VERSION}). "
                    "Update OVManager or restore an older database."
                )

            for version, description, step in STEPS:
                if version <= before:
                    continue
                logger.info("migrations: applying v%s — %s", version, description)
                step(session)  # type: ignore[operator]
                _stamp(session, version, description)
                session.commit()

            _create_extra_tables(session)
            _seed_settings(session)
            session.commit()
            logger.info("migrations: database is at version %s", SCHEMA_VERSION)
            return SCHEMA_VERSION
    except Exception:
        session.rollback()
        raise
    finally:
        if own_session:
            session.close()


def verify_schema(db: Session | None = None) -> list[str]:
    """Return human-readable problems describing how the DB differs from the models.

    An empty list means the schema matches ``models.py``. Used by the test
    suite and by ``main.py --check-schema`` so drift is caught at build time
    rather than by a production query failing.
    """
    own_session = db is None
    session = db or SessionLocal()
    problems: list[str] = []
    try:
        present_tables = table_names(session)
        for table in Base.metadata.sorted_tables:
            if table.name not in present_tables:
                problems.append(f"missing table: {table.name}")
                continue
            present = column_names(session, table.name)
            for column in table.columns:
                if column.name not in present:
                    problems.append(f"missing column: {table.name}.{column.name}")
        version = current_version(session)
        if version != SCHEMA_VERSION:
            problems.append(f"schema_version is {version}, expected {SCHEMA_VERSION}")
        return problems
    finally:
        if own_session:
            session.close()


# ── Command line ─────────────────────────────────────────────────────────────


def _self_check() -> int:
    """Build, downgrade, then re-upgrade a throwaway database and check it.

    Comparing a fresh database against the models would be a tautology — the
    fresh schema *is* created from the models. The failure mode that actually
    matters is an **existing** database that a new release has to upgrade: a
    model gains a column, no migration is written for it, and installs that
    already have the table keep running without it until a query breaks.

    So this simulates exactly that. It builds the schema, drops a couple of
    columns and the version stamp to fake an older install, then runs
    ``migrate()`` again and requires the result to match the models. Nothing
    the operator owns is touched.
    """
    import tempfile
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    problems: list[str] = []

    with tempfile.TemporaryDirectory(prefix="ovmanager-schema-check-") as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'check.db'}")
        db = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
        try:
            version = migrate(db)
            print(f"fresh database built at version {version}")
            problems += verify_schema(db)

            # Fake an install from before those columns existed.
            db.execute(text("ALTER TABLE users DROP COLUMN max_logins"))
            db.execute(text("ALTER TABLE settings DROP COLUMN timezone"))
            db.execute(text("DROP TABLE schema_version"))
            db.commit()
            print("simulated an older install (dropped users.max_logins, settings.timezone)")

            try:
                upgraded = migrate(db)
                print(f"older install adopted at version {upgraded}")
            except Exception as exc:
                db.rollback()
                problems.append(f"adopting an older database failed: {exc}")

            for table, column in (("users", "max_logins"), ("settings", "timezone")):
                if column not in column_names(db, table):
                    problems.append(f"adoption did not restore {table}.{column}")
            try:
                problems += verify_schema(db)
            except Exception as exc:
                problems.append(f"schema verification failed: {exc}")
        finally:
            db.close()
            engine.dispose()

    if problems:
        for problem in problems:
            print(f"  DRIFT: {problem}")
        return 1
    print("schema matches backend/db/models.py — no drift")
    return 0


def _apply() -> int:
    """Apply migrations to the configured database."""
    version = migrate()
    problems = verify_schema()
    print(f"database is at schema version {version}")
    for problem in problems:
        print(f"  DRIFT: {problem}")
    return 1 if problems else 0


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--check" in args:
        raise SystemExit(_self_check())
    if "--migrate" in args:
        raise SystemExit(_apply())
    print(__doc__)
    print("\nusage: python -m backend.db.migrations [--check | --migrate]")
    raise SystemExit(2)
