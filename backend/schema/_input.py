# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from datetime import date

from pydantic import BaseModel, Field


class CreateUser(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    total: int | None = None
    used: int | None = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: int = Field(default=1, ge=0, le=1000)
    # Optional: omitted → today + Settings.default_days (crud.create_user).
    # total=None stays unlimited; only expiry gets a default.
    expiry_date: date | None = None


class UpdateUser(BaseModel):
    name: str
    total: int | None = None
    used: int | None = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: int | None = Field(default=None, ge=0, le=1000)
    # `date | None` with no default is REQUIRED in Pydantic v2 (Optional does
    # not imply a default). That made every partial update a 422 — the
    # Telegram bot's "set traffic"/"set logins" buttons send neither field.
    # Defaulting to None makes it genuinely optional; crud.update_user
    # distinguishes omitted from explicitly-null via model_fields_set and
    # rejects the latter, since the column is NOT NULL.
    expiry_date: date | None = None
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
    # TLS on by default for new nodes; existing rows keep their stored value.
    use_tls: bool = Field(default=True)


class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    telegram_id: int | None = Field(default=None, ge=0)
    username_prefix: str | None = Field(default=None, max_length=20)


class AdminUpdate(BaseModel):
    username: str
    password: str | None = Field(default=None, min_length=8, max_length=128)
    telegram_id: int | None = Field(default=None, ge=0)
    username_prefix: str | None = Field(default=None, max_length=20)


class StatusToggle(BaseModel):
    name: str
    status: bool
