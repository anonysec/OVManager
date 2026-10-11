"""Panel settings + bot-token storage.

Secrets are stored as written (no at-rest encryption — removed in 1.0.5;
the owner-held server and 0600 DB perms are the trust boundary).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.config import settings_cache
from backend.db.models import Settings
from backend.logger import logger


def decrypt_bot_token(stored: str | None) -> str | None:
    """Return the bot token as stored (legacy ``enc:`` rows fail closed).

    At-rest encryption was removed in 1.0.5. A row still carrying the old
    ``enc:`` prefix cannot be read back without the retired key, so it is
    treated as unusable rather than sent to Telegram as a token.
    """
    if not stored:
        return None
    if str(stored).startswith("enc:"):
        logger.warning("Stored bot token is still encrypted (re-save it in Settings → Bot) — refusing to use it")
        return None
    return stored


def update_bot_config(db: Session, **kwargs):
    s = db.query(Settings).first()
    if not s:
        s = Settings(port=1194, protocol="tcp")
        db.add(s)
        db.flush()
    for k, v in kwargs.items():
        if v is None:
            continue
        if k == "bot_token" and not v:
            v = None  # clear token → NULL in DB
        if hasattr(s, k):
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    refresh_settings(db)
    return s


def get_settings(db: Session):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(port=1194)
        settings.protocol = "tcp"
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


def refresh_settings(db: Session):
    """Re-read the settings row and replace the process-local cache entry.

    ``populate_existing`` forces the row's attributes to be re-populated from
    the database: a session that already loaded the row would otherwise hand
    back its stale in-memory copy.
    """
    settings = db.query(Settings).populate_existing().first()
    if settings is None:
        settings = get_settings(db)
    settings_cache.set(settings)
    return settings


def get_cached_settings(db: Session):
    """Read-through access: cached row on hits, SELECT + cache on the first read."""
    cached = settings_cache.get()
    return cached if cached is not None else refresh_settings(db)


def update_setting_timezone(db: Session, timezone: str):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(port=1194)
        settings.protocol = "tcp"
        db.add(settings)
        db.commit()
        db.refresh(settings)
    settings.timezone = timezone
    db.commit()
    refresh_settings(db)
    return settings


def get_bot_config(db: Session):
    s = db.query(Settings).first()
    if not s:
        return {"bot_configured": False, "bot_enabled": False}
    return {
        "bot_configured": bool(s.bot_token),
        "bot_enabled": s.bot_enabled,
        "default_days": s.default_days,
        "default_traffic_gb": s.default_traffic_gb,
        "default_max_users": s.default_max_users,
        "owner_telegram_id": s.owner_telegram_id,
    }
