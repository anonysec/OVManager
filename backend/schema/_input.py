from datetime import date

from pydantic import BaseModel, Field


class CreateUser(BaseModel):
    name: str = Field(min_length=3, max_length=64)
    total: int | None = None
    used: int | None = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: int = Field(default=1, ge=0, le=1000)
    expiry_date: date


class UpdateUser(BaseModel):
    name: str
    total: int | None = None
    used: int | None = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: int | None = Field(default=None, ge=0, le=1000)
    expiry_date: date | None
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
    use_tls: bool = Field(default=False)


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
