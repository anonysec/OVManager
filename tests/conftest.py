# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Shared pytest fixtures."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _ensure_schema():
    """Create all tables (users/admins/settings/nodes/sessions + audit) once per session."""
    from backend.app import _run_migrations

    _run_migrations()

    from backend.db.engine import SessionLocal
    from backend.operations.audit import ensure_audit_table

    db = SessionLocal()
    try:
        ensure_audit_table(db)
    finally:
        db.close()


@pytest.fixture(scope="session")
def make_session_token():
    """Factory: mint a real opaque session token for tests.

    Auth is DB-backed, so a valid Bearer token requires a real session row —
    there is no offline-signed shortcut anymore (by design).
    """

    def _make(username: str, role: str) -> str:
        from backend.auth.sessions import create_session
        from backend.db.engine import SessionLocal

        db = SessionLocal()
        try:
            return create_session(db, username, role, user_agent="pytest", ip="127.0.0.1")
        finally:
            db.close()

    return _make
