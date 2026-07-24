from pydantic import BaseModel, Field, ConfigDict
from datetime import date
from typing import Any, Optional


class ResponseModel(BaseModel):
    success: bool
    msg: str
    data: Optional[Any] = None


class Users(BaseModel):
    name: str
    is_active: bool
    total: Optional[float] = None
    used: Optional[float] = None
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

    class Config:
        from_attributes = True


class Settings(BaseModel):
    subscription_url_prefix: str
    subscription_path: str
    timezone: str = "UTC"
    panel_version: str = "1.4.0"
    bot_token: Optional[str] = None
    bot_enabled: bool = False
    default_days: int = 30
    default_traffic_gb: int = 100
    default_max_users: int = 1
    owner_telegram_id: Optional[int] = None


class Admins(BaseModel):
    username: str
    users_count: int = 0
    telegram_id: Optional[int] = None
    username_prefix: Optional[str] = None

    class Config:
        from_attributes = True
