# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Node CRUD operations — add/update/delete nodes and users.

Handles all direct interactions with OVNode instances for user management:
creating, activating/deactivating, deleting users, and downloading configs.
"""

import asyncio
import time
import zipfile
from tempfile import SpooledTemporaryFile
from zipfile import ZIP_DEFLATED

from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from backend.db import crud
from backend.logger import logger
from backend.node.requests import NodeRequests, node_client
from backend.operations.geolocation import geolocate
from backend.schema import NodeCreate
from backend.version import __version__ as PANEL_VERSION


def node_version_compat(agent_version: object) -> dict:
    """Judge a node agent version against this panel.

    Policy (documented in OVNode docs): same major release is compatible
    (minor drift tolerated — both sides ignore unknown keys); a newer node
    than the panel is unsupported (the panel may not understand it); a
    different major is incompatible. Unparseable/missing versions are
    unknown, never silently accepted as compatible.
    """

    def _parts(value: object) -> tuple[int, ...] | None:
        try:
            nums = str(value).strip().lstrip("v").split(".")
            return tuple(int(p) for p in nums[:3])
        except (ValueError, TypeError, AttributeError):
            return None

    agent = _parts(agent_version)
    panel = _parts(PANEL_VERSION)
    if not agent or not panel:
        return {"verdict": "unknown", "agent_version": agent_version, "panel_version": PANEL_VERSION}
    if agent[0] != panel[0]:
        verdict = "incompatible"
    elif agent > panel:
        verdict = "node-newer"
    else:
        verdict = "compatible"
    return {"verdict": verdict, "agent_version": agent_version, "panel_version": PANEL_VERSION}


# Cap on concurrent per-node threadpool jobs for every fan-out below. A batch
# of 300 users × N nodes would otherwise queue thousands of jobs and starve
# unrelated requests on the AnyIO threadpool; 20 matches the sync.py sweep.
# asyncio primitives bind to the loop that first contends on them, so
# _fanout_semaphore() swaps in a fresh instance for a new loop (tests run one
# loop per case via asyncio.run).
NODE_FANOUT_LIMIT = 20
_node_fanout_semaphore = asyncio.Semaphore(NODE_FANOUT_LIMIT)
_node_fanout_loop: asyncio.AbstractEventLoop | None = None


def _fanout_semaphore() -> asyncio.Semaphore:
    """Return the fan-out semaphore for the running event loop."""
    global _node_fanout_semaphore, _node_fanout_loop
    loop = asyncio.get_running_loop()
    if _node_fanout_loop is not loop:
        _node_fanout_semaphore = asyncio.Semaphore(NODE_FANOUT_LIMIT)
        _node_fanout_loop = loop
    return _node_fanout_semaphore


async def _run_bounded(fn, *args):
    """Run one blocking node call in the threadpool under the fan-out cap."""
    async with _fanout_semaphore():
        return await run_in_threadpool(fn, *args)


async def add_node_handler(request: NodeCreate, db: Session) -> bool:
    """Add a new node: validate connectivity, geolocate, persist to DB."""
    # Geolocation does blocking DNS + HTTP (up to ~10s): run it in the
    # threadpool so a slow lookup cannot stall every other request.
    geo = await run_in_threadpool(geolocate, request.address)
    if not request.use_tls:
        logger.warning(
            "Node %s added without TLS — API key and traffic cross the network in cleartext. "
            "Enable TLS on the node and set use_tls=true.",
            request.address,
        )

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=request.key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=request.set_new_setting,
        use_tls=request.use_tls,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        return False

    if request.set_new_setting:
        configured = await run_in_threadpool(
            nr.update_config,
            tunnel_address=request.tunnel_address or "",
            protocol=request.protocol,
            ovpn_port=request.ovpn_port,
            set_new_setting=True,
        )
        if not configured:
            logger.error("Node %s accepted health check but rejected configuration", request.address)
            return False

    crud.create_node(db, request, geo)
    return True


async def update_node_handler(node_id: int, request: NodeCreate, db: Session) -> tuple[bool, str]:
    """Update an existing node's configuration.

    DB changes are persisted first so metadata edits (rename, address/port
    change, status toggle) always succeed even when the node is offline —
    e.g. when moving a node to a new IP the old address may be unreachable.

    The live node sync (health check + optional config push) is best-effort:
    failures are logged and surfaced in the message, but they do not roll back
    the saved record.
    """
    existing = crud.get_node_by_id(db, node_id)
    if not existing:
        return False, "Node not found"

    geo = await run_in_threadpool(geolocate, request.address)
    api_key = request.key or existing.key

    # Persist first — this is the source of truth for the panel.
    crud.update_node(db, node_id, request, geo)

    # Metadata-only edits (rename, address/port change, status toggle) never
    # need to reach the node, so they return instantly even when the node is
    # offline. Only when the operator asks to apply VPN settings on the node
    # do we contact it — and even then a failure only downgrades the message.
    if not request.set_new_setting:
        return True, "Node updated successfully"

    nr = NodeRequests(
        address=request.address,
        port=request.port,
        api_key=api_key,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
        use_tls=request.use_tls,
    )

    ok = await run_in_threadpool(nr.check_node)
    if not ok:
        logger.warning("Node %s updated in DB but unreachable for live sync", request.address)
        return True, "Node updated. Live node is unreachable — changes will apply on next reconnect."

    configured = await run_in_threadpool(
        nr.update_config,
        tunnel_address=request.tunnel_address or "",
        protocol=request.protocol,
        ovpn_port=request.ovpn_port,
        set_new_setting=True,
    )
    if not configured:
        logger.error("Node %s rejected configuration update", request.address)
        return True, "Node updated, but the new VPN settings could not be applied on the node."

    return True, "Node updated successfully"


async def delete_node_handler(node_id: int, db: Session) -> bool:
    """Delete a node from the panel."""
    from backend.node.connection import forget

    crud.delete_node(db, node_id)
    forget(node_id)  # drop the cached transport
    return True


async def list_nodes_handler(db: Session) -> list:
    """List all nodes with their current status."""
    nodes = crud.get_all_nodes(db)
    result = []
    for n in nodes:
        result.append(
            {
                "id": n.id,
                "name": n.name,
                "address": n.address,
                "tunnel_address": n.tunnel_address,
                "protocol": n.protocol,
                "ovpn_port": n.ovpn_port,
                "port": n.port,
                "status": n.status,
                "use_tls": n.use_tls,
                "country_code": n.country_code,
                "latitude": n.latitude,
                "longitude": n.longitude,
            }
        )
    return result


async def get_node_status_handler(node_id: int, db: Session):
    """Get detailed status of a specific node."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    nr = node_client(node)

    started = time.perf_counter()
    # Separate clients per concurrent call: tls_verified is per-instance
    # mutable state, so sharing one NodeRequests across two threads races.
    nr_sessions = node_client(node)
    info, sessions = await asyncio.gather(
        run_in_threadpool(nr.get_node_info),
        run_in_threadpool(nr_sessions.get_sessions, None, 8),
    )
    info = info if isinstance(info, dict) else {}
    sessions = sessions if isinstance(sessions, dict) else {}

    # Either call proves the TLS path (same node, same cert); prefer the
    # verified result if they ever disagree.
    tls_verified = nr.tls_verified if nr.tls_verified is True else nr_sessions.tls_verified
    tls_mode = nr.tls_mode if nr.tls_verified is True else nr_sessions.tls_mode

    return {
        "node": {
            "id": node.id,
            "name": node.name,
            "address": node.address,
            "status": node.status,
        },
        "node_info": info,
        "version_compat": node_version_compat(info.get("version")),
        "session_diagnostics": sessions,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "reachable": bool(info),
        # True = verified TLS; False = self-signed fallback (API key without
        # MITM protection); None = plain HTTP or never connected (unknown).
        "tls_verified": tls_verified,
        "tls_mode": tls_mode,
    }


