# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Owner credential modes: bcrypt hash (preferred) and legacy plaintext."""
import pytest

from backend.auth.hash import hash_password, verify_password


def _setting(**kw):
    from backend.config import Setting

    base = {"ADMIN_USERNAME": "admin", "_env_file": None}
    return Setting(**{**base, **kw})


def test_config_accepts_hash_only():
    s = _setting(ADMIN_PASSWORD="", ADMIN_PASSWORD_HASH=hash_password("a-strong-password"))
    assert not s.ADMIN_PASSWORD
    assert s.ADMIN_PASSWORD_HASH.startswith("$2")


def test_config_rejects_missing_credentials():
    with pytest.raises(ValueError, match="No owner credentials"):
        _setting(ADMIN_PASSWORD="", ADMIN_PASSWORD_HASH="")


def test_config_rejects_non_bcrypt_hash():
    with pytest.raises(ValueError, match="bcrypt"):
        _setting(ADMIN_PASSWORD="", ADMIN_PASSWORD_HASH="s3cret-password")


def test_config_still_rejects_placeholder_plaintext():
    with pytest.raises(ValueError, match="placeholder"):
        _setting(ADMIN_PASSWORD="change-me-please", ADMIN_PASSWORD_HASH="")


def test_authenticate_owner_with_hash(monkeypatch):
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal

    prev_hash, prev_pass = auth_mod.config.ADMIN_PASSWORD_HASH, auth_mod.config.ADMIN_PASSWORD
    auth_mod.config.ADMIN_PASSWORD_HASH = hash_password("a-strong-password-123")
    auth_mod.config.ADMIN_PASSWORD = ""
    owner = auth_mod.config.ADMIN_USERNAME
    try:
        db = SessionLocal()
        try:
            assert auth_mod.authenticate_user(db, owner, "a-strong-password-") is None
            assert auth_mod.authenticate_user(db, owner, "a-strong-password-1") is None
            ok = auth_mod.authenticate_user(db, owner, "a-strong-password-123")
            assert ok and ok["type"] == "owner"
        finally:
            db.close()
    finally:
        auth_mod.config.ADMIN_PASSWORD_HASH, auth_mod.config.ADMIN_PASSWORD = prev_hash, prev_pass


def test_authenticate_owner_plaintext_fallback(monkeypatch):
    from backend.auth import auth as auth_mod
    from backend.db.engine import SessionLocal

    prev_hash = auth_mod.config.ADMIN_PASSWORD_HASH
    auth_mod.config.ADMIN_PASSWORD_HASH = ""
    owner = auth_mod.config.ADMIN_USERNAME
    try:
        db = SessionLocal()
        try:
            ok = auth_mod.authenticate_user(db, owner, auth_mod.config.ADMIN_PASSWORD)
            assert ok and ok["type"] == "owner"
        finally:
            db.close()
    finally:
        auth_mod.config.ADMIN_PASSWORD_HASH = prev_hash


def test_startup_migration_hashes_env(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ADMIN_USERNAME=admin\nADMIN_PASSWORD=a-strong-password-1\nPORT=2095\n")
    env.chmod(0o600)
    import main

    monkeypatch.setattr(main.config, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(main.config, "ADMIN_PASSWORD", "a-strong-password-1")
    main._migrate_owner_password(str(env))
    text = env.read_text()
    assert "ADMIN_PASSWORD=" not in text.replace("ADMIN_PASSWORD_HASH=", "")
    hash_line = [ln for ln in text.splitlines() if ln.startswith("ADMIN_PASSWORD_HASH=")][0]
    stored = hash_line.split("=", 1)[1]
    assert stored.startswith("$2")
    assert verify_password("a-strong-password-1", stored)


def test_startup_migration_skips_when_hashed(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("ADMIN_PASSWORD_HASH=$2b$12$existing\n")
    import main

    monkeypatch.setattr(main.config, "ADMIN_PASSWORD_HASH", "$2b$12$existing")
    main._migrate_owner_password()
    assert "ADMIN_PASSWORD=" not in env.read_text()


def test_startup_migration_no_env_is_noop(tmp_path, monkeypatch):
    import main

    monkeypatch.setattr(main.config, "ADMIN_PASSWORD_HASH", "")
    monkeypatch.setattr(main.config, "ADMIN_PASSWORD", "a-strong-password-1")
    main._migrate_owner_password(str(tmp_path / "missing.env"))  # must not raise
