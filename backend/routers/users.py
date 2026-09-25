# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT


import hmac
import os
import time as _time
from collections.abc import Iterable

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.auth.auth import get_current_user
from backend.db import crud
from backend.db.engine import get_db
from backend.db.models import Node, User
from backend.logger import logger
from backend.node.requests import node_client
from backend.node.task import (
    change_user_status_on_all_nodes,
    delete_user_on_all_nodes,
    disconnect_user_on_all_nodes,
    get_active_connection_counts,
    get_user_session_diagnostics,
    reset_user_usage_on_all_nodes,
    set_user_limit_on_all_nodes,
)
from backend.operations import live as live_ops
from backend.operations.audit import log_event
from backend.schema import CreateUser, ResponseModel, StatusToggle, UpdateUser, Users

router = APIRouter(prefix="/users", tags=["Users"])

# ── Undo-delete buffer ────────────────────────────────────────────
# Snapshot recently deleted users in-memory (bounded + TTL) so the UI can
# offer "Undo" for a few seconds after a delete. Restoring re-inserts the
# row with its original UUID; node-side certs regenerate on next download.

_DELETED_TTL = 120  # seconds
_DELETED_MAX = 50
_deleted_users: dict[str, tuple[float, dict]] = {}


def _snapshot_user(u: User) -> dict:
    return {
        "name": u.name,
        "uuid": u.uuid,
        "total": u.total,
        "used": u.used,
        "node_usage": u.node_usage,
        "last_node_usage": u.last_node_usage,
        "max_logins": u.max_logins,
        "expiry_date": u.expiry_date.isoformat() if u.expiry_date else None,
        "is_active": u.is_active,
        "owner": u.owner,
    }


def _remember_deleted(u: User) -> None:
    now = _time.monotonic()
    _deleted_users[u.uuid] = (now, _snapshot_user(u))
    # Evict expired + overflow
    for k in [k for k, (ts, _) in _deleted_users.items() if now - ts > _DELETED_TTL]:
        _deleted_users.pop(k, None)
    while len(_deleted_users) > _DELETED_MAX:
        _deleted_users.pop(next(iter(_deleted_users)), None)


def _require_user_access(db_user: User, current_user: dict) -> None:
    """Enforce the same ownership rule for every user operation."""
    if current_user.get("type") == "admin" and db_user.owner != current_user.get("username"):
        raise HTTPException(status_code=403, detail="You do not have permission to access this resource")


