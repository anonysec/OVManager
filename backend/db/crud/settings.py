# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Panel settings + bot-token storage."""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.db.models import Settings
from backend.logger import logger

from .crypto import _fernet


def decrypt_bot_token(stored: str | None) -> str | None:
    """Return a configured bot token without ever logging its value."""
    if not stored:
        return None
    if _fernet is None:
        return stored
    try:
        return _fernet.decrypt(stored.encode()).decode()
    except Exception:
        logger.warning("Stored Telegram bot token could not be decrypted")
        return None


def update_bot_config(db: Session, **kwargs):
    s = db.query(Settings).first()
    if not s:
        s = Settings(port=1194, protocol="tcp")
        db.add(s)
        db.flush()
    for k, v in kwargs.items():
        if v is None:
            continue
        if k == "bot_token":
            if not v:
                v = None  # clear token → NULL in DB
            elif _fernet is None:
                raise RuntimeError("BOT_ENCRYPT_KEY is required before saving a bot token")
            else:
                v = _fernet.encrypt(v.encode()).decode()
        if hasattr(s, k):
            setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


def get_bot_config(db: Session):
    s = db.query(Settings).first()
    if not s:
        return {"bot_configured": False, "bot_enabled": False}
    return {
        # Never return plaintext or ciphertext token material to the browser.
        "bot_configured": bool(s.bot_token),
        "bot_enabled": s.bot_enabled,
        "default_days": s.default_days,
        "default_traffic_gb": s.default_traffic_gb,
        "default_max_users": s.default_max_users,
        "owner_telegram_id": s.owner_telegram_id,
    }


def get_settings(db: Session):
    settings = db.query(Settings).first()
    if not settings:
        settings = Settings(port=1194)
        settings.protocol = "tcp"
        db.add(settings)
        db.commit()
        db.refresh(settings)

    return settings


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
    return settings

