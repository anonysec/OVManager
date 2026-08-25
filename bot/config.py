# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

import os
from dataclasses import dataclass, field


def _default_plans():
    """Default plan definitions: {name: (days, traffic_kb, max_users)}."""
    return {
        "bronze": (30, 200, 1),
        "silver": (30, 200, 2),
        "gold": (0, 0, 0),
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
    webhook_url: str = ""
    plans: dict = field(default_factory=_default_plans)

    def load_plans_from_env(self):
        """Load plans from environment variables with fallback defaults.

        Each plan can be overridden via:
          BOT_PLAN_<NAME>_DAYS     – validity in days (0 = unlimited)
          BOT_PLAN_<NAME>_TRAFFIC  – traffic in KB (0 = unlimited)
          BOT_PLAN_<NAME>_USERS    – max users (0 = unlimited)
        """
        defaults = _default_plans()
        self.plans = {}
        for name, (d, t, mu) in defaults.items():
            env_prefix = f"BOT_PLAN_{name.upper()}"
            self.plans[name] = (
                int(os.getenv(f"{env_prefix}_DAYS", str(d))),
                int(os.getenv(f"{env_prefix}_TRAFFIC", str(t))),
                int(os.getenv(f"{env_prefix}_USERS", str(mu))),
            )

    def load_from_env(self):
        self.token = os.getenv("BOT_TOKEN", "")
        self.api_url = os.getenv("OVM_API_URL", "")
        self.default_days = int(os.getenv("DEFAULT_DAYS", "30"))
        self.default_traffic_gb = int(os.getenv("DEFAULT_TRAFFIC", "100"))
        self.default_max_users = int(os.getenv("DEFAULT_USERS", "1"))
        self.load_plans_from_env()

    def load_from_db(self):
        """Fetch bot config from local database when running in same process."""
        try:
            from backend.db import models
            from backend.db.engine import SessionLocal

            db = SessionLocal()
            try:
                s = db.query(models.Settings).first()
                if s:
                    if s.bot_token:
                        # Token is encrypted at rest via Fernet in crud.update_bot_config.
                        # Decrypt before use, but stay backwards-compatible if the DB
                        # still holds a plaintext token (from a pre-encryption migration).
                        from backend.db.crud import _fernet

                        if _fernet:
                            try:
                                self.token = _fernet.decrypt(s.bot_token.encode()).decode()
                            except Exception:
                                # Token wasn't encrypted — fall back to plaintext (legacy)
                                self.token = s.bot_token
                        else:
                            self.token = s.bot_token
                    self.bot_enabled = s.bot_enabled
                    self.owner_telegram_id = s.owner_telegram_id
                    self.default_days = s.default_days
                    self.default_traffic_gb = s.default_traffic_gb
                    self.default_max_users = s.default_max_users
            finally:
                db.close()
        except Exception as e:
            print(f"Failed to load config from DB: {e}")

    def resolve_api_url(self):
        """Resolve API URL — use env var, or auto-detect from panel config."""
        if self.api_url:
            return self.api_url
        try:
            from backend.config import config as panel_config

            port = getattr(panel_config, "PORT", 2095)
            host = getattr(panel_config, "HOST", "127.0.0.1")
            self.api_url = f"http://{host}:{port}"
        except Exception:
            self.api_url = "http://127.0.0.1:2095"
        return self.api_url


config = BotConfig()
