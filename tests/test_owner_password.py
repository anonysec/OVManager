"""The owner credential lives in the database, not in .env.

Credential resolution has one source of truth: the ``admins`` row whose
username matches ``ADMIN_USERNAME``. ``.env`` carries no credential at all —
a pre-upgrade ``ADMIN_PASSWORD_HASH`` is imported into that row by the v16
migration, and ``ADMIN_PASSWORD`` is never read.
"""

import pytest

from backend.auth.hash import hash_password


def _setting(**kw):
    from backend.config import Setting

    base = {"ADMIN_USERNAME": "admin", "_env_file": None}
    return Setting(**{**base, **kw})


def test_config_boots_without_any_credential_in_env():
    """A fresh install has no credential until the owner is created."""
    s = _setting(ADMIN_PASSWORD="", ADMIN_PASSWORD_HASH="")
    assert s.ADMIN_USERNAME == "admin"


def test_config_warns_when_legacy_env_credentials_are_present(caplog):
    with caplog.at_level("WARNING", logger="config"):
        _setting(ADMIN_PASSWORD="a-strong-password", ADMIN_PASSWORD_HASH="")
    assert any("no longer used" in r.message for r in caplog.records)


def test_owner_authenticates_from_the_database():
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    owner = auth_mod.config.ADMIN_USERNAME
    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == owner).first()
        assert row is not None, "the owner must exist as an admins row"
        original = row.password
        row.password = hash_password("a-strong-password-123")
        db.commit()

        assert auth_mod.authenticate_user(db, owner, "a-strong-password-") is None
        assert auth_mod.authenticate_user(db, owner, "a-strong-password-1") is None
        ok = auth_mod.authenticate_user(db, owner, "a-strong-password-123")
        assert ok and ok["type"] == "owner"

        row.password = original
        db.commit()
    finally:
        db.close()


def test_env_password_is_ignored_entirely():
    """The old plaintext fallback is gone: .env cannot authenticate anyone."""
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal

    db = SessionLocal()
    try:
        assert auth_mod.authenticate_user(db, auth_mod.config.ADMIN_USERNAME, "env-only-password") is None
    finally:
        db.close()


def test_admin_without_a_password_cannot_log_in():
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        db.add(Admin(username="no-password-admin", password="", disabled=False))
        db.commit()
        assert auth_mod.authenticate_user(db, "no-password-admin", "") is None
        assert auth_mod.authenticate_user(db, "no-password-admin", "anything") is None
        db.query(Admin).filter(Admin.username == "no-password-admin").delete()
        db.commit()
    finally:
        db.close()


def test_disabled_owner_cannot_log_in():
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    owner = auth_mod.config.ADMIN_USERNAME
    db = SessionLocal()
    try:
        row = db.query(Admin).filter(Admin.username == owner).first()
        row.disabled = True
        db.commit()
        assert auth_mod.authenticate_user(db, owner, "a-strong-password-123") is None
    finally:
        row = db.query(Admin).filter(Admin.username == owner).first()
        row.disabled = False
        db.commit()
        db.close()


def test_v16_migration_imports_the_env_hash(monkeypatch):
    """An upgrading install must not be locked out by the credential move."""
    from backend.config import config as panel_config
    from backend.db import migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    owner = "migrated-owner"
    db = SessionLocal()
    try:
        db.add(Admin(username=owner, password="", disabled=False))
        db.commit()

        monkeypatch.setattr(panel_config, "ADMIN_USERNAME", owner)
        env_hash = hash_password("from-the-env-file-1")
        monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", env_hash)

        migrations._import_owner_credential(db)

        row = db.query(Admin).filter(Admin.username == owner).first()
        assert row.password == env_hash

        db.query(Admin).filter(Admin.username == owner).delete()
        db.commit()
    finally:
        db.close()


def test_v16_migration_never_overwrites_an_existing_hash(monkeypatch):
    from backend.config import config as panel_config
    from backend.db import migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    owner = "already-set-owner"
    existing = hash_password("already-set-password-1")
    db = SessionLocal()
    try:
        db.add(Admin(username=owner, password=existing, disabled=False))
        db.commit()

        monkeypatch.setattr(panel_config, "ADMIN_USERNAME", owner)
        monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", hash_password("different-1"))

        migrations._import_owner_credential(db)

        row = db.query(Admin).filter(Admin.username == owner).first()
        assert row.password == existing

        db.query(Admin).filter(Admin.username == owner).delete()
        db.commit()
    finally:
        db.close()


@pytest.mark.parametrize("env_hash", ["", "not-a-bcrypt-hash"])
def test_v16_migration_is_a_noop_without_a_usable_hash(monkeypatch, env_hash):
    from backend.config import config as panel_config
    from backend.db import migrations
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    owner = "unimportable-owner"
    db = SessionLocal()
    try:
        db.add(Admin(username=owner, password="", disabled=False))
        db.commit()

        monkeypatch.setattr(panel_config, "ADMIN_USERNAME", owner)
        monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", env_hash)

        migrations._import_owner_credential(db)

        row = db.query(Admin).filter(Admin.username == owner).first()
        assert row.password == ""

        db.query(Admin).filter(Admin.username == owner).delete()
        db.commit()
    finally:
        db.close()
