import os
from dataclasses import dataclass, field


@dataclass
class BotConfig:
    token: str = ""
    api_url: str = ""
    default_days: int = 30
    default_traffic_gb: int = 100
    default_max_users: int = 1
    owner_telegram_id: int | None = None
    bot_enabled: bool = False

    def load_from_env(self):
        self.token = os.getenv("BOT_TOKEN", "")
        self.api_url = os.getenv("OVM_API_URL", "")
        self.default_days = int(os.getenv("DEFAULT_DAYS", "30"))
        self.default_traffic_gb = int(os.getenv("DEFAULT_TRAFFIC", "100"))
        self.default_max_users = int(os.getenv("DEFAULT_USERS", "1"))

    def load_from_db(self):
        """Fetch bot config from local database when running in same process."""
        try:
            from backend.db.engine import SessionLocal
            from backend.db import models

            db = SessionLocal()
            try:
                s = db.query(models.Settings).first()
                if s:
                    if s.bot_token:
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
