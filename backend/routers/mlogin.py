# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Global multi-login status for OpenVPN sessions.

Queries all reachable nodes for live session data and combines with a
panel-side registry for cross-node session tracking.
"""

from __future__ import annotations

import hmac
import os
from collections.abc import Iterable

import requests
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from backend.db.engine import get_db
from backend.db.models import Node
from backend.logger import logger
from backend.schema.output import ResponseModel

router = APIRouter(prefix="/mlogin", tags=["Global Multi-login"])

_NODE_TIMEOUT = float(os.getenv("OVMANAGER_MLOGIN_NODE_TIMEOUT", "1.5"))


def _authorize_node(db: Session, node_name: str | None, key: str | None) -> Node:
    """Authenticate a node request using constant-time key comparison."""
    if not node_name or not key:
        raise HTTPException(status_code=401, detail="Missing node name/key")
    node = db.query(Node).filter(Node.name == node_name).first()
    # Use hmac.compare_digest to prevent timing side-channel leaking key bytes.
    # node.key is Fernet-encrypted at rest — compare against the plaintext.
    if not node:
        raise HTTPException(status_code=401, detail="Invalid node key")
    from backend.db.crud import decrypt_node_key

    if not hmac.compare_digest(decrypt_node_key(node.key), key):
        raise HTTPException(status_code=401, detail="Invalid node key")
    return node


def _split_addr(addr: str) -> tuple[str, str]:
    if ":" in addr:
        ip, port = addr.rsplit(":", 1)
        return ip.strip("[]"), port
    return addr, ""


def _fetch_node_usage(node) -> dict | None:
    """Blocking HTTP call to fetch usage from a single node (run in threadpool)."""
    try:
        from backend.db.crud import decrypt_node_key

        scheme = "https" if node.use_tls else "http"
        r = requests.get(
            f"{scheme}://{node.address}:{node.port}/sync/usage",
            headers={"key": decrypt_node_key(node.key)},
            timeout=_NODE_TIMEOUT,
        )
        if r.status_code != 200:
            return None
        payload = r.json()
        if not payload.get("success"):
            return None
        return payload.get("data") or {}
    except Exception as e:
        logger.warning("mlogin: node %s unavailable: %s", node.name, e)
        return None


async def _live_sessions(username: str, db: Session) -> tuple[set[tuple], set[str]]:
    """Query all active nodes for live sessions of this user (async, non-blocking)."""
    import asyncio

    live: set[tuple] = set()
    reachable: set[str] = set()
    nodes: Iterable[Node] = db.query(Node).filter(Node.status == True).all()  # noqa: E712

    # Build id→name map once for all nodes (pairs only — no User objects).
    from backend.db.crud import get_user_id_name_pairs

    id_to_name = dict(get_user_id_name_pairs(db))

    async def check_node(node):
        data = await run_in_threadpool(_fetch_node_usage, node)
        return node, data

    results = await asyncio.gather(*[check_node(n) for n in nodes], return_exceptions=True)

    for item in results:
        if isinstance(item, Exception):
            continue
        node, data = item
        if data is None:
            continue
        reachable.add(node.name)
        for cn, sessions in data.get("sessions", {}).items():
            name = id_to_name.get(cn)
            if not name or name != username:
                continue
            if isinstance(sessions, dict) and sessions:
                for addr in sessions:
                    ip, port = _split_addr(str(addr))
                    live.add((node.name, cn, ip, port))
            else:
                live.add((node.name, cn, "", ""))

    return live, reachable


@router.get("/status/{username}", response_model=ResponseModel)
async def global_mlogin_status(
    username: str,
    request: Request,
    db: Session = Depends(get_db),
    key: str | None = Header(default=None),
    x_node_name: str | None = Header(default=None, alias="X-Node-Name"),
):
    """Global session count for a user across all reachable nodes.

    Accepts two caller types:
    1. OVNode hook: authenticates with X-Node-Name + key headers.
    2. Panel UI (owner only): authenticates with Bearer JWT in Authorization header.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Panel-user path: validate session token and require owner role.
        from backend.auth.auth import verify_session_token

        user = verify_session_token(auth_header[7:], db)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        if user.get("type") != "owner":
            raise HTTPException(status_code=403, detail="Owner privileges required")
    else:
        # OVNode hook path: authenticate by node name + API key
        _authorize_node(db, x_node_name, key)
    live, _ = await _live_sessions(username, db)
    # NOTE: the panel-side global_mlogin_sessions registry is retired — nothing
    # ever wrote to it, so the live poll is the whole answer. Response shape
    # (global_active + sessions list) is unchanged for existing consumers.
    sessions = sorted(live)
    return ResponseModel(
        success=True,
        msg="global multi-login status",
        data={"username": username, "global_active": len(sessions), "sessions": sessions},
    )
