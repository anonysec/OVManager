"""Global multi-login status for OpenVPN sessions.

Queries all reachable nodes for live session data and combines with a
panel-side registry for cross-node session tracking.
"""

from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from typing import Iterable

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.db.models import Node, User
from backend.logger import logger
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/mlogin", tags=["Global Multi-login"])

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
LOCK_PATH = os.path.join(DATA_DIR, "global_mlogin.lock")
_NODE_TIMEOUT = float(os.getenv("OVMANAGER_MLOGIN_NODE_TIMEOUT", "1.5"))
_SESSION_TTL = int(os.getenv("OVMANAGER_MLOGIN_SESSION_TTL", "86400"))
_STATUS_GRACE = int(os.getenv("OVMANAGER_MLOGIN_STATUS_GRACE", "30"))


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
    db.execute(text("""CREATE TABLE IF NOT EXISTS global_mlogin_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
        common_name TEXT NOT NULL, node_name TEXT NOT NULL,
        session_key TEXT NOT NULL UNIQUE, trusted_ip TEXT, trusted_port TEXT,
        pool_ip TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)"""))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_gml_user ON global_mlogin_sessions(username)"))
    db.execute(text("CREATE INDEX IF NOT EXISTS idx_gml_node ON global_mlogin_sessions(node_name)"))
    db.commit()


def _authorize_node(db: Session, node_name: str | None, key: str | None) -> Node:
    if not node_name or not key:
        raise HTTPException(status_code=401, detail="Missing node name/key")
    node = db.query(Node).filter(Node.name == node_name).first()
    if not node or node.key != key:
        raise HTTPException(status_code=401, detail="Invalid node key")
    return node


def _split_addr(addr: str) -> tuple[str, str]:
    if ":" in addr:
        ip, port = addr.rsplit(":", 1)
        return ip.strip("[]"), port
    return addr, ""


def _live_sessions(username: str, db: Session) -> tuple[set[tuple], set[str]]:
    """Query all active nodes for live sessions of this user."""
    live: set[tuple] = set()
    reachable: set[str] = set()
    nodes: Iterable[Node] = db.query(Node).filter(Node.status == True).all()  # noqa: E712

    for node in nodes:
        try:
            scheme = "https" if node.use_tls else "http"
            r = requests.get(f"{scheme}://{node.address}:{node.port}/sync/usage",
                             headers={"key": node.key}, timeout=_NODE_TIMEOUT)
            if r.status_code != 200:
                continue
            payload = r.json()
            if not payload.get("success"):
                continue
            reachable.add(node.name)
            for cn, sessions in (payload.get("data") or {}).get("sessions", {}).items():
                try:
                    user = db.query(User).filter(User.id == int(cn)).first()
                except (ValueError, TypeError):
                    continue
                if not user or user.name != username:
                    continue
                if isinstance(sessions, dict) and sessions:
                    for addr in sessions:
                        ip, port = _split_addr(str(addr))
                        live.add((node.name, cn, ip, port))
                else:
                    live.add((node.name, cn, "", ""))
        except Exception as e:
            logger.warning("mlogin: node %s unavailable: %s", node.name, e)
    return live, reachable


def _registry_sessions(username: str, db: Session) -> set[tuple]:
    rows = db.execute(text(
        "SELECT node_name, common_name, trusted_ip, trusted_port "
        "FROM global_mlogin_sessions WHERE username = :u"
    ), {"u": username}).fetchall()
    return {(str(r[0] or ""), str(r[1] or ""), str(r[2] or ""), str(r[3] or "")) for r in rows}


def _cleanup(db: Session, live: set[tuple], reachable: set[str], now: float) -> None:
    db.execute(text("DELETE FROM global_mlogin_sessions WHERE updated_at < :c"),
               {"c": now - _SESSION_TTL})
    if not reachable:
        return
    ph = ", ".join(f":rn{i}" for i in range(len(reachable)))
    params = {f"rn{i}": n for i, n in enumerate(reachable)}
    db.execute(text(f"DELETE FROM global_mlogin_sessions WHERE node_name IN ({ph}) "
                    f"AND created_at < :g"), {**params, "g": now - _STATUS_GRACE})
    rows = db.execute(text(
        f"SELECT id, node_name, common_name, trusted_ip, trusted_port "
        f"FROM global_mlogin_sessions WHERE node_name IN ({ph})"
    ), params).fetchall()
    for r in rows:
        key = (str(r[1] or ""), str(r[2] or ""), str(r[3] or ""), str(r[4] or ""))
        if key not in live:
            db.execute(text("DELETE FROM global_mlogin_sessions WHERE id = :id"), {"id": r[0]})


@router.get("/status/{username}", response_model=ResponseModel)
async def global_mlogin_status(
    username: str,
    db: Session = Depends(get_db),
    key: str | None = Header(default=None),
    x_node_name: str | None = Header(default=None, alias="X-Node-Name"),
):
    """Global session count for a user across all reachable nodes."""
    _authorize_node(db, x_node_name, key)
    now = time.time()
    live, reachable = _live_sessions(username, db)
    with _global_lock():
        _ensure_table(db)
        _cleanup(db, live, reachable, now)
        registry = _registry_sessions(username, db)
        db.commit()
    sessions = sorted(set(live) | set(registry))
    return ResponseModel(success=True, msg="global multi-login status",
                         data={"username": username, "global_active": len(sessions),
                               "sessions": sessions})
