"""A fresh database must not come up with an unusable owner.

The upgrade path is covered by the v16 migration (it imports an existing
ADMIN_PASSWORD_HASH into the owner row). A FRESH install takes a different
branch of migrate(): it creates the tables, seeds the owner row and stamps
itself at HEAD — deliberately skipping every STEP, because there is nothing
to migrate.

That made v16 unreachable on a fresh database, so a manual install
(git clone → .env → run) produced an owner row with an empty password.
authenticate_user() refuses an empty hash by design, so nobody could log in
and nothing in the docs could fix it.
"""

import pytest

from backend.auth.hash import hash_password


@pytest.fixture
def fresh_db(tmp_path):
    """A genuinely empty database, migrated the way a first boot does."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.db import migrations

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    session = sessionmaker(bind=engine)()
    try:
        yield session, migrations
    finally:
        session.close()
        engine.dispose()


def test_fresh_install_imports_an_env_hash(fresh_db, monkeypatch):
    """ADMIN_PASSWORD_HASH in .env must work on a first boot, not only upgrade."""
    from backend.config import config as panel_config
    from backend.db.models import Admin

    session, migrations = fresh_db
    env_hash = hash_password("manual-install-password-1")
    monkeypatch.setattr(panel_config, "ADMIN_USERNAME", "freshadmin")
    monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", env_hash)

    migrations.migrate(session)

    row = session.query(Admin).filter(Admin.username == "freshadmin").first()
    assert row is not None, "a fresh install must seed the owner row"
    assert row.password == env_hash, (
        "the fresh-install path skipped the credential import — a manual install would come up with an owner nobody can log in as"
    )


def test_fresh_install_without_a_hash_still_boots(fresh_db, monkeypatch):
    """No credential anywhere is allowed: reset-password is the bootstrap."""
    from backend.config import config as panel_config
    from backend.db.models import Admin

    session, migrations = fresh_db
    monkeypatch.setattr(panel_config, "ADMIN_USERNAME", "noauthadmin")
    monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", "")

    version = migrations.migrate(session)

    row = session.query(Admin).filter(Admin.username == "noauthadmin").first()
    assert row is not None
    assert row.password == ""
    assert version == migrations.SCHEMA_VERSION


def test_upgrade_path_still_imports(fresh_db, monkeypatch):
    """The v16 step must keep working for databases that predate it."""
    from sqlalchemy import text

    from backend.config import config as panel_config
    from backend.db.models import Admin

    session, migrations = fresh_db
    env_hash = hash_password("upgrading-password-1")
    monkeypatch.setattr(panel_config, "ADMIN_USERNAME", "upgradeadmin")
    monkeypatch.setattr(panel_config, "ADMIN_PASSWORD_HASH", env_hash)

    # Build at HEAD, then rewind to look like an install that predates v16.
    migrations.migrate(session)
    session.execute(text("DELETE FROM schema_version WHERE version >= 16"))
    session.execute(text("UPDATE admins SET password = '' WHERE username = 'upgradeadmin'"))
    session.commit()

    migrations.migrate(session)
    row = session.query(Admin).filter(Admin.username == "upgradeadmin").first()
    assert row.password == env_hash
