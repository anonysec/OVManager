from pydantic import BaseModel, Field
from datetime import date
from typing import Optional


class CreateUser(BaseModel):
    name: str = Field(min_length=3, max_length=10)
    total: Optional[float] = None
    used: Optional[float] = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: int = Field(default=1, ge=0, le=1000)
    expiry_date: date


class UpdateUser(BaseModel):
    name: str
    total: Optional[float] = None
    used: Optional[float] = None
    # Max simultaneous logins/devices per config. 1 = single login, 0 = unlimited.
    max_logins: Optional[int] = Field(default=None, ge=0, le=1000)
    expiry_date: Optional[date]
    status: bool = True


class NodeCreate(BaseModel):
    name: str = Field(max_length=10)
    address: str
    tunnel_address: str = Field(default=None)
    protocol: str = Field(default="tcp")
    ovpn_port: int = Field(default=1194)
    port: int = 2083
    key: Optional[str] = Field(default=None, min_length=10, max_length=40)
    status: bool = Field(default=True)
    set_new_setting: bool = Field(default=False)
    use_tls: bool = Field(default=False)


class AdminCreate(BaseModel):
    username: str = Field(min_length=3, max_length=10)
    password: str = Field(min_length=6, max_length=20)
    telegram_id: Optional[int] = Field(default=None, ge=0)
    username_prefix: Optional[str] = Field(default=None, max_length=20)


class AdminUpdate(BaseModel):
    username: str
    password: Optional[str] = Field(default=None, min_length=6, max_length=20)
    telegram_id: Optional[int] = Field(default=None, ge=0)
    username_prefix: Optional[str] = Field(default=None, max_length=20)
