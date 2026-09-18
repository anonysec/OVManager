# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from backend.version import __version__


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
        # The metrics job stores a datetime on the ORM row while the API
        # contract is an ISO string (or null). Coerce here so every
        # model_validate(db_user) call site survives a non-null value —
        # otherwise the first user to come online 500s the whole list.
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

    model_config = ConfigDict(from_attributes=True)
