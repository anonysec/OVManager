# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

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
    # JSON map {node_name: last_seen_cumulative_bytes}. Lets traffic deltas be
    # computed correctly per node when a user is connected to several nodes.
    node_usage: Mapped[str] = mapped_column(default="{}", server_default="{}")
    # Max simultaneous logins/devices allowed per config.
    # 1 = single login (OpenVPN default), 0 = unlimited.
    max_logins: Mapped[int] = mapped_column(default=1, nullable=False)
    expiry_date: Mapped[date] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)
    owner: Mapped[str] = mapped_column(nullable=False)
    # Last time the user had at least one live connection (set whenever
    # active_connections > 0). Used by the UI "Last Online" column.
    last_online: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(unique=True)
    password: Mapped[str] = mapped_column()
    telegram_id: Mapped[int] = mapped_column(nullable=True, unique=True)
    username_prefix: Mapped[str] = mapped_column(nullable=True)


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
    country_code: Mapped[str] = mapped_column(nullable=True)
    latitude: Mapped[float] = mapped_column(nullable=True)
    longitude: Mapped[float] = mapped_column(nullable=True)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tunnel_address: Mapped[str] = mapped_column(nullable=True)
    port: Mapped[int] = mapped_column(default=1194, nullable=False)
    protocol: Mapped[str] = mapped_column(default="tcp", nullable=False)
    # Operator-configured display timezone (IANA name, e.g. "Asia/Tehran").
    # Used by the UI to render "last online", logs, and expiry times.
    timezone: Mapped[str] = mapped_column(default="UTC", nullable=False)
    # Prefix for auto-generated usernames (e.g. "420" → 4201, 4202...).
    # Null/empty = manual naming only.
    # Telegram bot config
    bot_token: Mapped[str] = mapped_column(nullable=True)
    bot_enabled: Mapped[bool] = mapped_column(default=False)
    default_days: Mapped[int] = mapped_column(default=30)
    default_traffic_gb: Mapped[int] = mapped_column(default=100)
    default_max_users: Mapped[int] = mapped_column(default=1)
    owner_telegram_id: Mapped[int] = mapped_column(nullable=True)
    # Subscription link settings — persisted to DB (was in-memory only).
    subscription_url_prefix: Mapped[str] = mapped_column(nullable=True)
    subscription_path: Mapped[str] = mapped_column(default="sub", nullable=False)
    # Dynamic URL path prefix for the panel (like 3x-ui's "panel path" feature).
    # Empty = serve at root (/). Non-empty = serve at /<urlpath>/... only.
    # When set, requests to root or other paths get an empty response (no 404).
    # Changeable at runtime via the web UI — no restart required.
    urlpath: Mapped[str] = mapped_column(default="", nullable=False)