async def create_user_on_all_nodes(name: str, db: Session, max_logins: int = 1, user_id: int = None):
    """Create a user on every active node concurrently.

    Uses numeric user ID as the OpenVPN CN and node-side identity.
    """
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else None
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(_run_bounded(nr.create_user, name, max_logins, uid))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results


async def change_user_status_on_all_nodes(
    user_id: int,
    name: str,
    status: bool,
    db: Session,
    max_logins: int = None,
    nodes: list | None = None,
) -> bool:
    """Toggle user status on every active node. Uses numeric user ID.

    ``nodes`` lets a sweep that already loaded the active list (e.g.
    enforce_user_limits) pass it in once instead of re-querying per user.
    ``None`` keeps the old behavior: query here.
    """
    nodes = crud.get_active_nodes(db) if nodes is None else nodes
    uid = str(user_id)
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(_run_bounded(nr.change_user_status, name, status, max_logins, uid))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


async def set_user_limit_on_all_nodes(name: str, max_logins: int, db: Session, user_id: int = None) -> bool:
    """Push max_login limit to every active node. Uses numeric user ID."""
    nodes = crud.get_active_nodes(db)
    uid = str(user_id) if user_id else name
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(_run_bounded(nr.set_user_limit, uid, int(max_logins or 0)))
    if not tasks:
        return True
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return all(result is True for result in results)


