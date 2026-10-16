"""First-run data: settings and the owner row."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db import models as _models  # noqa: F401
from backend.db.migrations.schema import (
    column_names,
)
from backend.logger import logger


def _seed_settings(db: Session) -> None:
    """Ensure a settings row exists and its URLPATH is populated.

    The row is created through the ORM rather than a raw INSERT: ``create_all()``
    emits no DEFAULT clause for Python-side defaults, so ``timezone``,
    ``bot_enabled`` and friends are NOT NULL with no SQL default, and a partial
    INSERT under ``INSERT OR IGNORE`` is discarded silently.

    An existing row keeps its own values: a prefix that is blank is a
    deliberate value (panel at root) and is left alone — only a NULL one
    (a row that predates the column) is seeded from ``.env``.
    """
    from backend.config import config
    from backend.db.models import Settings

    settings = db.query(Settings).first()
    if settings is None:
        settings = Settings()
        settings.urlpath = (config.URLPATH or "").strip("/")
        db.add(settings)
        db.flush()
    elif settings.urlpath is None:
        settings.urlpath = (config.URLPATH or "").strip("/")


def _add_admin_user_defaults(db: Session) -> None:
    """Retired no-op (was: per-admin new-user defaults, v13).

    Multi-admin is gone: defaults live on ``settings`` alone, so the
    ``admins.default_*`` columns no longer exist in the models.
    """
    logger.info("migrations v13: per-admin defaults are retired — no-op")


def _seed_summary() -> str:
    return "owner row and first user provisioned on a fresh install"


def _seed_owner_and_first_user(db: Session) -> None:
    """Give a fresh install a usable starting point (v12).

    Without it the owner authenticates from ``.env`` with no matching ``admins``
    row, and the enrolment/download flow has no user to exercise. Additive and
    idempotent: existing rows are never touched, and the audit entry is written
    only when this step actually created something.
    """
    import uuid as uuid_mod
    from datetime import date, timedelta

    from backend.config import config
    from backend.db.models import Admin, Settings, User

    seeded = False
    owner = (config.ADMIN_USERNAME or "admin").strip()
    if owner and db.query(Admin).filter(Admin.username == owner).first() is None:
        kwargs = {}
        if "is_owner" in column_names(db, "admins"):
            kwargs["is_owner"] = True
        db.add(Admin(username=owner, password="", **kwargs))
        db.flush()
        seeded = True

    legacy_owner_column = "owner" in column_names(db, "users")
    if db.query(User).count() == 0 and not legacy_owner_column:
        settings = db.query(Settings).first()
        days = int(getattr(settings, "default_days", 30) or 30) if settings else 30
        name = (getattr(config, "DEFAULT_USER", "") or "user1").strip() or "user1"
        if db.query(User).filter(User.name == name).first() is None:
            db.add(
                User(
                    uuid=str(uuid_mod.uuid4()),
                    name=name,
                    max_logins=1,
                    expiry_date=date.today() + timedelta(days=days),
                    is_active=True,
                    used=0,
                )
            )
            db.flush()
            seeded = True

    if not seeded:
        return
    try:
        from backend.operations.observability.audit import log_event

        log_event(db, "panel.first_run", actor=owner or "system", detail=_seed_summary())
    except Exception:
        logger.debug("migration: first-run audit entry skipped")


def _import_owner_credential(db: Session) -> None:
    """Move the owner credential out of ``.env`` and into the ``admins`` row (v16).

    v12 creates the matching ``admins`` row but leaves its ``password`` empty,
    so the hash is copied in here — that is what stops ``.env`` being a
    credential store without locking anyone out.

    Idempotent and fail-safe: an existing non-empty hash is never overwritten,
    and a missing or invalid env hash leaves the row alone (the owner then sets
    a password through the one-time setup key instead of being locked out).
    """
    from backend.config import config
    from backend.db.models import Admin

    owner = (config.ADMIN_USERNAME or "").strip()
    if not owner:
        logger.info("migrations v16: no ADMIN_USERNAME — nothing to import")
        return

    env_hash = (config.ADMIN_PASSWORD_HASH or "").strip()
    if not env_hash.startswith("$2"):
        logger.info("migrations v16: no bcrypt hash in .env — owner credential stays DB-managed")
        return

    row = db.query(Admin).filter(Admin.username == owner).first()
    if row is None:
        db.add(Admin(username=owner, password=env_hash))
        logger.info("migrations v16: created the owner row from the .env hash")
        return

    if row.password:
        logger.info("migrations v16: owner row already has a credential — left untouched")
        return

    row.password = env_hash
    logger.info("migrations v16: imported the owner credential into the database")
