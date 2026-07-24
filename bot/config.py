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
        # Default to panel port 2095 if OVM_API_URL not set
        self.api_url = os.getenv("OVM_API_URL", "http://ovmanager:2095")
        self.default_days = int(os.getenv("DEFAULT_DAYS", "30"))
        self.default_traffic_gb = int(os.getenv("DEFAULT_TRAFFIC", "100"))
        self.default_max_users = int(os.getenv("DEFAULT_USERS", "1"))

    def load_from_db(self):
        """Fetch bot config from local database when running in same container."""
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


config = BotConfig()