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
from datetime import date, datetime, UTC
from typing import Iterable

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.db.models import Node, User
from backend.logger import logger
from backend.node.requests import NodeRequests
from backend.schema.output import ResponseModel


router = APIRouter(prefix="/mlogin", tags=["Global Multi-login"])

DATA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data")
)
LOCK_PATH = os.path.join(DATA_DIR, "global_mlogin.lock")

# Keep registry rows for unreachable nodes for a while, but aggressively remove
# stale rows for nodes whose live /sync/usage was reachable and no longer lists
# the session. This prevents missed disconnect hooks from blocking users.
SESSION_TTL_SECONDS = int(os.getenv("OVPANEL_MLOGIN_SESSION_TTL", "86400"))  # 24 hours
STATUS_GRACE_SECONDS = int(os.getenv("OVPANEL_MLOGIN_STATUS_GRACE", "30"))
NODE_USAGE_TIMEOUT = float(os.getenv("OVPANEL_MLOGIN_NODE_TIMEOUT", "1.5"))
_MAX_SESSION_KEY_LEN = 256


class MLoginEvent(BaseModel):
    common_name: str = Field(max_length=128)
    session_key: str = Field(min_length=1, max_length=_MAX_SESSION_KEY_LEN)
    trusted_ip: str | None = Field(default=None, max_length=64)
    trusted_port: str | None = Field(default=None, max_length=8)
    ifconfig_pool_remote_ip: str | None = Field(default=None, max_length=64)


# ── File lock ─────────────────────────────────────────────────────
# NOTE: fcntl.flock is advisory-only on NFS. Ensure DATA_DIR is on
# a local filesystem for correct locking.

@contextmanager
def _global_lock():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_PATH, "a+") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


_mlogin_table_ready: bool = False


def _ensure_table(db: Session) -> None:
    global _mlogin_table_ready
    if _mlogin_table_ready:
        return
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
    _mlogin_table_ready = True


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
    """Strip the '-<node_name>' suffix from the CN to get the panel username.

    The CN format is '<username>-<node_name>'. When the node name itself
    contains dashes, we strip the exact suffix length to avoid ambiguity.
    """
    suffix = f"-{node_name}"
    if common_name.endswith(suffix):
        return common_name[: -len(suffix)]
    # Fallback: strip after the LAST dash (matches old/odd configs).
    if "-" in common_name:
        return common_name.rsplit("-", 1)[0]
    return common_name


