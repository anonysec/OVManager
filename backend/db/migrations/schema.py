"""Schema inspection, table creation and column reconciliation."""

from __future__ import annotations

import time

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.db import models as _models  # noqa: F401
from backend.db.engine import Base
from backend.db.migrations.constants import (
    _EXTRA_DDL,
    VERSION_TABLE,
    _ddl_compiler,
    _sqlite,
)
from backend.logger import logger


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

    A declared ``server_default`` is rendered by SQLAlchemy's DDL compiler so
    quoting matches ``CREATE TABLE``; a scalar Python-side default keeps
    ``ALTER TABLE ADD COLUMN`` consistent with a fresh database.
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


def _create_mapped_tables(db: Session) -> None:
    Base.metadata.create_all(bind=db.get_bind())


def _create_extra_tables(db: Session) -> None:
    for ddl in _EXTRA_DDL:
        db.execute(text(ddl))


def ensure_extra_tables(db: Session) -> None:
    """Create the non-ORM tables (audit + metrics) if they are missing.

    Kept here so one module holds every piece of DDL, and it runs once per
    process instead of on every write.
    """
    _create_extra_tables(db)
    db.commit()


def _reconcile_columns(db: Session) -> list[str]:
    """Add mapped columns missing from existing tables.

    The one thing ``create_all()`` cannot do, and the reason an existing install
    needs a migration path rather than a table creator.
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
