"""Request/response models for the OVManager API.

Input models (validated by FastAPI) and response envelopes lived in two
underscore-prefixed files; they are one module now. Import from the
package root: ``from backend.schema import CreateUser, ResponseModel``.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.version import __version__


class CreateUser(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    total: int | None = Field(default=None, ge=0, le=2**60)
    used: int | None = Field(default=None, ge=0, le=2**60)
    max_logins: int | None = Field(default=None, ge=0, le=1000)
    expiry_date: date | None = None
    tag: str | None = Field(default=None, max_length=64)


class UpdateUser(BaseModel):
    name: str
    total: int | None = Field(default=None, ge=0, le=2**60)
    used: int | None = Field(default=None, ge=0, le=2**60)
    max_logins: int | None = Field(default=None, ge=0, le=1000)
    expiry_date: date | None = None
    tag: str | None = Field(default=None, max_length=64)
    status: bool | None = None


class NodeCreate(BaseModel):
    name: str = Field(max_length=64)
    address: str
    tunnel_address: str = Field(default=None)
    protocol: str = Field(default="tcp")
    ovpn_port: int = Field(default=1194)
    port: int = 2083
    key: str | None = Field(default=None, min_length=16, max_length=128)
    status: bool = Field(default=True)
    set_new_setting: bool = Field(default=False)
    use_tls: bool = Field(default=True)
    country_code: str | None = Field(default=None, max_length=3, pattern=r"^[A-Za-z]{2,3}$")

    @field_validator("key", mode="before")
    @classmethod
    def _blank_key_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    telegram_id: int | None = Field(default=None, ge=0)
    username_prefix: str | None = Field(default=None, max_length=20)
    default_days: int | None = Field(default=None, ge=1, le=3650)
    default_traffic_gb: int | None = Field(default=None, ge=0, le=1000000)
    default_max_users: int | None = Field(default=None, ge=0, le=1000)


class AdminUpdate(BaseModel):
    username: str
    password: str | None = Field(default=None, min_length=8, max_length=128)
    telegram_id: int | None = Field(default=None, ge=0)
    username_prefix: str | None = Field(default=None, max_length=20)
    default_days: int | None = Field(default=None, ge=1, le=3650)
    default_traffic_gb: int | None = Field(default=None, ge=0, le=1000000)
    default_max_users: int | None = Field(default=None, ge=0, le=1000)


class StatusToggle(BaseModel):
    name: str
    status: bool


class AdminStatusUpdate(BaseModel):
    status: bool


class ResponseModel(BaseModel):
    success: bool
    msg: str
    data: Any | None = None


class Users(BaseModel):
    id: int  # autoincrement creation order; UI default-sorts newest-first
    name: str
    is_active: bool
    total: int | None = None
    used: int | None = None
    max_logins: int = 1
    expiry_date: date
    owner: str
    uuid: str
    last_online: str | None = None
    tag: str | None = None
    model_config = ConfigDict(from_attributes=True)

    @field_validator("last_online", mode="before")
    @classmethod
    def _coerce_last_online(cls, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return value


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
    id: int  # autoincrement creation order; UI default-sorts newest-first
    username: str
    users_count: int = 0
    telegram_id: int | None = None
    username_prefix: str | None = None
    disabled: bool = False
    default_days: int | None = None
    default_traffic_gb: int | None = None
    default_max_users: int | None = None
    effective_defaults: dict = {}

    model_config = ConfigDict(from_attributes=True)