def _split_real_address(real_address: str) -> tuple[str, str]:
    if not real_address:
        return "", ""
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
            resp = requests.get(
                api, headers={"key": node.key}, timeout=NODE_USAGE_TIMEOUT
            )
            if resp.status_code != 200:
                logger.warning(
                    "global mlogin: node %s usage HTTP %s",
                    node.name, resp.status_code,
                )
                continue
            payload = resp.json()
            if not payload.get("success"):
                logger.warning(
                    "global mlogin: node %s usage failed: %s",
                    node.name, payload.get("msg"),
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
            logger.warning(
                "global mlogin: node %s usage unavailable: %s", node.name, e
            )

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
    """Remove stale rows: expired TTL, or gone from a reachable node's live status."""
    # 1. Purge all rows older than SESSION_TTL_SECONDS
    db.execute(
        text("DELETE FROM global_mlogin_sessions WHERE updated_at < :cutoff"),
        {"cutoff": now - SESSION_TTL_SECONDS},
    )

    # 2. For reachable nodes, purge rows that are NOT in the live set
    #    (the node's status is the source of truth for active sessions).
    if reachable_nodes:
        placeholders = ", ".join(f":rn{i}" for i in range(len(reachable_nodes)))
        rn_params = {f"rn{i}": name for i, name in enumerate(reachable_nodes)}
        db.execute(
            text(
                "DELETE FROM global_mlogin_sessions "
                "WHERE node_name IN (" + placeholders + ") "
                "AND created_at < :grace_cutoff"
            ),
            {**rn_params, "grace_cutoff": now - STATUS_GRACE_SECONDS},
        )
        # Then remove any remaining rows for those nodes that are NOT in live
        rows = db.execute(
            text(
                "SELECT id, node_name, common_name, trusted_ip, trusted_port "
                "FROM global_mlogin_sessions "
                "WHERE node_name IN (" + placeholders + ")"
            ),
            rn_params,
        ).fetchall()
        for row in rows:
            key = (
                str(row[1] or ""),
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
    user = db.query(User).filter(User.name == username).first()
    uid = user.uuid if user else username  # fall back to name if user not found

    nodes: Iterable[Node] = db.query(Node).filter(Node.status == True).all()  # noqa: E712
    for node in nodes:
        common_name = f"{username}-{node.name}"
        try:
            # disconnect_user expects the UID (primary key), not the CN
            NodeRequests(
                address=node.address,
                port=node.port,
                api_key=node.key,
                use_tls=node.use_tls,
            ).disconnect_user(uid)
        except Exception as e:
            logger.warning(
                "single-login takeover: failed to disconnect %s on %s: %s",
                common_name, node.name, e,
            )
    db.execute(
        text("DELETE FROM global_mlogin_sessions WHERE username = :username"),
        {"username": username},
    )
    db.commit()


def _user_policy(user: User | None) -> tuple[bool, str, int, int]:
    """Check user policy. Returns (ok, msg, global_active, max_logins)."""
    if not user:
        return False, "user not found", 0, 0
    if not bool(user.is_active):
        return False, "user inactive", 0, 0
    if user.expiry_date and user.expiry_date < date.today():
        return False, "user expired", 0, 0
    used = user.used or 0
    if user.total is not None and user.total <= used:
        return False, "traffic limit reached", 0, 0
    max_logins = int(user.max_logins or 0)
    return True, "ok", 0, max_logins


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

    policy_ok, policy_msg, _, max_logins = _user_policy(user)
    if not policy_ok:
        return {
            "success": True,
            "allow": False,
            "msg": policy_msg,
            "data": {"username": username, "global_active": 0, "max_logins": max_logins},
        }

    now = time.time()

    # Poll live sessions BEFORE acquiring the lock. This keeps the
    # HTTP-bound node polling outside the critical section so other
    # connect/disconnect requests aren't blocked by slow nodes.
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
                    "MAX_LOGIN_TAKEOVER tehran=%s user=%s cn=%s node=%s "
                    "active=%s max=1 action=disconnect_old_allow_new",
                    _panel_now(), username, event.common_name, node.name,
                    global_active,
                )
                _disconnect_user_everywhere(username, db)
                existing_sessions = set()
                global_active = 0
            else:
                logger.info(
                    "MAX_LOGIN_REJECT tehran=%s user=%s cn=%s node=%s "
                    "active=%s max=%s reason=max_login_reached",
                    _panel_now(), username, event.common_name, node.name,
                    global_active, max_logins,
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
            text(
                "DELETE FROM global_mlogin_sessions "
                "WHERE session_key = :session_key"
            ),
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
            # Fallback: match by session identity (key may be absent from
            # registry if cleanup already ran, so match by CN + IP + port).
            db.execute(
                text(
                    "DELETE FROM global_mlogin_sessions "
                    "WHERE node_name = :node_name "
                    "AND common_name = :common_name "
                    "AND trusted_ip = :trusted_ip "
                    "AND trusted_port = :trusted_port"
                ),
                {
                    "node_name": node.name,
                    "common_name": event.common_name,
                    "trusted_ip": event.trusted_ip or "",
                    "trusted_port": event.trusted_port or "",
                },
            )
        db.commit()

    return ResponseModel(
        success=True, msg="disconnected",
        data={"username": _base_username(event.common_name, node.name)},
    )


def _panel_now() -> str:
    """Current time in the panel's configured timezone."""
    from backend.db.engine import SessionLocal
    from backend.db import crud as _crud

    db = SessionLocal()
    try:
        settings = _crud.get_settings(db)
        tz_name = getattr(settings, "timezone", "UTC") or "UTC"
    finally:
        db.close()
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


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