@router.get("/next-username", response_model=ResponseModel)
async def get_next_username(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    admin = crud.get_admin_by_username(db, username=user.get("username"))
    prefix = admin.username_prefix if admin else None
    if not prefix:
        return ResponseModel(success=False, msg="No username prefix configured for this admin")

    # Fetch only names that start with the prefix and end with digits.
    # Limit to 100_000 to bound memory; in practice admins have far fewer users.
    # Escape LIKE wildcards: a prefix like "50%" must be a literal prefix, not
    # "every username starting with 50".
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    existing = db.query(User.name).filter(User.name.like(f"{escaped}%", escape="\\")).limit(100_000).all()
    taken = {n[0] for n in existing}

    i = 1
    while f"{prefix}{i}" in taken:
        i += 1

    return ResponseModel(
        success=True,
        msg="Next username generated",
        data={"username": f"{prefix}{i}"},
    )


@router.get("/traffic/top", response_model=ResponseModel)
async def top_traffic_users(
    days: int = Query(default=7, ge=1, le=90),
    limit: int = Query(default=5, ge=1, le=25),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Top users by billed bytes over the last N days (admins: own users)."""
    from backend.operations.usage_history import top_users

    owner = None if user.get("type") == "owner" else user.get("username")
    return ResponseModel(success=True, msg="Top traffic users retrieved", data=top_users(db, days=days, limit=limit, owner=owner))


@router.get("/{uuid}/traffic", response_model=ResponseModel)
async def user_traffic_history(
    uuid: str,
    days: int = Query(default=14, ge=1, le=90),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Per-day billed bytes for one user (zero-filled), plus lifetime used."""
    from backend.operations.usage_history import user_daily_series

    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    return ResponseModel(
        success=True,
        msg="User traffic history retrieved",
        data={"days": user_daily_series(db, db_user.id, days=days), "used": db_user.used or 0, "total": db_user.total},
    )


@router.get("/", response_model=ResponseModel)
async def get_all_users(
    page: int | None = Query(default=None, ge=1, le=10_000),
    page_size: int | None = Query(default=None, ge=1, le=500),
    search: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # The panel filters, sorts and paginates client-side, so the default is
    # the full set. Passing page/page_size/search opts into DB-level
    # filtering for API consumers (notably the Telegram bot, which used to
    # pull the whole table on every keystroke).
    paginate = page is not None or page_size is not None
    server_filter = paginate or bool(search and search.strip())
    page = page or 1
    page_size = page_size or 100
    needle = search.strip() if search and search.strip() else None

    # Connection counts come from the live collector's in-memory cache, so a
    # page load never fans out to every node (a dead node used to stall this
    # endpoint for up to 30s). Only on cold start — before the collector's
    # first poll completes — do we fall back to querying nodes directly.
    if live_ops.last_poll_ts() > 0:
        active_counts = live_ops.get_connection_counts()
    else:
        active_counts = await get_active_connection_counts(db)

    def serialize(db_user):
        item = Users.model_validate(db_user).model_dump()
        item["active_connections"] = int(active_counts.get(db_user.name, 0) or 0)
        item["online"] = item["active_connections"] > 0
        # last_online is updated by the background metrics job, not here.
        # GET endpoints must not modify data.
        item["last_online"] = db_user.last_online.isoformat() if db_user.last_online else None
        return item

    if user["type"] == "owner":
        if server_filter:
            page_users, total = crud.get_users_page(db, search=needle, page=page, page_size=page_size)
        else:
            page_users = crud.get_all_users(db)
            total = len(page_users)
    elif user["type"] == "admin":
        if server_filter:
            page_users, total = crud.get_users_page(db, owner=user["username"], search=needle, page=page, page_size=page_size)
        else:
            page_users = crud.get_users_by_admin(db, admin_username=user["username"])
            total = len(page_users)
    else:
        return ResponseModel(success=False, msg="Unauthorized access")

    users_list = [serialize(u) for u in page_users]
    return ResponseModel(
        success=True,
        msg="Users retrieved successfully",
        data={
            "users": users_list,
            "total": total,
            "page": page if server_filter else 1,
            "page_size": page_size if server_filter else total,
        },
    )


@router.post("/{uuid}/reset-usage", response_model=ResponseModel)
async def reset_user_usage(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    reset = crud.reset_user_usage(db, uuid)
    if not reset:
        raise HTTPException(status_code=404, detail="User not found")
    # Fan out to nodes (best-effort): node banked files must go too, or the
    # totals-based collector would resurrect pre-reset bytes as "growth".
    # An offline node is fine — the cleared panel baselines make its return
    # rebaseline instead of rebill.
    fanout = await reset_user_usage_on_all_nodes(db_user.id, db)
    if fanout.get("failed"):
        logger.warning("reset-usage node fan-out failed on: %s", fanout["failed"])
    live_ops.publish("users", {"op": "reset-usage"})
    return ResponseModel(success=True, msg="User usage reset successfully", data=None)


@router.post("/", response_model=ResponseModel)
async def create_user(
    request: CreateUser,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    # Normalize exactly as the DB layer does before checking duplicates and
    # before using the name to create node-side CNs.
    normalized_name = request.name.replace(" ", "_")
    check_user = crud.get_user_by_name(db, normalized_name)
    if check_user is not None:
        return ResponseModel(success=False, msg="User with this name already exists", data=None)

    # Use the actual username as the owner so users created by the panel owner
    # are associated with a real identity, not the generic sentinel "owner".
    owner = user["username"]
    new_user = crud.create_user(db, request, owner)

    # Do NOT synchronously create the user on every node here. The OpenVPN client
    # generation script is slow and can make the Add User popup look stuck.
    # The node-side client/config is created lazily when Download is clicked.
    log_event(db, "user.create", actor=user.get("username"), target=new_user.name, detail="User created")
    live_ops.publish("users", {"op": "create"})
    return ResponseModel(
        success=True,
        msg="User created successfully. VPN config will be generated on first download.",
        data=Users.model_validate(new_user),
    )


@router.put("/{uuid}/", response_model=ResponseModel, include_in_schema=False)
@router.put("/{uuid}", response_model=ResponseModel)
async def update_user(
    uuid: str,
    request: UpdateUser,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    crud.update_user(db, uuid, request)
    db_user = crud.get_user_by_uuid(db, uuid)
    final_active = bool(db_user.is_active)
    status_synced = await change_user_status_on_all_nodes(db_user.id, db_user.name, final_active, db)
    limit_synced = await set_user_limit_on_all_nodes(db_user.name, db_user.max_logins, db, db_user.id)
    if not status_synced or not limit_synced:
        return ResponseModel(
            success=False,
            msg="User saved locally but one or more nodes failed to synchronize",
            data={"status_synced": status_synced, "limit_synced": limit_synced},
        )
    # enforce_user_limits runs as a daily background job in app.py;
    # calling it per user update is O(n²) — each call queries all expired/exceeded users.
    log_event(db, "user.update", actor=user.get("username"), target=request.name, detail="User updated")
    live_ops.publish("users", {"op": "update"})
    return ResponseModel(success=True, msg="User updated successfully")


@router.put("/{uuid}/status", response_model=ResponseModel)
async def change_user_status(
    uuid: str,
    request: StatusToggle,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    if request.status:
        # Same rule as the edit form: an expired or out-of-traffic account
        # must not be switched on, or it would stay online until the next
        # enforce sweep.
        blocked = crud.activation_blocked(db_user)
        if blocked:
            return ResponseModel(success=False, msg=f"Cannot activate: user is {blocked}", data=None)
    db_user.is_active = bool(request.status)
    db.commit()
    synced = await change_user_status_on_all_nodes(db_user.id, db_user.name, request.status, db)
    if not synced:
        return ResponseModel(
            success=False,
            msg="User status saved locally but node synchronization failed",
            data={"synced": False},
        )
    log_event(db, "user.status", actor=user.get("username"), target=request.name, detail=f"status={request.status}")
    live_ops.publish("users", {"op": "status"})
    return ResponseModel(success=True, msg="Changed user status successfully")


@router.get("/{uuid}/sessions", response_model=ResponseModel)
async def user_sessions(
    uuid: str,
    hours: int = 8,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    data = await get_user_session_diagnostics(db_user.id, db, hours=hours)
    return ResponseModel(success=True, msg="User session diagnostics", data=data)


@router.post("/{uuid}/disconnect", response_model=ResponseModel)
async def disconnect_user_sessions(
    uuid: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    _require_user_access(db_user, user)
    data = await disconnect_user_on_all_nodes(db_user.name, db_user.id, db)
    log_event(db, "user.disconnect", actor=user.get("username"), target=db_user.name, detail="Disconnect requested")
    live_ops.publish("users", {"op": "disconnect"})
    return ResponseModel(success=True, msg="Disconnect command processed", data=data)


@router.delete("/{uuid}", response_model=ResponseModel)
async def delete_user(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    db_user = crud.get_user_by_uuid(db, uuid)
    if db_user is None:
        return ResponseModel(success=False, msg="User not found", data=None)
    _require_user_access(db_user, user)

    # Best-effort: the DB row is the source of truth and always goes away —
    # one dead node must not wedge the whole delete. Unreachable nodes are
    # named in the response + audit log so the operator can follow up
    # (their certs stop working the moment the node is replaced/re-synced).
    result = await delete_user_on_all_nodes(db_user.name, db_user.id, db)
    failed = result.get("failed", [])
    name = db_user.name
    _remember_deleted(db_user)  # enable Undo
    crud.delete_user(db, name)
    detail = "User deleted" if not failed else f"User deleted; unreachable nodes: {', '.join(failed)}"
    log_event(db, "user.delete", actor=user.get("username"), target=name, detail=detail)
    live_ops.publish("users", {"op": "delete"})
    if failed:
        return ResponseModel(
            success=True,
            msg=f"User deleted locally, but unreachable on: {', '.join(failed)}",
            data={"failed_nodes": failed},
        )
    return ResponseModel(success=True, msg="User deleted successfully")


@router.post("/{uuid}/restore", response_model=ResponseModel)
async def restore_user(uuid: str, db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """Undo a recent delete: re-insert the user with its original UUID."""
    entry = _deleted_users.get(uuid)
    if not entry or (_time.monotonic() - entry[0]) > _DELETED_TTL:
        return ResponseModel(success=False, msg="Undo window expired — user can no longer be restored", data=None)
    snap = entry[1]
    # The undo buffer is process-global, keyed by UUID. Enforce the same
    # ownership rule as every other user operation: an admin must not
    # resurrect a user that belonged to someone else.
    if user.get("type") != "owner" and snap.get("owner") != user.get("username"):
        return ResponseModel(success=False, msg="You do not have permission to restore this user", data=None)
    if crud.get_user_by_uuid(db, uuid) is not None:
        _deleted_users.pop(uuid, None)
        return ResponseModel(success=False, msg="User already exists", data=None)
    try:
        restored = crud.restore_user(db, snap)
    except Exception as exc:
        return ResponseModel(success=False, msg=f"Restore failed: {exc}", data=None)
    _deleted_users.pop(uuid, None)
    # Re-push the login limit to nodes (best-effort; certs regenerate on download).
    await set_user_limit_on_all_nodes(restored.name, restored.max_logins, db, restored.id)
    log_event(db, "user.restore", actor=user.get("username"), target=restored.name, detail="User restored (undo)")
    live_ops.publish("users", {"op": "restore"})
    return ResponseModel(
        success=True,
        msg="User restored successfully",
        data=Users.model_validate(restored).model_dump(),
    )


class _UserAdjust(BaseModel):
    days: int = Field(default=0, ge=0, le=3650)
    # Bounded so the SQLite 64-bit INTEGER column cannot overflow.
    bytes: int = Field(default=0, ge=0, le=2**60)


@router.post("/{uuid}/extend", response_model=ResponseModel)
async def extend_user(
    uuid: str,
    payload: _UserAdjust,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Extend one user's expiry and/or add traffic quota.

    Admins may only touch their own users — a foreign UUID is a 404 so
    tenancy is not leaked. Both days and bytes of 0 is a 422.
    """
    if payload.days == 0 and payload.bytes == 0:
        raise HTTPException(status_code=422, detail="days or bytes must be greater than 0")
    owner = None if user["type"] == "owner" else user["username"]
    updated = crud.adjust_user(db, uuid, days=payload.days, add_bytes=payload.bytes, owner=owner)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    log_event(
        db,
        "user.extend",
        actor=user.get("username"),
        target=updated.name,
        detail=f"days={payload.days} bytes={payload.bytes}",
    )
    live_ops.publish("users", {"op": "extend"})
    return ResponseModel(success=True, msg="User updated", data=Users.model_validate(updated))


# ── Global multi-login status (/mlogin) ─────────────────────────────────
# Moved from routers/mlogin.py: same /mlogin prefix and wire shape, one
# user-session domain file. Two caller types: OVNode hook (X-Node-Name +
# key headers) and the panel UI (owner bearer).
mlogin_router = APIRouter(prefix="/mlogin", tags=["Global Multi-login"])


def _authorize_node(db: Session, node_name: str | None, key: str | None) -> Node:
    """Authenticate a node request using constant-time key comparison."""
    if not node_name or not key:
        raise HTTPException(status_code=401, detail="Missing node name/key")
    node = db.query(Node).filter(Node.name == node_name).first()
    # Use hmac.compare_digest to prevent timing side-channel leaking key bytes.
    if not node:
        raise HTTPException(status_code=401, detail="Invalid node key")
    if not hmac.compare_digest((node.key or "").encode("utf-8"), key.encode("utf-8", "ignore")):
        raise HTTPException(status_code=401, detail="Invalid node key")
    return node


def _split_addr(addr: str) -> tuple[str, str]:
    if ":" in addr:
        ip, port = addr.rsplit(":", 1)
        return ip.strip("[]"), port
    return addr, ""


def _fetch_node_usage(node) -> dict | None:
    """Blocking usage fetch for one node (run in threadpool).

    Goes through :class:`NodeRequests` so the mlogin path shares the main
    client's address sanitising, self-signed TLS fallback and flap-aware
    logging — the previous bare ``requests.get`` failed every self-signed
    node and silently undercounted global sessions.
    """
    try:
        req = node_client(node)
        # `or None` preserves the old contract: transport failure → None
        # (caller skips the node), while a live-but-idle node returns its
        # (truthy) payload dict. Without it every dead node would count as
        # "reachable with zero sessions".
        return req.get_usage(timeout=float(os.getenv("OVMANAGER_MLOGIN_NODE_TIMEOUT", "1.5"))) or None
    except Exception:
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


@mlogin_router.get("/status/{username}", response_model=ResponseModel)
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
    2. Panel UI (owner only): authenticates with a Bearer session token in Authorization header.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        # Panel-user path: validate session token and require owner role.
        from backend.auth.auth import role_is_current, verify_session_token

        user = verify_session_token(auth_header[7:], db)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        # Re-check role currency: a session minted while this username was the
        # owner must stop working after ADMIN_USERNAME changes.
        if user.get("type") != "owner" or not role_is_current(db, user.get("username", ""), "owner"):
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
