# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Runtime configuration for the Telegram operator bot."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


def _default_plans() -> dict[str, tuple[int, int, int]]:
    """Named plans: (days, traffic_gb, max_logins). 0 = unlimited."""
    return {
        "standard": (30, 100, 1),
        "team": (30, 200, 2),
        "unlimited": (0, 0, 0),
    }


@dataclass
class BotConfig:
    token: str = ""
    api_url: str = ""
    default_days: int = 30
    default_traffic_gb: int = 100
    default_max_users: int = 1
    owner_telegram_id: int | None = None
    bot_enabled: bool = False
    plans: dict[str, tuple[int, int, int]] = field(default_factory=_default_plans)
    # Standalone (Docker) login, used when the bot cannot mint a local session.
    api_username: str = ""
    api_password: str = ""
    api_token: str = ""

    def load_from_env(self) -> None:
        self.token = os.getenv("BOT_TOKEN", "") or self.token
        self.api_url = os.getenv("OVM_API_URL", "") or self.api_url
        self.default_days = int(os.getenv("DEFAULT_DAYS", str(self.default_days)))
        self.default_traffic_gb = int(os.getenv("DEFAULT_TRAFFIC", str(self.default_traffic_gb)))
        self.default_max_users = int(os.getenv("DEFAULT_USERS", str(self.default_max_users)))
        self.api_username = os.getenv("OVM_USERNAME", "")
        self.api_password = os.getenv("OVM_PASSWORD", "")
        self.api_token = os.getenv("OVM_API_TOKEN", "")
        owner = os.getenv("OWNER_TELEGRAM_ID", "")
        if owner.isdigit():
            self.owner_telegram_id = int(owner)
        self._load_plans_from_env()

    def _load_plans_from_env(self) -> None:
        defaults = _default_plans()
        plans: dict[str, tuple[int, int, int]] = {}
        for name, (days, traffic, logins) in defaults.items():
            prefix = f"BOT_PLAN_{name.upper()}"
            plans[name] = (
                int(os.getenv(f"{prefix}_DAYS", str(days))),
                int(os.getenv(f"{prefix}_TRAFFIC", str(traffic))),
                int(os.getenv(f"{prefix}_USERS", str(logins))),
            )
        self.plans = plans

    def load_from_db(self) -> None:
        """Read token / enable flag / defaults from the panel database."""
        try:
            from backend.db import models
            from backend.db.engine import SessionLocal

            db = SessionLocal()
            try:
                settings = db.query(models.Settings).first()
                if not settings:
                    return
                if settings.bot_token:
                    self.token = _decrypt_bot_token(settings.bot_token)
                self.bot_enabled = bool(settings.bot_enabled)
                self.owner_telegram_id = settings.owner_telegram_id
                self.default_days = settings.default_days or self.default_days
                self.default_traffic_gb = settings.default_traffic_gb or self.default_traffic_gb
                self.default_max_users = settings.default_max_users or self.default_max_users
                self.plans["standard"] = (
                    self.default_days,
                    self.default_traffic_gb,
                    self.default_max_users,
                )
            finally:
                db.close()
        except Exception as exc:
            log.warning("Could not load bot config from database: %s", exc)

    def resolve_api_url(self) -> str:
        if self.api_url:
            return self.api_url.rstrip("/")
        host, port = "127.0.0.1", 2095
        try:
            from backend.config import config as panel

            host = getattr(panel, "HOST", host) or host
            port = int(getattr(panel, "PORT", port) or port)
        except Exception:
            pass
        if host in {"0.0.0.0", "::", ""}:
            host = "127.0.0.1"
        self.api_url = f"http://{host}:{port}"
        return self.api_url


def _decrypt_bot_token(stored: str) -> str:
    """Decrypt a Fernet-wrapped token; fall back to plaintext (legacy rows)."""
    try:
        from backend.db.crud import _fernet

        if _fernet:
            try:
                return _fernet.decrypt(stored.encode()).decode()
            except Exception:
                return stored
    except Exception:
        pass
    return stored


config = BotConfig()
