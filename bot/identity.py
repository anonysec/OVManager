# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Map a Telegram account onto a panel owner/admin and mint an API session."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from bot.config import config

log = logging.getLogger(__name__)

_CACHE_TTL = 45.0
_identity_cache: dict[int, tuple[float, Actor | None]] = {}
_token_cache: dict[tuple[str, str], tuple[float, str]] = {}
_TOKEN_TTL = 25 * 60


@dataclass(frozen=True)
class Actor:
    telegram_id: int
    username: str
    role: str  # owner | admin
    token: str


def invalidate(telegram_id: int | None = None) -> None:
    if telegram_id is None:
        _identity_cache.clear()
        return
    _identity_cache.pop(telegram_id, None)


def invalidate_token(token: str | None) -> None:
    """Drop every cached identity/session matching a revoked token.

    Called when the panel answers 401: the next require_actor() re-resolves
    and mints a fresh session instead of replaying the dead token.
    """
    if not token:
        return
    for tg_id, (_, actor) in list(_identity_cache.items()):
        if actor is not None and actor.token == token:
            _identity_cache.pop(tg_id, None)
    for key, (_, cached) in list(_token_cache.items()):
        if cached == token:
            _token_cache.pop(key, None)


async def resolve(telegram_id: int) -> Actor | None:
    now = time.monotonic()
    hit = _identity_cache.get(telegram_id)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    actor = _resolve_local(telegram_id)
    if actor is None:
        actor = await _resolve_remote(telegram_id)

    _identity_cache[telegram_id] = (now, actor)
    return actor


def _resolve_local(telegram_id: int) -> Actor | None:
    try:
        from backend.config import config as panel
        from backend.db import crud
        from backend.db.engine import SessionLocal
    except Exception:
        return None

    db = SessionLocal()
    try:
        settings = crud.get_settings(db)
        owner_id = getattr(settings, "owner_telegram_id", None)
        if owner_id and int(owner_id) == telegram_id:
            token = _mint_local(panel.ADMIN_USERNAME, "owner")
            return Actor(telegram_id, panel.ADMIN_USERNAME, "owner", token) if token else None
        admin = crud.get_admin_by_telegram_id(db, telegram_id)
        if admin:
            token = _mint_local(admin.username, "admin")
            return Actor(telegram_id, admin.username, "admin", token) if token else None
    except Exception as exc:
        log.warning("Local identity lookup failed: %s", exc)
    finally:
        db.close()
    return None


def _mint_local(username: str, role: str) -> str | None:
    key = (username, role)
    now = time.monotonic()
    cached = _token_cache.get(key)
    if cached and now - cached[0] < _TOKEN_TTL:
        return cached[1]
    try:
        from backend.auth.sessions import create_session
        from backend.db.engine import SessionLocal
    except Exception:
        return None
    db = SessionLocal()
    try:
        token = create_session(db, username, role, user_agent="ovmanager-telegram-bot")
        _token_cache[key] = (now, token)
        return token
    except Exception as exc:
        log.error("Could not mint panel session for %s: %s", username, exc)
        return None
    finally:
        db.close()


async def _resolve_remote(telegram_id: int) -> Actor | None:
    """Standalone mode: log in with env credentials and match Telegram IDs via API."""
    token = await service_token()
    if not token:
        return None
    from bot.api import Panel

    panel = Panel(token)
    settings = await panel.get_settings()
    if int(settings.get("owner_telegram_id") or 0) == telegram_id:
        username = config.api_username or "owner"
        return Actor(telegram_id, username, "owner", token)
    # Admin list is owner-only; if we are logged in as owner we can see it.
    for admin in await panel.get_admins():
        if int(admin.get("telegram_id") or 0) == telegram_id:
            return Actor(telegram_id, admin.get("username") or "admin", "admin", token)
    return None


async def service_token() -> str | None:
    if config.api_token:
        return config.api_token
    if config.api_username and config.api_password:
        from bot.api import login

        return await login(config.api_username, config.api_password)
    # Last resort when running next to the panel: owner session.
    try:
        from backend.config import config as panel

        return _mint_local(panel.ADMIN_USERNAME, "owner")
    except Exception:
        return None
