from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from backend.version import __version__


class ResponseModel(BaseModel):
    success: bool
    msg: str
    data: Any | None = None


class Users(BaseModel):
    name: str
    is_active: bool
    total: int | None = None
    used: int | None = None
    max_logins: int = 1
    expiry_date: date
    owner: str
    uuid: str
    last_online: str | None = None
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
    bot_token: str | None = None  # write-only; never populated in responses
    bot_configured: bool = False
    bot_enabled: bool = False
    default_days: int = 30
    default_traffic_gb: int = 100
    default_max_users: int = 1
    owner_telegram_id: int | None = None
    urlpath: str = ""


class Admins(BaseModel):
    username: str
    users_count: int = 0
    telegram_id: int | None = None
    username_prefix: str | None = None

    model_config = ConfigDict(from_attributes=True)
