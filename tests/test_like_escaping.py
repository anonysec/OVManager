"""User-supplied text going into a LIKE must not carry wildcards.

`%` and `_` are wildcards in SQL LIKE. Interpolating a search term unescaped
lets a caller widen their own query — `%` matches everything they are allowed
to see rather than the literal character they typed. It is not injection (the
value is still bound), but it makes a filter mean something other than what it
says, and the audit filter is used to *narrow* an investigation.
"""

import datetime as dt

import pytest
from sqlalchemy import text

from backend.utils.like import escape_like


def test_escapes_the_like_metacharacters():
    assert escape_like("100%") == "100\\%"
    assert escape_like("a_b") == "a\\_b"
    assert escape_like("back\\slash") == "back\\\\slash"


def test_leaves_ordinary_text_alone():
    for value in ("alice", "user-1", "a b c", "Ünïcode", "42"):
        assert escape_like(value) == value


def test_escapes_backslash_first():
    """Otherwise escaping % would double the backslash it just added."""
    assert escape_like("\\%") == "\\\\\\%"


def test_empty_and_none_are_passthrough():
    assert escape_like("") == ""
    assert escape_like(None) is None


@pytest.fixture
def db_session():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def seeded_users(db_session):
    from backend.db.models import User

    names = ("alice", "bob", "carol")
    for name in names:
        db_session.add(
            User(
                uuid=f"uuid-{name}",
                name=name,
                owner="owner1",
                max_logins=1,
                expiry_date=dt.date(2030, 1, 1),
                is_active=True,
                used=0,
            )
        )
    db_session.commit()
    try:
        yield
    finally:
        db_session.query(User).filter(User.name.in_(names)).delete(synchronize_session=False)
        db_session.commit()


def test_user_search_does_not_widen_on_a_wildcard(db_session, seeded_users):
    """A literal '%' search must match nothing, not everything."""
    from backend.db import crud

    rows, total = crud.get_users_page(db_session, search="%")
    assert total == 0, f"a literal '%' matched {total} users — the wildcard leaked through"
    assert rows == []


def test_user_search_still_matches_a_real_substring(db_session, seeded_users):
    from backend.db import crud

    rows, total = crud.get_users_page(db_session, search="ali")
    assert total == 1
    assert rows[0].name == "alice"


def test_audit_action_filter_does_not_widen(db_session):
    """The audit filter narrows an investigation; a '%' must not defeat it."""
    from backend.operations.observability.audit import log_event, recent_events

    log_event(db_session, "user.create", actor="like-test-actor", target="alice")
    log_event(db_session, "node.delete", actor="like-test-actor", target="node1")

    try:
        rows = recent_events(db_session, action="user.", limit=50)
        assert rows and all(r["action"].startswith("user.") for r in rows)

        rows = recent_events(db_session, action="%", limit=50)
        assert rows == [], f"a literal '%' returned {len(rows)} audit rows"
    finally:
        db_session.execute(text("DELETE FROM audit_logs WHERE actor = 'like-test-actor'"))
        db_session.commit()
