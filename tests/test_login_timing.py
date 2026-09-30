"""A failed login must cost the same whether or not the account exists.

bcrypt is deliberately slow. If the unknown-username path returns before
calling it, a 401 comes back in microseconds for a name that does not exist and
in ~100ms for one that does — which turns the login endpoint into a username
oracle. The fix is to verify against a hash nobody can supply, so every failure
pays the same price.

The assertion is on the mechanism (was a verify attempted?) rather than on
wall-clock time, which would be flaky on a shared box.
"""

import pytest

from backend.auth import auth as auth_mod
from backend.auth.hash import hash_password


@pytest.fixture
def db_session():
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def spy_verify(monkeypatch):
    """Count verify_password calls without changing its behaviour."""
    calls: list[str] = []
    real = auth_mod.verify_password

    def wrapper(password, hashed):
        calls.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(auth_mod, "verify_password", wrapper)
    return calls


def test_unknown_username_still_pays_for_a_verify(db_session, spy_verify):
    assert auth_mod.authenticate_user(db_session, "no-such-user-at-all", "whatever") is None
    assert spy_verify, "an unknown username returned without attempting a verify — timing oracle"


def test_disabled_admin_still_pays_for_a_verify(db_session, spy_verify):
    from backend.db.models import Admin

    db_session.add(Admin(username="timing-disabled", password=hash_password("a-real-password-1"), disabled=True))
    db_session.commit()
    try:
        assert auth_mod.authenticate_user(db_session, "timing-disabled", "a-real-password-1") is None
        assert spy_verify, "a disabled admin returned without attempting a verify"
    finally:
        db_session.query(Admin).filter(Admin.username == "timing-disabled").delete()
        db_session.commit()


def test_admin_with_no_password_still_pays_for_a_verify(db_session, spy_verify):
    from backend.db.models import Admin

    db_session.add(Admin(username="timing-nopass", password="", disabled=False))
    db_session.commit()
    try:
        assert auth_mod.authenticate_user(db_session, "timing-nopass", "anything") is None
        assert spy_verify, "an admin with no stored credential returned without a verify"
    finally:
        db_session.query(Admin).filter(Admin.username == "timing-nopass").delete()
        db_session.commit()


def test_the_dummy_hash_is_a_real_bcrypt_hash():
    """A malformed placeholder would raise instead of costing time."""
    assert auth_mod._DUMMY_HASH.startswith("$2")
    # It must not accidentally be a usable credential for any input.
    assert not auth_mod.verify_password("", auth_mod._DUMMY_HASH)


def test_a_correct_login_still_succeeds(db_session):
    """The oracle fix must not break the happy path."""
    import conftest

    from backend.config import config

    ok = auth_mod.authenticate_user(db_session, config.ADMIN_USERNAME, conftest.TEST_OWNER_PASSWORD)
    assert ok and ok["type"] == "owner"
