"""The migration runner: bring a database to HEAD, then verify it."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db import models as _models  # noqa: F401
from backend.db.engine import Base, SessionLocal
from backend.db.migrations.constants import SCHEMA_VERSION, _lock
from backend.db.migrations.schema import (
    _create_extra_tables,
    _create_mapped_tables,
    _reconcile_columns,
    _stamp,
    column_names,
    current_version,
    table_names,
)
from backend.db.migrations.seeds import (
    _import_owner_credential,
    _seed_owner_and_first_user,
    _seed_settings,
)
from backend.db.migrations.steps import STEPS
from backend.logger import logger


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
                _seed_owner_and_first_user(session)
                # The fresh path stamps itself at HEAD and skips STEPS, so v16
                # would never run here — meaning a manual install (git clone →
                # .env → run) got an owner row with an empty password and no
                # way in. The import is idempotent and no-ops without a hash.
                _import_owner_credential(session)
                _stamp(session, SCHEMA_VERSION, "initial schema")
                session.commit()
                logger.info("migrations: created fresh schema at version %s", SCHEMA_VERSION)
                return SCHEMA_VERSION

            if before == 0:
                _create_mapped_tables(session)
                _create_extra_tables(session)
                added = _reconcile_columns(session)
                _seed_settings(session)
                _stamp(session, 1, f"adopted legacy database (+{len(added)} columns)")
                session.commit()
                before = 1
                logger.info(
                    "migrations: adopted legacy database (added columns: %s)",
                    ", ".join(added) or "none",
                )

            if before > SCHEMA_VERSION:
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
