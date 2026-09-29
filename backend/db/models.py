from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    uuid: Mapped[str] = mapped_column(unique=True, nullable=True)
    name: Mapped[str] = mapped_column(unique=True)
    total: Mapped[int] = mapped_column(BigInteger, nullable=True)
    used: Mapped[int] = mapped_column(BigInteger, nullable=True)
    last_node_usage: Mapped[int] = mapped_column(BigInteger, default=0)
    node_usage: Mapped[str] = mapped_column(default="{}", server_default="{}")
    max_logins: Mapped[int] = mapped_column(default=1, nullable=False)
    expiry_date: Mapped[date] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
    owner: Mapped[str] = mapped_column(nullable=False)
    last_online: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    tag: Mapped[str] = mapped_column(nullable=True, default=None)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str] = mapped_column()
    telegram_id: Mapped[int] = mapped_column(nullable=True, unique=True)
    username_prefix: Mapped[str] = mapped_column(nullable=True)
    disabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    default_days: Mapped[int | None] = mapped_column(nullable=True)
    default_traffic_gb: Mapped[int | None] = mapped_column(nullable=True)
    default_max_users: Mapped[int | None] = mapped_column(nullable=True)


class AuthSession(Base):
    """Opaque login session. Only the SHA-256 of the raw token is stored."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    username: Mapped[str] = mapped_column(index=True)
    role: Mapped[str] = mapped_column()  # "owner" | "admin"
    created_at: Mapped[float] = mapped_column()  # unix ts
    expires_at: Mapped[float] = mapped_column()  # absolute cap: created + SESSION_MAX_SECONDS
    last_seen_at: Mapped[float] = mapped_column()  # idle timeout reference (sliding)
    user_agent: Mapped[str] = mapped_column(nullable=True)
    ip: Mapped[str] = mapped_column(nullable=True)


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column()
    address: Mapped[str] = mapped_column()
    tunnel_address: Mapped[str] = mapped_column(nullable=True)
    protocol: Mapped[str] = mapped_column()
    ovpn_port: Mapped[int] = mapped_column()
    port: Mapped[int] = mapped_column()
    key: Mapped[str] = mapped_column(nullable=False)
    status: Mapped[bool] = mapped_column(default=True)
    use_tls: Mapped[bool] = mapped_column(default=False)
    server_ca: Mapped[str | None] = mapped_column(nullable=True, default=None)
    country_code: Mapped[str] = mapped_column(nullable=True)
    latitude: Mapped[float] = mapped_column(nullable=True)
    longitude: Mapped[float] = mapped_column(nullable=True)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tunnel_address: Mapped[str] = mapped_column(nullable=True)
    port: Mapped[int] = mapped_column(default=1194, nullable=False)
    protocol: Mapped[str] = mapped_column(default="tcp", nullable=False)
    timezone: Mapped[str] = mapped_column(default="UTC", nullable=False)
    bot_token: Mapped[str] = mapped_column(nullable=True)
    bot_enabled: Mapped[bool] = mapped_column(default=False)
    default_days: Mapped[int] = mapped_column(default=30)
    default_traffic_gb: Mapped[int] = mapped_column(default=100)
    default_max_users: Mapped[int] = mapped_column(default=1)
    owner_telegram_id: Mapped[int] = mapped_column(nullable=True)
    notify_expiry: Mapped[bool] = mapped_column(default=True, nullable=False)
    notify_traffic: Mapped[bool] = mapped_column(default=True, nullable=False)
    notify_node_down: Mapped[bool] = mapped_column(default=True, nullable=False)
    subscription_url_prefix: Mapped[str] = mapped_column(nullable=True)
    subscription_path: Mapped[str] = mapped_column(default="sub", nullable=False)
    urlpath: Mapped[str] = mapped_column(default="", nullable=False)
    auto_backup_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    auto_backup_time: Mapped[str] = mapped_column(default="03:30", nullable=False)
    auto_backup_keep: Mapped[int] = mapped_column(default=50, nullable=False)
    offsite_backup_target: Mapped[str] = mapped_column(nullable=True)
    telegram_backup_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
