from pydantic import BaseModel, Field, ConfigDict
from datetime import date
from typing import Any, Optional

from cryptography.fernet import Fernet
import os

from backend.version import __version__


_ENCRYPTION_KEY = os.environ.get("BOT_TOKEN_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    _ENCRYPTION_KEY = Fernet.generate_key().decode()
_fernet = Fernet(_ENCRYPTION_KEY.encode())


class ResponseModel(BaseModel):
    success: bool
    msg: str
    data: Optional[Any] = None


class Users(BaseModel):
    name: str
    is_active: bool
    total: Optional[int] = None
    used: Optional[int] = None
    max_logins: int = 1
    expiry_date: date
    owner: str
    uuid: str
    last_online: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class ServerInfo(BaseModel):
    cpu: float
    memory_total: int
    memory_used: int
    memory_percent: float
    disk_total: int
    disk_used: int
    disk_percent: float
    uptime: int

    model_config = ConfigDict(from_attributes=True)


class Settings(BaseModel):
    subscription_url_prefix: str
    subscription_path: str
    timezone: str = "UTC"
    panel_version: str = __version__
    bot_token: Optional[str] = None  # masked — never expose raw token
    bot_enabled: bool = False
    default_days: int = 30
    default_traffic_gb: int = 100
    default_max_users: int = 1
    owner_telegram_id: Optional[int] = None
    urlpath: str = ""


class Admins(BaseModel):
    username: str
    users_count: int = 0
    telegram_id: Optional[int] = None
    username_prefix: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
