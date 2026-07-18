from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import BigInteger, DateTime
from .engine import Base
from datetime import date, datetime


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


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tunnel_address: Mapped[str] = mapped_column(nullable=True)
    port: Mapped[int] = mapped_column(default=1194, nullable=False)
    protocol: Mapped[str] = mapped_column(default="tcp", nullable=False)
    # Operator-configured display timezone (IANA name, e.g. "Asia/Tehran").
    # Used by the UI to render "last online", logs, and expiry times.
    timezone: Mapped[str] = mapped_column(default="UTC", nullable=False)