async def download_ovpn_client_from_node(user_id: int, node_id: int, db: Session):
    """Download a user's .ovpn config from a specific node. Uses numeric user ID."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    nr = node_client(node)
    return await run_in_threadpool(nr.download_ovpn_client, str(user_id))


async def download_all_ovpn_clients_from_node(node_id: int, db: Session) -> StreamingResponse | None:
    """Download all users' .ovpn configs from a node as a ZIP file. Uses numeric user IDs."""
    node = crud.get_node_by_id(db, node_id)
    if not node:
        return None

    users = crud.get_all_users(db)
    nr = node_client(node)

    # Spool to disk past 8 MB so a node with thousands of users cannot pin
    # the whole archive in memory on a small VPS.
    buf = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with zipfile.ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for user in users:
            # Use download_ovpn_bytes() which returns raw bytes — avoids
            # depending on the internal .body attribute of starlette Response.
            content = await run_in_threadpool(nr.download_ovpn_bytes, str(user.id))
            if content:
                zf.writestr(f"{user.name}.ovpn", content)

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{node.name}_all_clients.zip"'},
        background=BackgroundTask(buf.close),
    )


async def delete_user_on_all_nodes(name: str, user_id: int, db: Session) -> dict:
    """Delete a user from every active node. Uses numeric user ID.

    Returns {"ok", "failed"} where ``failed`` names unreachable nodes.
    A dead node must not block panel-side deletion (its cert is already
    unusable once the node is gone; NOT_FOUND counts as success so already
    cleaned nodes never block either). Callers surface ``failed`` so the
    operator knows which nodes need attention.
    """
    nodes = crud.get_active_nodes(db)
    if not nodes:
        return {"ok": True, "failed": []}
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(_run_bounded(nr.delete_user, str(user_id)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = [n.name for n, r in zip(nodes, results, strict=True) if r is not True]
    return {"ok": not failed, "failed": failed}


async def reset_user_usage_on_all_nodes(user_id: int, db: Session) -> dict:
    """Zero a user's banked counters on every active node (panel reset fan-out).

    Best-effort like delete: an offline node keeps its banked file, but the
    panel already cleared its baselines, so the collector rebaselines (bills
    zero) instead of resurrecting old bytes when the node returns.
    Returns {"ok", "failed"} naming unreachable nodes.
    """
    nodes = crud.get_active_nodes(db)
    if not nodes:
        return {"ok": True, "failed": []}
    tasks = []
    for n in nodes:
        nr = node_client(n)
        tasks.append(_run_bounded(nr.reset_usage, str(user_id)))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    failed = [n.name for n, r in zip(nodes, results, strict=True) if r is not True]
    return {"ok": not failed, "failed": failed}
