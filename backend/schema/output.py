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


class Admins(BaseModel):
    username: str
    users_count: int = 0

    class Config:
        from_attributes = True
