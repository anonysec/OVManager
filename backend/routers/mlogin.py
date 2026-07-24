"""Global multi-login enforcement endpoints used by OpenVPN node hooks.

The node-side client-connect hook calls these endpoints before accepting a VPN
session. The panel combines:

* live OpenVPN status reported by all reachable nodes, and
* a small panel-side active-session registry for race-free simultaneous connects.

This makes ``users.max_logins`` global across nodes instead of per-node.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import Iterable, Optional

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.db.models import Node, User
from backend.logger import logger
from backend.node.requests import NodeRequests
from backend.schema.output import ResponseModel


router = APIRouter(prefix="/mlogin", tags=["Global Multi-login"])

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
LOCK_PATH = os.path.join(DATA_DIR, "global_mlogin.lock")

# Keep registry rows for unreachable nodes for a while, but aggressively remove
# stale rows for nodes whose live /sync/usage was reachable and no longer lists
# the session. This prevents missed disconnect hooks from blocking users.
SESSION_TTL_SECONDS = int(os.getenv("OVPANEL_MLOGIN_SESSION_TTL", "604800"))  # 7 days
STATUS_GRACE_SECONDS = int(os.getenv("OVPANEL_MLOGIN_STATUS_GRACE", "30"))
NODE_USAGE_TIMEOUT = float(os.getenv("OVPANEL_MLOGIN_NODE_TIMEOUT", "1.5"))


class MLoginEvent(BaseModel):
    common_name: str
    session_key: str
    trusted_ip: Optional[str] = None
    trusted_port: Optional[str] = None
    ifconfig_pool_remote_ip: Optional[str] = None


@contextmanager
def _global_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_PATH, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _ensure_table(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS global_mlogin_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                common_name TEXT NOT NULL,
                node_name TEXT NOT NULL,
                session_key TEXT NOT NULL UNIQUE,
                trusted_ip TEXT,
                trusted_port TEXT,
                pool_ip TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_global_mlogin_username "
            "ON global_mlogin_sessions(username)"
        )
    )
    db.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_global_mlogin_node "
            "ON global_mlogin_sessions(node_name)"
        )
    )
    db.commit()


def _authorize_node(db: Session, node_name: str | None, key: str | None) -> Node:
    if not node_name or not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing node name/key",
        )
    node = db.query(Node).filter(Node.name == node_name).first()
    if not node or node.key != key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid node key",
        )
    return node


def _base_username(common_name: str, node_name: str) -> str:
    suffix = f"-{node_name}"
    if common_name.endswith(suffix):
        return common_name[: -len(suffix)]
    # Fallback for old/odd configs. Usernames can contain dashes, but node CNs
    # are generated as <username>-<node>, so stripping the last component is the
    # best fallback when the explicit suffix is missing.
    if "-" in common_name:
        return common_name.rsplit("-", 1)[0]
    return common_name


def _split_real_address(real_address: str) -> tuple[str, str]:
    if not real_address:
        return "", ""
    # OpenVPN usually reports IPv4 as "ip:port". If IPv6 appears, keep the last
    # colon as the port delimiter.
    if ":" in real_address:
        ip, port = real_address.rsplit(":", 1)
        return ip.strip("[]"), port
    return real_address, ""


def _live_sessions_for_user(
    username: str, db: Session
) -> tuple[set[tuple[str, str, str, str]], set[str]]:
    """Return live session keys and node names whose status was reachable.

    Session key tuple: (node_name, common_name, trusted_ip, trusted_port)
    """
    live: set[tuple[str, str, str, str]] = set()
    reachable_nodes: set[str] = set()
    nodes: Iterable[Node] = db.query(Node).filter(Node.status == True).all()  # noqa: E712

    for node in nodes:
        scheme = "https" if node.use_tls else "http"
        api = f"{scheme}://{node.address}:{node.port}/sync/usage"
        try:
            resp = requests.get(api, headers={"key": node.key}, timeout=NODE_USAGE_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(
                    "global mlogin: node %s usage HTTP %s", node.name, resp.status_code
                )
                continue
            payload = resp.json()
            if not payload.get("success"):
                logger.warning(
                    "global mlogin: node %s usage failed: %s",
                    node.name,
                    payload.get("msg"),
                )
                continue
            reachable_nodes.add(node.name)
            data = payload.get("data") or {}
            sessions = data.get("sessions") or {}
            for common_name, per_session in sessions.items():
                if _base_username(common_name, node.name) != username:
                    continue
                if isinstance(per_session, dict) and per_session:
                    for real_address in per_session.keys():
                        ip, port = _split_real_address(str(real_address))
                        live.add((node.name, common_name, ip, port))
                else:
                    live.add((node.name, common_name, "", ""))
        except Exception as e:
            logger.warning("global mlogin: node %s usage unavailable: %s", node.name, e)

    return live, reachable_nodes


def _registry_sessions_for_user(
    username: str, db: Session,
) -> set[tuple[str, str, str, str]]:
    rows = db.execute(
        text(
            "SELECT node_name, common_name, trusted_ip, trusted_port "
            "FROM global_mlogin_sessions WHERE username = :username"
        ),
        {"username": username},
    ).fetchall()
    return {
        (
            str(row[0] or ""),
            str(row[1] or ""),
            str(row[2] or ""),
            str(row[3] or ""),
        )
        for row in rows
    }


def _cleanup_registry(
    db: Session,
    live: set[tuple[str, str, str, str]],
    reachable_nodes: set[str],
    now: float,
) -> None:
    # Always remove very old rows as a last-resort stale protection.
    db.execute(
        text("DELETE FROM global_mlogin_sessions WHERE updated_at < :cutoff"),
        {"cutoff": now - SESSION_TTL_SECONDS},
    )

    # If a node is reachable, its status log is the source of truth for sessions
    # older than the short status refresh grace period.
    if reachable_nodes:
        rows = db.execute(
            text(
                "SELECT id, node_name, common_name, trusted_ip, trusted_port, created_at "
                "FROM global_mlogin_sessions"
            )
        ).fetchall()
        for row in rows:
            node_name = str(row[1] or "")
            if node_name not in reachable_nodes:
                continue
            created_at = float(row[5] or 0)
            if created_at > now - STATUS_GRACE_SECONDS:
                continue
            key = (
                node_name,
                str(row[2] or ""),
                str(row[3] or ""),
                str(row[4] or ""),
            )
            if key not in live:
                db.execute(
                    text("DELETE FROM global_mlogin_sessions WHERE id = :id"),
                    {"id": row[0]},
                )



def _disconnect_user_everywhere(username: str, db: Session) -> None:
    """Best-effort disconnect for single-login takeover.

    For max_logins=1 we keep fair pricing (only one live session) but avoid
    user-facing AUTH_FAILED when switching devices: the newest connection takes
    over and older sessions/markers are cleared across nodes.
    """
    nodes: Iterable[Node] = db.query(Node).filter(Node.status == True).all()  # noqa: E712
    for node in nodes:
        common_name = f"{username}-{node.name}"
        try:
            NodeRequests(address=node.address, port=node.port, api_key=node.key, use_tls=node.use_tls).disconnect_user(common_name)
        except Exception as e:
            logger.warning("single-login takeover: failed to disconnect %s on %s: %s", common_name, node.name, e)
    db.execute(text("DELETE FROM global_mlogin_sessions WHERE username = :username"), {"username": username})
    db.commit()

def _tehran_now() -> str:
    return datetime.now(ZoneInfo("Asia/Tehran")).strftime("%Y-%m-%d %H:%M:%S")


def _user_policy(user: User | None) -> tuple[bool, str]:
    if not user:
        return False, "user not found"
    if not bool(user.is_active):
        return False, "user inactive"
    if user.expiry_date and user.expiry_date < date.today():
        return False, "user expired"
    used = user.used or 0
    if user.total is not None and user.total <= used:
        return False, "traffic limit reached"
    return True, "ok"


@router.post("/connect")
async def global_mlogin_connect(
    event: MLoginEvent,
    db: Session = Depends(get_db),
    key: str | None = Header(default=None),
    x_node_name: str | None = Header(default=None, alias="X-Node-Name"),
):
    """Atomically allow/deny a new OpenVPN session globally."""
    node = _authorize_node(db, x_node_name, key)
    username = _base_username(event.common_name, node.name)
    user = db.query(User).filter(User.name == username).first()

    policy_ok, policy_msg = _user_policy(user)
    if not policy_ok:
        return {
            "success": True,
            "allow": False,
            "msg": policy_msg,
            "data": {"username": username, "global_active": 0, "max_logins": 0},
        }

    max_logins = int(user.max_logins or 0)
    now = time.time()

    # Snapshot live sessions before taking the lock. The registry under the lock
    # handles connect races; live status handles sessions that existed before the
    # global registry feature was installed.
    live, reachable_nodes = _live_sessions_for_user(username, db)
    current = (
        node.name,
        event.common_name,
        str(event.trusted_ip or ""),
        str(event.trusted_port or ""),
    )

    with _global_lock():
        _ensure_table(db)
        _cleanup_registry(db, live, reachable_nodes, now)
        registry = _registry_sessions_for_user(username, db)
        existing_sessions = set(live) | set(registry)
        already_registered = current in existing_sessions
        if not already_registered:
            existing_sessions.discard(current)

        global_active = len(existing_sessions)

        if max_logins > 0 and not already_registered and global_active >= max_logins:
            if max_logins == 1:
                logger.info(
                    "MAX_LOGIN_TAKEOVER tehran=%s user=%s cn=%s node=%s active=%s max=1 action=disconnect_old_allow_new",
                    _tehran_now(), username, event.common_name, node.name, global_active,
                )
                _disconnect_user_everywhere(username, db)
                existing_sessions = set()
                global_active = 0
            else:
                db.commit()
                logger.info(
                    "MAX_LOGIN_REJECT tehran=%s user=%s cn=%s node=%s active=%s max=%s reason=max_login_reached",
                    _tehran_now(),
                    username,
                    event.common_name,
                    node.name,
                    global_active,
                    max_logins,
                )
                return {
                    "success": True,
                    "allow": False,
                    "msg": "max login reached",
                    "data": {
                        "username": username,
                        "global_active": global_active,
                        "max_logins": max_logins,
                    },
                }

        # Re-registering the same session is harmless.
        db.execute(
            text("DELETE FROM global_mlogin_sessions WHERE session_key = :session_key"),
            {"session_key": event.session_key},
        )
        db.execute(
            text(
                """
                INSERT INTO global_mlogin_sessions
                    (username, common_name, node_name, session_key, trusted_ip,
                     trusted_port, pool_ip, created_at, updated_at)
                VALUES
                    (:username, :common_name, :node_name, :session_key, :trusted_ip,
                     :trusted_port, :pool_ip, :created_at, :updated_at)
                """
            ),
            {
                "username": username,
                "common_name": event.common_name,
                "node_name": node.name,
                "session_key": event.session_key,
                "trusted_ip": event.trusted_ip or "",
                "trusted_port": event.trusted_port or "",
                "pool_ip": event.ifconfig_pool_remote_ip or "",
                "created_at": now,
                "updated_at": now,
            },
        )
        db.commit()

    return {
        "success": True,
        "allow": True,
        "msg": "allowed",
        "data": {
            "username": username,
            "global_active": global_active,
            "max_logins": max_logins,
        },
    }


@router.post("/disconnect", response_model=ResponseModel)
async def global_mlogin_disconnect(
    event: MLoginEvent,
    db: Session = Depends(get_db),
    key: str | None = Header(default=None),
    x_node_name: str | None = Header(default=None, alias="X-Node-Name"),
):
    """Unregister an OpenVPN session after client-disconnect."""
    node = _authorize_node(db, x_node_name, key)
    username = _base_username(event.common_name, node.name)

    with _global_lock():
        _ensure_table(db)
        result = db.execute(
            text(
                "DELETE FROM global_mlogin_sessions "
                "WHERE session_key = :session_key AND node_name = :node_name"
            ),
            {"session_key": event.session_key, "node_name": node.name},
        )
        if (result.rowcount or 0) == 0:
            db.execute(
                text(
                    "DELETE FROM global_mlogin_sessions "
                    "WHERE username = :username AND common_name = :common_name "
                    "AND node_name = :node_name AND trusted_ip = :trusted_ip "
                    "AND trusted_port = :trusted_port"
                ),
                {
                    "username": username,
                    "common_name": event.common_name,
                    "node_name": node.name,
                    "trusted_ip": event.trusted_ip or "",
                    "trusted_port": event.trusted_port or "",
                },
            )
        db.commit()

    return ResponseModel(success=True, msg="disconnected", data={"username": username})


@router.get("/status/{username}", response_model=ResponseModel)
async def global_mlogin_status(
    username: str,
    db: Session = Depends(get_db),
    key: str | None = Header(default=None),
    x_node_name: str | None = Header(default=None, alias="X-Node-Name"),
):
    """Debug endpoint for node-authenticated global session count."""
    _authorize_node(db, x_node_name, key)
    now = time.time()
    live, reachable_nodes = _live_sessions_for_user(username, db)
    with _global_lock():
        _ensure_table(db)
        _cleanup_registry(db, live, reachable_nodes, now)
        registry = _registry_sessions_for_user(username, db)
        db.commit()
    sessions = sorted(set(live) | set(registry))
    return ResponseModel(
        success=True,
        msg="global multi-login status",
        data={"username": username, "global_active": len(sessions), "sessions": sessions},
    )